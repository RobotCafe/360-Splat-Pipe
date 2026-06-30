# panorama_processing.py - Enhanced with progress callbacks and validation

# Standard library imports
import os
import sys
import traceback

# Third-party imports
import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

# Local imports
from _common_utils import NP, GPU_ENABLED

# Remove: import matplotlib.pyplot as plt (unused)
# Remove: FOV_DEG, RIG_UUID from _common_utils (unused)

# --- Camera intrinsics ---
def create_virtual_camera(pano_height, fov_deg):
    image_size = int(pano_height * fov_deg / 180)
    focal = image_size / (2 * NP.tan(NP.deg2rad(fov_deg / 2)))
    return image_size, focal

# --- Generate rays in camera space ---
def get_virtual_camera_rays(image_size, focal):
    # Pixel -> normalized local ray via the actual pinhole focal length, so the
    # rendered content's real angular extent matches fov_deg (and therefore the
    # focal length create_virtual_camera() tells COLMAP). Previously this divided
    # by image_size instead of focal, which implies a fixed focal of image_size/2
    # (exactly 90 deg FOV) regardless of the requested fov_deg -- a mismatch
    # between what was rendered and what downstream consumers were told, e.g. a
    # 7.7% systematic focal error at fov_deg=94.6 (the default). See
    # FieldRaven_desktop/RIG_PIPELINE_PROCESS.md, "Open issue" section.
    y, x = NP.indices((image_size, image_size)).astype(NP.float32)
    xy = NP.stack([(x + 0.5), (image_size - y - 0.5)], axis=-1)
    xy = (xy - image_size / 2) / focal
    rays = NP.concatenate([xy, NP.ones((*xy.shape[:2], 1), dtype=NP.float32)], axis=-1)
    rays /= NP.linalg.norm(rays, axis=-1, keepdims=True)
    return rays.reshape(-1, 3)

# --- Convert rays to spherical UV coordinates ---
def spherical_uv_from_rays(rays):
    x, y, z = rays.T
    yaw = NP.arctan2(x, z)
    pitch = -NP.arctan2(y, NP.sqrt(x**2 + z**2))
    u = (yaw / NP.pi + 1) / 2
    v = (pitch / (NP.pi / 2) + 1) / 2
    return NP.stack([u, v], axis=-1)

# --- Generate rotations ---
def get_virtual_rotations(yaw_steps, pitch_angles, horizon_ref=False):
    def look_at_rotation(yaw_deg, pitch_deg):
        yaw = NP.radians(yaw_deg)
        pitch = NP.radians(pitch_deg)
        direction = NP.array([
            NP.sin(yaw) * NP.cos(pitch),
            NP.sin(pitch),
            NP.cos(yaw) * NP.cos(pitch)
        ])
        direction = direction / NP.linalg.norm(direction)

        up = NP.array([0, 1, 0])
        right = NP.cross(up, direction)
        right /= NP.linalg.norm(right)
        true_up = NP.cross(direction, right)

        R = NP.stack([right, true_up, direction], axis=1)
        return R

    rotations = []
    if horizon_ref:
        rotations.append(look_at_rotation(0.0, 0.0))  # view_00: horizon reference sensor
    yaws = NP.linspace(0, 360, yaw_steps, endpoint=False)
    for pitch in pitch_angles:
        yaw_offset = (360 / yaw_steps / 2) if pitch > 0 else 0
        for yaw in yaws + yaw_offset:
            R = look_at_rotation(yaw, pitch)
            rotations.append(R)
    return rotations

# --- Sample from equirectangular panorama ---
def sample_equirectangular(pano_array, uv_coords):
    h, w = pano_array.shape[:2]
    
    u = NP.clip(uv_coords[:, 0], 0, 0.999999)
    v = NP.clip(uv_coords[:, 1], 0, 0.999999)
    
    x = u * (w - 1)
    y = v * (h - 1)
    
    x0 = NP.floor(x).astype(NP.int32)
    x1 = NP.minimum(x0 + 1, w - 1)
    y0 = NP.floor(y).astype(NP.int32)
    y1 = NP.minimum(y0 + 1, h - 1)
    
    wx = (x - x0)[:, NP.newaxis]
    wy = (y - y0)[:, NP.newaxis]
    
    c00 = pano_array[y0, x0]
    c01 = pano_array[y1, x0]
    c10 = pano_array[y0, x1]
    c11 = pano_array[y1, x1]
    
    c0 = c00 * (1 - wy) + c01 * wy
    c1 = c10 * (1 - wy) + c11 * wy
    color = c0 * (1 - wx) + c1 * wx
    
    return color.astype(NP.uint8)

# --- Enhanced render perspective views with validation and progress ---
def render_views(pano_path, out_root, fov_deg, yaw_steps, pitch_angles, export_xmp,
                save_images, cancel_event, progress_callback=None, horizon_ref=False):
    """
    Enhanced view rendering with file validation and progress callbacks.
    """
    try:
        # === FILE VALIDATION ===
        if not os.path.exists(pano_path):
            raise FileNotFoundError(f"Panorama file not found: {pano_path}")
        
        if not os.path.isfile(pano_path):
            raise ValueError(f"Path is not a file: {pano_path}")
        
        # Check file size (avoid loading huge files accidentally)
        file_size = os.path.getsize(pano_path)
        if file_size == 0:
            raise ValueError(f"Panorama file is empty: {pano_path}")
        
        if file_size > 500 * 1024 * 1024:  # 500MB limit
            raise ValueError(f"Panorama file too large ({file_size / (1024*1024):.1f}MB): {pano_path}")
        
        # === IMAGE LOADING WITH BETTER ERROR HANDLING ===
        try:
            pano = Image.open(pano_path).convert("RGB")
        except UnidentifiedImageError:
            raise ValueError(f"File is not a valid image: {pano_path}")
        except Exception as img_error:
            raise ValueError(f"Failed to load image {os.path.basename(pano_path)}: {img_error}")
        
        pano_np_cpu = np.array(pano)
        h, w = pano_np_cpu.shape[:2]

        # === ASPECT RATIO VALIDATION ===
        if w != 2 * h:
            raise ValueError(f"Input must be 2:1 equirectangular panorama. Got {w}x{h} (aspect ratio: {w/h:.2f})")

        # === REST OF PROCESSING ===
        pano_array = NP.asarray(pano_np_cpu) if GPU_ENABLED else pano_np_cpu
        
        image_size, focal = create_virtual_camera(h, fov_deg)
        rays_array = get_virtual_camera_rays(image_size, focal)
        rotations = get_virtual_rotations(yaw_steps, pitch_angles, horizon_ref=horizon_ref)

        base_name = os.path.splitext(os.path.basename(pano_path))[0]
        out_dir = os.path.join(out_root, base_name)
        
        if save_images:
            os.makedirs(out_dir, exist_ok=True)

        images = []
        total_views = len(rotations)
        
        print(f"Rendering {total_views} views from {base_name}...")
        
        for i, R in enumerate(rotations):
            # CHECK CANCELLATION AT START OF EACH VIEW
            if cancel_event and cancel_event.is_set():
                print(f"🛑 View rendering cancelled at view {i+1}/{total_views}")
                break

            # Call progress callback before processing each view
            if progress_callback:
                progress_callback(i, total_views)
            
            R_array = R 
            
            world_rays = rays_array @ R_array.T
            uv_coords_array = spherical_uv_from_rays(world_rays)
            sampled_colors_array = sample_equirectangular(pano_array, uv_coords_array)
            
            rendered_img_cpu = NP.asnumpy(sampled_colors_array) if GPU_ENABLED else sampled_colors_array
            R_cpu = NP.asnumpy(R_array) if GPU_ENABLED else R_array
            
            rendered_img = rendered_img_cpu.reshape(image_size, image_size, 3)
            img_pil = Image.fromarray(rendered_img)
            
            if horizon_ref and i == 0:
                view_pitch, yaw_idx = 0.0, 0
            else:
                adj = i - (1 if horizon_ref else 0)
                view_pitch = pitch_angles[adj // yaw_steps]
                yaw_idx = adj % yaw_steps
            filename = f"{base_name}_view_{i:02d}_p{view_pitch:+03.0f}_y{yaw_idx:02d}"
            
            if save_images: 
                img_path = os.path.join(out_dir, f"{filename}.jpg")
                img_pil.save(img_path, quality=95)
            
            images.append((img_pil, f"View {i}", R_cpu))

            # CHECK CANCELLATION AFTER EACH VIEW PROCESSING
            if cancel_event and cancel_event.is_set():
                print(f"🛑 View rendering cancelled after view {i+1}/{total_views}")
                break
        
        # Final progress callback for completion
        if progress_callback and not cancel_event.is_set():
            progress_callback(total_views, total_views)
        
        print(f"Completed rendering {len(images)} views from {base_name}")
        return images, pano_np_cpu
    
    except Exception as e:
        # Better error context
        error_msg = f"Failed to process panorama {os.path.basename(pano_path)}: {e}"
        print(error_msg)
        traceback.print_exc()
        raise RuntimeError(error_msg) from e
    
    finally:
        # Always clean up GPU memory using helper function
        _cleanup_gpu_memory()

# --- Centralized GPU memory cleanup ---

def _cleanup_gpu_memory():
    """Centralized GPU memory cleanup."""
    if GPU_ENABLED and 'cp' in sys.modules:
        try:
            if hasattr(sys.modules['cp'], 'cuda') and sys.modules['cp'].cuda.is_available():
                sys.modules['cp'].get_default_memory_pool().free_all_blocks()
                return True
        except Exception as e:
            print(f"Warning: GPU memory cleanup failed: {e}")
    return False