# xmp_rig_export.py - RealityScan XMP calibration sidecar generation
#
# Simplified to match Epic's own pano2views tool
# (https://github.com/EpicGames/RealityScan) rather than our earlier
# full pose/rig XMP. That tool writes ONLY intrinsic calibration
# (CalibrationPrior="exact" + focal length derived from FOV) and deliberately
# omits pose/position/rig fields, letting RealityScan's own SfM recover
# camera poses and rig structure freely.
#
# Why: RealityCapture/RealityScan detects zero-baseline (zero-parallax)
# sibling views from the same panorama automatically via feature matching --
# it doesn't need to be told the rig structure the way COLMAP does. Writing
# xcr:PosePrior="exact" with an absolute world position of (0,0,0) for every
# camera (our old approach) is actively wrong: it tells RS every camera in
# the whole sequence sits at the same world-space point, which is impossible
# for a moving capture. The only prior RS genuinely needs from a virtual
# 360-camera rig is the focal length, since that's the one thing it cannot
# recover from feature matching alone.

import os
import uuid
from pathlib import Path

import numpy as np


def focal_length_35mm_from_fov(fov_deg: float) -> float:
    """35mm-equivalent focal length for a given horizontal FOV (36mm sensor width
    assumed, the standard "35mm equivalent" reference). Must track the actual
    rendered FOV -- panorama_processing.py's get_virtual_camera_rays() renders
    pixels at the real fov_deg, so RealityScan must be told the matching focal
    length or its reconstruction has the same focal/frustum mismatch that caused
    the wall/surface "double vision" bug in the COLMAP path (see
    COLMAP_POSE_CORRECTION_BRIEF.md Problem 15)."""
    return 18.0 / np.tan(np.radians(fov_deg / 2.0))


def generate_xmp_content(focal_length_35mm: float) -> str:
    """Generate XMP content: intrinsic calibration only, no pose/rig fields.
    Matches Epic's own pano2views tool's XMP format for 360-camera virtual
    cameras."""
    xmp_template = f'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#"
   xcr:Version="3"
   xcr:DistortionModel="division"
   xcr:DistortionCoeficients="0 0 0 0 0 0"
   xcr:FocalLength35mm="{focal_length_35mm}"
   xcr:Skew="0"
   xcr:AspectRatio="1"
   xcr:PrincipalPointU="0"
   xcr:PrincipalPointV="0"
   xcr:CalibrationPrior="exact"
   xcr:CalibrationGroup="-1"
   xcr:DistortionGroup="-1">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>'''
    return xmp_template


def export_xmp_rig_files(output_dir: str, frame_name: str, pitch_angles: list, yaw_steps: int,
                         fov_deg: float, horizon_ref: bool = False, **_ignored):
    """
    Export XMP calibration sidecars for a single frame's extracted views.

    Args:
        output_dir:   Directory where the frame's view images are stored
        frame_name:   Base name of the frame (e.g., "frame_000001")
        pitch_angles: List of pitch angles used for extraction
        yaw_steps:    Number of yaw steps used for extraction
        fov_deg:      The FOV the views were actually rendered at (must match
                      panorama_processing.py's fov_deg so the focal length told to
                      RealityScan matches the rendered frustum -- see
                      focal_length_35mm_from_fov()).
        horizon_ref:  If True, include a view_00 at pitch=0°, yaw=0° matching
                      panorama_processing.py's horizon reference sensor.

    Note: rig_id/pose_prior kwargs from the old call signature are accepted
    and ignored (**_ignored) so existing call sites don't need to change.
    """
    output_path = Path(output_dir)
    focal_length_35mm = focal_length_35mm_from_fov(fov_deg)
    xmp_content = generate_xmp_content(focal_length_35mm)

    # Build view metadata list to match panorama_processing.py naming exactly
    view_meta = []  # (view_index, pitch_deg, yaw_idx)
    if horizon_ref:
        view_meta.append((0, 0.0, 0))
    for pitch in pitch_angles:
        for yaw_idx in range(yaw_steps):
            view_meta.append((len(view_meta), pitch, yaw_idx))

    print(f"Generating XMP calibration sidecars for {frame_name} ({len(view_meta)} views)")

    for view_idx, pitch, yaw_idx in view_meta:
        view_filename = f"{frame_name}_view_{view_idx:02d}_p{pitch:+03.0f}_y{yaw_idx:02d}.jpg"
        xmp_path = output_path / f"{view_filename}.xmp"
        try:
            with open(xmp_path, 'w', encoding='utf-8') as f:
                f.write(xmp_content)
        except Exception as e:
            print(f"   Failed to create {xmp_path.name}: {e}")

    print(f"XMP export complete: {len(view_meta)} files created")


def export_all_frame_rigs(views_dir: str, pitch_angles: list, yaw_steps: int, fov_deg: float,
                          horizon_ref: bool = False):
    """
    Export XMP calibration sidecars for all frames in the views directory.

    Args:
        views_dir:    Root directory containing frame subdirectories
        pitch_angles: List of pitch angles used for extraction
        yaw_steps:    Number of yaw steps used for extraction
        fov_deg:      The FOV the views were actually rendered at -- must match the
                      fov_deg passed to panorama_processing.render_views() for this job.
        horizon_ref:  If True, include the view_00 horizon reference sensor in each frame's XMP set
    """
    views_path = Path(views_dir)

    if not views_path.exists():
        print(f"Views directory not found: {views_dir}")
        return False

    frame_dirs = sorted(d for d in views_path.iterdir() if d.is_dir())

    if not frame_dirs:
        print(f"No frame directories found in: {views_dir}")
        return False

    print(f"Exporting XMP calibration sidecars for {len(frame_dirs)} frames...")

    success_count = 0
    for frame_dir in frame_dirs:
        try:
            export_xmp_rig_files(str(frame_dir), frame_dir.name, pitch_angles, yaw_steps,
                                 fov_deg=fov_deg, horizon_ref=horizon_ref)
            success_count += 1
        except Exception as e:
            print(f"Failed to export XMP for {frame_dir.name}: {e}")

    print(f"XMP export complete: {success_count}/{len(frame_dirs)} frames processed")
    return success_count > 0
