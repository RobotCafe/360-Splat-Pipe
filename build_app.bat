@echo off
:: 360° SplatPipe - App Build Script

TITLE Building 360° SplatPipe Application

echo =======================================================================
echo.
echo           360° SplatPipe - Application Builder
echo.
echo =======================================================================
echo.

:: Check if we're in the right directory
if not exist "SplatPipe.py" (
    echo [ERROR] SplatPipe.py not found. Please run this script from the project root.
    goto :end_with_pause
)

if not exist "App\main_app.py" (
    echo [ERROR] App directory not found. Please run this script from the project root.
    goto :end_with_pause
)

:: Check Python
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.8+ from python.org
    goto :end_with_pause
)

echo [INFO] Python found:
py --version

:: Install PyInstaller if needed
echo.
echo [INFO] Checking PyInstaller installation...
py -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] PyInstaller not found. Installing...
    py -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller
        goto :end_with_pause
    )
) else (
    echo [INFO] PyInstaller is available
)

:: Clean previous build
echo.
echo [INFO] Cleaning previous build...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "__pycache__" rmdir /s /q "__pycache__"

:: Build the application
echo.
echo [INFO] Building SplatPipe application...
echo [INFO] This may take a few minutes...
echo.

py -m PyInstaller SplatPipe.spec

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed! Check the output above for errors.
    goto :end_with_pause
)

:: Check if build succeeded
if not exist "dist\SplatPipe\SplatPipe.exe" (
    echo [ERROR] Build completed but executable not found in dist\SplatPipe\
    goto :end_with_pause
)

:: Build success
echo.
echo =======================================================================
echo [SUCCESS] SplatPipe application built successfully!
echo =======================================================================
echo.
echo Built application location:
echo   %cd%\dist\SplatPipe\
echo.
echo Main executable:
echo   %cd%\dist\SplatPipe\SplatPipe.exe
echo.
echo [NEXT STEPS]
echo 1. Test the application by running: dist\SplatPipe\SplatPipe.exe
echo 2. The first run will show a dependency setup wizard
echo 3. Package the dist\SplatPipe folder for distribution
echo.
echo [OPTIONAL] Create installer:
echo   - Use NSIS or similar to create a proper Windows installer
echo   - Include the entire dist\SplatPipe folder in the installer
echo.
echo =======================================================================

:end_with_pause
echo.
pause
exit