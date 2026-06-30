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


def generate_xmp_content(focal_length_35mm: float,
                         gps: dict | None = None) -> str:
    """Generate XMP content: intrinsic calibration only (no pose/rig fields),
    matching Epic's own pano2views tool's XMP format.  If `gps` is provided
    (dict with 'lat', 'lon', optional 'alt'), adds a GPS position prior so
    RealityScan can use approximate camera positions to seed alignment.

    Note: RealityCapture's xcr:Coordinates="absolute" position order is
    longitude, latitude, altitude (NOT lat/lon).  PosePrior is "draft" (not
    "exact") because GPS has ~3–10 m accuracy — RS refines poses via feature
    matching, using GPS only as an initial constraint."""
    gps_attrs = ""
    gps_pos   = ""
    if gps and gps.get('lat') is not None and gps.get('lon') is not None:
        lat = float(gps['lat'])
        lon = float(gps['lon'])
        alt = float(gps.get('alt', 0))
        gps_attrs = (
            '\n   xcr:Coordinates="absolute"'
            '\n   xcr:PosePrior="draft"'
        )
        gps_pos = f"\n   <xcr:Position>{lon:.8f} {lat:.8f} {alt:.3f}</xcr:Position>"

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
   xcr:DistortionGroup="-1"{gps_attrs}>{gps_pos}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>'''
    return xmp_template


def export_xmp_rig_files(output_dir: str, frame_name: str, pitch_angles: list, yaw_steps: int,
                         fov_deg: float, horizon_ref: bool = False,
                         gps: dict | None = None, **_ignored):
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
    xmp_content = generate_xmp_content(focal_length_35mm, gps=gps)

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
                          horizon_ref: bool = False,
                          gps_map: "dict[str, dict] | None" = None,
                          gps_sidecar_dir: str | None = None):
    """
    Export XMP calibration sidecars for all frames in the views directory.

    Args:
        views_dir:         Root directory containing frame subdirectories (02_views/)
        pitch_angles:      List of pitch angles used for extraction
        yaw_steps:         Number of yaw steps used for extraction
        fov_deg:           The FOV the views were actually rendered at
        horizon_ref:       If True, include the view_00 horizon reference sensor
        gps_map:           Optional {frame_stem: {lat, lon, alt}} dict. When provided,
                           GPS position priors are written into each frame's XMP files.
        gps_sidecar_dir:   If gps_map is None, look for <frame_stem>.gps.json files in
                           this directory (typically the input "import from camera" dir).
                           This is the automatic path: GPS written during camera import
                           is picked up here without needing extra parameters.
    """
    import json as _json

    views_path = Path(views_dir)

    if not views_path.exists():
        print(f"Views directory not found: {views_dir}")
        return False

    frame_dirs = sorted(d for d in views_path.iterdir() if d.is_dir())

    if not frame_dirs:
        print(f"No frame directories found in: {views_dir}")
        return False

    # Auto-discover GPS sidecar dir if not given (sibling of 02_views/)
    sidecar_path = None
    if gps_map is None and gps_sidecar_dir is None:
        # Try <views_dir>/../import from camera/  then  <views_dir>/../imported photos/
        parent = views_path.parent
        for candidate in ("import from camera", "imported photos"):
            p = parent / candidate
            if p.is_dir():
                sidecar_path = p
                break
    elif gps_sidecar_dir:
        sidecar_path = Path(gps_sidecar_dir)

    gps_count = 0
    print(f"Exporting XMP calibration sidecars for {len(frame_dirs)} frames...")

    success_count = 0
    for frame_dir in frame_dirs:
        stem = frame_dir.name
        # Resolve GPS for this frame
        gps = None
        if gps_map:
            gps = gps_map.get(stem)
        elif sidecar_path:
            sidecar = sidecar_path / f"{stem}.gps.json"
            if sidecar.exists():
                try:
                    gps = _json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    pass
        if gps:
            gps_count += 1
        try:
            export_xmp_rig_files(str(frame_dir), stem, pitch_angles, yaw_steps,
                                 fov_deg=fov_deg, horizon_ref=horizon_ref, gps=gps)
            success_count += 1
        except Exception as e:
            print(f"Failed to export XMP for {stem}: {e}")

    gps_note = f" ({gps_count} with GPS position priors)" if gps_count else ""
    print(f"XMP export complete: {success_count}/{len(frame_dirs)} frames processed{gps_note}")
    return success_count > 0
