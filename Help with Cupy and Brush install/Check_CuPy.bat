@echo off
:: Check CuPy Installation and CUDA Compatibility
:: This script diagnoses GPU acceleration issues for 360° SplatPipe

TITLE 360° SplatPipe - CuPy Diagnostic Tool

echo =======================================================================
echo.
echo           360° SplatPipe - CuPy Diagnostic Tool
echo.
echo =======================================================================
echo.

:: Check if Python is available
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python launcher 'py.exe' not found.
    echo Please ensure Python is properly installed.
    goto :end_with_pause
)

echo [INFO] Python launcher found. Checking Python version...
py --version

:: Check if CuPy diagnostic script exists
if not exist "check_cupy.py" (
    echo.
    echo [INFO] Creating CuPy diagnostic script...
    
    :: Create the diagnostic script inline
    echo # CuPy Diagnostic Script for 360° SplatPipe > check_cupy.py
    echo import sys >> check_cupy.py
    echo import os >> check_cupy.py
    echo. >> check_cupy.py
    echo print^("==="^*60^) >> check_cupy.py
    echo print^("360° SplatPipe - CuPy Diagnostic Report"^) >> check_cupy.py
    echo print^("==="^*60^) >> check_cupy.py
    echo print^(f"Python Executable: {sys.executable}"^) >> check_cupy.py
    echo print^(f"Python Version: {sys.version}"^) >> check_cupy.py
    echo print^("\\n1. TESTING CUPY IMPORT..."^) >> check_cupy.py
    echo. >> check_cupy.py
    echo try: >> check_cupy.py
    echo     import cupy as cp >> check_cupy.py
    echo     print^("CuPy import successful!"^) >> check_cupy.py
    echo     cupy_available = True >> check_cupy.py
    echo except ImportError as e: >> check_cupy.py
    echo     print^(f"CuPy import failed: {e}"^) >> check_cupy.py
    echo     cupy_available = False >> check_cupy.py
    echo except Exception as e: >> check_cupy.py
    echo     print^(f"Unexpected CuPy error: {e}"^) >> check_cupy.py
    echo     cupy_available = False >> check_cupy.py
    echo. >> check_cupy.py
    echo if cupy_available: >> check_cupy.py
    echo     print^("\\n2. TESTING CUDA OPERATIONS..."^) >> check_cupy.py
    echo     try: >> check_cupy.py
    echo         # Test basic CUDA operation >> check_cupy.py
    echo         test_array = cp.array^([1, 2, 3, 4, 5]^) >> check_cupy.py
    echo         result = cp.sum^(test_array^) >> check_cupy.py
    echo         print^(f"CUDA operation successful! Test sum: {result}"^) >> check_cupy.py
    echo.  >> check_cupy.py
    echo         # Show CuPy configuration >> check_cupy.py
    echo         print^("\\n3. CUPY CONFIGURATION:"^) >> check_cupy.py
    echo         print^("---"^*30^) >> check_cupy.py
    echo         print^(cp.show_config^(^)^) >> check_cupy.py
    echo.  >> check_cupy.py
    echo         # Show CUDA device info >> check_cupy.py
    echo         print^("\\n4. CUDA DEVICE INFORMATION:"^) >> check_cupy.py
    echo         print^("---"^*30^) >> check_cupy.py
    echo         device = cp.cuda.Device^(0^) >> check_cupy.py
    echo         print^(f"Device 0: {device}"^) >> check_cupy.py
    echo         print^(f"Total Memory: {device.mem_info[1] / 1024**3:.1f} GB"^) >> check_cupy.py
    echo         print^(f"Free Memory: {device.mem_info[0] / 1024**3:.1f} GB"^) >> check_cupy.py
    echo.  >> check_cupy.py
    echo     except Exception as e: >> check_cupy.py
    echo         print^(f"CUDA operation failed: {e}"^) >> check_cupy.py
    echo         print^("This usually indicates a CUDA/CuPy compatibility issue."^) >> check_cupy.py
    echo. >> check_cupy.py
    echo print^("\\n5. SYSTEM CUDA INFORMATION:"^) >> check_cupy.py
    echo print^("---"^*30^) >> check_cupy.py
    echo import subprocess >> check_cupy.py
    echo try: >> check_cupy.py
    echo     result = subprocess.run^(['nvidia-smi', '--query-gpu=name,driver_version,cuda_version', '--format=csv,noheader,nounits'], capture_output=True, text=True^) >> check_cupy.py
    echo     if result.returncode == 0: >> check_cupy.py
    echo         print^("GPU Information ^(nvidia-smi^):"^) >> check_cupy.py
    echo         print^(result.stdout.strip^(^)^) >> check_cupy.py
    echo     else: >> check_cupy.py
    echo         print^("nvidia-smi command failed"^) >> check_cupy.py
    echo except FileNotFoundError: >> check_cupy.py
    echo     print^("nvidia-smi not found - NVIDIA drivers may not be installed"^) >> check_cupy.py
    echo except Exception as e: >> check_cupy.py
    echo     print^(f"Error running nvidia-smi: {e}"^) >> check_cupy.py
    echo. >> check_cupy.py
    echo print^("\\n6. ENVIRONMENT DIAGNOSIS:"^) >> check_cupy.py
    echo print^("---"^*30^) >> check_cupy.py
    echo cuda_path = os.environ.get^('CUDA_PATH'^) >> check_cupy.py
    echo if cuda_path: >> check_cupy.py
    echo     print^(f"CUDA_PATH environment variable: {cuda_path}"^) >> check_cupy.py
    echo else: >> check_cupy.py
    echo     print^("CUDA_PATH environment variable not set"^) >> check_cupy.py
    echo. >> check_cupy.py
    echo path_env = os.environ.get^('PATH', ''^) >> check_cupy.py
    echo cuda_paths = [p for p in path_env.split^(';'^) if 'cuda' in p.lower^(^)]^) >> check_cupy.py
    echo if cuda_paths: >> check_cupy.py
    echo     print^("CUDA-related paths in PATH:"^) >> check_cupy.py
    echo     for i, path in enumerate^(cuda_paths, 1^): >> check_cupy.py
    echo         print^(f"  {i}. {path}"^) >> check_cupy.py
    echo     if len^(cuda_paths^) ^> 1: >> check_cupy.py
    echo         print^("WARNING: Multiple CUDA paths detected!"^) >> check_cupy.py
    echo         print^("   This can cause DLL conflicts. Consider keeping only one CUDA version."^) >> check_cupy.py
    echo else: >> check_cupy.py
    echo     print^("No CUDA paths found in PATH environment variable"^) >> check_cupy.py
    echo. >> check_cupy.py
    echo print^("\\n7. RECOMMENDATIONS:"^) >> check_cupy.py
    echo print^("---"^*30^) >> check_cupy.py
    echo if not cupy_available: >> check_cupy.py
    echo     print^(" To fix CuPy issues:"^) >> check_cupy.py
    echo     print^("   1. Install CUDA Toolkit 12.x from NVIDIA"^) >> check_cupy.py
    echo     print^("   2. Restart computer after CUDA installation"^) >> check_cupy.py
    echo     print^("   3. Run: py -m pip install cupy-cuda12x"^) >> check_cupy.py
    echo     print^("   4. Clean PATH environment variable of old CUDA versions"^) >> check_cupy.py
    echo else: >> check_cupy.py
    echo     print^("CuPy is working correctly!"^) >> check_cupy.py
    echo     print^("   360° SplatPipe should have GPU acceleration enabled."^) >> check_cupy.py
    echo. >> check_cupy.py
    echo print^("==="^*60^) >> check_cupy.py
    
    echo [SUCCESS] Diagnostic script created.
)

echo.
echo [INFO] Running CuPy diagnostic...
echo.

:: Run the diagnostic script
py check_cupy.py

echo.
echo =======================================================================
echo.
echo [INFO] Diagnostic complete! 
echo.
echo If CuPy is working, you should see "CuPy import successful" above.
echo If not, follow the recommendations provided in the diagnostic output.
echo.
echo For additional help:
echo - Check the README.md for CUDA installation troubleshooting
echo - Ensure only one CUDA version is in your PATH environment variable  
echo - Restart your computer after installing/changing CUDA versions
echo.
echo =======================================================================
echo.

:end_with_pause
echo Press any key to exit...
pause >nul
exit