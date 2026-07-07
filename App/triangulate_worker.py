# triangulate_worker.py
"""
Python 3.14 / pycolmap 4.0.4 worker for VGGT anchor+rig triangulation.

Receives a JSON payload via sys.argv[1] containing:
  sparse_dir — path to the sparse/ directory that write_colmap_files already wrote
               (contains cameras.txt, images.txt, points3D.txt)

The flat images/ directory is expected at sparse_dir/../images/ — app_callbacks.py
copies all rig images (anchor + siblings) there before run_full_pipeline is called.

Steps:
  1. Read cameras.txt -> recover camera model and intrinsics
  2. Extract SIFT features from images/ using those intrinsics
  3. Sequential matching across the temporal+sensor sequence
  4. Build a pycolmap Reconstruction from the fixed poses in images.txt
  5. Triangulate via pycolmap.triangulate_points (fixed poses, refine_intrinsics=False)
  6. Output written to sparse_dir by triangulate_points (overwrites points3D.txt)

Progress lines: WORKER_PROGRESS:<pct>:<message>
Final stdout line: JSON result
"""
import sys
import json
import traceback
from pathlib import Path

import numpy as np


def _prog(pct: int, msg: str) -> None:
    print(f"WORKER_PROGRESS:{pct}:{msg}", flush=True)


def _parse_cameras_txt(cameras_txt: Path):
    """
    Parse cameras.txt and return the first camera's (model, width, height, params).
    In anchor+rig mode all cameras share the same intrinsics so we only need the first.
    Returns (model_name_str, width, height, params_list).
    """
    for line in cameras_txt.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        model  = parts[1]                               # e.g. PINHOLE or SIMPLE_PINHOLE
        width  = int(parts[2])
        height = int(parts[3])
        params = [float(x) for x in parts[4:]]         # e.g. [893.0, 960.0, 960.0]
        return model, width, height, params
    return None, 0, 0, []


def main():
    try:
        payload    = json.loads(sys.argv[1])
        sparse_dir = Path(payload["sparse_dir"])
        images_dir = sparse_dir.parent / "images"   # already populated by app_callbacks

        cameras_txt   = sparse_dir / "cameras.txt"
        images_txt    = sparse_dir / "images.txt"
        database_path = sparse_dir / "database.db"

        if not cameras_txt.exists():
            raise FileNotFoundError(f"cameras.txt not found at {cameras_txt}")
        if not images_txt.exists():
            raise FileNotFoundError(f"images.txt not found at {images_txt}")
        if not images_dir.exists():
            raise FileNotFoundError(f"images/ directory not found at {images_dir}")

        import pycolmap

        # ── 1. Read intrinsics from cameras.txt ───────────────────────────────
        _prog(5, "Reading camera intrinsics from cameras.txt…")
        model, img_width, img_height, params = _parse_cameras_txt(cameras_txt)
        if not model:
            raise RuntimeError("Could not parse cameras.txt")
        params_str = ",".join(str(p) for p in params)
        _prog(8, f"Camera: {model} {img_width}x{img_height}  params={params_str}")

        n_images = sum(1 for ln in images_txt.read_text().splitlines()
                       if ln.strip() and not ln.startswith("#"))
        # images.txt has two lines per image (pose line + points2D line)
        n_images = n_images // 2
        _prog(10, f"Found {n_images} registered images in images.txt")

        # ── 2. Feature extraction ─────────────────────────────────────────────
        _prog(15, "Extracting SIFT features from images/…")
        if database_path.exists():
            database_path.unlink()

        reader_opts = pycolmap.ImageReaderOptions(
            camera_model=model,
            camera_params=params_str,
        )
        pycolmap.extract_features(
            database_path=database_path,
            image_path=images_dir,
            reader_options=reader_opts,
            camera_mode=pycolmap.CameraMode.SINGLE,
        )
        _prog(35, "Feature extraction complete.")

        # ── 3. Sequential matching ─────────────────────────────────────────────
        # Images are ordered: anchor frame 0, anchor frame 1, …, sibling1 frame 0, …
        # Sequential matching catches temporal continuity within each sensor and,
        # with sufficient overlap, also cross-sensor neighbours at the same time step.
        _prog(40, "Sequential feature matching…")
        pycolmap.match_sequential(
            database_path,
            matching_options=pycolmap.FeatureMatchingOptions(),
        )
        _prog(60, "Feature matching complete.")

        # ── 4. Build reconstruction with fixed poses from images.txt ──────────
        _prog(62, "Building reconstruction from fixed camera poses in images.txt…")

        recon = pycolmap.Reconstruction()

        # Single shared camera for all images (VGGT anchor+rig uses same intrinsics)
        camera = pycolmap.Camera(
            model=model,
            width=img_width,
            height=img_height,
            params=params,
            camera_id=1,
        )
        camera.has_prior_focal_length = True
        recon.add_camera(camera)

        # Parse images.txt — two lines per image: pose line then points2D line
        img_id_counter = 1
        data_line = False
        for raw in images_txt.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not data_line:
                parts = line.split()
                if len(parts) >= 9:
                    qw  = float(parts[1]); qx = float(parts[2])
                    qy  = float(parts[3]); qz = float(parts[4])
                    tx  = float(parts[5]); ty = float(parts[6]); tz = float(parts[7])
                    img_name = parts[9] if len(parts) > 9 else f"image_{img_id_counter}.jpg"
                    image = pycolmap.Image(
                        id=img_id_counter, name=img_name, camera_id=1,
                    )
                    # COLMAP images.txt stores [qw,qx,qy,qz]; Rotation3d expects [x,y,z,w]
                    image.cam_from_world = pycolmap.Rigid3d(
                        pycolmap.Rotation3d(np.array([qx, qy, qz, qw])),
                        np.array([tx, ty, tz]),
                    )
                    image.registered = True
                    recon.add_image(image)
                    img_id_counter += 1
                data_line = True
            else:
                data_line = False

        _prog(65, f"Reconstruction: {len(recon.images)} images, {len(recon.cameras)} camera models.")

        # ── 5. Triangulate with fixed poses ───────────────────────────────────
        # pycolmap.triangulate_points is the correct API for fixed-pose triangulation
        # in pycolmap 4.0.4. CorrespondenceGraph.from_database does NOT exist in 4.0.4.
        _prog(68, "Triangulating 3D points with fixed camera poses…")

        tri_options = pycolmap.IncrementalPipelineOptions()
        tri_options.ba_refine_focal_length    = False   # keep intrinsics fixed
        tri_options.ba_refine_principal_point = False
        tri_options.ba_refine_extra_params    = False
        tri_options.fix_existing_frames       = True    # keep poses fixed
        tri_options.multiple_models           = False   # single reconstruction

        result = pycolmap.triangulate_points(
            recon,
            database_path,
            images_dir,
            sparse_dir,                  # writes cameras/images/points3D.txt here
            clear_points=True,
            options=tri_options,
            refine_intrinsics=False,
        )

        n_pts = len(result.points3D)
        _prog(95, f"Triangulation complete — {n_pts} 3D points written to {sparse_dir}")

        print(json.dumps({"success": True, "points3D": n_pts}), flush=True)

    except Exception as e:
        print(json.dumps({
            "success":   False,
            "error":     str(e),
            "traceback": traceback.format_exc(),
        }), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
