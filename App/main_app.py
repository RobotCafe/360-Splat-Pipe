# main_app.py

import tkinter as tk
from tkinter import messagebox
from extraction_frame_manager import setup_extraction_frame_system
import sv_ttk

# --- Main Application Entry Point ---

def main():
    """
    Initializes and runs the 360° SplatPipe application.
    """
    # === NEW: First-run dependency management for packaged app ===
    print("🚀 Starting 360° SplatPipe...")
    
    # Create a temporary root for dependency checking
    temp_root = tk.Tk()
    temp_root.withdraw()  # Hide during dependency check
    
    try:
        from dependency_manager import check_and_handle_dependencies
        
        # Check dependencies and show setup wizard if needed
        can_continue = check_and_handle_dependencies(parent_app=None)
        
        if not can_continue:
            print("❌ Dependency setup cancelled or failed")
            temp_root.destroy()
            return
            
    except Exception as e:
        print(f"⚠️ Dependency check failed: {e}")
        # Fall back to simple py360convert check
        try:
            from py360convert import e2p
        except ImportError:
            messagebox.showerror(
                "Fatal Error: Missing Dependencies",
                "Required dependencies are not installed.\n\n"
                "Please run: install_requirements.bat --core"
            )
            temp_root.destroy()
            return
    
    temp_root.destroy()
    
    # If dependency check passes, import the main GUI class and run the app.
    # We import here to avoid a partial GUI appearing if the check fails.
    from app_gui import PipelineGUI

    root = tk.Tk()
    
    # Apply the Sun Valley theme.
    # The theme can be 'light' or 'dark'.
    # sv_ttk.set_theme("dark")

    # Apply a modern theme before creating the main application window.
    # We try Azure first, then fall back to Sun Valley if Azure is not found.
    try:
        import os
        # Assumes azure files are in the same directory as app_gui.py
        app_dir = os.path.dirname(os.path.abspath(__file__))
        azure_theme_path = os.path.join(app_dir, "azure.tcl")
        
        if os.path.exists(azure_theme_path):
            root.tk.call("source", azure_theme_path)
            root.tk.call("set_theme", "light") # Or "dark"
            print("🎨 Applied Azure TTK theme.")
        else:
            # Fallback to Sun Valley if Azure is not found
            #sv_ttk.set_theme("light") # Or "dark"
            print("🎨 Applied TTK theme as a fallback.")

    except Exception as e:
        print(f"⚠️ Could not apply a modern theme: {e}")
        # If all themes fail, the app will use the default system theme.
    
    app = PipelineGUI(root)

        # === NEW: Setup extraction frame system after app initialization ===
    try:
        from extraction_frame_manager import setup_extraction_frame_system
        app.extraction_manager = setup_extraction_frame_system(
            app, app.state, app.visuals, app.callbacks
        )
        print("🎬 Extraction frame system initialized successfully")
    except Exception as e:
        print(f"❌ Warning: Could not initialize extraction frame system: {e}")
        print("   App will work in legacy mode")

    root.mainloop()

if __name__ == "__main__":
    main()
