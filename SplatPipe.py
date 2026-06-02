#!/usr/bin/env python3
"""
360° SplatPipe - Main Entry Point for Packaged Application
Entry point script for PyInstaller packaging
"""

import sys
import os
from pathlib import Path

# Add App directory to Python path
app_dir = Path(__file__).parent / "App"
sys.path.insert(0, str(app_dir))

# Import and run the main application
if __name__ == "__main__":
    try:
        from main_app import main
        main()
    except Exception as e:
        print(f"Fatal error starting SplatPipe: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
        sys.exit(1)