# xmp_rig_export.py - RealityScan XMP rig file generation

# Standard library imports
import os
import uuid
from pathlib import Path

# Third-party imports
import numpy as np

# Remove: from scipy.spatial.transform import Rotation (unused)


def generate_xmp_content(
    position: np.ndarray,
    rotation_matrix: np.ndarray,
    rig_id: str,
    rig_instance_id: str,
    rig_pose_index: int,
    focal_length_35mm: float = 18.0,
    pose_prior: str = "exact"  # "initial", "draft", "exact"
) -> str:
    """Generate XMP content for RealityScan rig configuration."""
    
    # Convert rotation matrix to RealityScan format (row-major 3x3 flattened)
    rotation_flat = rotation_matrix.flatten()
    rotation_str = " ".join(f"{r:.10f}" for r in rotation_flat)
    
    # Position as space-separated string
    position_str = " ".join(f"{p:.12f}" for p in position)
    
    xmp_template = f'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#"
   xcr:Version="3"
   xcr:PosePrior="{pose_prior}"
   xcr:Rotation="{rotation_str}"
   xcr:Coordinates="absolute"
   xcr:DistortionModel="division"
   xcr:DistortionCoeficients="0 0 0 0 0 0"
   xcr:FocalLength35mm="{focal_length_35mm}"
   xcr:Skew="0"
   xcr:AspectRatio="1"
   xcr:PrincipalPointU="0"
   xcr:PrincipalPointV="0"
   xcr:CalibrationPrior="initial"
   xcr:CalibrationGroup="-1"
   xcr:DistortionGroup="-1"
   xcr:Rig="{{{rig_id}}}"
   xcr:RigInstance="{{{rig_instance_id}}}"
   xcr:RigPoseIndex="{rig_pose_index}"
   xcr:InTexturing="1"
   xcr:InMeshing="1">
   <xcr:Position>{position_str}</xcr:Position>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>'''
    
    return xmp_template


def create_rig_rotation_matrices(yaw_steps: int, pitch_angles: list):
    """
    Create rotation matrices for virtual cameras matching your panorama_processing logic.
    This should match the rotation logic in panorama_processing.py
    """
    rotations = []
    
    for pitch in pitch_angles:
        # Calculate yaw offset (matches your existing logic)
        yaw_offset = (360 / yaw_steps / 2) if pitch > 0 else 0
        yaws = np.linspace(0, 360, yaw_steps, endpoint=False) + yaw_offset
        
        for yaw in yaws:
            # Create look-at rotation matrix (matching your panorama_processing.py)
            yaw_rad = np.radians(yaw)
            pitch_rad = np.radians(pitch)
            
            # Direction vector
            direction = np.array([
                np.sin(yaw_rad) * np.cos(pitch_rad),
                np.sin(pitch_rad),
                np.cos(yaw_rad) * np.cos(pitch_rad)
            ])
            direction = direction / np.linalg.norm(direction)

            # Create orthonormal basis
            up = np.array([0, 1, 0])
            right = np.cross(up, direction)
            right /= np.linalg.norm(right)
            true_up = np.cross(direction, right)

            # Rotation matrix (camera-to-world)
            R = np.stack([right, true_up, direction], axis=1)
            rotations.append(R)
    
    return rotations


def export_xmp_rig_files(output_dir: str, frame_name: str, pitch_angles: list, yaw_steps: int):
    """
    Export XMP rig files for a single frame's extracted views.
    
    Args:
        output_dir: Directory where the frame's view images are stored
        frame_name: Base name of the frame (e.g., "frame_000001")
        pitch_angles: List of pitch angles used for extraction
        yaw_steps: Number of yaw steps used for extraction
    """
    output_path = Path(output_dir)
    
    # Generate unique IDs for this frame's rig
    rig_id = str(uuid.uuid4()).upper()
    rig_instance_id = str(uuid.uuid4()).upper()
    
    # Create rotation matrices matching your view extraction
    rotations = create_rig_rotation_matrices(yaw_steps, pitch_angles)
    
    print(f"🎯 Generating XMP rig files for {frame_name} ({len(rotations)} views)")
    
    camera_index = 0
    for pitch_idx, pitch in enumerate(pitch_angles):
        for yaw_idx in range(yaw_steps):
            # Get the rotation matrix for this camera
            rotation_matrix = rotations[camera_index]
            
            # Camera position (at origin since it's relative to panorama center)
            position = np.array([0.0, 0.0, 0.0])
            
            # Generate XMP content
            xmp_content = generate_xmp_content(
                position=position,
                rotation_matrix=rotation_matrix,
                rig_id=rig_id,
                rig_instance_id=rig_instance_id,
                rig_pose_index=camera_index,
                pose_prior="exact"  # We know exact positions
            )
            
            # Generate filename matching your existing naming convention
            # This should match the format in panorama_processing.py
            view_filename = f"{frame_name}_view_{camera_index:02d}_p{pitch:+03.0f}_y{yaw_idx:02d}.jpg"
            xmp_filename = f"{view_filename}.xmp"
            xmp_path = output_path / xmp_filename
            
            # Write XMP file
            try:
                with open(xmp_path, 'w', encoding='utf-8') as f:
                    f.write(xmp_content)
                print(f"   ✅ Created: {xmp_filename}")
            except Exception as e:
                print(f"   ❌ Failed to create {xmp_filename}: {e}")
            
            camera_index += 1
    
    print(f"✅ XMP rig export complete: {camera_index} files created")


def export_all_frame_rigs(views_dir: str, pitch_angles: list, yaw_steps: int):
    """
    Export XMP rig files for all frames in the views directory.
    
    Args:
        views_dir: Root directory containing frame subdirectories
        pitch_angles: List of pitch angles used for extraction  
        yaw_steps: Number of yaw steps used for extraction
    """
    views_path = Path(views_dir)
    
    if not views_path.exists():
        print(f"❌ Views directory not found: {views_dir}")
        return False
    
    # Find all frame subdirectories
    frame_dirs = [d for d in views_path.iterdir() if d.is_dir()]
    
    if not frame_dirs:
        print(f"❌ No frame directories found in: {views_dir}")
        return False
    
    print(f"🚀 Exporting XMP rigs for {len(frame_dirs)} frames...")
    
    success_count = 0
    for frame_dir in sorted(frame_dirs):
        frame_name = frame_dir.name
        try:
            export_xmp_rig_files(str(frame_dir), frame_name, pitch_angles, yaw_steps)
            success_count += 1
        except Exception as e:
            print(f"❌ Failed to export XMP for {frame_name}: {e}")
    
    print(f"✅ XMP export complete: {success_count}/{len(frame_dirs)} frames processed")
    return success_count > 0