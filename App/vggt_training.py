# -*- coding: utf-8 -*-
# vggt_training.py - VGGT Integration for 360 Degree SplatPipe
# Refactored for clean rigid body alignment and single source of truth

import os
import sys
import traceback
import glob
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable
import threading
import time
import collections
import struct
import tempfile
import shutil # Added for file operations in filtering
import queue  # Added for threaded COLMAP writing

import trimesh
import re

import numpy as np
import cv2
import torch
import torch.nn.functional as F
from PIL import Image
import matplotlib.cm as cm
from scipy.spatial.transform import Rotation
import pycolmap
# Note: We implement our own get_virtual_rotations with OpenCV convention
# from panorama_processing import get_virtual_rotations


# Add VGGT to path if needed
def add_vggt_to_path(vggt_path: str = None):
    """Add VGGT directory to Python path for imports"""
    if vggt_path:
        # Use configured path
        vggt_dir = Path(vggt_path)
    else:
        # Fallback to relative path
        vggt_dir = Path(__file__).parent.parent.parent / "vggt"
        
    if vggt_dir.exists() and str(vggt_dir) not in sys.path:
        sys.path.append(str(vggt_dir))  # Append to end so local modules take priority

# Try to import VGGT
try:
    add_vggt_to_path()
    from vggt.models.vggt import VGGT # type: ignore
    from vggt.utils.load_fn import load_and_preprocess_images # type: ignore
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri # type: ignore
    from vggt.utils.geometry import unproject_depth_map_to_point_map # type: ignore
    from vggt.dependency.track_predict import predict_tracks # type: ignore
    from vggt.dependency.np_to_pycolmap import batch_np_matrix_to_pycolmap_wo_track, _build_pycolmap_intri # type: ignore
    VGGT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: VGGT not available: {e}")
    VGGT_AVAILABLE = False


# =====================================================================================
# OPENCV COORDINATE SYSTEM FUNCTIONS FOR VGGT COMPATIBILITY
# =====================================================================================

def look_at_rotation_opencv(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """
    Creates a rotation matrix for OpenCV camera convention (Y down, Z forward).
    This generates the camera's orientation matrix for the given yaw/pitch angles.
    """
    yaw = np.radians(yaw_deg)
    pitch = np.radians(pitch_deg)
    
    # Create rotation matrix by composing yaw and pitch rotations
    # In OpenCV: Yaw rotates around Y-axis (down), Pitch rotates around X-axis (right)
    
    # Yaw rotation (around Y-axis in OpenCV, which points down)
    cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
    R_yaw = np.array([
        [cos_yaw,  0, sin_yaw],
        [0,        1, 0      ],
        [-sin_yaw, 0, cos_yaw]
    ])
    
    # Pitch rotation (around X-axis)
    cos_pitch, sin_pitch = np.cos(pitch), np.sin(pitch)
    R_pitch = np.array([
        [1, 0,         0        ],
        [0, cos_pitch, -sin_pitch],
        [0, sin_pitch,  cos_pitch]
    ])
    
    # Combine rotations: R = R_yaw @ R_pitch
    R = R_yaw @ R_pitch
    return R.astype(np.float32)


def get_virtual_rotations(yaw_steps: int, pitch_angles: List[float]) -> List[np.ndarray]:
    """
    Generates rotation matrices for a camera rig where:
    1. All cameras share the same tilted coordinate system (defined by pitch)
    2. All cameras have the same pitch angle relative to the shared up axis
    3. Cameras differ only by yaw rotation around the shared up axis
    """
    rotations = []
    yaws = np.linspace(0, 360, yaw_steps, endpoint=False)
    
    for pitch in pitch_angles:
        pitch_rad = np.radians(pitch)
        yaw_offset = (360 / yaw_steps / 2) if pitch > 0 else 0
        
        # Define the shared tilted coordinate system for this pitch
        # Start with identity, then apply pitch rotation around X-axis
        cos_pitch, sin_pitch = np.cos(pitch_rad), np.sin(pitch_rad)
        
        # After pitch rotation around X-axis in OpenCV convention:
        shared_right = np.array([1, 0, 0])                    # X unchanged
        shared_up = np.array([0, cos_pitch, sin_pitch])       # Y tilted by pitch  
        shared_forward_base = np.array([0, -sin_pitch, cos_pitch])  # Z tilted by pitch
        
        for yaw_deg in yaws + yaw_offset:
            yaw_rad = np.radians(yaw_deg)
            cos_yaw, sin_yaw = np.cos(yaw_rad), np.sin(yaw_rad)
            
            # Rotate around the shared up axis (Rodrigues' rotation formula)
            # This rotates the right and forward vectors while preserving shared_up
            camera_right = (cos_yaw * shared_right + 
                          sin_yaw * np.cross(shared_up, shared_right))
            
            camera_forward = (cos_yaw * shared_forward_base + 
                            sin_yaw * np.cross(shared_up, shared_forward_base))
            
            # Normalize for precision
            camera_right /= np.linalg.norm(camera_right)
            camera_forward /= np.linalg.norm(camera_forward)
            
            # Build rotation matrix [right, up, forward] as columns
            R = np.stack([camera_right, shared_up, camera_forward], axis=1)
            rotations.append(R.astype(np.float32))
    
    return rotations


def debug_rig_coordinate_system(rotations: List[np.ndarray], expected_pitch: float):
    """Debug function to verify the rig coordinate system is correct."""
    print(f"\n🔍 Debugging Rig Coordinate System (Expected pitch: {expected_pitch}°)")
    
    if len(rotations) == 0:
        return
        
    anchor_up = rotations[0][:, 1]  # First camera's up vector (should be shared by all)
    print(f"   Shared up vector: [{anchor_up[0]:.3f}, {anchor_up[1]:.3f}, {anchor_up[2]:.3f}]")
    
    for i, R in enumerate(rotations[:6]):  # Check first 6 cameras
        forward = R[:, 2]
        up = R[:, 1]
        right = R[:, 0]
        
        # Verify up vectors are shared (should be identical for all cameras)
        up_shared = np.allclose(up, anchor_up, atol=1e-6)
        
        # Calculate pitch as validation does: arcsin(-dot(forward, anchor_up))
        validation_pitch = np.degrees(np.arcsin(-np.dot(forward, anchor_up)))
        
        # Calculate yaw from right vector
        yaw_calculated = np.degrees(np.arctan2(right[0], np.dot(right, [0, 0, 1])))
        
        print(f"   Cam {i}: up_shared={up_shared}, pitch={validation_pitch:.1f}°, yaw={yaw_calculated:.1f}°")
    
    print()


# =================================================================================
# COLMAP EXPORT FUNCTIONS - From working gradio demo
# =================================================================================

def rotmat2qvec(R):
    """Convert rotation matrix to quaternion (w, x, y, z)"""
    q = np.empty((4,))
    t = np.trace(R)
    if t > 0:
        t = np.sqrt(t + 1)
        q[0] = 0.5 * t
        t = 0.5 / t
        q[1] = (R[2, 1] - R[1, 2]) * t
        q[2] = (R[0, 2] - R[2, 0]) * t
        q[3] = (R[1, 0] - R[0, 1]) * t
    else:
        i = 0
        if R[1, 1] > R[0, 0]: i = 1
        if R[2, 2] > R[i, i]: i = 2
        j = (i + 1) % 3
        k = (j + 1) % 3
        t = np.sqrt(R[i, i] - R[j, j] - R[k, k] + 1)
        q[i + 1] = 0.5 * t
        t = 0.5 / t
        q[0] = (R[k, j] - R[j, k]) * t
        q[j + 1] = (R[j, i] + R[i, j]) * t
        q[k + 1] = (R[k, i] + R[i, k]) * t
    return q

def save_ply(points_np, colors_np, filename):
    """Save point cloud as PLY file"""
    from plyfile import PlyData, PlyElement
    vertices = np.empty(points_np.shape[0], dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4'), ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')])
    vertices['x'], vertices['y'], vertices['z'] = points_np.T
    vertices['red'], vertices['green'], vertices['blue'] = colors_np.T
    ply_data = PlyData([PlyElement.describe(vertices, 'vertex')], text=False)
    ply_data.write(filename)
    print(f"✅ PLY file saved to {filename}")

# =================================================================================
# HELPER FUNCTIONS FOR RIGID BODY ALIGNMENT (User confirmed these are correct)
# =================================================================================

def calculate_rigid_body_transform(source_position, source_rotation, target_position, target_rotation):
    """
    Calculate 4x4 transformation matrix to move rigid body from source frame to target frame.
    This computes the transformation T such that: T @ source_pose = target_pose
    where source_pose and target_pose are 4x4 homogeneous transformation matrices.

    Args:
        source_position: 3D position vector of source frame (e.g., rig anchor at origin)
        source_rotation: 3x3 rotation matrix of source frame
        target_position: 3D position vector of target frame (e.g., VGGT anchor position)
        target_rotation: 3x3 rotation matrix of target frame

    Returns:
        4x4 transformation matrix T
    """
    # Calculate rotation from source to target coordinate frame
    # target_rotation = R_align @ source_rotation  => R_align = target_rotation @ source_rotation.T
    rotation_transform = target_rotation @ source_rotation.T
    
    # Calculate translation (after rotation)
    # target_position = R_align @ source_position + t_align => t_align = target_position - R_align @ source_position
    translation_transform = target_position - rotation_transform @ source_position
    
    # Build 4x4 transformation matrix
    transform = np.eye(4, dtype=target_position.dtype)
    transform[:3, :3] = rotation_transform
    transform[:3, 3] = translation_transform
    

    
    return transform

def align_rig_to_anchor_pose(virtual_rig_poses_c2w: List[np.ndarray], anchor_pose_c2w: np.ndarray) -> List[np.ndarray]:
    """
    Direct rigid body alignment: Aligns a pre-defined virtual rig (camera-to-world poses
    around the origin) to a single VGGT-predicted anchor pose (camera-to-world).
    
    This function calculates a single transformation that moves the entire virtual rig
    so that its internal anchor camera perfectly matches the VGGT anchor pose.
    This ensures that the rig's internal geometry, including any specific pitch angles,
    is preserved relative to the world coordinate system.

    Args:
        virtual_rig_poses_c2w (List[np.ndarray]): List of 4x4 camera-to-world matrices
                                                  for the virtual rig, defined around the origin.
        anchor_pose_c2w (np.ndarray): The 4x4 camera-to-world matrix (VGGT ground truth reference).

    Returns:
        List[np.ndarray]: List of aligned 4x4 camera-to-world matrices for the entire rig.
    """
    # print(f"   🎯 CORRECTED RIGID BODY ALIGNMENT: Direct anchor-to-rig pose matching")

    if not virtual_rig_poses_c2w:
        return []

    # Step 1: Extract coordinate frames from both the anchor and the rig's reference point.
    # The rig's reference point is the first camera in the virtual_rig_poses_c2w list (index 0).
    # This is assumed to be the "anchor camera" within the rig, defined at the origin.
    anchor_position_target = anchor_pose_c2w[:3, 3]
    anchor_rotation_target = anchor_pose_c2w[:3, :3]
    
    virtual_rig_anchor_pose_source = virtual_rig_poses_c2w[0]
    virtual_rig_anchor_position_source = virtual_rig_anchor_pose_source[:3, 3]  # Should be [0,0,0]
    virtual_rig_anchor_rotation_source = virtual_rig_anchor_pose_source[:3, :3]

    print(f"   📍 ALIGNMENT ANALYSIS:")
    print(f"     VGGT Anchor target position:     [{anchor_position_target[0]:.6f}, {anchor_position_target[1]:.6f}, {anchor_position_target[2]:.6f}]")
    print(f"     Virtual rig anchor source pos:   [{virtual_rig_anchor_position_source[0]:.6f}, {virtual_rig_anchor_position_source[1]:.6f}, {virtual_rig_anchor_position_source[2]:.6f}]")
    print(f"     VGGT Anchor target rotation det: {np.linalg.det(anchor_rotation_target):.6f}")
    print(f"     Virtual rig source rotation det: {np.linalg.det(virtual_rig_anchor_rotation_source):.6f}")
    
    # Step 2: Calculate the rigid body transformation.
    # This transform moves the entire virtual rig so that its anchor camera perfectly
    # matches the VGGT-predicted anchor pose.
    rigid_body_transform = calculate_rigid_body_transform(
        source_position=virtual_rig_anchor_position_source,
        source_rotation=virtual_rig_anchor_rotation_source,
        target_position=anchor_position_target,
        target_rotation=anchor_rotation_target
    )
    
    # Step 3: Apply the transformation to ALL virtual rig poses.
    aligned_poses = []
    
    for i, virtual_pose in enumerate(virtual_rig_poses_c2w):
        # Apply the rigid body transformation: T @ virtual_pose
        # This translates and rotates the entire rig as one unit.
        aligned_pose = rigid_body_transform @ virtual_pose
        aligned_poses.append(aligned_pose)
        
        # Debug information for first few poses
        if i < 3:
            original_pos = virtual_pose[:3, 3]
            aligned_pos = aligned_pose[:3, 3]
            original_forward = virtual_pose[:3, :3][:, 2]  # Z-axis (forward direction)
            aligned_forward = aligned_pose[:3, :3][:, 2]
            
            original_pitch = np.degrees(np.arcsin(np.clip(-original_forward[1], -1, 1)))  # Y component gives pitch
            aligned_pitch = np.degrees(np.arcsin(np.clip(-aligned_forward[1], -1, 1)))
            
            print(f"     Rig Camera {i}:")
            print(f"       Position: [{original_pos[0]:.3f}, {original_pos[1]:.3f}, {original_pos[2]:.3f}] -> [{aligned_pos[0]:.3f}, {aligned_pos[1]:.3f}, {aligned_pos[2]:.3f}]")
            print(f"       Pitch angle: {original_pitch:.1f}° -> {aligned_pitch:.1f}° (should preserve virtual rig pitch)")
    
    # Step 4: Validation - check if first aligned pose matches anchor exactly
    if aligned_poses:
        first_aligned_pos = aligned_poses[0][:3, 3]
        position_match_error = np.linalg.norm(first_aligned_pos - anchor_position_target)
        
        first_aligned_rot = aligned_poses[0][:3, :3]
        orientation_match_error = np.linalg.norm(first_aligned_rot - anchor_rotation_target, 'fro')
        
        print(f"   📊 ALIGNMENT VALIDATION:")
        print(f"     Position match error:  {position_match_error:.8f} (should be ~0)")
        print(f"     Orientation error:     {orientation_match_error:.8f} (should be ~0)")
        
        if position_match_error < 0.001 and orientation_match_error < 0.001:
            print(f"     ✅ ALIGNMENT SUCCESSFUL - Virtual rig pitch preserved")
        else:
            print(f"     ⚠️ ALIGNMENT FAILED - Check source and target poses")
    
    return aligned_poses



def extract_yaw_pitch_roll_from_c2w(R_c2w: np.ndarray) -> Tuple[float, float, float]:
    """
    Extract yaw, pitch, roll (degrees) from a C2W rotation matrix in OpenCV convention.
    - X: right
    - Y: down
    - Z: forward
    """
    # Forward = camera's Z axis (third column)
    forward = R_c2w[:, 2]

    # Pitch = arcsin(-forward.y) in OpenCV convention
    pitch = np.degrees(np.arcsin(-forward[1]))

    # Yaw = atan2(forward.x, forward.z)
    yaw = np.degrees(np.arctan2(forward[0], forward[2]))

    # Roll requires full frame (optional) → we’ll compute from right vector
    right = R_c2w[:, 0]
    roll = np.degrees(np.arctan2(right[1], R_c2w[1, 1]))

    return yaw, pitch, roll


def validate_rig_z_y_axis_angles(rig_poses: List[np.ndarray], expected_pitch_angles: List[float], yaw_steps: int, tolerance_deg: float = 2.0) -> None:
    """
    Validate that the angle between Z-axis (forward) and Y-axis (up) matches expected geometry.
    For a camera with pitch angle P, the Z-Y angle should be approximately 90° - P.
    
    Args:
        rig_poses: List of 4x4 camera poses for one rig
        expected_pitch_angles: List of pitch angles (e.g., [-30, 0, +30])
        yaw_steps: Number of yaw steps per pitch level
        tolerance_deg: Tolerance for angle validation
    """
    print(f"\n🔍 Validating Z-Y axis angles for rig ({len(rig_poses)} cameras)")
    
    for i, pose in enumerate(rig_poses):
        # Extract the camera axes
        y_axis = pose[:3, 1]  # Up vector
        z_axis = pose[:3, 2]  # Forward vector
        
        # Calculate angle between Y and Z axes
        dot_product = np.dot(y_axis, z_axis)
        dot_product = np.clip(dot_product, -1.0, 1.0)  # Ensure valid range for arccos
        angle_rad = np.arccos(dot_product)  # Remove abs() to get true angle (0°-180°)
        angle_deg = np.degrees(angle_rad)
        
        # Determine which pitch level this camera belongs to
        pitch_level = i // yaw_steps
        yaw_index = i % yaw_steps
        expected_pitch = expected_pitch_angles[pitch_level] if pitch_level < len(expected_pitch_angles) else expected_pitch_angles[0]
        
        # Expected Z-Y angle: 90° modified by pitch
        # For negative pitch (tilted down), Z-Y angle should be > 90°
        # For positive pitch (tilted up), Z-Y angle should be < 90°
        expected_angle = 90.0 - expected_pitch  # This gives us the expected Z-Y angle
        
        angle_error = abs(angle_deg - expected_angle)
        status = "✅" if angle_error <= tolerance_deg else "❌"
        
        print(f"  {status} Cam {i:02d} (pitch={expected_pitch:+.0f}°, yaw={yaw_index}): Z-Y angle = {angle_deg:.1f}° (expected ~{expected_angle:.1f}°, error = {angle_error:.1f}°)")
        print(f"       Y=[{y_axis[0]:+.3f}, {y_axis[1]:+.3f}, {y_axis[2]:+.3f}], Z=[{z_axis[0]:+.3f}, {z_axis[1]:+.3f}, {z_axis[2]:+.3f}]")


# =================================================================================
# CORE PIPELINE FUNCTIONS
# =================================================================================

def convert_w2c_to_c2w(w2c_pose_3x4: np.ndarray) -> np.ndarray:
    """
    Converts a 3x4 World-to-Camera (W2C) matrix to a 4x4 Camera-to-World (C2W) matrix.
    
    Args:
        w2c_pose_3x4 (np.ndarray): The 3x4 world-to-camera extrinsic matrix.
                                   [R_w2c | t_w2c]
    Returns:
        np.ndarray: The 4x4 camera-to-world extrinsic matrix.
                    [R_c2w | t_c2w]
                    [  0   |   1  ]
    """
    # Ensure input is float32
    w2c_pose_3x4 = w2c_pose_3x4.astype(np.float32)

    R_w2c = w2c_pose_3x4[:3, :3]
    t_w2c = w2c_pose_3x4[:3, 3]

    R_c2w = R_w2c.T
    t_c2w = -R_c2w @ t_w2c

    c2w_pose_4x4 = np.eye(4, dtype=np.float32)
    c2w_pose_4x4[:3, :3] = R_c2w
    c2w_pose_4x4[:3, 3] = t_c2w
    return c2w_pose_4x4


def expand_anchor_to_rig(
    anchor_extrinsic_w2c: np.ndarray, 
    anchor_intrinsic: np.ndarray,
    pitch_angles: List[float], 
    yaw_steps: int, 
    progress_callback: Optional[Callable] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Expands VGGT-predicted anchor poses into a full rig using direct coordinate system approach.
    
    Two-stage process:
    1. Pre-tilt anchor's coordinate system by global pitch (e.g., -30°)
    2. Build rig cameras with yaw rotation + individual pitch around each camera's X-axis

    Args:
        anchor_extrinsic_w2c (np.ndarray): Array of 3x4 world-to-camera matrices for VGGT anchors.
        anchor_intrinsic (np.ndarray): Array of 3x3 intrinsic matrices for VGGT anchors.
        pitch_angles (List[float]): List of individual pitch angles in degrees for each camera.
        yaw_steps (int): Number of yaw steps for the rig (360° / yaw_steps spacing).
        progress_callback (Optional[Callable]): Optional callback for progress updates.

    Returns:
        Tuple[np.ndarray, np.ndarray]: 
            - Expanded extrinsic matrices (C2W) of shape (N, 3, 4)
            - Expanded intrinsic matrices of shape (N, 3, 3)
    """
    num_anchors = len(anchor_extrinsic_w2c)
    target_dtype = anchor_extrinsic_w2c.dtype
    
    print(f"\n🎯 PITCH ANGLES VALIDATION:")
    print(f"   📥 Received from UI: pitch_angles = {pitch_angles}")
    print(f"   📊 Will generate: {len(pitch_angles)} pitch levels × {yaw_steps} yaw steps = {len(pitch_angles) * yaw_steps} cameras per anchor")
    
    if progress_callback:
        progress_callback(f"   🚀 Starting rig expansion: {num_anchors} anchors, pitch_angles={pitch_angles}")

    final_expanded_poses_c2w = []
    
    for anchor_idx in range(num_anchors):
        # Convert VGGT's 3x4 W2C anchor pose to 4x4 C2W
        anchor_pose_w2c_3x4 = anchor_extrinsic_w2c[anchor_idx]
        anchor_pose_c2w_4x4 = convert_w2c_to_c2w(anchor_pose_w2c_3x4)
        
        # Extract anchor's coordinate system
        anchor_position = anchor_pose_c2w_4x4[:3, 3]
        anchor_right = anchor_pose_c2w_4x4[:3, 0]   # X axis
        anchor_up = anchor_pose_c2w_4x4[:3, 1]      # Y axis  
        anchor_forward = anchor_pose_c2w_4x4[:3, 2] # Z axis
        
        # Generate rig cameras for each pitch level
        yaws = np.linspace(0, 360, yaw_steps, endpoint=False)
        
        for pitch_idx, individual_pitch in enumerate(pitch_angles):
            # Calculate the appropriate global tilt for this pitch level
            # This counter-balances the extraction pitch bias
            global_pitch = -individual_pitch  # Inverse the pitch (e.g., -30° becomes +30°)
            global_pitch_rad = np.radians(global_pitch)
            cos_pitch, sin_pitch = np.cos(global_pitch_rad), np.sin(global_pitch_rad)
            
            # Create coordinate system for this pitch level
            tilted_right = anchor_right  # X axis unchanged
            tilted_up = (anchor_up * cos_pitch + anchor_forward * sin_pitch)      # Tilted Y axis
            tilted_forward = (-anchor_up * sin_pitch + anchor_forward * cos_pitch) # Tilted Z axis
            
            for yaw_idx, yaw in enumerate(yaws):
                # CRITICAL: Preserve original VGGT anchor orientation for the first camera of first pitch
                if pitch_idx == 0 and yaw_idx == 0:
                    # First camera in rig = Original VGGT anchor pose (unchanged)
                    final_expanded_poses_c2w.append(anchor_pose_c2w_4x4)
                    continue
                
                # Generate rig camera using coordinate system approach
                yaw_rad = np.radians(yaw)
                cos_yaw, sin_yaw = np.cos(yaw_rad), np.sin(yaw_rad)
                
                # Yaw rotation around tilted up-axis
                camera_right = tilted_right * cos_yaw + tilted_forward * sin_yaw
                camera_up = tilted_up  # Unchanged by yaw
                camera_forward = -tilted_right * sin_yaw + tilted_forward * cos_yaw
                
                # Apply the individual pitch rotation around camera's right axis (X)
                individual_pitch_rad = np.radians(individual_pitch)
                cos_ind_pitch, sin_ind_pitch = np.cos(individual_pitch_rad), np.sin(individual_pitch_rad)
                
                final_right = camera_right  # X unchanged
                final_up = camera_up * cos_ind_pitch + camera_forward * sin_ind_pitch
                final_forward = -camera_up * sin_ind_pitch + camera_forward * cos_ind_pitch
                
                # Build final camera pose
                final_pose = np.eye(4, dtype=target_dtype)
                final_pose[:3, 0] = final_right
                final_pose[:3, 1] = final_up  
                final_pose[:3, 2] = final_forward
                final_pose[:3, 3] = anchor_position  # All cameras at anchor position
                
                final_expanded_poses_c2w.append(final_pose)
        
        # Debug visualization for anchor 24 (last anchor, index 23)
        if anchor_idx == 23:  # Last anchor (24th)
            print(f"\n📐 DEBUG: Visualizing Y and Z axes for Anchor {anchor_idx + 1} rig:")
            anchor_rig_poses = final_expanded_poses_c2w[-len(pitch_angles) * yaw_steps:]
            for i, pose in enumerate(anchor_rig_poses):
                y_axis = pose[:3, 1]  # Y axis (up)
                z_axis = pose[:3, 2]  # Z axis (forward/camera direction)
                
                pitch_level = i // yaw_steps
                yaw_index = i % yaw_steps
                expected_pitch = pitch_angles[pitch_level] if pitch_level < len(pitch_angles) else pitch_angles[0]
                
                print(f"  Cam {i:02d} (pitch={expected_pitch:+.0f}°, yaw={yaw_index}): "
                      f"Y=[{y_axis[0]:+.3f}, {y_axis[1]:+.3f}, {y_axis[2]:+.3f}], "
                      f"Z=[{z_axis[0]:+.3f}, {z_axis[1]:+.3f}, {z_axis[2]:+.3f}]")
        
        # Validate Z-Y axis angles for this anchor's rig (DISABLED - validation logic is incorrect)
        # anchor_rig_poses = final_expanded_poses_c2w[-len(pitch_angles) * yaw_steps:]
        # validate_rig_z_y_axis_angles(anchor_rig_poses, pitch_angles, yaw_steps)
        
        # Progress reporting
        if progress_callback and (anchor_idx + 1) % 5 == 0:
            progress_callback(f"   ✅ Processed rig for anchor {anchor_idx + 1}/{num_anchors}")
        elif anchor_idx + 1 == num_anchors:  # Always show completion
            if progress_callback:
                progress_callback(f"   ✅ Processed rig for anchor {anchor_idx + 1}/{num_anchors}")

    # Convert list of 4x4 C2W matrices to single (N, 3, 4) C2W array
    final_expanded_extrinsic_c2w_3x4 = np.array([p[:3, :4] for p in final_expanded_poses_c2w], dtype=target_dtype)
    
    # Tile the first anchor's intrinsic matrix for all expanded cameras
    expanded_intrinsic = np.tile(anchor_intrinsic[0:1], (len(final_expanded_poses_c2w), 1, 1)).astype(target_dtype)
    
    if progress_callback:
        progress_callback(f"   ✅ Rig expansion complete: {len(final_expanded_extrinsic_c2w_3x4)} total cameras with pitch_angles={pitch_angles}")
        
    return final_expanded_extrinsic_c2w_3x4, expanded_intrinsic


# =================================================================================
# UNIFIED FILTERING PIPELINE (Retained and simplified)
# =================================================================================

def create_sparse_point_cloud_for_3dgs(points, colors, confidences, target_points=150000, progress_callback=None):
    """
    Create an intelligent sparse point cloud optimized for Gaussian Splatting training.
    Uses spatial voxel grid + confidence weighting for optimal point distribution.
    """
    if progress_callback:
        progress_callback(f"🎯 Creating sparse point cloud for 3DGS: {len(points):,} → {target_points:,} points")
    
    if len(points) <= target_points:
        if progress_callback:
            progress_callback(f"✅ Already sparse enough: using all {len(points):,} points")
        return points, colors, confidences
    
    # 1. Calculate bounding box and create voxel grid
    min_bounds = np.min(points, axis=0)
    max_bounds = np.max(points, axis=0)
    bbox_size = max_bounds - min_bounds
    
    # Calculate voxel size to get approximately target_points voxels
    # Aim for slightly more voxels than target points to allow confidence-based selection
    voxels_per_dim = int(np.ceil((target_points * 1.5) ** (1/3)))
    voxel_size = bbox_size / voxels_per_dim
    
    if progress_callback:
        progress_callback(f"📦 Using {voxels_per_dim}³ voxel grid, voxel size: {voxel_size}")
    
    # 2. Assign points to voxels
    voxel_indices = np.floor((points - min_bounds) / voxel_size).astype(int)
    voxel_indices = np.clip(voxel_indices, 0, voxels_per_dim - 1)
    
    # Create unique voxel keys
    voxel_keys = voxel_indices[:, 0] * (voxels_per_dim ** 2) + voxel_indices[:, 1] * voxels_per_dim + voxel_indices[:, 2]
    
    # 3. Group points by voxel and select best representative from each
    unique_voxels = np.unique(voxel_keys)
    selected_indices = []
    
    for voxel_key in unique_voxels:
        voxel_mask = (voxel_keys == voxel_key)
        voxel_points_idx = np.where(voxel_mask)[0]
        
        if len(voxel_points_idx) == 1:
            # Single point in voxel - always keep it
            selected_indices.append(voxel_points_idx[0])
        else:
            # Multiple points - select based on confidence + spatial distribution
            voxel_confidences = confidences[voxel_points_idx]
            
            # Strategy: Take highest confidence point, unless there are many points
            # in which case take a few to preserve detail
            if len(voxel_points_idx) <= 3:
                # Few points - take the best one
                best_idx = voxel_points_idx[np.argmax(voxel_confidences)]
                selected_indices.append(best_idx)
            else:
                # Many points - take top 2-3 based on confidence
                n_keep = min(3, max(1, len(voxel_points_idx) // 10))
                top_indices = voxel_points_idx[np.argsort(voxel_confidences)[-n_keep:]]
                selected_indices.extend(top_indices)
    
    # 4. If we have too many points, do final confidence-based selection
    if len(selected_indices) > target_points:
        if progress_callback:
            progress_callback(f"🔄 Refining selection: {len(selected_indices)} → {target_points} points")
        
        selected_confidences = confidences[selected_indices]
        final_indices = np.array(selected_indices)[np.argsort(selected_confidences)[-target_points:]]
        selected_indices = final_indices.tolist()
    
    selected_indices = np.array(selected_indices)
    sparse_points = points[selected_indices]
    sparse_colors = colors[selected_indices]
    sparse_confidences = confidences[selected_indices]
    
    if progress_callback:
        progress_callback(f"✅ Created sparse point cloud: {len(sparse_points):,} points")
        progress_callback(f"   Confidence range: {sparse_confidences.min():.3f} - {sparse_confidences.max():.3f}")
    
    return sparse_points, sparse_colors, sparse_confidences


def apply_quality_filters(predictions, conf_thres=50.0, mask_sky=False, mask_black_bg=False, mask_white_bg=False, 
                         prediction_mode="Depthmap and Camera Branch", progress_callback=None, sky_sensitivity_threshold=32):
    """
    Apply quality-based filters (confidence, sky, background) to the point cloud.
    This is the first stage of the filtering pipeline, focusing on point quality rather than count.
    
    Filter sequence:
    1. Sky filtering (if enabled) - Uses soft confidence multiplication like visual_util
    2. Confidence filtering (always applied) - Percentile-based threshold
    3. Background filters (if enabled) - Black/white background masking  
    
    Args:
        predictions (dict): VGGT prediction data
        conf_thres (float): Confidence threshold as percentage (0-100)
        mask_sky (bool): Apply sky segmentation mask
        mask_black_bg (bool): Filter out black background pixels
        mask_white_bg (bool): Filter out white background pixels  
        prediction_mode (str): Prediction branch to use ("Pointmap" vs "Depthmap")
        progress_callback (callable): Progress reporting function
        sky_sensitivity_threshold (float): Sky detection sensitivity threshold
        
    Returns:
        tuple: (filtered_points, filtered_colors, filtered_confidences)
    """
    if progress_callback:
        progress_callback("🔄 Starting quality filtering pipeline...")
        progress_callback(f"   Settings: conf={conf_thres}%, sky={mask_sky}, black_bg={mask_black_bg}, white_bg={mask_white_bg}")
    
    # Step 1: Extract data based on prediction mode (same as filter_points_like_visualization)
    if "Pointmap" in prediction_mode and "world_points" in predictions:
        world_points = predictions["world_points"]
        confidence = predictions.get("world_points_conf", np.ones_like(world_points[..., 0]))
        if progress_callback:
            progress_callback("📊 Using Pointmap branch data")
    else:
        world_points = predictions["world_points_from_depth"]
        confidence = predictions.get("depth_conf", np.ones_like(world_points[..., 0]))
        if progress_callback:
            progress_callback("📊 Using Depthmap branch data")
    
    # Get colors - Handle format conversion exactly like visual_util.py and original VGGT
    if "images" in predictions:
        images = predictions["images"]
        # Handle different image formats - check if images need transposing (like visual_util.py line 154-157)
        if images.ndim == 4 and images.shape[1] == 3:  # NCHW format
            colors_rgb = np.transpose(images, (0, 2, 3, 1))  # Convert to NHWC like original VGGT
        else:  # Assume already in NHWC format
            colors_rgb = images
    else:
        S, H, W = world_points.shape[:3]
        colors_rgb = np.ones((S, H, W, 3), dtype=np.float32) * 0.5
    
    S, H, W = world_points.shape[:3]
    if progress_callback:
        progress_callback(f"🔍 Input data: {S*H*W:,} total points")
    
    # Step 2: Sky filtering FIRST (if enabled) - Uses soft confidence multiplication like visual_util
    if mask_sky:
        if progress_callback:
            progress_callback("☁️ Applying sky segmentation...")
        try:
            import onnxruntime
            import tempfile
            import cv2
            
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_images_dir = os.path.join(temp_dir, "images")
                os.makedirs(temp_images_dir, exist_ok=True)
                
                # Save images for sky segmentation
                image_list = []
                for i, img in enumerate(colors_rgb):
                    img_path = os.path.join(temp_images_dir, f"image_{i:04d}.png")
                    image_list.append(img_path)
                    # Convert from 0-1 float to 0-255 uint8 for cv2
                    img_uint8 = (img * 255).astype(np.uint8)
                    cv2.imwrite(img_path, cv2.cvtColor(img_uint8, cv2.COLOR_RGB2BGR))
                
                # Get sky model (same logic as filter_points_like_visualization)
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                local_skyseg_paths = [
                    os.path.join(project_root, "models", "skyseg.onnx"),
                    os.path.join(project_root, "skyseg.onnx"), 
                    "skyseg.onnx"
                ]
                
                local_skyseg_path = None
                for path in local_skyseg_paths:
                    if os.path.exists(path):
                        local_skyseg_path = path
                        break
                
                skyseg_path = os.path.join(temp_dir, "skyseg.onnx")
                
                if local_skyseg_path:
                    if progress_callback:
                        progress_callback(f"✅ Using cached skyseg.onnx from {local_skyseg_path}")
                    import shutil
                    shutil.copy(local_skyseg_path, skyseg_path)
                else:
                    # Download (same logic as existing)
                    cached_model_path = os.path.join(project_root, "models", "skyseg.onnx")
                    os.makedirs(os.path.dirname(cached_model_path), exist_ok=True)
                    if progress_callback:
                        progress_callback("⬇️ Downloading skyseg.onnx...")
                    
                    def download_file_from_url(url, filename):
                        try:
                            import requests
                            response = requests.get(url, allow_redirects=False)
                            if response.status_code == 302:
                                redirect_url = response.headers["Location"]
                                response = requests.get(redirect_url, stream=True)
                            else:
                                response = requests.get(url, stream=True)
                            response.raise_for_status()
                            
                            with open(filename, "wb") as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            return True
                        except Exception as e:
                            if progress_callback:
                                progress_callback(f"❌ Download error: {e}")
                            return False
                    
                    download_success = download_file_from_url(
                        "https://huggingface.co/JianyuanWang/skyseg/resolve/main/skyseg.onnx",
                        cached_model_path
                    )
                    
                    if download_success:
                        import shutil
                        shutil.copy(cached_model_path, skyseg_path)
                        if progress_callback:
                            progress_callback(f"✅ Downloaded and cached to {cached_model_path}")
                    else:
                        if progress_callback:
                            progress_callback("❌ Sky model download failed, skipping sky filter")
                        mask_sky = False
                
                if mask_sky:
                    # Run sky segmentation
                    def segment_sky_unified(image_path, onnx_session, sky_sensitivity_threshold):
                        image = cv2.imread(image_path)
                        temp_image = image.copy()
                        resize_image = cv2.resize(temp_image, dsize=(320, 320))
                        x = cv2.cvtColor(resize_image, cv2.COLOR_BGR2RGB)
                        x = np.array(x, dtype=np.float32)
                        mean = [0.485, 0.456, 0.406]
                        std = [0.229, 0.224, 0.225]
                        x = (x / 255 - mean) / std
                        x = x.transpose(2, 0, 1)
                        x = x.reshape(-1, 3, 320, 320).astype("float32")
                        
                        input_name = onnx_session.get_inputs()[0].name
                        output_name = onnx_session.get_outputs()[0].name
                        onnx_result = onnx_session.run([output_name], {input_name: x})
                        
                        onnx_result = np.array(onnx_result).squeeze()
                        min_value = np.min(onnx_result)
                        max_value = np.max(onnx_result)
                        onnx_result = (onnx_result - min_value) / (max_value - min_value)
                        onnx_result *= 255
                        onnx_result = onnx_result.astype("uint8")
                        
                        result_map_original = cv2.resize(onnx_result, (image.shape[1], image.shape[0]))
                        
                        # Create mask (255 = non-sky, 0 = sky) with threshold of 32 like visual_util
                        output_mask = np.zeros_like(result_map_original)
                        output_mask[result_map_original < sky_sensitivity_threshold] = 255  # Use same threshold as visual_util, this is also passed on to UI
                        
                        return output_mask
                    
                    skyseg_session = onnxruntime.InferenceSession(skyseg_path)
                    sky_mask_list = []
                    
                    for img_path in image_list:
                        sky_mask = segment_sky_unified(img_path, skyseg_session, sky_sensitivity_threshold)
                        if sky_mask.shape[0] != H or sky_mask.shape[1] != W:
                            sky_mask = cv2.resize(sky_mask, (W, H))
                        sky_mask_list.append(sky_mask)
                    
                    sky_mask_array = np.array(sky_mask_list)
                    sky_mask_binary = (sky_mask_array > 0.1).astype(np.float32)
                    
                    # Apply sky mask using soft confidence multiplication (exactly like visual_util line 144)
                    original_points = np.sum(confidence > 1e-5)
                    confidence = confidence * sky_mask_binary
                    sky_filtered_points = np.sum(confidence > 1e-5)
                    
                    if progress_callback:
                        progress_callback(f"☁️ Sky filter: {original_points:,} → {sky_filtered_points:,} points")
        
        except (ImportError, Exception) as e:
            if progress_callback:
                progress_callback(f"❌ Sky segmentation error: {e}")
            mask_sky = False
    
    # Step 3: Flatten data for remaining filters
    world_points_flat = world_points.reshape(-1, 3)
    colors_flat = colors_rgb.reshape(-1, 3)
    conf_flat = confidence.flatten()
    
    # Step 4: Apply confidence threshold (percentile-based, same as both existing functions)
    if conf_thres == 0.0:
        conf_threshold = 0.0
    else:
        conf_threshold = np.percentile(conf_flat, conf_thres)
    
    conf_mask = (conf_flat >= conf_threshold) & (conf_flat > 1e-5)
    conf_filtered_count = np.sum(conf_mask)
    
    if progress_callback:
        progress_callback(f"📈 Confidence filter ({conf_thres}% = {conf_threshold:.4f}): {conf_filtered_count:,} points")
    
    # Step 5: Apply background filters (if enabled)
    if mask_black_bg:
        # Convert colors to uint8 for background filtering
        colors_uint8 = (colors_flat * 255).astype(np.uint8)
        black_bg_mask = colors_uint8.sum(axis=1) >= 16
        conf_mask = conf_mask & black_bg_mask
        black_filtered_count = np.sum(conf_mask)
        if progress_callback:
            progress_callback(f"🖤 Black background filter: {black_filtered_count:,} points")
    
    if mask_white_bg:
        colors_uint8 = (colors_flat * 255).astype(np.uint8)
        white_bg_mask = ~((colors_uint8[:, 0] > 240) & (colors_uint8[:, 1] > 240) & (colors_uint8[:, 2] > 240))
        conf_mask = conf_mask & white_bg_mask
        white_filtered_count = np.sum(conf_mask)
        if progress_callback:
            progress_callback(f"🤍 White background filter: {white_filtered_count:,} points")
    
    # Step 6: Extract valid points
    valid_indices = np.where(conf_mask & np.all(np.isfinite(world_points_flat), axis=1))[0]
    
    if len(valid_indices) == 0:
        if progress_callback:
            progress_callback("❌ No points remaining after filtering!")
        return np.array([]).reshape(0, 3), np.array([]).reshape(0, 3), np.array([])
    
    filtered_points = world_points_flat[valid_indices]
    filtered_colors = colors_flat[valid_indices]
    filtered_conf = conf_flat[valid_indices]
    
    if progress_callback:
        progress_callback(f"✅ Quality filtering complete: {len(filtered_points):,} points")
    
    # Step 7: Final color conversion (exactly like visual_util line 158)
    # Add color monitoring for debugging
    max_color = np.max(filtered_colors)
    min_color = np.min(filtered_colors)
    overflow_count = np.sum(filtered_colors > 1.0)
    underflow_count = np.sum(filtered_colors < 0.0)
    
    if progress_callback:
        progress_callback(f"🎨 Color range before uint8 conversion: [{min_color:.3f}, {max_color:.3f}]")
        if overflow_count > 0:
            progress_callback(f"   ⚠️ OVERFLOW detected: {overflow_count:,} pixels > 1.0 ({100*overflow_count/filtered_colors.size:.2f}%)")
        if underflow_count > 0:
            progress_callback(f"   ⚠️ UNDERFLOW detected: {underflow_count:,} pixels < 0.0 ({100*underflow_count/filtered_colors.size:.2f}%)")
        if overflow_count == 0 and underflow_count == 0:
            progress_callback(f"   ✅ Color range is valid [0.0, 1.0]")
    
    # Original working color conversion (exactly like visual_util.py and demo_colmap.py)
    filtered_colors = (filtered_colors * 255).astype(np.uint8)
    
    if progress_callback:
        progress_callback(f"✅ Unified filtering complete: {len(filtered_points):,} points")
        progress_callback(f"   Confidence range: {filtered_conf.min():.4f} - {filtered_conf.max():.4f}")
    
    return filtered_points, filtered_colors, filtered_conf


def apply_sparse_filter(points, colors, confidences, sparse_target_points=150000, progress_callback=None):
    """
    Apply sparse point cloud filtering to reduce point count while maintaining spatial distribution.
    This is the final stage of the filtering pipeline, focusing on point count optimization.
    
    Args:
        points (np.ndarray): N x 3 array of 3D points
        colors (np.ndarray): N x 3 array of RGB colors
        confidences (np.ndarray): N array of confidence values
        sparse_target_points (int): Target number of points for sparse filtering
        progress_callback (callable): Progress reporting function
        
    Returns:
        tuple: (sparse_points, sparse_colors, sparse_confidences)
    """
    if len(points) <= sparse_target_points:
        if progress_callback:
            progress_callback(f"ℹ️ Sparse filter not needed: {len(points):,} ≤ {sparse_target_points:,}")
        return points, colors, confidences
    
    if progress_callback:
        progress_callback(f"🎯 Applying sparse filter: {len(points):,} → {sparse_target_points:,} points")
    
    # Use the existing sparse filtering algorithm
    sparse_points, sparse_colors, sparse_conf = create_sparse_point_cloud_for_3dgs(
        points, colors, confidences, 
        target_points=sparse_target_points, 
        progress_callback=progress_callback
    )
    
    return sparse_points, sparse_colors, sparse_conf


def apply_rig_optimization(points, colors, confidences, predictions_dict, use_anchor_rig=False, 
                          rig_optimization_min_points=500000, progress_callback=None):
    """
    Apply rig camera optimization to improve point distribution for anchor+rig mode.
    This is the middle stage of the filtering pipeline, between quality and count filtering.
    
    Args:
        points (np.ndarray): N x 3 array of 3D points
        colors (np.ndarray): N x 3 array of RGB colors  
        confidences (np.ndarray): N array of confidence values
        predictions_dict (dict): VGGT predictions containing camera parameters
        use_anchor_rig (bool): Whether anchor+rig mode is active
        rig_optimization_min_points (int): Minimum points required to trigger optimization
        progress_callback (callable): Progress reporting function
        
    Returns:
        tuple: (optimized_points, optimized_colors, optimized_confidences)
    """
    if not use_anchor_rig:
        if progress_callback:
            progress_callback("ℹ️ Rig optimization skipped - not in anchor+rig mode")
        return points, colors, confidences
    
    if predictions_dict is None:
        if progress_callback:
            progress_callback("⚠️ Rig optimization skipped - no predictions available")
        return points, colors, confidences
        
    if len(points) <= rig_optimization_min_points:
        if progress_callback:
            progress_callback(f"ℹ️ Rig optimization skipped - insufficient points: {len(points):,} ≤ {rig_optimization_min_points:,}")
        return points, colors, confidences
    
    if progress_callback:
        progress_callback("🎯 Optimizing 3D point distribution for anchor+rig mode...")
    
    # Apply intelligent point sampling to ensure good rig camera coverage
    optimized_points, optimized_colors, _ = optimize_points_for_rig_coverage(
        points, colors, predictions_dict.get("depth_conf", np.ones(points.shape[0])), 
        predictions_dict, use_anchor_rig, progress_callback
    )
    
    if progress_callback:
        progress_callback(f"✅ Rig optimization complete. {len(optimized_points):,} points selected.")
    
    return optimized_points, optimized_colors, confidences  # Return original confidences since rig optimization doesn't modify them


# =================================================================================
# VGGT PROCESSOR CLASS (Simplified)
# =================================================================================

class VGGTProcessor:
    """
    Enhanced VGGT integration for camera pose estimation and 3D reconstruction.
    Simplified to focus on VGGT inference only.
    """
    
    def __init__(self, models_dir: str = None, vggt_path: str = None):
        self.models_dir = models_dir or (Path(__file__).parent.parent / "models").as_posix()
        self.vggt_path = vggt_path
        self.model = None
        self.device = None
        self.dtype = None
        self.is_initialized = False
        
    def initialize(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Initialize VGGT model and GPU resources.
        
        This function has been corrected to always return a tuple (bool, str)
        to prevent a TypeError in the calling function.
        """
        if not VGGT_AVAILABLE:
            status_msg = "VGGT not available - check installation"
            if progress_callback:
                progress_callback(status_msg)
            # CORRECTED: Return a tuple instead of a single value
            return False, status_msg 
            
        try:
            if progress_callback:
                progress_callback("Initializing VGGT...")
            
            if self.vggt_path:
                add_vggt_to_path(self.vggt_path)
            
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            capability = torch.cuda.get_device_capability() if self.device == "cuda" else (0, 0)
            self.dtype = torch.bfloat16 if capability[0] >= 8 else torch.float16
            if progress_callback:
                progress_callback(f"Using device: {self.device} ({self.dtype})")
                
            model_path = Path(self.models_dir) / "model.pt"
            if model_path.exists():
                if progress_callback:
                    progress_callback(f"Loading local model from {model_path}")
                self.model = VGGT()
                state_dict = torch.load(model_path, map_location=self.device)
                self.model.load_state_dict(state_dict)
            else:
                if progress_callback:
                    progress_callback("Downloading VGGT model from Hugging Face...")
                self.model = VGGT.from_pretrained("facebook/VGGT-1B")
                
            self.model.to(self.device)
            self.model.eval()
            
            status_msg = "VGGT model initialized successfully"
            if progress_callback:
                progress_callback(status_msg)
                
            self.is_initialized = True
            # CORRECTED: Return a tuple instead of a single value
            return True, status_msg
            
        except Exception as e:
            error_msg = f"Failed to initialize VGGT: {str(e)}"
            if progress_callback:
                progress_callback(error_msg)
            print(f"{error_msg}\n{traceback.format_exc()}")
            # CORRECTED: Return a tuple instead of a single value
            return False, error_msg
    
    def process_vggt_inference(self, image_paths: List[str], progress_callback: Optional[Callable] = None, cancel_event: Optional[threading.Event] = None) -> Dict:
        """
        Runs VGGT inference to get raw predictions (extrinsic, intrinsic, depth, confidence).
        Returns poses in World-to-Camera (W2C) format.
        """
        if not self.is_initialized:
            raise RuntimeError("VGGTProcessor not initialized. Call initialize() first.")
        
        if cancel_event and cancel_event.is_set():
            return {"success": False, "error": "Processing cancelled"}

        # GPU memory monitoring and management (like old implementation)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if progress_callback:
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                gpu_allocated = torch.cuda.memory_allocated(0) / (1024**3)
                progress_callback(f"🖥️ GPU: {gpu_memory:.1f}GB total, {gpu_allocated:.1f}GB allocated")
        
        # Memory management and image count check
        import gc
        gc.collect()
        
        # Check image count and warn if large
        if len(image_paths) > 50:
            if progress_callback:
                progress_callback(f"⚠️ Processing {len(image_paths)} images - this may require significant GPU memory")

        if progress_callback: progress_callback(f"Loading and preprocessing {len(image_paths)} images for VGGT...")
        images = load_and_preprocess_images(image_paths).to(self.device)
        if progress_callback: 
            progress_callback(f"✅ Loaded {len(image_paths)} images to GPU.")
            
            # Check GPU memory after loading (like old implementation)
            if torch.cuda.is_available():
                gpu_allocated = torch.cuda.memory_allocated(0) / (1024**3)
                progress_callback(f"📊 GPU memory after loading: {gpu_allocated:.1f}GB allocated")

        if progress_callback: progress_callback("Running VGGT inference...")
        with torch.no_grad():
            with torch.amp.autocast('cuda', dtype=self.dtype): # Using AMP for efficiency
                predictions = self.model(images)
        if progress_callback: progress_callback("✅ VGGT inference complete.")

        # Convert pose encoding to camera parameters (extrinsic in W2C, intrinsic)
        extrinsic_w2c, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])
        
        # CRITICAL FIX: Use same data format as old version with squeeze operations
        processed_predictions = {}
        processed_predictions["extrinsic"] = extrinsic_w2c.cpu().numpy().squeeze(0).astype(np.float32) # W2C 3x4 - squeeze like old version
        processed_predictions["intrinsic"] = intrinsic.cpu().numpy().squeeze(0).astype(np.float32) # Squeeze like old version
        
        # Process other tensors with conditional squeezing (like old version)
        for key in ["depth", "images"]:
            if key in predictions:
                tensor_cpu = predictions[key].cpu().numpy()
                # Remove batch dimension if present and shape allows (like old version logic)
                if tensor_cpu.ndim > 3 and tensor_cpu.shape[0] == 1:
                    processed_predictions[key] = tensor_cpu.squeeze(0).astype(np.float32)
                else:
                    processed_predictions[key] = tensor_cpu.astype(np.float32)
        
        # CRITICAL: Handle both Pointmap and Depthmap branches (like old implementation)
        # Pointmap branch (direct 3D points from model)
        if "world_points" in predictions:
            processed_predictions["world_points"] = predictions["world_points"].cpu().numpy().astype(np.float32)
        
        if "world_points_conf" in predictions:
            processed_predictions["world_points_conf"] = predictions["world_points_conf"].cpu().numpy().astype(np.float32)
        
        # NOTE: world_points_from_depth will be computed later in the pipeline when needed
        # Don't compute it here as it causes dimension issues and performance problems
        
        # Confidence maps (if available)
        if "depth_conf" in predictions:
            processed_predictions["depth_conf"] = predictions["depth_conf"].cpu().numpy().astype(np.float32)
        else:
            processed_predictions["depth_conf"] = np.ones_like(processed_predictions["depth"]).astype(np.float32)

        # Store image paths for COLMAP export (like old implementation)
        processed_predictions["image_names"] = image_paths

        # CRITICAL: Store raw tensor predictions for later unprojection (like old implementation)
        # The old implementation calls unproject_depth_map_to_point_map on the original tensor predictions
        processed_predictions["_raw_predictions"] = predictions  # Keep original PyTorch tensors
        
        # Final GPU memory cleanup and reporting (like old implementation)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if progress_callback:
                memory_allocated = torch.cuda.memory_allocated() / 1024**3
                memory_reserved = torch.cuda.memory_reserved() / 1024**3
                progress_callback(f"📊 Final GPU Memory: {memory_allocated:.1f}GB allocated, {memory_reserved:.1f}GB reserved")

        if progress_callback: progress_callback(f"✅ Extracted poses, depth, and point cloud data.")
        return processed_predictions

    def cleanup(self):
        if self.model is not None:
            del self.model
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        self.is_initialized = False


# =================================================================================
# GLB CREATION (Simplified and corrected)
# =================================================================================

def create_glb_scene(
    filtered_points: np.ndarray, 
    filtered_colors: np.ndarray, 
    camera_poses_c2w: np.ndarray, # Expects C2W 3x4 or 4x4 matrices
    camera_intrinsics: np.ndarray,
    output_glb_path: str, 
    show_camera_frustums: bool = True, 
    progress_callback: Optional[Callable] = None,
    original_anchor_count: int = 0, # For coloring in anchor+rig mode
    rig_yaw_steps: int = 0
) -> Optional[str]:
    """
    Creates a GLB file containing the 3D point cloud and camera frustums.
    This function expects final, correctly aligned camera-to-world (C2W) poses.
    
    Args:
        filtered_points (np.ndarray): N x 3 array of filtered 3D points.
        filtered_colors (np.ndarray): N x 3 array of filtered RGB colors (uint8).
        camera_poses_c2w (np.ndarray): M x 3 x 4 (or M x 4 x 4) array of camera-to-world poses.
        camera_intrinsics (np.ndarray): M x 3 x 3 array of intrinsic matrices.
        output_glb_path (str): Path to save the output GLB file.
        show_camera_frustums (bool): Whether to include camera frustums in the GLB.
        progress_callback (Optional[Callable]): Callback for progress updates.
        original_anchor_count (int): Number of original anchors, for coloring.
        rig_yaw_steps (int): Number of yaw steps per anchor, for coloring.

    Returns:
        Optional[str]: Path to the created GLB file if successful, None otherwise.
    """
    try:
        import trimesh
        from visual_util import integrate_camera_into_scene, apply_scene_alignment
        
        if progress_callback: progress_callback("🌐 Building GLB scene with filtered points and camera frustums...")
        
        scene = trimesh.Scene()
        
        # Add point cloud data to the scene
        if filtered_points.size > 0:
            point_cloud = trimesh.PointCloud(vertices=filtered_points, colors=filtered_colors)
            scene.add_geometry(point_cloud, geom_name="point_cloud")
            if progress_callback: progress_callback(f"   ✅ Added {len(filtered_points):,} points to GLB scene.")
        else:
            if progress_callback: progress_callback("   ⚠️ No points to add to GLB scene.")
            # Add a dummy point to prevent empty scene errors
            scene.add_geometry(trimesh.points.PointCloud([[0,0,0]], colors=[[255,255,255]]), geom_name="dummy_point_cloud")


        # Calculate scene_scale for camera frustums
        scene_scale = 1.0
        if filtered_points.size > 0:
            lower_percentile = np.percentile(filtered_points, 5, axis=0)
            upper_percentile = np.percentile(filtered_points, 95, axis=0)
            scene_scale = np.linalg.norm(upper_percentile - lower_percentile)
            if scene_scale < 0.1: scene_scale = 1.0 # Prevent extremely small scales
            
        if progress_callback: progress_callback(f"   📊 Calculated scene scale: {scene_scale:.3f}")

        # Add camera frustums
        if show_camera_frustums and camera_poses_c2w.size > 0:
            num_cameras = len(camera_poses_c2w)
            if progress_callback: progress_callback(f"   🎥 Adding {num_cameras} camera frustums...")
            
            # Define colors for anchor and rig cameras
            anchor_color = (255, 0, 0) # Red
            rig_colors = [
                (0, 255, 255), (0, 128, 0), (255, 165, 0), 
                (128, 0, 128), (0, 0, 255), (255, 255, 0),
            ] # Cyan, Green, Orange, Purple, Blue, Yellow

            for i in range(num_cameras):
                current_pose_c2w = camera_poses_c2w[i]
                if current_pose_c2w.shape == (3, 4):
                    # Convert 3x4 to 4x4 if needed for integrate_camera_into_scene
                    pose_4x4 = np.eye(4, dtype=current_pose_c2w.dtype)
                    pose_4x4[:3, :4] = current_pose_c2w
                else:
                    pose_4x4 = current_pose_c2w

                # Determine camera color (Anchor vs Rig)
                if original_anchor_count > 0 and rig_yaw_steps > 0:
                    # Anchor+Rig mode, color based on position in sequence
                    # An anchor camera is one of the original_anchor_count, and is the first in its rig group
                    is_anchor = (i < original_anchor_count * rig_yaw_steps) and (i % rig_yaw_steps == 0)
                    if is_anchor:
                        color = anchor_color
                        camera_label = f"Anchor_Frustum_{i//rig_yaw_steps}"
                    else:
                        color_idx = (i // rig_yaw_steps) % len(rig_colors) # Cycle per anchor group
                        color = rig_colors[color_idx]
                        camera_label = f"Rig_Frustum_{i//rig_yaw_steps}_{i%rig_yaw_steps}"
                else:
                    # Standard mode, or single anchor mode, use a default color
                    color = (0, 0, 255) # Blue for all cameras
                    camera_label = f"Camera_Frustum_{i}"
                
                integrate_camera_into_scene(scene, pose_4x4, color, scene_scale)
                if progress_callback and (i + 1) % 50 == 0:
                    progress_callback(f"   🎥 Added {i+1}/{num_cameras} frustums to scene.")
            if progress_callback: progress_callback(f"   ✅ All {num_cameras} frustums added.")

        # Add ORIGINAL VGGT anchor Y-axis visualization for anchor 24 (debug comparison)
        if original_anchor_count >= 24:
            anchor_24_idx = 23  # 0-indexed, so anchor 24 is at index 23
            if anchor_24_idx < len(camera_poses_c2w):
                if progress_callback: progress_callback("   🔍 Adding ORIGINAL VGGT anchor 24 Y-axis for comparison...")
                
                # Find the original VGGT anchor pose (first camera of anchor 24's rig)
                if rig_yaw_steps > 0:
                    original_anchor_idx = 23 * rig_yaw_steps  # First camera of anchor 24's rig
                else:
                    original_anchor_idx = 23  # Direct anchor index if no rig expansion
                
                if original_anchor_idx < num_cameras:
                    current_pose_c2w = camera_poses_c2w[original_anchor_idx]
                    if current_pose_c2w.shape == (3, 4):
                        pose_4x4 = np.eye(4, dtype=current_pose_c2w.dtype)
                        pose_4x4[:3, :4] = current_pose_c2w
                    else:
                        pose_4x4 = current_pose_c2w
                    
                    # Get camera position and Y-axis
                    cam_pos = pose_4x4[:3, 3]
                    y_axis = pose_4x4[:3, 1]  # Up vector from ORIGINAL VGGT anchor
                    
                    axis_length = scene_scale * 0.25  # Make original anchor axis longer for visibility
                    
                    # Create ORIGINAL VGGT Y axis line (BRIGHT RED for distinction)
                    y_end = cam_pos + y_axis * axis_length
                    orig_y_line = trimesh.path.Path3D(
                        entities=[trimesh.path.entities.Line([0, 1])],
                        vertices=[cam_pos, y_end]
                    )
                    orig_y_line.colors = [[255, 0, 0, 255]]  # BRIGHT RED for original VGGT Y-axis
                    scene.add_geometry(orig_y_line, geom_name="ORIGINAL_VGGT_anchor24_Y_axis")
                    
                    if progress_callback: progress_callback("   ✅ Added ORIGINAL VGGT anchor 24 Y-axis (RED line)")

        # Add Y and Z axis visualization for anchor 24 (debug visualization)
        if original_anchor_count >= 24 and rig_yaw_steps > 0:
            anchor_24_start_idx = 23 * rig_yaw_steps  # 0-indexed, so anchor 24 starts at index 23*rig_yaw_steps
            anchor_24_end_idx = anchor_24_start_idx + rig_yaw_steps
            
            if anchor_24_end_idx <= num_cameras:
                if progress_callback: progress_callback("   🔍 Adding Y/Z axis vectors for Anchor 24 debug...")
                
                axis_length = scene_scale * 0.15  # Make axes 15% of scene scale
                
                for cam_idx in range(anchor_24_start_idx, anchor_24_end_idx):
                    current_pose_c2w = camera_poses_c2w[cam_idx]
                    if current_pose_c2w.shape == (3, 4):
                        pose_4x4 = np.eye(4, dtype=current_pose_c2w.dtype)
                        pose_4x4[:3, :4] = current_pose_c2w
                    else:
                        pose_4x4 = current_pose_c2w
                    
                    # Get camera position and axes
                    cam_pos = pose_4x4[:3, 3]
                    y_axis = pose_4x4[:3, 1]  # Up vector
                    z_axis = pose_4x4[:3, 2]  # Forward vector
                    
                    # Create color-coded axes for each camera to identify reassociation issues
                    rig_cam_idx = cam_idx - anchor_24_start_idx
                    
                    # Use unique colors for each rig camera (0-5)
                    axis_colors = [
                        [255, 100, 100],  # Cam 0: Light Red
                        [255, 165, 0],    # Cam 1: Orange  
                        [255, 255, 100],  # Cam 2: Light Yellow
                        [100, 255, 100],  # Cam 3: Light Green
                        [100, 100, 255],  # Cam 4: Light Blue
                        [200, 100, 255],  # Cam 5: Light Purple
                    ]
                    
                    if rig_cam_idx < len(axis_colors):
                        color = axis_colors[rig_cam_idx]
                    else:
                        color = [255, 255, 255]  # White for unexpected cameras
                    
                    # Create Y axis line with unique color per camera
                    y_end = cam_pos + y_axis * axis_length
                    y_line = trimesh.path.Path3D(
                        entities=[trimesh.path.entities.Line([0, 1])],
                        vertices=[cam_pos, y_end]
                    )
                    y_line.colors = [[color[0], color[1], color[2], 255]]
                    scene.add_geometry(y_line, geom_name=f"Y_axis_anchor24_cam{rig_cam_idx}_color{rig_cam_idx}")
                    
                    # Create Z axis line with same color but thicker/different style
                    z_end = cam_pos + z_axis * axis_length * 1.2  # Make Z axis 20% longer
                    z_line = trimesh.path.Path3D(
                        entities=[trimesh.path.entities.Line([0, 1])],
                        vertices=[cam_pos, z_end]
                    )
                    # Make Z axis slightly darker version of same color
                    dark_color = [max(0, c - 50) for c in color]
                    z_line.colors = [[dark_color[0], dark_color[1], dark_color[2], 255]]
                    scene.add_geometry(z_line, geom_name=f"Z_axis_anchor24_cam{rig_cam_idx}_color{rig_cam_idx}_Z")
                
                if progress_callback: progress_callback("   ✅ Added Y/Z axis vectors for Anchor 24")

        # Apply final scene alignment
        if camera_poses_c2w.size > 0:
            if progress_callback: progress_callback("   🔄 Applying final scene alignment...")
            # Use the first C2W pose as reference for scene alignment
            first_camera_c2w = camera_poses_c2w[0]
            if first_camera_c2w.shape == (3,4):
                temp_c2w = np.eye(4, dtype=first_camera_c2w.dtype)
                temp_c2w[:3,:4] = first_camera_c2w
                first_camera_c2w = temp_c2w
            
            # Convert camera poses to the format expected by apply_scene_alignment
            extrinsics_matrices = np.zeros((num_cameras, 4, 4))
            for i, pose in enumerate(camera_poses_c2w):
                if pose.shape == (3, 4):
                    extrinsics_matrices[i, :3, :4] = pose
                    extrinsics_matrices[i, 3, 3] = 1
                else:
                    extrinsics_matrices[i] = pose
            scene = apply_scene_alignment(scene, extrinsics_matrices)
            if progress_callback: progress_callback("   ✅ Scene alignment applied.")
        else:
            if progress_callback: progress_callback("   ⚠️ Skipping scene alignment (no cameras).")
            
        # Export GLB
        scene.export(output_glb_path)
        if progress_callback: progress_callback(f"✅ GLB file created: {output_glb_path}")
        return output_glb_path
        
    except Exception as e:
        if progress_callback: progress_callback(f"❌ Error creating GLB: {e}")
        print(f"Error creating GLB: {e}\n{traceback.format_exc()}")
        return None

def create_simple_glb_viewer(glb_path, html_path, title):
    """Create a simple HTML viewer for GLB files using Three.js with local HTTP server"""
    import threading
    import http.server
    import socketserver
    import os
    from urllib.parse import quote
    
    glb_filename = os.path.basename(glb_path)
    glb_dir = os.path.dirname(glb_path)
    
    # Custom HTTP handler that adds CORS headers
    class CORSHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            super().end_headers()
    
    # Start a simple HTTP server in the GLB directory
    def start_server():
        os.chdir(glb_dir)
        port = 8089  # Use a specific port to avoid conflicts
        try:
            with socketserver.TCPServer(("", port), CORSHTTPRequestHandler) as httpd:
                print(f"🌐 Starting HTTP server on port {port} for GLB viewing...")
                httpd.timeout = 60  # Auto-close after 60 seconds of inactivity
                httpd.serve_forever()
        except Exception as e:
            print(f"HTTP server error: {e}")
    
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait a moment for server to start
    import time
    time.sleep(0.5)
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body {{ 
            margin: 20px; 
            padding: 20px; 
            font-family: Arial, sans-serif; 
            background: #f0f0f0; 
        }}
        .header {{
            background: #333;
            color: white;
            padding: 15px;
            border-radius: 8px 8px 0 0;
            margin-bottom: 0;
        }}
        .viewer-container {{
            background: #000;
            border-radius: 0 0 8px 8px;
            border: 2px solid #333;
            position: relative;
            width: 800px;
            height: 600px;
            margin: 0 auto;
        }}
        .controls-info {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            color: #ccc;
            font-size: 12px;
            z-index: 100;
            background: rgba(0,0,0,0.7);
            padding: 8px;
            border-radius: 4px;
        }}
        canvas {{ 
            width: 100%; 
            height: 100%; 
            border-radius: 0 0 6px 6px;
        }}
        .footer {{
            text-align: center;
            margin-top: 15px;
            color: #666;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h3 style="margin: 0;">{title}</h3>
        <p style="margin: 5px 0 0 0;">VGGT 3D Point Cloud Visualization</p>
    </div>
    
    <div class="viewer-container" id="viewer-container">
        <div class="controls-info">
            Mouse: Rotate | Wheel: Zoom | Right-click: Pan
        </div>
    </div>
    
    <div class="footer">
        <p>🌐 Auto-generated from VGGT processing • Close this tab when done</p>
    </div>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    
    <script>
        // Get container dimensions
        const container = document.getElementById('viewer-container');
        const width = 800;
        const height = 600;
        
        // Scene setup
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
        const renderer = new THREE.WebGLRenderer({{ antialias: true }});
        renderer.setSize(width, height);
        renderer.setClearColor(0x000000);
        container.appendChild(renderer.domElement);
        
        // 💡 Add proper lighting for vertex colors
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        scene.add(ambientLight);
        
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
        directionalLight.position.set(10, 10, 10);
        scene.add(directionalLight);
        
        // Controls
        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.25;
        
        // Load GLB via HTTP server (avoids CORS issues)
        const loader = new THREE.GLTFLoader();
        loader.load('http://localhost:8089/{glb_filename}', function(gltf) {{
            // 🎨 CRITICAL: Enable vertex colors for all meshes
            gltf.scene.traverse(function(child) {{
                if (child.isMesh) {{
                    console.log('Found mesh:', child.name, 'Geometry:', child.geometry.type);
                    
                    // Enable vertex colors on the material (match Gradio behavior)
                    if (child.material) {{
                        // Ensure material supports vertex colors
                        child.material.vertexColors = true;
                        child.material.needsUpdate = true;
                        
                        // Additional material properties for better color display
                        if (child.material.isMeshStandardMaterial) {{
                            child.material.metalness = 0.0;
                            child.material.roughness = 0.8;
                        }}
                        
                        console.log('Enabled vertex colors for mesh:', child.name, 'Material type:', child.material.type);
                    }}
                    
                    // Check if geometry has vertex colors
                    if (child.geometry.attributes.color) {{
                        console.log('Mesh has vertex colors:', child.name, child.geometry.attributes.color.count);
                    }} else {{
                        console.log('Mesh missing vertex colors:', child.name);
                    }}
                }}
            }});
            
            scene.add(gltf.scene);
            
            // Center and scale the model
            const box = new THREE.Box3().setFromObject(gltf.scene);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            
            const maxDim = Math.max(size.x, size.y, size.z);
            const scale = 10 / maxDim;
            gltf.scene.scale.multiplyScalar(scale);
            gltf.scene.position.sub(center.multiplyScalar(scale));
            
            // Position camera
            camera.position.set(15, 10, 15);
            camera.lookAt(0, 0, 0);
        }}, undefined, function(error) {{
            console.error('Error loading GLB:', error);
            document.querySelector('.controls-info').innerHTML = 'Error loading 3D model. Check browser console.';
        }});
        
        // Animation loop
        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}
        
        animate();
    </script>
</body>
</html>
"""
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
# =================================================================================
# COLMAP EXPORT (Simplified and corrected)
# =================================================================================

def write_colmap_files(
    output_dir: str, 
    filtered_points: np.ndarray, 
    filtered_colors: np.ndarray, 
    camera_poses_c2w: np.ndarray, # Expects C2W 3x4 or 4x4 matrices
    camera_intrinsics: np.ndarray, 
    image_names: List[str], 
    progress_callback: Optional[Callable] = None,
    colmap_image_width: int = 1920, # Desired output image dimensions for COLMAP
    colmap_image_height: int = 1920, # This should match actual image files COLMAP uses 
    use_anchor_rig: bool = False, # NEW: Flag for anchor+rig mode
    predictions_dict: Optional[Dict] = None # NEW: Pass full predictions for rig info
) -> Tuple[Optional[str], int]:
    """
    Writes COLMAP text format files (cameras.txt, images.txt, points3D.txt) using a
    dedicated writer thread to significantly speed up the process by overlapping
    string formatting (CPU) and file writing (I/O). This version correctly handles
    C2W to W2C coordinate conversion for COLMAP compatibility.
    
    Args:
        output_dir (str): Directory to save COLMAP files.
        filtered_points (np.ndarray): N x 3 array of filtered 3D points.
        filtered_colors (np.ndarray): N x 3 array of filtered RGB colors (uint8).
        camera_poses_c2w (np.ndarray): M x 3 x 4 (or M x 4 x 4) array of camera-to-world poses.
        camera_intrinsics (np.ndarray): M x 3 x 3 array of intrinsic matrices.
        image_names (List[str]): List of image file paths/names.
        progress_callback (Optional[Callable]): Callback for progress updates.
        colmap_image_width (int): Target width for images in COLMAP.
        colmap_image_height (int): Target height for images in COLMAP.
        use_anchor_rig (bool): Flag indicating if anchor+rig mode is active.
        predictions_dict (Optional[Dict]): Full predictions dictionary, needed for rig details.

    Returns:
        Tuple[Optional[str], int]: Path to output directory and number of 3D points.
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    sparse_dir = output_dir_path / "sparse"
    images_dir = output_dir_path / "images"
    sparse_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    
    if progress_callback:
        progress_callback(f"🚀 Starting threaded COLMAP export to {output_dir}")

    if len(filtered_points) == 0:
        if progress_callback:
            progress_callback("❌ No points to export.")
        return str(output_dir), 0
    
    # --- Threaded Writer Setup ---
    write_queue = queue.Queue(maxsize=20000)  # Buffer up to 20k lines in memory

    def writer_job(q: queue.Queue, filepath: str):
        """Consumes lines from the queue and writes them to a file."""
        with open(filepath, 'w') as f:
            while True:
                chunk = q.get()
                if chunk is None:  # Sentinel value to signal completion
                    break
                f.writelines(chunk)
                q.task_done()
    
    # --- 1. Write cameras.txt (can be done directly, it's fast) ---
    cameras_path = sparse_dir / "cameras.txt"
    with open(cameras_path, 'w') as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"# Number of cameras: {len(camera_poses_c2w)}\n")
        vggt_base_res = 518
        
        for cam_idx in range(len(camera_poses_c2w)):
            vggt_fx = camera_intrinsics[cam_idx, 0, 0]
            vggt_fy = camera_intrinsics[cam_idx, 1, 1]
            resize_ratio = colmap_image_width / vggt_base_res
            fx = vggt_fx * resize_ratio
            fy = vggt_fy * resize_ratio
            cx = colmap_image_width / 2.0
            cy = colmap_image_height / 2.0
            f.write(f"{cam_idx + 1} PINHOLE {colmap_image_width} {colmap_image_height} {fx:.6f} {fy:.6f} {cx:.6f} {cy:.6f}\n")
    if progress_callback: progress_callback("   ✅ cameras.txt written.")

    # --- 2. Project Points and Prepare Data (CPU-bound bottleneck) ---
    if progress_callback: progress_callback(f"   🧠 Projecting {len(filtered_points):,} points to {len(camera_poses_c2w)} cameras...")
    points3D_colmap, image_points2D_colmap_lists = _project_points_for_colmap(
        filtered_points, filtered_colors, camera_poses_c2w, camera_intrinsics,
        colmap_image_width, colmap_image_height, use_anchor_rig, predictions_dict, progress_callback
    )
    if progress_callback: progress_callback(f"   ✅ Projection complete. {len(points3D_colmap)} valid 3D points created.")

    # --- 3. Write images.txt (optimize for large point counts) ---
    if progress_callback: progress_callback("   ✍️ Writing images.txt with 2D point associations...")
    images_path = sparse_dir / "images.txt"
    with open(images_path, 'w') as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        f.write(f"# Number of images: {len(camera_poses_c2w)}\n")
        
        total_2d_points_written = 0
        for img_idx in range(len(camera_poses_c2w)):
            c2w_pose = camera_poses_c2w[img_idx]
            R_c2w = c2w_pose[:3, :3]
            t_c2w = c2w_pose[:3, 3]
            
            # Convert C2W to W2C for COLMAP images.txt format (same as projection code)
            R_w2c = R_c2w.T
            t_w2c = -R_c2w.T @ t_c2w
            
            # Convert W2C rotation to quaternion (W, X, Y, Z) for COLMAP
            r_scipy = Rotation.from_matrix(R_w2c)
            quat_xyzw = r_scipy.as_quat() # (x, y, z, w)
            qw, qx, qy, qz = quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]
            
            img_name = Path(image_names[img_idx]).name if isinstance(image_names[img_idx], str) else f"image_{img_idx}.jpg"
            f.write(f"{img_idx + 1} {qw:.6f} {qx:.6f} {qy:.6f} {qz:.6f} {t_w2c[0]:.6f} {t_w2c[1]:.6f} {t_w2c[2]:.6f} {img_idx + 1} {img_name}\n")
            
            # Write 2D points for this image (optimized for large counts)
            points_2d = image_points2D_colmap_lists[img_idx]
            if len(points_2d) > 0:
                # Use more efficient string building for large point counts
                if len(points_2d) > 50000:  # For very large point counts, build in chunks
                    point_strs = []
                    for u, v, pid in points_2d:
                        point_strs.append(f"{u:.6f} {v:.6f} {pid}")
                    f.write(" ".join(point_strs) + "\n")
                else:
                    points2d_str = " ".join([f"{u:.6f} {v:.6f} {pid}" for u, v, pid in points_2d])
                    f.write(points2d_str + "\n")
                total_2d_points_written += len(points_2d)
            else:
                f.write("\n")  # Empty line for images with no 2D points
            
            # Progress reporting for large datasets
            if progress_callback and (img_idx + 1) % 10 == 0:
                progress_callback(f"     Processed {img_idx + 1}/{len(camera_poses_c2w)} cameras, {total_2d_points_written:,} 2D points written")
    
    if progress_callback: progress_callback(f"   ✅ images.txt written with {total_2d_points_written:,} total 2D point associations.")

    # --- 4. Start Writer Thread for points3D.txt ---
    points3d_path = sparse_dir / "points3D.txt"
    points_writer_thread = threading.Thread(target=writer_job, args=(write_queue, points3d_path), daemon=True)
    points_writer_thread.start()
    
    if progress_callback: progress_callback("   ✍️ Writing points3D.txt via background thread...")
    
    # Write header directly to the file via the queue
    header_chunk = [
        "# 3D point list with one line of data per point:\n",
        "#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n",
        f"# Number of points: {len(points3D_colmap)}\n"
    ]
    write_queue.put(header_chunk)

    buffer = []
    BUFFER_SIZE = 10000
    total_points = len(points3D_colmap)

    for i, point in enumerate(points3D_colmap):
        x, y, z = point['xyz']
        r, g, b = point['rgb']
        track_str = " ".join([f"{img_id} {point2d_idx}" for img_id, point2d_idx in point['track']])
        line = f"{point['point_id']} {x:.6f} {y:.6f} {z:.6f} {r} {g} {b} 0.0 {track_str}\n"
        buffer.append(line)

        if len(buffer) >= BUFFER_SIZE:
            write_queue.put(buffer)
            buffer = []
        
        if progress_callback and (i + 1) % 50000 == 0:
            progress_callback(f"     Queued {i+1:,}/{total_points:,} points for writing...")

    if buffer:
        write_queue.put(buffer)

    # --- 5. Signal completion and wait for writer thread ---
    write_queue.put(None)  # Sentinel to stop the writer thread
    points_writer_thread.join()  # Wait for the writer to finish its job
    
    if progress_callback: progress_callback(f"   ✅ points3D.txt written successfully.")
    

    if progress_callback: progress_callback(f"✅ COLMAP files saved to {output_dir_path}. Total 3D points: {len(points3D_colmap)}.")

    return str(output_dir), len(points3D_colmap)


def _project_points_vectorized(points_3d, camera_poses_c2w, camera_intrinsics, 
                              colmap_image_width, colmap_image_height, chunk_size=100000):
    """
    Vectorized projection of 3D points to all cameras with chunked processing to avoid memory issues.
    
    IMPORTANT: This preserves the exact coordinate conversions from our working implementation:
    - C2W to W2C conversion: R_w2c = R_c2w.T, t_w2c = -R_c2w.T @ t_c2w  
    - COLMAP scaling with centered principal points
    
    Args:
        points_3d: (N, 3) array of 3D points
        camera_poses_c2w: (M, 3, 4) or (M, 4, 4) array of C2W poses
        camera_intrinsics: (M, 3, 3) array of intrinsic matrices
        colmap_image_width, colmap_image_height: target image dimensions
        chunk_size: Number of points to process at once (default 100K)
        
    Returns:
        u, v: (M, N) arrays of projected coordinates
        valid_mask: (M, N) boolean array of valid projections
    """
    num_points = points_3d.shape[0]
    num_cameras = camera_poses_c2w.shape[0]
    
    print(f"      📦 Processing in chunks of {chunk_size:,} points to avoid memory issues...")
    
    # Initialize output arrays
    u_all = np.zeros((num_cameras, num_points), dtype=np.float32)
    v_all = np.zeros((num_cameras, num_points), dtype=np.float32)
    valid_mask_all = np.zeros((num_cameras, num_points), dtype=bool)
    vggt_base_res = 518
    width_scale = colmap_image_width / vggt_base_res
    height_scale = colmap_image_height / vggt_base_res

    # Pre-compute camera transformations (same for all chunks)
    R_c2w = camera_poses_c2w[:, :3, :3]  # (M, 3, 3)
    t_c2w = camera_poses_c2w[:, :3, 3]   # (M, 3)
    R_w2c = R_c2w.transpose(0, 2, 1)     # (M, 3, 3) 
    t_w2c = -np.einsum('mij,mj->mi', R_w2c, t_c2w)  # (M, 3)

    # Pre-compute scaled intrinsics (same for all chunks)
    scaled_intrinsics = camera_intrinsics.copy()  # (M, 3, 3)
    scaled_intrinsics[:, 0, 0] *= width_scale   # Scale fx
    scaled_intrinsics[:, 1, 1] *= height_scale  # Scale fy 
    scaled_intrinsics[:, 0, 2] = colmap_image_width / 2.0   # Set cx to center
    scaled_intrinsics[:, 1, 2] = colmap_image_height / 2.0  # Set cy to center

    # Process points in chunks
    num_chunks = (num_points + chunk_size - 1) // chunk_size
    margin = 10  # 10-pixel margin from edges
    
    for chunk_idx in range(num_chunks):
        start_idx = chunk_idx * chunk_size
        end_idx = min((chunk_idx + 1) * chunk_size, num_points)
        chunk_points = points_3d[start_idx:end_idx]
        
        if chunk_idx % 10 == 0 or chunk_idx == num_chunks - 1:  # Progress every 10th chunk + last
            print(f"         📊 Processing chunk {chunk_idx + 1}/{num_chunks} ({end_idx:,}/{num_points:,} points)")
        
        # Transform points to camera coordinates for this chunk
        points_cam = np.einsum('mij,nj->mni', R_w2c, chunk_points) + t_w2c[:, np.newaxis, :]
        
        # Filter points behind cameras (minimal check only)
        depth = points_cam[:, :, 2]
        valid_depth_mask = depth > 1e-6  # Basic sanity check only
        
        # Project to image coordinates
        points_2d_homo = np.einsum('mij,mnj->mni', scaled_intrinsics, points_cam)
        
        # Normalize to get (u, v) coordinates
        z_coords = points_2d_homo[:, :, 2]
        u_chunk = np.divide(points_2d_homo[:, :, 0], z_coords, out=np.full_like(z_coords, -1), where=z_coords!=0)
        v_chunk = np.divide(points_2d_homo[:, :, 1], z_coords, out=np.full_like(z_coords, -1), where=z_coords!=0)
        
        # Basic bounds check only (no restrictive margins)
        in_bounds_mask = (u_chunk >= 0) & (u_chunk < colmap_image_width) & (v_chunk >= 0) & (v_chunk < colmap_image_height)
        valid_mask_chunk = valid_depth_mask & in_bounds_mask
        
        # Store results in output arrays
        u_all[:, start_idx:end_idx] = u_chunk
        v_all[:, start_idx:end_idx] = v_chunk
        valid_mask_all[:, start_idx:end_idx] = valid_mask_chunk

    return u_all, v_all, valid_mask_all


def _project_points_for_colmap(filtered_points, filtered_colors, camera_poses_c2w, camera_intrinsics,
                               colmap_image_width, colmap_image_height, use_anchor_rig, predictions_dict, progress_callback):
    """
    Vectorized helper function for CPU-intensive point projection logic with preserved coordinate systems.
    Uses vectorized operations for massive speedup while maintaining exact coordinate conversions.
    """
    if progress_callback:
        progress_callback(f"   🚀 Using vectorized projection for {len(filtered_points):,} points × {len(camera_poses_c2w)} cameras...")
    
    # Vectorized projection (preserves our coordinate system fixes)
    u, v, valid_mask = _project_points_vectorized(
        filtered_points, camera_poses_c2w, camera_intrinsics, 
        colmap_image_width, colmap_image_height
    )
    
    # Convert vectorized results to COLMAP track format
    points3D_colmap = []
    image_points2D_colmap_lists = [[] for _ in range(len(camera_poses_c2w))]
    anchor_point_count = 0
    rig_point_count = 0
    multi_view_count = 0
    rig_yaw_steps = predictions_dict.get("rig_yaw_steps", 6) if predictions_dict else 6
    
    for point_idx, (point_3d, color) in enumerate(zip(filtered_points, filtered_colors)):
        track_entries = []
        point_anchor_visible = False
        point_rig_visible = False
        
        # Check each camera using vectorized results (no artificial limits)
        for cam_idx in range(len(camera_poses_c2w)):
            if valid_mask[cam_idx, point_idx]:
                track_entries.append((cam_idx + 1, len(image_points2D_colmap_lists[cam_idx])))
                image_points2D_colmap_lists[cam_idx].append((u[cam_idx, point_idx], v[cam_idx, point_idx], point_idx + 1))

                if use_anchor_rig:
                    if cam_idx % rig_yaw_steps == 0:
                        point_anchor_visible = True
                    else:
                        point_rig_visible = True
        
        if len(track_entries) >= 2:  # Only keep points visible in at least 2 cameras
            points3D_colmap.append({
                'point_id': len(points3D_colmap) + 1, 'xyz': point_3d, 'rgb': color, 'track': track_entries
            })
            
            if use_anchor_rig:
                if point_anchor_visible:
                    anchor_point_count += 1
                if point_rig_visible:
                    rig_point_count += 1
                if len(track_entries) > 2:
                    multi_view_count += 1
                    
        if progress_callback and (point_idx + 1) % 25000 == 0:  # Less frequent progress updates for vectorized version
            percentage = ((point_idx + 1) / len(filtered_points)) * 100
            progress_callback(f"   Processed {point_idx+1:,}/{len(filtered_points):,} points ({percentage:.1f}%)...")
    
    # Final statistics
    if progress_callback and len(points3D_colmap) > 0:
        total_observations = sum(len(track['track']) for track in points3D_colmap)
        avg_obs = total_observations / len(points3D_colmap)
        if use_anchor_rig:
            progress_callback(f"   ✅ Track Analysis: {anchor_point_count:,} anchor points, {rig_point_count:,} rig points, {multi_view_count:,} multi-view")
        progress_callback(f"   📊 Created {len(points3D_colmap):,} valid 3D points with {total_observations} 2D observations (avg {avg_obs:.1f} per point)")
    
    return points3D_colmap, image_points2D_colmap_lists


def optimize_points_for_rig_coverage(points, colors, confidences, predictions, use_anchor_rig, progress_callback=None):
    """
    Optimize 3D point distribution to ensure good coverage across all rig cameras.
    
    For anchor+rig mode, we want to ensure that rig cameras get sufficient 2D projections
    for robust Gaussian Splatting training.
    """
    if not use_anchor_rig or len(points) < 10000:
        return points, colors, confidences
    
    if progress_callback:
        progress_callback(f"   Analyzing point visibility across rig cameras...")
    
    # Get camera parameters
    extrinsic_mat = predictions["extrinsic"]
    intrinsic_mat = predictions["intrinsic"]
    num_cameras = len(extrinsic_mat)
    rig_yaw_steps = predictions.get("rig_yaw_steps", 6)
    
    # Analyze point visibility per camera
    camera_visibility_counts = [0] * num_cameras
    point_visibility_scores = []  # Score for each point based on rig coverage
    
    # Configuration constants for visibility analysis
    MAX_ANALYSIS_SAMPLE_SIZE = 150000  # Maximum sample size for performance
    
    # Quick visibility analysis (sample for performance)
    sample_size = min(len(points), MAX_ANALYSIS_SAMPLE_SIZE)  # Sample points for analysis
    sample_indices = np.random.choice(len(points), sample_size, replace=False)
    
    for idx in sample_indices:
        point_3d = points[idx]
        point_3d_homog = np.append(point_3d, 1.0)
        
        visibility_score = 0
        anchor_visible = False
        rig_visible = False
        
        for cam_idx in range(num_cameras):
            # Quick projection test
            point_cam = extrinsic_mat[cam_idx] @ point_3d_homog
            if point_cam[2] > 0:  # In front of camera
                point_img_homog = intrinsic_mat[cam_idx] @ point_cam[:3]
                if point_img_homog[2] > 0:
                    u = point_img_homog[0] / point_img_homog[2]
                    v = point_img_homog[1] / point_img_homog[2]
                    
                    # Check if in image bounds (dynamic bounds based on VGGT resolution)
                    vggt_res = 518  # VGGT base resolution
                    margin = vggt_res * 0.4  # 40% margin for generous bounds
                    if -margin <= u <= vggt_res + margin and -margin <= v <= vggt_res + margin:
                        camera_visibility_counts[cam_idx] += 1
                        visibility_score += 1
                        
                        # Track anchor vs rig visibility
                        if cam_idx % rig_yaw_steps == 0:  # Anchor camera
                            anchor_visible = True
                        else:  # Rig camera
                            rig_visible = True
        
        # Boost score for points visible in both anchor and rig cameras
        if anchor_visible and rig_visible:
            visibility_score *= 1.5
        elif rig_visible:
            visibility_score *= 1.2  # Slight boost for rig visibility
        
        point_visibility_scores.append(visibility_score)
    
    # Analyze coverage balance
    anchor_cameras = list(range(0, num_cameras, rig_yaw_steps))
    rig_cameras = [i for i in range(num_cameras) if i not in anchor_cameras]
    
    anchor_coverage = sum(camera_visibility_counts[i] for i in anchor_cameras)
    rig_coverage = sum(camera_visibility_counts[i] for i in rig_cameras)
    
    coverage_ratio = rig_coverage / anchor_coverage if anchor_coverage > 0 else 0
    
    if progress_callback:
        progress_callback(f"   Point coverage analysis: {coverage_ratio:.2f} rig/anchor ratio")
    
    # Configuration constants for coverage analysis
    MIN_COVERAGE_RATIO = 0.4  # Minimum rig/anchor coverage ratio before optimization
    
    # Apply optimization if needed
    if coverage_ratio < MIN_COVERAGE_RATIO:  # Rig cameras have poor coverage
        if progress_callback:
            progress_callback(f"   🔧 Applying point optimization for better rig coverage...")
        
        # Smart sampling: prefer points with good rig visibility
        avg_score = np.mean(point_visibility_scores)
        high_quality_indices = []
        
        for i, score in enumerate(point_visibility_scores):
            sample_idx = sample_indices[i]
            if score > avg_score * 0.8:  # Keep high-scoring points
                high_quality_indices.append(sample_idx)
        
        # If we filtered too aggressively, add back some medium-quality points
        if len(high_quality_indices) < len(points) * 0.7:
            medium_threshold = avg_score * 0.5
            for i, score in enumerate(point_visibility_scores):
                sample_idx = sample_indices[i]
                if score > medium_threshold and sample_idx not in high_quality_indices:
                    high_quality_indices.append(sample_idx)
                    if len(high_quality_indices) >= len(points) * 0.8:
                        break
        
        # Add remaining points to maintain sufficient density
        remaining_indices = [i for i in range(len(points)) if i not in high_quality_indices and i not in sample_indices]
        final_indices = high_quality_indices + remaining_indices
        
        # Apply the optimized selection
        optimized_points = points[final_indices]
        optimized_colors = colors[final_indices]
        optimized_conf = confidences[final_indices]
        
        if progress_callback:
            progress_callback(f"   ✅ Point optimization complete: {len(optimized_points):,} points selected for balanced coverage")
        
        return optimized_points, optimized_colors, optimized_conf
    
    else:
        if progress_callback:
            progress_callback(f"   ✅ Point distribution already good for rig coverage")
        return points, colors, confidences

# =================================================================================
# MAIN PIPELINE ORCHESTRATION
# =================================================================================

def run_full_pipeline(
    image_dir: str, 
    output_dir: str, 
    progress_callback: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    conf_thres: float = 50.0,
    mask_sky: bool = False,
    mask_black_bg: bool = False,
    mask_white_bg: bool = False,
    prediction_mode: str = "Depthmap and Camera Branch",
    temporal_sequencing: bool = True,
    enable_sparse: bool = False,
    sparse_target_points: int = 150000,
    sky_sensitivity_threshold: int = 32,
    use_anchor_rig: bool = False,
    anchor_view: str = 'y00',
    rig_optimization_min_points: int = 500000,
    show_camera: bool = True,
    pitch_angles: List[float] = None, # e.g., [-30.0, 0.0, 30.0]
    yaw_steps: int = 6,              # e.g., 6 (for 0, 60, 120...)
    colmap_image_width: int = 1920,
    colmap_image_height: int = 1920
) -> Dict:
    """
    Orchestrates the complete VGGT 3D Gaussian Splatting pipeline:
    1. VGGT inference to get anchor poses (W2C)
    2. Rig expansion to get final camera-to-world poses (C2W)
    3. Unified point cloud filtering
    4. GLB visualization
    5. COLMAP export
    """
    
    if progress_callback: progress_callback("🚀 Starting VGGT 3D Gaussian Splatting Pipeline...")
    
    processor = VGGTProcessor()
    init_ok, init_msg = processor.initialize(progress_callback)
    if not init_ok:
        return {"success": False, "error": f"VGGT initialization failed: {init_msg}"}

    try:
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Collect image paths with anchor_view filtering support
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']  # Convert to list for consistency
        image_paths = []
        
        # Check if we're dealing with structured frame directories
        from pathlib import Path
        image_dir_path = Path(image_dir)
        frame_dirs = [d for d in image_dir_path.iterdir() if d.is_dir() and 'frame_' in d.name]
        
        if frame_dirs and use_anchor_rig:
            # Structured frame directory with anchor+rig mode
            # Note: Anchor+Rig mode always uses temporal sequencing (optimal for tracking)
            if progress_callback: progress_callback(f"🎯 Anchor+Rig mode: Processing only {anchor_view} view (temporal sequencing - optimal for tracking)")
            
            frame_dirs_sorted = sorted(frame_dirs, key=lambda x: x.name)
            
            # Extract all viewpoints from first frame
            first_frame = frame_dirs_sorted[0] if frame_dirs_sorted else None
            viewpoints = []
            
            if first_frame:
                for ext in image_extensions:
                    for img_file in first_frame.glob(f"*{ext}"):
                        # Extract viewpoint identifier (e.g., "view_00_p-30_y00")
                        filename = img_file.stem
                        if "view_" in filename:
                            view_part = filename.split("view_")[1]  # Get "00_p-30_y00" part
                            viewpoints.append(view_part)
                    for img_file in first_frame.glob(f"*{ext.upper()}"):
                        filename = img_file.stem
                        if "view_" in filename:
                            view_part = filename.split("view_")[1]
                            viewpoints.append(view_part)
                            
            viewpoints = sorted(list(set(viewpoints)))
            
            if progress_callback:
                progress_callback(f"Found {len(viewpoints)} viewpoints across {len(frame_dirs_sorted)} frames")
            
            # Find the anchor viewpoint in the available viewpoints - improved multi-pitch support
            anchor_viewpoint = None
            anchor_candidates = []
            
            # Collect all viewpoints that match the anchor yaw pattern
            anchor_view_pattern = f"_{anchor_view}"  # e.g., "_y00"
            for viewpoint in viewpoints:
                if anchor_view_pattern in viewpoint:
                    anchor_candidates.append(viewpoint)
            
            if not anchor_candidates:
                return {"success": False, "error": f"Anchor view '{anchor_view}' not found in available viewpoints: {viewpoints}"}
            
            # For multi-pitch scenarios, prefer the pitch angle closest to 0 degrees (horizon level)
            if len(anchor_candidates) > 1 and pitch_angles:
                # Find the pitch angle closest to 0 (horizon) from user-provided pitch_angles
                best_pitch = min(pitch_angles, key=lambda p: abs(p - 0))
                anchor_pitch_pattern = f"p{best_pitch:+.0f}"  # e.g., "p-30" or "p+0"
                
                # Find candidate that matches the best pitch
                best_candidate = None
                for candidate in anchor_candidates:
                    if anchor_pitch_pattern in candidate:
                        best_candidate = candidate
                        break
                
                anchor_viewpoint = best_candidate or anchor_candidates[0]
                if progress_callback:
                    progress_callback(f"   Multi-pitch anchor selection: chose '{anchor_viewpoint}' (pitch {best_pitch}° closest to 0°) from {anchor_candidates}")
            else:
                anchor_viewpoint = anchor_candidates[0]
                if progress_callback:
                    progress_callback(f"   Single pitch anchor selection found: '{anchor_viewpoint}'")
            
            # Collect only anchor view images across all frames
            for frame_dir in frame_dirs_sorted:
                for ext in image_extensions:
                    pattern = f"*view_{anchor_viewpoint}{ext}"
                    matches = list(frame_dir.glob(pattern))
                    matches.extend(frame_dir.glob(pattern.upper()))
                    if matches:
                        image_paths.append(str(matches[0]))
                        break  # Found match for this viewpoint in this frame
        
        elif frame_dirs:
            # Structured frame directory but normal mode (process all viewpoints)
            frame_dirs_sorted = sorted(frame_dirs, key=lambda x: x.name)
            
            # Extract all viewpoints from first frame  
            first_frame = frame_dirs_sorted[0] if frame_dirs_sorted else None
            viewpoints = []
            
            if first_frame:
                for ext in image_extensions:
                    for img_file in first_frame.glob(f"*{ext}"):
                        filename = img_file.stem
                        if "view_" in filename:
                            view_part = filename.split("view_")[1]
                            viewpoints.append(view_part)
                            
            viewpoints = sorted(list(set(viewpoints)))
            
            if progress_callback:
                progress_callback(f"Found {len(viewpoints)} viewpoints across {len(frame_dirs_sorted)} frames")
                if temporal_sequencing:
                    progress_callback(f"Organizing images for temporal sequence (by viewpoint - VGGT recommended)")
                else:
                    progress_callback(f"Organizing images for spatial sequence (by frame)")
            
            if temporal_sequencing:
                # Temporal sequence: Collect images by viewpoint across time 
                # (all view_00 images first, then all view_01 images, etc.)
                for viewpoint in viewpoints:
                    for frame_dir in frame_dirs_sorted:
                        for ext in image_extensions:
                            pattern = f"*view_{viewpoint}{ext}"
                            matches = list(frame_dir.glob(pattern))
                            matches.extend(frame_dir.glob(pattern.upper()))
                            if matches:
                                image_paths.append(str(matches[0]))
                                break  # Found match for this viewpoint in this frame
            else:
                # Spatial sequence: Collect images by frame across viewpoints
                # (all images from frame_1, then all images from frame_2, etc.)
                for frame_dir in frame_dirs_sorted:
                    frame_images = []
                    for viewpoint in viewpoints:
                        for ext in image_extensions:
                            pattern = f"*view_{viewpoint}{ext}"
                            matches = list(frame_dir.glob(pattern))
                            matches.extend(frame_dir.glob(pattern.upper()))
                            if matches:
                                frame_images.append(str(matches[0]))
                                break  # Found match for this viewpoint in this frame
                    # Add frame's images in sorted order
                    image_paths.extend(sorted(frame_images))
        
        else:
            # Simple flat directory structure
            if use_anchor_rig and pitch_angles:
                # Anchor+Rig mode: Filter images to only include the anchor viewpoint
                if progress_callback: progress_callback("🎯 Anchor+Rig mode: Filtering images by anchor viewpoint...")

                # Find the pitch angle closest to 0 (horizon)
                if not pitch_angles:
                    return {"success": False, "error": "pitch_angles must be provided in Anchor+Rig mode"}
                best_pitch = min(pitch_angles, key=lambda p: abs(p - 0))
                
                # Construct the anchor patterns (separate pitch and yaw patterns)
                # Format: frame_000001_view_00_p-30_y00
                anchor_pitch_pattern = f"p{best_pitch:+.0f}"  # e.g., "p-30" or "p+0"
                anchor_view_pattern = f"_{anchor_view}"        # e.g., "_y00"
                
                if progress_callback: progress_callback(f"   Searching for images with pitch '{anchor_pitch_pattern}' AND view '{anchor_view_pattern}'")
                
                # Find images matching BOTH anchor patterns
                all_images = []
                for ext in image_extensions:
                    pattern = os.path.join(image_dir, f"**/*{ext}")
                    all_images.extend(glob.glob(pattern, recursive=True))
                
                # Filter images to only those matching BOTH patterns (like old implementation)
                for img_path in all_images:
                    filename = os.path.basename(img_path)
                    if anchor_pitch_pattern in filename and anchor_view_pattern in filename:
                        image_paths.append(img_path)

                # CRITICAL FIX: If no images match the anchor patterns, raise an error.
                # Do NOT fall back to processing all images, as this defeats the purpose.
                if not image_paths:
                    return {"success": False, "error": f"No images found matching anchor patterns '{anchor_pitch_pattern}' AND '{anchor_view_pattern}'. Please check your file names or anchor_view setting."}
                
                image_paths = sorted(list(set(image_paths))) # Remove duplicates and sort
                if progress_callback: progress_callback(f"   Found {len(image_paths)} anchor images matching pattern")
            else:
                # Standard mode: Process all images
                for ext in image_extensions:
                    image_paths.extend(glob.glob(os.path.join(image_dir, f"**/*{ext}"), recursive=True))
                image_paths = sorted(list(set(image_paths))) # Remove duplicates and sort
        
        if not image_paths:
            return {"success": False, "error": f"No images found in {image_dir}."}
        if progress_callback: progress_callback(f"Collected {len(image_paths)} images for processing.")

        # 2. Run VGGT inference to get RAW predictions (W2C poses for anchors)
        raw_predictions = processor.process_vggt_inference(image_paths, progress_callback, cancel_event)
        if not raw_predictions.get("success", True): # Check for inference errors
            return raw_predictions
        
        # 3. Create 3D Point Cloud from Depth Map IMMEDIATELY (using original W2C poses)
        # CRITICAL: This must happen before any pose conversion (W2C -> C2W)
        if progress_callback: progress_callback("🔧 Creating 3D point cloud from depth map (batched like old version)...")
        try:
            # Now that we match the old version's data format, use batched processing
            if progress_callback:
                progress_callback(f"   Depth map shape: {raw_predictions['depth'].shape}")
                progress_callback(f"   Extrinsic shape: {raw_predictions['extrinsic'].shape}")
                progress_callback(f"   Intrinsic shape: {raw_predictions['intrinsic'].shape}")
            
            # Call with batch data (like old version) - should work now with correct data format
            world_points_from_depth = unproject_depth_map_to_point_map(
                raw_predictions["depth"],      # Should now be correct format
                raw_predictions["extrinsic"],  # W2C matrices (function will invert internally) 
                raw_predictions["intrinsic"]   # Intrinsic matrices
            )
            raw_predictions["world_points_from_depth"] = world_points_from_depth.astype(np.float32)
            
            if progress_callback: 
                progress_callback(f"✅ 3D point cloud created successfully ({world_points_from_depth.shape[0]:,} points).")

        except Exception as e:
            error_msg = f"Failed to create point cloud from depth map. Error: {e}"
            if progress_callback: progress_callback(f"❌ {error_msg}")
            print(traceback.format_exc())  # Print full traceback for debugging
            return {"success": False, "error": error_msg}
        
        # 4. Extract initial anchor data from raw predictions (still W2C at this point)
        anchor_extrinsic_w2c = raw_predictions["extrinsic"] # 3x4 W2C
        anchor_intrinsic = raw_predictions["intrinsic"]     # 3x3
        
        # Add rig parameters to predictions for downstream functions
        if use_anchor_rig:
            raw_predictions["rig_yaw_steps"] = yaw_steps
            raw_predictions["rig_pitch_angles"] = pitch_angles

        # 3. Expand anchor poses to final rig poses (C2W)
        if use_anchor_rig:
            if progress_callback: progress_callback("🎯 Expanding anchor poses to full camera rig...")
            final_camera_poses_c2w_3x4, final_intrinsic = expand_anchor_to_rig(
                anchor_extrinsic_w2c, anchor_intrinsic, pitch_angles, yaw_steps, progress_callback
            )
            # Generate correct image names matching the actual files in the filesystem
            expanded_image_names = []
            total_views_per_anchor = len(get_virtual_rotations(yaw_steps, pitch_angles)) # Total per anchor
            
            for anchor_idx, original_path in enumerate(image_paths):
                # Extract frame number from original anchor filename
                # e.g., "frame_000001_view_00_p-30_y00.jpg" -> frame_000001
                original_name = Path(original_path).stem  # Remove .jpg extension
                frame_base = original_name.split('_view_')[0]  # Get "frame_000001" part
                
                # Generate all view names for this anchor (including the original anchor view)
                for view_idx in range(total_views_per_anchor):
                    # Determine pitch and yaw for this view
                    pitch_idx = view_idx // yaw_steps
                    yaw_idx = view_idx % yaw_steps
                    pitch_value = pitch_angles[pitch_idx] if pitch_idx < len(pitch_angles) else pitch_angles[0]
                    yaw_step = yaw_idx  # Use step index, not angle
                    
                    # Generate filename matching the actual pattern
                    view_name = f"{frame_base}_view_{view_idx:02d}_p{int(pitch_value):+d}_y{yaw_step:02d}.jpg"
                    expanded_image_names.append(view_name)

            num_original_anchors = len(image_paths) # Number of images fed to VGGT
        else:
            if progress_callback: progress_callback("📋 Using VGGT anchor poses directly (no rig expansion)...")
            final_camera_poses_c2w_3x4 = np.array([convert_w2c_to_c2w(p)[:3, :4] for p in anchor_extrinsic_w2c])
            final_intrinsic = anchor_intrinsic
            expanded_image_names = image_paths
            num_original_anchors = len(image_paths)
        
        # Update raw_predictions with final poses for filtering (if filtering needs C2W)
        # Note: apply_user_filters uses original world_points_from_depth
        
        # 5. Three-stage filtering pipeline: Quality → Rig Optimization → Count
        
        # Stage 1: Quality filters (confidence, sky, background)
        if progress_callback: progress_callback("🎨 Applying quality filters...")
        filtered_points, filtered_colors, filtered_conf = apply_quality_filters(
            raw_predictions, # Use raw_predictions as source for filtering
            conf_thres, mask_sky, mask_black_bg, mask_white_bg,
            prediction_mode, progress_callback, sky_sensitivity_threshold
        )
        if filtered_points.size == 0:
            return {"success": False, "error": "No 3D points remaining after quality filtering."}

        # Stage 2: Rig optimization (if anchor+rig mode and sufficient points)
        filtered_points, filtered_colors, filtered_conf = apply_rig_optimization(
            filtered_points, filtered_colors, filtered_conf, raw_predictions,
            use_anchor_rig, rig_optimization_min_points, progress_callback
        )
        if filtered_points.size == 0:
            return {"success": False, "error": "No 3D points remaining after rig optimization."}

        # Stage 3: Sparse filtering (final count reduction if needed)
        if enable_sparse:
            filtered_points, filtered_colors, filtered_conf = apply_sparse_filter(
                filtered_points, filtered_colors, filtered_conf, 
                sparse_target_points, progress_callback
            )
            if filtered_points.size == 0:
                return {"success": False, "error": "No 3D points remaining after sparse filtering."}


        # 6. Create GLB visualization
        if progress_callback: progress_callback("🌐 Creating 3D GLB visualization...")
        glb_output_path = os.path.join(output_dir, "vggt_scene.glb")
        glb_path = create_glb_scene(
            filtered_points, filtered_colors, 
            final_camera_poses_c2w_3x4, final_intrinsic, # Pass final C2W poses
            glb_output_path, show_camera, progress_callback,
            original_anchor_count=num_original_anchors,
            rig_yaw_steps=yaw_steps
        )
        if not glb_path:
            return {"success": False, "error": "Failed to create GLB visualization."}

        # # 7. Export COLMAP files
            #moved to callbacks to stop blocking
        
        if progress_callback: progress_callback("✅ VGGT Pipeline Completed Successfully!")
        
        return {
            "success": True,
            "glb_path": glb_path,
            # Pass ALL necessary data back for the slow COLMAP stage
            "colmap_output_dir": output_dir, # This is postshot_input_dir
            "filtered_points": filtered_points,
            "filtered_colors": filtered_colors,
            "num_cameras_processed_poses_c2w": final_camera_poses_c2w_3x4,
            "final_intrinsic": final_intrinsic,
            "expanded_image_names": expanded_image_names,
            "raw_predictions": raw_predictions,
        }
        
    except Exception as e:
        error_msg = f"VGGT pipeline failed: {str(e)}"
        if progress_callback: progress_callback(f"❌ {error_msg}")
        print(f"{error_msg}\n{traceback.format_exc()}")
        return {"success": False, "error": error_msg}
    finally:
        processor.cleanup()


