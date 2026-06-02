# _common_utils.py - Unified GPU detection system

import sys
import os
import uuid
import numpy as np
from pathlib import Path

# import traceback

# === UNIFIED GPU DETECTION SYSTEM ===

def check_cupy_availability():
    """Check if CuPy (CUDA for Python) is available."""
    try:
        import cupy as cp
        # Test basic CUDA operation
        test_array = cp.array([1, 2, 3])
        _ = cp.sum(test_array)  # Force CUDA context creation
        return True, cp, None
    except Exception as e:
        return False, None, str(e)

def check_opencv_cuda_availability():
    """Check if OpenCV has CUDA support."""
    try:
        import cv2
        
        # Check if CUDA module exists
        if not hasattr(cv2, 'cuda'):
            return False, "OpenCV compiled without CUDA support"
        
        # Check device count
        device_count = cv2.cuda.getCudaEnabledDeviceCount()
        
        if device_count == 0:
            return False, "No CUDA devices detected by OpenCV (may need OpenCV compiled with CUDA)"
        elif device_count == -1:
            return False, "CUDA driver incompatible or insufficient"
        else:
            return True, f"OpenCV CUDA: {device_count} device(s) available"
            
    except Exception as e:
        return False, f"OpenCV CUDA check failed: {e}"

# === PERFORM GPU CHECKS ===

# Check CuPy first (for panorama processing)
CUPY_AVAILABLE, cp_module, cupy_error = check_cupy_availability()

# Check OpenCV CUDA (for video extraction)
OPENCV_CUDA_AVAILABLE, opencv_cuda_msg = check_opencv_cuda_availability()

# === SET GLOBAL VARIABLES ===

if CUPY_AVAILABLE:
    import cupy as cp
    GPU_ENABLED = True
    print("✅ CuPy and CUDA Toolkit found. GPU acceleration enabled for panorama processing.")
else:
    import numpy as cp  # Fallback to NumPy
    GPU_ENABLED = False
    print(f"⚠️ CuPy not available: {cupy_error}")
    print("Falling back to CPU for panorama processing.")

# Video extraction GPU status
if OPENCV_CUDA_AVAILABLE:
    GPU_EXTRACTION_ENABLED = True
    print(f"✅ {opencv_cuda_msg}")
else:
    GPU_EXTRACTION_ENABLED = False
    print(f"⚠️ OpenCV CUDA not available: {opencv_cuda_msg}")
    print("Video extraction will use CPU/FFmpeg fallback.")

# === SUMMARY MESSAGE ===
def get_gpu_status_summary():
    """Get a summary of GPU capabilities."""
    if GPU_ENABLED and GPU_EXTRACTION_ENABLED:
        return "Ready - ✅ Full GPU acceleration enabled (CuPy + OpenCV CUDA)"
    elif GPU_ENABLED:
        return "Ready - ✅ Partial GPU acceleration (CuPy only, CPU video extraction)"
    elif GPU_EXTRACTION_ENABLED:
        return "Ready - ✅ Partial GPU acceleration (OpenCV CUDA only, CPU panorama processing)"
    else:
        return "Ready - ⚠️ CPU-only mode. Install CUDA 12.x + rebuild OpenCV for full GPU acceleration."

# Try to import the GPU video extractor if available
try:
    from GPU_video_extraction import VideoFrameExtractor
    # Don't perform any tests here - just check if it imports
    print("📦 GPU video extractor module available")
except ImportError as e:
    print(f"📦 GPU video extractor not available: {e}")

# === GLOBAL PARAMETERS ===
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / '360_SplatPipe_config.ini'

# Alias for the numerical library based on GPU_ENABLED
NP = cp

# === LOG DIRECTORY MANAGEMENT ===

def get_user_logs_directory():
    """
    Get appropriate logs directory for current OS and packaging state.
    
    Returns:
        Path: Logs directory path
        - Development mode: project_root/logs/
        - Packaged app: User data directory (APPDATA on Windows, ~/.config on Unix)
    """
    # Detect if we're running as packaged app (PyInstaller sets sys.frozen)
    if getattr(sys, 'frozen', False):
        # Packaged app - use user data directory
        if os.name == 'nt':  # Windows
            app_data = os.environ.get('APPDATA')
            if app_data:
                return Path(app_data) / "SplatPipe" / "logs"
            else:
                # Fallback to user profile if APPDATA not available
                return Path.home() / "SplatPipe" / "logs"
        else:  # macOS/Linux
            home = Path.home()
            return home / ".config" / "splatpipe" / "logs"
    else:
        # Development mode - keep current behavior (relative to project root)
        app_dir = Path(__file__).parent
        return app_dir.parent / "logs"