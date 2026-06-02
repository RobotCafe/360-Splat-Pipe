@echo off
:: 360° SplatPipe - Dependency Installer (CUDA 12.x)

TITLE 360° SplatPipe - Installing Dependencies

:: Parse command line arguments
set INSTALL_TYPE=full
if "%1"=="--core" set INSTALL_TYPE=core
if "%1"=="--full" set INSTALL_TYPE=full

echo =======================================================================
echo.
echo           360° SplatPipe - Dependency Installer
echo.
echo =======================================================================
echo.
if "%INSTALL_TYPE%"=="core" (
    echo [INFO] Installing CORE dependencies only ^(lightweight^)
) else (
    echo [INFO] Installing FULL dependencies ^(includes GPU acceleration^)
    echo [INFO] This installer requires CUDA Toolkit 12.x for GPU acceleration
    echo [INFO] If you don't have CUDA 12.x, the app will run in CPU-only mode
)
echo.

:: Check Python
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.8+ from python.org
    goto :end_with_pause
)

echo [INFO] Python found:
py --version

:: Upgrade pip
echo.
echo [INFO] Upgrading pip...
py -m pip install --upgrade pip

:: Install requirements based on type
echo.
if "%INSTALL_TYPE%"=="core" (
    echo [INFO] Installing core dependencies only...
    echo [INFO] This should be quick ^(~30 seconds^)
    py -m pip install -r requirements-core.txt
) else (
    echo [INFO] Installing all dependencies ^(including CuPy for CUDA 12.x^)...
    echo [INFO] This may take a few minutes...
    py -m pip install -r requirements.txt
)

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Installation had issues. Common causes:
    echo   - Missing CUDA 12.x toolkit
    echo   - Internet connection problems
    echo   - Missing Visual Studio Build Tools
    echo.
    echo [INFO] The app may still work in CPU-only mode.
    echo [TIP] For GPU acceleration, install CUDA 12.x and re-run this script.
) else (
    echo.
    echo [SUCCESS] All dependencies installed successfully!
)

:: Test installation based on type
echo.
if "%INSTALL_TYPE%"=="core" (
    echo [INFO] Testing core dependencies...
    py -c "import numpy, PIL, psutil, py360convert; print('✅ Core dependencies installed successfully!')" 2>nul
    if %errorlevel% equ 0 (
        echo [SUCCESS] Core dependencies are working correctly!
        echo [INFO] Run with --full flag to install GPU acceleration and heavy dependencies
    ) else (
        echo [WARNING] Some core dependencies may not be working properly
    )
) else (
    echo [INFO] Testing GPU acceleration...
    py -c "import cupy; print('✅ GPU acceleration available!'); import cupy as cp; test=cp.array([1,2,3]); print('✅ CuPy test passed:', cp.sum(test).item())" 2>nul
    if %errorlevel% equ 0 (
        echo [SUCCESS] GPU acceleration is working correctly!
    ) else (
        echo [INFO] GPU acceleration not available - app will use CPU mode
        echo [TIP] For GPU acceleration: Install CUDA 12.x, restart, and re-run this script
    )
)

echo.
echo =======================================================================
echo.
echo [COMPLETE] Installation finished!
echo.
echo [NEXT] Before launching, ensure these files are in place:
echo.
echo   1. FFmpeg ^(not included^):
echo      - Download from https://ffmpeg.org/download.html
echo      - Place ffmpeg.exe and ffprobe.exe in "FFmpeg and RS Settings\" folder
echo.
echo   2. VGGT Model ^(not included^):
echo      - Download from https://github.com/facebookresearch/vggt
echo      - Accepts Meta license agreement required
echo      - Place model file^(s^) in "models\" folder
echo      - skyseg.onnx will be downloaded automatically on first use
echo.
echo   3. Configure tool paths in the Configuration tab:
echo      - FFmpeg path
echo      - VGGT installation path + model path
echo      - RealityScan, Postshot, Brush executables
echo.
echo =======================================================================

:end_with_pause
echo.
pause
exit