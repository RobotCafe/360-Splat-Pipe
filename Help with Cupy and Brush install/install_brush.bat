@echo off
echo This script will help you install Brush.
echo.

REM Check for Rust
echo Checking for Rust installation...
where rustc >nul 2>nul
if %errorlevel% neq 0 (
    echo Rust is not installed. Please install it from https://www.rust-lang.org/tools/install
    pause
    exit /b
) else (
    echo Rust is already installed.
)
echo.

REM Install rerun-cli (optional)
echo Installing rerun-cli (optional but recommended)...
cargo install rerun-cli
echo.

REM Clone the repository
echo Cloning the Brush repository...
git clone https://github.com/ArthurBrussee/brush.git
cd brush
echo.

REM Build and run Brush
echo Building and running Brush...
cargo run --release
echo.

echo Brush installation and setup is complete.
pause