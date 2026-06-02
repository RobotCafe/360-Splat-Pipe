# dependency_manager.py
# Handles dependency checking and first-run setup for packaged app

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pathlib import Path


class DependencyManager:
    """
    Manages dependency checking and installation for packaged SplatPipe app.
    Handles first-run setup and graceful fallbacks.
    """
    
    def __init__(self, parent_app=None):
        self.parent_app = parent_app
        self.missing_dependencies = []
        self.has_gpu_support = False
        self.has_core_deps = False
        self.setup_window = None
        
    def check_dependencies(self):
        """Check which dependencies are available."""
        print("🔍 Checking dependencies...")
        
        # Check core dependencies
        self.has_core_deps = self._check_core_dependencies()
        
        # Check GPU acceleration
        self.has_gpu_support = self._check_gpu_acceleration()
        
        # Check heavy dependencies
        missing_heavy = self._check_heavy_dependencies()
        
        return self.has_core_deps, self.has_gpu_support, missing_heavy
    
    def _check_core_dependencies(self):
        """Check if core dependencies are available."""
        core_deps = ['numpy', 'PIL', 'psutil', 'py360convert']
        missing = []
        
        for dep in core_deps:
            try:
                __import__(dep)
            except ImportError:
                missing.append(dep)
        
        if missing:
            print(f"❌ Missing core dependencies: {missing}")
            self.missing_dependencies.extend(missing)
            return False
        else:
            print("✅ Core dependencies available")
            return True
    
    def _check_gpu_acceleration(self):
        """Check if GPU acceleration is available."""
        try:
            import cupy
            # Test basic operation
            test = cupy.array([1, 2, 3])
            result = cupy.sum(test).item()
            print(f"✅ GPU acceleration available (CuPy test: {result})")
            return True
        except ImportError:
            print("ℹ️ CuPy not available - will use CPU mode")
            return False
        except Exception as e:
            print(f"⚠️ GPU acceleration test failed: {e}")
            return False
    
    def _check_heavy_dependencies(self):
        """Check which heavy dependencies are missing."""
        heavy_deps = {
            'cv2': 'opencv-python',
            'scipy': 'scipy',
            'matplotlib': 'matplotlib',
            'pycolmap': 'pycolmap',
            'trimesh': 'trimesh',
            'requests': 'requests',
            'onnxruntime': 'onnxruntime'
        }
        
        missing = []
        for import_name, package_name in heavy_deps.items():
            try:
                __import__(import_name)
            except ImportError:
                missing.append(package_name)
        
        if missing:
            print(f"ℹ️ Missing heavy dependencies: {missing}")
            self.missing_dependencies.extend(missing)
        
        return missing
    
    def show_first_run_setup(self):
        """Show first-run setup dialog if dependencies are missing."""
        if not self.missing_dependencies:
            return True  # All dependencies available
        
        self.setup_window = tk.Toplevel()
        self.setup_window.title("360° SplatPipe - First Run Setup")
        self.setup_window.geometry("600x500")
        self.setup_window.resizable(False, False)
        self.setup_window.grab_set()  # Make modal
        
        # Center the window
        self.setup_window.transient(self.parent_app.root if self.parent_app else None)
        
        self._create_setup_ui()
        
        # Wait for user decision
        self.setup_window.wait_window()
        
        return self.has_core_deps and len(self.missing_dependencies) == 0
    
    def _create_setup_ui(self):
        """Create the setup dialog UI."""
        main_frame = ttk.Frame(self.setup_window, padding=20)
        main_frame.pack(fill='both', expand=True)
        
        # Title
        title_label = tk.Label(
            main_frame, 
            text="🚀 Welcome to 360° SplatPipe!",
            font=('Arial', 16, 'bold')
        )
        title_label.pack(pady=(0, 10))
        
        # Description
        desc_text = """This appears to be your first run. Some dependencies need to be installed 
for full functionality. You can choose how to proceed:"""
        
        desc_label = tk.Label(
            main_frame,
            text=desc_text,
            wraplength=550,
            justify='left'
        )
        desc_label.pack(pady=(0, 20))
        
        # Options frame
        options_frame = ttk.LabelFrame(main_frame, text="Installation Options", padding=15)
        options_frame.pack(fill='x', pady=(0, 20))
        
        # Option 1: Full installation
        full_frame = ttk.Frame(options_frame)
        full_frame.pack(fill='x', pady=5)
        
        ttk.Button(
            full_frame,
            text="🎯 Full Installation (Recommended)",
            command=self._install_full_dependencies,
            width=40
        ).pack(side='left')
        
        ttk.Label(
            full_frame,
            text="GPU acceleration + all features",
            foreground='gray'
        ).pack(side='left', padx=(10, 0))
        
        # Option 2: Core only
        core_frame = ttk.Frame(options_frame)
        core_frame.pack(fill='x', pady=5)
        
        ttk.Button(
            core_frame,
            text="⚡ Quick Start (Core Only)",
            command=self._install_core_dependencies,
            width=40
        ).pack(side='left')
        
        ttk.Label(
            core_frame,
            text="CPU mode, faster setup",
            foreground='gray'
        ).pack(side='left', padx=(10, 0))
        
        # Option 3: Skip
        skip_frame = ttk.Frame(options_frame)
        skip_frame.pack(fill='x', pady=5)
        
        ttk.Button(
            skip_frame,
            text="⏭️ Skip Setup",
            command=self._skip_setup,
            width=40
        ).pack(side='left')
        
        ttk.Label(
            skip_frame,
            text="Use existing dependencies",
            foreground='gray'
        ).pack(side='left', padx=(10, 0))
        
        # Progress frame (hidden initially)
        self.progress_frame = ttk.LabelFrame(main_frame, text="Installation Progress", padding=15)
        
        self.progress_label = ttk.Label(self.progress_frame, text="Ready to install...")
        self.progress_label.pack(pady=5)
        
        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            mode='indeterminate',
            length=400
        )
        self.progress_bar.pack(pady=5)
        
        # Info text
        info_text = """💡 Tip: You can always run the installer manually later:
    • Full: install_requirements.bat --full
    • Core: install_requirements.bat --core"""
        
        info_label = tk.Label(
            main_frame,
            text=info_text,
            font=('Consolas', 9),
            foreground='gray',
            justify='left'
        )
        info_label.pack(pady=(10, 0))
    
    def _install_full_dependencies(self):
        """Install all dependencies including GPU support."""
        self._show_progress("Installing full dependencies...")
        thread = threading.Thread(target=self._run_installer, args=("--full",))
        thread.daemon = True
        thread.start()
    
    def _install_core_dependencies(self):
        """Install only core dependencies."""
        self._show_progress("Installing core dependencies...")
        thread = threading.Thread(target=self._run_installer, args=("--core",))
        thread.daemon = True
        thread.start()
    
    def _skip_setup(self):
        """Skip dependency installation."""
        result = messagebox.askyesno(
            "Skip Setup",
            "Are you sure you want to skip dependency installation?\n\n"
            "The app may not work correctly if required dependencies are missing."
        )
        
        if result:
            self.setup_window.destroy()
    
    def _show_progress(self, message):
        """Show installation progress."""
        self.progress_frame.pack(fill='x', pady=(20, 0))
        self.progress_label.config(text=message)
        self.progress_bar.start()
        
        # Disable option buttons
        for widget in self.setup_window.winfo_children():
            self._disable_buttons(widget)
    
    def _disable_buttons(self, widget):
        """Recursively disable all buttons."""
        if isinstance(widget, ttk.Button):
            widget.config(state='disabled')
        
        for child in widget.winfo_children():
            self._disable_buttons(child)
    
    def _run_installer(self, install_type):
        """Run the dependency installer in background."""
        try:
            # Get path to installer script
            app_dir = Path(__file__).parent.parent
            installer_path = app_dir / "install_requirements.bat"
            
            # Run installer
            self.setup_window.after(0, lambda: self.progress_label.config(
                text=f"Running installer {install_type}... (this may take a few minutes)"
            ))
            
            process = subprocess.run(
                [str(installer_path), install_type],
                capture_output=True,
                text=True,
                cwd=str(app_dir)
            )
            
            # Update UI based on result
            if process.returncode == 0:
                self.setup_window.after(0, self._installation_success)
            else:
                self.setup_window.after(0, lambda: self._installation_failed(process.stderr))
                
        except Exception as e:
            self.setup_window.after(0, lambda: self._installation_failed(str(e)))
    
    def _installation_success(self):
        """Handle successful installation."""
        self.progress_bar.stop()
        self.progress_label.config(text="✅ Installation completed successfully!")
        
        # Re-check dependencies
        self.missing_dependencies = []
        self.check_dependencies()
        
        messagebox.showinfo(
            "Installation Complete",
            "Dependencies installed successfully!\n\n"
            "The application will now restart to use the new dependencies."
        )
        
        self.setup_window.destroy()
        
        # Restart the application
        self._restart_application()
    
    def _installation_failed(self, error_msg):
        """Handle installation failure."""
        self.progress_bar.stop()
        self.progress_label.config(text="❌ Installation failed")
        
        messagebox.showerror(
            "Installation Failed",
            f"Dependency installation failed.\n\n"
            f"Error: {error_msg}\n\n"
            f"You can try installing manually using:\n"
            f"install_requirements.bat --full"
        )
        
        self.setup_window.destroy()
    
    def _restart_application(self):
        """Restart the application."""
        if self.parent_app:
            self.parent_app.root.quit()
        
        # Restart Python script
        python = sys.executable
        os.execl(python, python, *sys.argv)
    
    def get_cpu_fallback_message(self):
        """Get message about CPU fallback mode."""
        if not self.has_gpu_support:
            return ("ℹ️ Running in CPU mode. For GPU acceleration, install CUDA 12.x and run:\n"
                   "install_requirements.bat --full")
        return None


def check_and_handle_dependencies(parent_app=None):
    """
    Main entry point for dependency checking.
    Returns True if app can continue, False if it should exit.
    """
    manager = DependencyManager(parent_app)
    
    # Check current state
    has_core, has_gpu, missing_heavy = manager.check_dependencies()
    
    # If core dependencies are missing, must show setup
    if not has_core or missing_heavy:
        print("🔧 First-run setup required")
        return manager.show_first_run_setup()
    
    # Show GPU fallback message if needed
    if not has_gpu and parent_app:
        fallback_msg = manager.get_cpu_fallback_message()
        if fallback_msg:
            print(fallback_msg)
    
    return True