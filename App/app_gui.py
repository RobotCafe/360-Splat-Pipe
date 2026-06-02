# app_gui.py

import locale
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
import datetime




# Local imports
import _common_utils
import settings_manager
from app_callbacks import CallbacksManager
from app_help_docs import AppHelpDocs
from app_state import AppState
from app_visuals import VisualsManager
from progress_manager import ProgressManager

# Remove: import io (unused)

def ensure_emoji_support():
    """Ensure proper Unicode support for emojis"""
    try:
        # Try to set UTF-8 encoding if possible
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        
        # Set locale for proper Unicode handling
        try:
            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_ALL, 'C.UTF-8')
            except locale.Error:
                pass  # Use system default
                
    except Exception:
        pass  # Fail silently if not supported

class AccordionFrame(tk.Frame):
    """A collapsible frame widget that can expand/collapse content."""
    
    def __init__(self, parent, title, is_expanded=True, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.is_expanded = is_expanded
        self.title = title
        
        # Header frame with toggle button
        self.header_frame = tk.Frame(self, relief='raised', bd=1)
        self.header_frame.pack(fill='x', pady=(0, 2))
        
        # Toggle button (arrow + title)
        self.toggle_button = tk.Button(
            self.header_frame,
            text=f"{'▼' if self.is_expanded else '▶'} {self.title}",
            anchor='w',
            relief='flat',
            bg='lightgray',
            command=self.toggle
        )
        self.toggle_button.pack(fill='x', padx=2, pady=1)
        
        # Content frame
        self.content_frame = tk.Frame(self)
        if self.is_expanded:
            self.content_frame.pack(fill='both', expand=True, padx=5, pady=2)
    
    def toggle(self):
        """Toggle the expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
        self.toggle_button.config(text=f"{'▼' if self.is_expanded else '▶'} {self.title}")
        
        if self.is_expanded:
            self.content_frame.pack(fill='both', expand=True, padx=5, pady=2)
        else:
            self.content_frame.pack_forget()
    
    def get_content_frame(self):
        """Return the content frame for adding widgets."""
        return self.content_frame

class PipelineGUI:
    """
    The main class for the application's graphical user interface.
    This class is responsible for creating, configuring, and laying out all
    the tkinter widgets. It delegates all logic and event handling to the
    CallbacksManager and VisualsManager.
    """
    def __init__(self, root):
        ensure_emoji_support()
        self.root = root
        self.root.title("360° SplatPipe")
        
        # Load settings (will be used again later)
        self.loaded_settings = settings_manager.load_settings(_common_utils.CONFIG_FILE)
        window_x = self.loaded_settings.get('window_x', 100)
        window_y = self.loaded_settings.get('window_y', 100) 
        window_width = self.loaded_settings.get('window_width', 1520)
        window_height = self.loaded_settings.get('window_height', 1300)
        
        self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")

        # --- Initialize Core Components ---
        self.state = AppState()
        self.visuals = VisualsManager(self, self.state, None)
        self.callbacks = CallbacksManager(self, self.state, self.visuals)
        self.visuals.callbacks = self.callbacks # Complete the circular reference
        self.console_window = ConsoleWindow(self)

        # --- Initialize Console System ---
        self.console_visible = True
        self.console_height = 130  # Default console height
        self.setup_console_capture()

        # --- Constants ---
        self.OVERLAY_COLORS = [
            "red", "orange", "green", "cyan", "blue", "magenta", "purple", "lime",
            "pink", "brown", "teal", "maroon", "navy", "olive", "indigo", "violet"
        ]

        # === ADD THESE CRITICAL INITIALIZATIONS ===
        self._save_timer = None  # For per-video settings saving
        
        # Initialize trace lists BEFORE setup
        self.save_traces = []
        self.estimation_traces = []
        self.visual_update_traces = []


        # --- Setup UI ---
        self.setup_tkinter_variables()
        self.setup_gui()

        # --- Initialize Managers ---
        self.progress_manager = ProgressManager(
            self.progress_bar,
            self.progress_label,
            self.state.progress_queue,
            parent_gui=self
        )

        # -- progress Bars
        self.setup_progress_bar_styles()  # Setup custom styles
        
        # --- Initialize Help Documentation (AFTER GUI is set up) ---
        self.help_docs = AppHelpDocs(self)
        self.help_docs.create_help_menu()  # This creates the menu bar

        # --- Setup Variable Traces
        self._setup_variable_traces()

        # --- Final Initialization Steps ---
        self.visuals._reset_preview_to_initial_state()
        self._update_anchor_view_dropdown()  # Initialize anchor view dropdown based on current yaw_steps
        self.check_queues()
        self.root.protocol("WM_DELETE_WINDOW", self.callbacks.on_closing)

        if _common_utils.GPU_ENABLED and _common_utils.GPU_EXTRACTION_ENABLED:
            self.state.progress_var.set("Ready - ✅ Full GPU acceleration enabled")
        elif _common_utils.GPU_ENABLED:
            self.state.progress_var.set("Ready - ✅ GPU acceleration (Accelerating 360 view extraction)")
        elif _common_utils.GPU_EXTRACTION_ENABLED:
            self.state.progress_var.set("Ready - ✅ Partial GPU acceleration (Accelerating video frame extraction only - Numpy fallback)")
        else:
            self.state.progress_var.set("Ready - ⚠️ CPU-only mode. Install CUDA 12.x for GPU acceleration.")

        # INITIALIZE: Set up initial queue status monitoring
        self.update_queue_status_and_progress_bars()

    def _setup_extraction_frame_system(self):
        """Setup the new extraction frame system after GUI is ready."""
        # Prevent this from ever running twice
        if hasattr(self, 'extraction_manager') and self.extraction_manager is not None:
            print("⚠️ Extraction frame system already initialized. Skipping.")
            return

        try:
            from extraction_frame_manager import setup_extraction_frame_system
            self.extraction_manager = setup_extraction_frame_system(
                self, self.state, self.visuals, self.callbacks
            )
            print("🎬 Extraction frame system ready")
        except Exception as e:
            print(f"❌ Error setting up extraction frame system: {e}")
            import traceback
            traceback.print_exc()

    def setup_tkinter_variables(self):
        """
        Creates and initializes all tkinter control variables, loading
        default values from the settings file.
        """
        loaded_settings = self.loaded_settings

        # Frame & View Extraction
        self.extraction_method_var = tk.StringVar(value=loaded_settings.get('extraction_method', 'interval'))
        self.interval_value_var = tk.DoubleVar(value=loaded_settings.get('interval_value'))
        self.interval_unit_var = tk.StringVar(value=loaded_settings.get('interval_unit'))
        self.frame_count_var = tk.IntVar(value=loaded_settings.get('frame_count', 30))
        self.pitch_angles_str_var = tk.StringVar(value=loaded_settings.get('pitch_angles_str'))
        self.yaw_steps_var = tk.StringVar(value=loaded_settings.get('yaw_steps'))
        self.fov_var = tk.StringVar(value=loaded_settings.get('fov'))
        self.overlay_opacity_var = tk.DoubleVar(value=loaded_settings.get('overlay_opacity', 0.6))
        self.frame_format_var = tk.StringVar(value=loaded_settings.get('frame_format', 'jpg'))

        # Postshot Settings
        self.postshot_profile_var = tk.StringVar(value=loaded_settings.get('postshot_profile'))
        self.postshot_max_size_var = tk.IntVar(value=loaded_settings.get('postshot_max_size'))
        self.postshot_steps_var = tk.IntVar(value=loaded_settings.get('postshot_steps'))
        self.postshot_max_splats_var = tk.IntVar(value=loaded_settings.get('postshot_max_splats'))
        self.postshot_aa_var = tk.BooleanVar(value=loaded_settings.get('postshot_aa'))
        self.postshot_error_var = tk.BooleanVar(value=loaded_settings.get('postshot_error'))
        self.postshot_context_var = tk.BooleanVar(value=loaded_settings.get('postshot_context'))
        self.postshot_export_ply_var = tk.BooleanVar(value=loaded_settings.get('postshot_export_ply'))
        self.postshot_alpha_mask_var = tk.BooleanVar(value=loaded_settings.get('postshot_alpha_mask'))
        self.postshot_sky_model_var = tk.BooleanVar(value=loaded_settings.get('postshot_sky_model'))

        # Brush Settings
        self.brush_total_steps_var = tk.IntVar(value=loaded_settings.get('brush_total_steps'))
        self.brush_max_splats_var = tk.IntVar(value=loaded_settings.get('brush_max_splats'))
        self.brush_max_resolution_var = tk.IntVar(value=loaded_settings.get('brush_max_resolution'))
        self.brush_seed_var = tk.IntVar(value=loaded_settings.get('brush_seed'))
        self.brush_rerun_var = tk.BooleanVar(value=loaded_settings.get('brush_rerun'))
        self.brush_viewer_var = tk.BooleanVar(value=loaded_settings.get('brush_viewer'))
        
        # Training selection
        self.run_postshot_var = tk.BooleanVar(value=loaded_settings.get('run_postshot', True))
        self.run_brush_var = tk.BooleanVar(value=loaded_settings.get('run_brush', False))
        self.run_vggt_var = tk.BooleanVar(value=loaded_settings.get('run_vggt', False))
        
        # VGGT filter controls (from gradio demo)
        self.vggt_conf_threshold_var = tk.DoubleVar(value=loaded_settings.get('vggt_conf_threshold', 50.0))
        self.vggt_mask_sky_var = tk.BooleanVar(value=loaded_settings.get('vggt_mask_sky', True))
        self.vggt_sky_sensitivity_threshold_var = tk.IntVar(value=loaded_settings.get('vggt_sky_sensitivity_threshold', 32))
        self.vggt_mask_black_bg_var = tk.BooleanVar(value=loaded_settings.get('vggt_mask_black_bg', False))
        self.vggt_mask_white_bg_var = tk.BooleanVar(value=loaded_settings.get('vggt_mask_white_bg', False))
        self.vggt_prediction_mode_var = tk.StringVar(value=loaded_settings.get('vggt_prediction_mode', 'Depthmap and Camera Branch'))
        self.vggt_temporal_sequencing_var = tk.BooleanVar(value=loaded_settings.get('vggt_temporal_sequencing', True))
        # self.vggt_estimated_points_var = tk.StringVar(value="Points: Unknown")
        
        # Sparse point cloud filter controls
        self.vggt_enable_sparse_var = tk.BooleanVar(value=loaded_settings.get('vggt_enable_sparse', False))
        self.vggt_sparse_target_var = tk.IntVar(value=loaded_settings.get('vggt_sparse_target', 150000))
        
        # Anchor+Rig mode controls (experimental)
        self.vggt_use_anchor_rig_var = tk.BooleanVar(value=loaded_settings.get('vggt_use_anchor_rig', False))
        self.vggt_anchor_view_var = tk.StringVar(value=loaded_settings.get('vggt_anchor_view', 'y00'))
        self.vggt_rig_optimization_min_points_var = tk.IntVar(value=loaded_settings.get('vggt_rig_optimization_min_points', 500000))
        
        # GLB visualization controls
        self.vggt_show_camera_var = tk.BooleanVar(value=loaded_settings.get('vggt_show_camera', True))
        
        self.export_xmp_var = tk.BooleanVar(value=loaded_settings.get('export_xmp', True))
        self.skip_realityscan_var = tk.BooleanVar(value=loaded_settings.get('skip_realityscan', False))
        self.alignment_export_info_var = tk.StringVar()

        # Configuration Paths
        self.ffmpeg_path_var = tk.StringVar(value=loaded_settings.get('ffmpeg_path'))
        self.rs_path_var = tk.StringVar(value=loaded_settings.get('rs_path'))
        self.postshot_path_var = tk.StringVar(value=loaded_settings.get('postshot_path'))
        self.brush_path_var = tk.StringVar(value=loaded_settings.get('brush_path'))
        self.rs_settings_path_var = tk.StringVar(value=loaded_settings.get('rs_settings_path'))
        self.vggt_path_var = tk.StringVar(value=loaded_settings.get('vggt_path'))
        self.vggt_model_path_var = tk.StringVar(value=loaded_settings.get('vggt_model_path', ''))

    def _setup_variable_traces(self):
        """FIXED: Trace setup with proper separation of concerns."""
        # Clear existing traces
        if hasattr(self, 'save_traces'):
            for var, trace_id in self.save_traces:
                try:
                    var.trace_remove('write', trace_id)
                except tk.TclError:
                    pass
        
        if hasattr(self, 'estimation_traces'):
            for var, trace_id in self.estimation_traces:
                try:
                    var.trace_remove('write', trace_id)
                except tk.TclError:
                    pass
        
        if hasattr(self, 'visual_update_traces'):
            for var, trace_id in self.visual_update_traces:
                try:
                    var.trace_remove('write', trace_id)
                except tk.TclError:
                    pass

        # === SAVE TRACES (per-video settings) ===
        self.save_traces = []
        settings_vars = [
            self.extraction_method_var, self.interval_value_var, self.interval_unit_var,
            self.frame_count_var, self.pitch_angles_str_var, self.yaw_steps_var,
            self.fov_var, self.overlay_opacity_var, self.frame_format_var
        ]
        for var in settings_vars:
            trace_id = var.trace_add("write", self._on_settings_change_for_save)
            self.save_traces.append((var, trace_id))

        # === ESTIMATION TRACES (frame count updates) ===
        self.estimation_traces = []
        estimation_vars = [
            self.extraction_method_var, self.interval_value_var, 
            self.interval_unit_var, self.frame_count_var
        ]
        for var in estimation_vars:
            trace_id = var.trace_add("write", self.callbacks.on_extraction_settings_change)
            self.estimation_traces.append((var, trace_id))
        
        # === VISUAL UPDATE TRACES (overlay updates) ===
        self.visual_update_traces = []
        visual_vars = [self.pitch_angles_str_var, self.yaw_steps_var, self.fov_var]
        for var in visual_vars:
            trace_id = var.trace_add("write", self.callbacks._debounced_visual_update)
            self.visual_update_traces.append((var, trace_id))
        
        op_id = self.overlay_opacity_var.trace_add("write", self.visuals._update_overlay_appearance)
        self.visual_update_traces.append((self.overlay_opacity_var, op_id))
        
        # === ANCHOR VIEW DROPDOWN UPDATE TRACE ===
        self.yaw_steps_var.trace_add("write", self._update_anchor_view_dropdown)
        
        # === ALIGNMENT TRACES ===
        alignment_vars = [
            self.run_postshot_var, self.run_brush_var, self.run_vggt_var, self.export_xmp_var, self.skip_realityscan_var
        ]
        for var in alignment_vars:
            var.trace_add("write", self.callbacks._update_alignment_tab_feedback)
            
        # VGGT filter control traces
        vggt_filter_vars = [
            self.vggt_conf_threshold_var, self.vggt_mask_sky_var, self.vggt_mask_black_bg_var, 
            self.vggt_mask_white_bg_var, self.vggt_prediction_mode_var, self.vggt_temporal_sequencing_var,
            self.vggt_enable_sparse_var, self.vggt_sparse_target_var,
            self.vggt_use_anchor_rig_var, self.vggt_anchor_view_var, self.vggt_rig_optimization_min_points_var,
            self.vggt_show_camera_var
        ]
        for var in vggt_filter_vars:
            var.trace_add("write", self._on_settings_change_for_save)
            # var.trace_add("write", self._update_vggt_point_estimation)
            
        # Special trace for VGGT to update Brush state
        self.run_vggt_var.trace_add("write", self._on_vggt_toggle)

    def _on_settings_change_for_save(self, *args):
        """FIXED: Separate trace for per-video settings saving with safe timer handling."""
        if hasattr(self.callbacks, '_settings_loading_in_progress') and \
           self.callbacks._settings_loading_in_progress:
            return
            
        # === CRITICAL FIX: Safe timer cancellation ===
        if hasattr(self, '_save_timer') and self._save_timer is not None:
            try:
                self.root.after_cancel(self._save_timer)
            except (ValueError, tk.TclError):
                # Timer was already cancelled or invalid - ignore
                pass
            finally:
                self._save_timer = None
        
        # Use longer delay for saving to reduce frequency
        self._save_timer = self.root.after(1000, self._save_current_video_settings)
    
    def _save_current_video_settings(self):
        """FIXED: Save current settings for active video with safe timer cleanup."""
        try:
            active_path = self.callbacks._get_active_content_path()
            if active_path:
                self.callbacks._save_settings_for_content(active_path)
        finally:
            # Always clear the timer reference
            self._save_timer = None

    def _disable_all_visual_traces(self):
        """ENHANCED: More robust trace disabling."""
        all_traces = []
        
        if hasattr(self, 'save_traces'):
            all_traces.extend(self.save_traces)
        if hasattr(self, 'estimation_traces'):
            all_traces.extend(self.estimation_traces)
        if hasattr(self, 'visual_update_traces'):
            all_traces.extend(self.visual_update_traces)
        
        for var, trace_id in all_traces:
            try:
                var.trace_remove('write', trace_id)
            except (tk.TclError, ValueError):
                pass  # Trace already removed or invalid

    def _enable_all_visual_traces(self):
        """ENHANCED: More robust trace re-enabling."""
        try:
            self._setup_variable_traces()
        except Exception as e:
            print(f"❌ Error re-enabling traces: {e}")

    def _debounced_parameter_update_with_video(self, *args):
        """Enhanced parameter update that notifies video manager."""
        # Always call existing parameter update regardless of video manager state
        self.callbacks._debounced_parameter_update(*args)

    def setup_gui(self):
        """Creates the main two-column layout and populates all tabs."""
        # Project directory selection
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill='x', side='top')
        ttk.Label(top_frame, text="Output Project Directory:", font=('Arial', 10, 'bold')).pack(side='left')
        ttk.Entry(top_frame, textvariable=self.state.project_dir, state='readonly', width=100).pack(side='left', fill='x', expand=True, padx=5)
        ttk.Button(top_frame, text="Select...", command=self.callbacks.select_project_dir).pack(side='left')

        # Pipeline control buttons
        self.run_pipeline_button = ttk.Button(top_frame, text="Run Full Pipeline", command=self.callbacks.run_full_pipeline, state='disabled')
        self.run_pipeline_button.pack(side='left', padx=2)
        
        self.cancel_pipeline_button = ttk.Button(top_frame, text="Cancel Pipeline", command=self.callbacks.cancel_pipeline, state='disabled')
        self.cancel_pipeline_button.pack(side='left', padx=2)

        # Console toggle in menu or toolbar
        ttk.Button(top_frame, text="Toggle Console", command=self.console_window.toggle_console).pack(side='right', padx=2)

        # MAIN CONTENT AREA (will resize when console is shown/hidden)
        main_content_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        main_content_frame.pack(fill='both', expand=True)
        main_content_frame.grid_columnconfigure(1, weight=1)
        main_content_frame.grid_rowconfigure(0, weight=1)

        self._create_input_queue_panel(main_content_frame)

        self.notebook = ttk.Notebook(main_content_frame)
        self.notebook.grid(row=0, column=1, sticky='nsew', padx=(10, 0))

        # Create tabs
        tab_names = ['1. Frame & View Extraction', '2. Alignment', '3. Postshot Training', '4. Brush Training', '5. Configuration']
        self.tabs = {name: ttk.Frame(self.notebook) for name in tab_names}
        for name, frame in self.tabs.items():
            self.notebook.add(frame, text=name)

        self._create_extraction_tab(self.tabs['1. Frame & View Extraction'])
        self._create_rs_alignment_tab_content(self.tabs['2. Alignment'])
        self._create_postshot_tab_content(self.tabs['3. Postshot Training'])
        self._create_brush_tab_content(self.tabs['4. Brush Training'])
        self._create_config_tab_content(self.tabs['5. Configuration'])

        # Status frame - Enhanced for dual progress support
        self.status_frame = ttk.Frame(self.root, padding=5)
        self.status_frame.pack(fill='x', side='bottom', before=main_content_frame)
        self.status_frame.pack_propagate(False)
        self.status_frame.configure(height=40)  # Increased height for dual progress bars
        
        # Left side: Main status
        self.progress_label = tk.Label(
            self.status_frame, 
            textvariable=self.state.progress_var, 
            anchor='w',
            font=('Arial', 9)  # Slightly smaller font for better space utilization
        )
        self.progress_label.pack(side='left', fill='x', expand=True)
        
        # Right side: Progress bar (will be replaced by dual bars when needed)
        self.progress_bar = ttk.Progressbar(
            self.status_frame, 
            mode='determinate', 
            length=200
        )
        self.progress_bar.pack(side='right')

        # CONSOLE FRAME
        self.console_frame = ttk.Frame(self.root)
        self.setup_console_widgets()
        self.show_console()  # Show console immediately on startup

    def add_extraction_button(self):
        """Adds the 'Extract Frames' button to the top button row."""
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Frame):
                if hasattr(self, 'run_pipeline_button') and self.run_pipeline_button in child.winfo_children():
                    top_frame = child
                    
                    self.extraction_button = ttk.Button(
                        top_frame, 
                        text="Extract Frames", 
                        command=self.callbacks.handle_extraction_button_click,
                        state='disabled'
                    )
                    self.extraction_button.pack(side='left', padx=2, before=self.run_pipeline_button)
                    print("🎬 Stateful Extraction button added to UI")
                    return
                
    # -- Dual progress bars and monitor queue changes
    def update_queue_status_and_progress_bars(self):
        """
        Update status bar and progress bar configuration based on current queue state.
        Called whenever queue contents change.
        """
        video_count = len(self.state.video_queue)
        folder_count = len(self.state.image_folder_queue)
        total_items = video_count + folder_count
        
        print(f"🔄 Queue updated: {video_count} videos + {folder_count} folders = {total_items} total")
        
        # Update progress bar configuration
        self.check_and_enable_dual_progress(total_items)
        
        # Update status message based on queue state
        if total_items == 0:
            # Empty queues - reset to ready state
            current_status = self.state.progress_var.get()
            if "Ready -" in current_status and ("GPU" in current_status or "CPU-only" in current_status):
                pass
            else:
                self.state.progress_var.set("Ready - Add videos or image folders to begin processing")
            # Reset progress bars to 0
            if hasattr(self, 'current_pipe_progress'):
                self.current_pipe_progress['value'] = 0
                self.batch_pipes_progress['value'] = 0
            else:
                self.progress_bar['value'] = 0
                
        elif total_items == 1:
            # Single item - show ready for single processing
            if video_count == 1:
                video_name = os.path.basename(self.state.video_queue[0])
                self.state.progress_var.set(f"Ready - 1 video queued: {video_name}")
            else:
                folder_name = os.path.basename(self.state.image_folder_queue[0])
                self.state.progress_var.set(f"Ready - 1 folder queued: {folder_name}")
            
            # Reset progress bars
            self.progress_bar['value'] = 0
                
        else:
            # Multiple items - show batch processing ready
            self.state.progress_var.set(f"Ready - Batch processing: {video_count} videos, {folder_count} folders ({total_items} total)")
            
            # Reset dual progress bars
            if hasattr(self, 'current_pipe_progress'):
                self.current_pipe_progress['value'] = 0
                self.batch_pipes_progress['value'] = 0
        
        # Update button state
        self.callbacks.check_if_ready()

    def check_and_enable_dual_progress(self, total_items):
        """
        Check if dual progress bars should be enabled based on TOTAL queue size.
        Works correctly with the enhanced revert method above.
        
        Args:
            total_items: Total number of items to be processed (videos + folders)
        """
        # Get current queue breakdown for better logging
        video_count = len(self.state.video_queue)
        folder_count = len(self.state.image_folder_queue)
        
        # Simple existence check (now works correctly due to proper cleanup)
        dual_bars_exist = hasattr(self, 'current_pipe_progress')
        
        if total_items > 1 and not dual_bars_exist:
            # Multiple items total - enable dual progress bars
            print(f"🔄 Enabling dual progress bars for batch processing ({total_items} total items)")
            print(f"   Queue breakdown: {video_count} videos + {folder_count} folders = {total_items} total")
            self.setup_dual_progress_bars()
            
        elif total_items <= 1 and dual_bars_exist:
            # Single item or empty - revert to single progress bar
            print(f"🔄 Reverting to single progress bar ({total_items} item(s))")
            self.revert_to_single_progress_bar()
        
        elif total_items > 1 and dual_bars_exist:
            # Already have dual progress bars enabled for multiple items
            print(f"✅ Dual progress bars already enabled for {total_items} items")
        
        else:
            # Single item or empty, single progress bar already - no change needed
            if total_items == 0:
                print(f"✅ Single progress bar appropriate (empty queues)")
            else:
                print(f"✅ Single progress bar appropriate for {total_items} item")

    def setup_dual_progress_bars(self):
        """
        Set up dual progress bars:
        - Left: Status text (existing)
        - Middle: Current Pipe progress bar
        - Right: Batch Pipes progress bar
        """
        # Store reference to original single progress bar
        self.original_progress_bar = self.progress_bar
        
        # Hide existing progress bar
        self.progress_bar.pack_forget()
        
        # Left: Status (keep existing progress_label as is)
        # No changes needed for self.progress_label
        
        # Middle: Current Pipe progress
        self.middle_frame = ttk.Frame(self.status_frame)
        self.middle_frame.pack(side='right', padx=(10, 5))
        
        ttk.Label(self.middle_frame, text="Current Pipe:", font=('Arial', 8)).pack(side='top')
        self.current_pipe_progress = ttk.Progressbar(
            self.middle_frame, 
            mode='determinate', 
            length=150,
            style='Current.Horizontal.TProgressbar'
        )
        self.current_pipe_progress.pack(side='bottom')
        
        # Right: Batch Pipes progress  
        self.right_frame = ttk.Frame(self.status_frame)
        self.right_frame.pack(side='right', padx=(5, 0))
        
        ttk.Label(self.right_frame, text="Batch Progress:", font=('Arial', 8)).pack(side='top')
        self.batch_pipes_progress = ttk.Progressbar(
            self.right_frame, 
            mode='determinate', 
            length=150,
            style='Batch.Horizontal.TProgressbar'
        )
        self.batch_pipes_progress.pack(side='bottom')
        
        # Initialize progress bars
        self.current_pipe_progress['value'] = 0
        self.batch_pipes_progress['value'] = 0
        
        # Update progress manager to use current pipe progress bar
        self.progress_manager.progress_bar = self.current_pipe_progress
        
        # Add batch progress tracking
        self.batch_current_item = 0
        self.batch_total_items = 0
        
        print("✅ Dual progress bars enabled - Current Pipe + Batch Progress")

    def revert_to_single_progress_bar(self):
        """
        ENHANCED: Revert back to single progress bar with proper state cleanup.
        This ensures that the dual progress detection logic works correctly on subsequent calls.
        """
        try:
            # Hide dual progress frames
            if hasattr(self, 'middle_frame'):
                self.middle_frame.pack_forget()
            if hasattr(self, 'right_frame'):
                self.right_frame.pack_forget()
            
            # Restore original progress bar
            if hasattr(self, 'original_progress_bar'):
                self.original_progress_bar.pack(side='right')
                # Restore progress manager reference
                self.progress_manager.progress_bar = self.original_progress_bar
            
            # ✅ ENHANCED: Properly destroy dual progress widgets to clean up state
            if hasattr(self, 'current_pipe_progress'):
                self.current_pipe_progress.destroy()
                delattr(self, 'current_pipe_progress')
            
            if hasattr(self, 'batch_pipes_progress'):
                self.batch_pipes_progress.destroy()
                delattr(self, 'batch_pipes_progress')
            
            if hasattr(self, 'middle_frame'):
                self.middle_frame.destroy()
                delattr(self, 'middle_frame')
            
            if hasattr(self, 'right_frame'):
                self.right_frame.destroy()
                delattr(self, 'right_frame')
            
            # Clean up batch tracking
            self.batch_current_item = 0
            self.batch_total_items = 0
            
            print("✅ Reverted to single progress bar and cleaned up dual progress state")
            
        except Exception as e:
            print(f"⚠️ Error reverting progress bars: {e}")

    def update_batch_progress(self, current_item, total_items, item_name=""):
        """
        Update the batch progress bar.
        
        Args:
            current_item: Current item being processed (0-based)
            total_items: Total number of items in batch
            item_name: Optional name of current item
        """
        if not hasattr(self, 'batch_pipes_progress'):
            return
            
        self.batch_current_item = current_item
        self.batch_total_items = total_items
        
        if total_items > 0:
            # Calculate percentage (current_item is 0-based, so add 1 for display)
            percentage = ((current_item + 1) / total_items) * 100
            self.batch_pipes_progress['value'] = min(100, max(0, percentage))
            
            # Update status label to show batch info
            if item_name:
                batch_info = f"[{current_item + 1}/{total_items}] {item_name}"
            else:
                batch_info = f"Item {current_item + 1}/{total_items}"
                
            # Update the main status to include batch context
            current_status = self.state.progress_var.get()
            if not current_status.startswith("["):
                self.state.progress_var.set(f"[{current_item + 1}/{total_items}] {current_status}")

    def reset_batch_progress(self):
        """Reset batch progress bar to 0"""
        if hasattr(self, 'batch_pipes_progress'):
            self.batch_pipes_progress['value'] = 0
        self.batch_current_item = 0
        self.batch_total_items = 0

    def complete_batch_progress(self):
        """Mark batch progress as complete"""
        if hasattr(self, 'batch_pipes_progress'):
            self.batch_pipes_progress['value'] = 100
            self.state.progress_var.set(f"✅ Batch completed! Processed {self.batch_total_items} items successfully.")

    # customize progress bar styles
    def setup_progress_bar_styles(self):
        """Setup custom styles for different progress bars"""
        try:
            style = ttk.Style()
            
            # Current pipe progress bar - blue theme
            style.configure(
                'Current.Horizontal.TProgressbar',
                background='#2196F3',  # Blue
                troughcolor='#E3F2FD',  # Light blue background
                borderwidth=1,
                relief='flat'
            )
            
            # Batch progress bar - green theme  
            style.configure(
                'Batch.Horizontal.TProgressbar',
                background='#4CAF50',  # Green
                troughcolor='#E8F5E8',  # Light green background
                borderwidth=1,
                relief='flat'
            )
            
        except Exception as e:
            print(f"⚠️ Could not setup progress bar styles: {e}")

    # -- Console setup and window write and emoji colour additions
    def setup_console_capture(self):
        """Setup console output capture"""
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.console_line_buffer = ""  # Buffer incomplete lines

        # === NEW: Setup file logging ===
        self.setup_file_logging()
        
        # Redirect stdout/stderr to capture prints
        sys.stdout = self
        sys.stderr = self

    def write(self, text):
        """ENHANCED: Write method with file logging and emoji preservation."""
        # Write to original console
        self.original_stdout.write(text)
        
        # === NEW: Write to log file ===
        self.write_to_log_file(text)
        
        # Add to console widget if it exists and is visible
        if hasattr(self, 'console_text') and self.console_visible:
            try:
                # Buffer the text until we have complete lines
                self.console_line_buffer += text
                
                # Process complete lines
                while '\n' in self.console_line_buffer:
                    line, self.console_line_buffer = self.console_line_buffer.split('\n', 1)
                    
                    # Only add non-empty lines (skip pure whitespace)
                    if line.strip():
                        self._add_colored_line(line.strip())
                        self.console_text.see(tk.END)
                        
                        # Limit console to last 1000 lines to prevent memory issues
                        line_count = int(self.console_text.index('end-1c').split('.')[0])
                        if line_count > 1000:
                            self.console_text.delete('1.0', '100.0')
                            
            except tk.TclError:
                pass  # Widget might be destroyed

    def flush(self):
        """ENHANCED: Flush method with log file flushing."""
        self.original_stdout.flush()
        
        # Flush any remaining buffer content
        if hasattr(self, 'console_line_buffer') and self.console_line_buffer.strip():
            if hasattr(self, 'console_text') and self.console_visible:
                try:
                    self._add_colored_line(self.console_line_buffer.strip())
                    self.console_text.see(tk.END)
                    self.console_line_buffer = ""
                except tk.TclError:
                    pass

    def setup_console_widgets(self):
        """Create console widgets with proper emoji support"""
        # Console header
        console_header = ttk.Frame(self.console_frame)
        console_header.pack(fill='x', padx=5, pady=(5,0))
        
        ttk.Label(console_header, text="Console Output", font=('Arial', 10, 'bold')).pack(side='left')
        ttk.Button(console_header, text="Clear", command=self.clear_console).pack(side='right', padx=2)
        ttk.Button(console_header, text="Hide", command=self.hide_console).pack(side='right', padx=2)
        
        # Console text with emoji-compatible font
        # Try different fonts that support emojis well
        emoji_fonts = [
            ("Segoe UI Emoji", 9),     # Windows emoji font
            ("Apple Color Emoji", 9),  # macOS emoji font  
            ("Noto Color Emoji", 9),   # Linux emoji font
            ("Consolas", 9),           # Fallback monospace
            ("Courier New", 9)         # Final fallback
        ]
        
        # Find the first available emoji font
        selected_font = ("Consolas", 9)  # Default fallback
        for font_name, size in emoji_fonts:
            try:
                import tkinter.font as tkFont
                test_font = tkFont.Font(family=font_name, size=size)
                # If we can create the font, use it
                selected_font = (font_name, size)
                break
            except:
                continue
        
        self.console_text = scrolledtext.ScrolledText(
            self.console_frame,
            wrap=tk.WORD,
            font=selected_font,
            bg="#1e1e1e",              # Dark background
            fg="#d4d4d4",              # Light gray default text
            height=10,
            insertbackground="#d4d4d4"  # Cursor color
        )
        self.console_text.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Setup color tags
        self.setup_console_colors()

    def setup_console_colors(self):
        """Setup color tags with emoji-friendly styling"""
        # Configure text tags for different colors
        self.console_text.tag_config("timestamp", foreground="#608b4e", font=("Consolas", 8))
        self.console_text.tag_config("success", foreground="#4fc3f7")      # Light blue
        self.console_text.tag_config("error", foreground="#f44336")        # Red
        self.console_text.tag_config("warning", foreground="#ff9800")      # Orange  
        self.console_text.tag_config("info", foreground="#2196f3")         # Blue
        self.console_text.tag_config("debug", foreground="#9c27b0")        # Purple
        self.console_text.tag_config("progress", foreground="#ffeb3b")     # Yellow
        self.console_text.tag_config("path", foreground="#81c784")         # Light green
        self.console_text.tag_config("default", foreground="#d4d4d4")      # Light gray
        
        # Special tag for emojis to ensure they render properly
        self.console_text.tag_config("emoji", font=("Segoe UI Emoji", 10))

    def _add_colored_line(self, line):
        """Add a line with proper emoji and color handling"""
        import time
        timestamp = time.strftime("%H:%M:%S")
        
        # Insert timestamp
        self.console_text.insert(tk.END, f"[{timestamp}] ", "timestamp")
        
        # Parse the line for emojis and text
        self._insert_line_with_emojis(line)
        self.console_text.insert(tk.END, "\n")
        self.console_text.see(tk.END)

    def _insert_line_with_emojis(self, line):
        """Insert line with proper emoji rendering and colors"""
        # Define emoji patterns and their corresponding colors
        emoji_patterns = {
            "✅": "success",      # Green checkmark
            "❌": "error",        # Red X  
            "⚠️": "warning",      # Warning sign
            "🔄": "progress",     # Blue refresh/loading
            "🔍": "debug",        # Magnifying glass
            "ℹ️": "info",         # Info
            "📹": "info",         # Video camera
            "🎬": "progress",     # Movie clapper
            "⚙️": "warning",      # Gear/settings
            "📊": "debug",        # Bar chart
            "🚀": "success",      # Rocket
            "🎯": "info",         # Target
            "🧪": "debug",        # Test tube
            "🛑": "error",        # Stop sign
            "⏰": "warning",      # Clock
            "💾": "info",         # Floppy disk
            "🗑️": "warning",      # Trash
            "🧹": "info",         # Broom
            "📦": "info",         # Package
            "🔧": "warning",      # Wrench
            "⏱️": "debug",        # Stopwatch
            "📄": "info",         # Document
            "🎨": "success"       # Artist palette
        }
        
        i = 0
        while i < len(line):
            # Check for emoji at current position
            emoji_found = None
            emoji_color = "default"
            
            # Check for multi-character emojis first (like ⚠️)
            for emoji, color in emoji_patterns.items():
                if line[i:].startswith(emoji):
                    emoji_found = emoji
                    emoji_color = color
                    break
            
            if emoji_found:
                # Insert emoji with special formatting
                self.console_text.insert(tk.END, emoji_found, ("emoji", emoji_color))
                i += len(emoji_found)
            else:
                # Find the next emoji or end of string
                next_emoji_pos = len(line)
                next_emoji = None
                
                for emoji in emoji_patterns.keys():
                    pos = line.find(emoji, i)
                    if pos != -1 and pos < next_emoji_pos:
                        next_emoji_pos = pos
                        next_emoji = emoji
                
                # Insert text up to next emoji
                text_segment = line[i:next_emoji_pos]
                if text_segment:
                    # Determine color for text based on content
                    if any(keyword in text_segment.lower() for keyword in ["error", "failed", "exception"]):
                        text_color = "error"
                    elif any(keyword in text_segment.lower() for keyword in ["success", "completed", "ready"]):
                        text_color = "success" 
                    elif any(keyword in text_segment.lower() for keyword in ["warning", "warn"]):
                        text_color = "warning"
                    elif any(keyword in text_segment.lower() for keyword in ["debug", "trace"]):
                        text_color = "debug"
                    elif any(ext in text_segment for ext in [".mp4", ".jpg", ".png", ".ply", ".csv", "/", "\\"]):
                        text_color = "path"
                    else:
                        text_color = "default"
                    
                    self.console_text.insert(tk.END, text_segment, text_color)
                
                i = next_emoji_pos

    def toggle_console(self):
        """Toggle console visibility"""
        if self.console_visible:
            self.hide_console()
        else:
            self.show_console()

    def show_console(self):
        """Show console with emoji welcome message"""
        self.console_frame.pack(fill='x', side='bottom', after=self.status_frame)
        self.console_frame.pack_propagate(False)
        self.console_frame.configure(height=self.console_height)
        self.console_visible = True
        
        # Add welcome message with emojis
        welcome_lines = [
            "🎨 🎨 360° SplatPipe Console - Ready for Processing! 🎨 🎨" 
        ]
        for line in welcome_lines:
            self._add_colored_line(line)
        
        self.console_text.see(tk.END)

    def hide_console(self):
        """Hide the console frame"""
        if self.console_visible:
            self.console_frame.pack_forget()
            self.console_visible = False

    def clear_console(self):
        """Clear console content"""
        if hasattr(self, 'console_text'):
            self.console_text.delete(1.0, tk.END)

    def restore_stdout(self):
        """Restore original stdout/stderr (for cleanup)"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def setup_file_logging(self):
        """Setup comprehensive file logging system."""
        # Create logs directory using proper path for packaged/development mode
        from _common_utils import get_user_logs_directory
        self.logs_dir = get_user_logs_directory()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate timestamped log filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_filename = self.logs_dir / f"splatpipe_session_{timestamp}.log"
        
        # Print log location for user reference
        print(f"📁 Session logs: {self.logs_dir}")
        
        # Initialize log file with session header
        try:
            with open(str(self.log_filename), 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("360° SPLATPIPE SESSION LOG\n")
                f.write("=" * 80 + "\n")
                f.write(f"Session started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Log file: {self.log_filename}\n")
                f.write("=" * 80 + "\n\n")
            
            print(f"📝 Session logging started: {self.log_filename}")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize log file: {e}")
            self.log_filename = None
        
        # Setup log file lock for thread safety
        self.log_lock = threading.Lock()

    def write_to_log_file(self, text):
        """Write text to log file with thread safety and timestamps."""
        if not self.log_filename:
            return
            
        try:
            with self.log_lock:
                with open(str(self.log_filename), 'a', encoding='utf-8') as f:
                    # Add timestamp for each new line
                    if text.endswith('\n') and text.strip():
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        # Write the line with timestamp
                        f.write(f"[{timestamp}] {text}")
                    else:
                        # Continuation of previous line or incomplete
                        f.write(text)
                    f.flush()  # Ensure immediate write
                    
        except Exception as e:
            # Don't let logging errors crash the app
            self.original_stdout.write(f"⚠️ Log write error: {e}\n")

    # -- Frames and Panels and Tabs
    def _create_input_queue_panel(self, parent):
        main_frame = ttk.Labelframe(parent, text="Input Queue", padding=10)
        main_frame.grid(row=0, column=0, sticky='nswe')
        
        # FIXED: Equal weights for both frames
        main_frame.grid_rowconfigure(0, weight=1)  # Video frame gets 50%
        main_frame.grid_rowconfigure(1, weight=1)  # Image frame gets 50%
        main_frame.grid_columnconfigure(0, weight=1)

        # === Video Queue Frame ===
        video_frame = ttk.LabelFrame(main_frame, text="Video Queue", padding=5)
        video_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))  # Small gap between frames
        video_frame.grid_rowconfigure(0, weight=1)
        video_frame.grid_columnconfigure(0, weight=1)
        
        # Video listbox with scrollbars
        video_scroll_frame = ttk.Frame(video_frame)
        video_scroll_frame.grid(row=0, column=0, columnspan=3, sticky='nsew', pady=(0, 5))
        video_scroll_frame.grid_rowconfigure(0, weight=1)
        video_scroll_frame.grid_columnconfigure(0, weight=1)
        
        self.video_listbox = tk.Listbox(video_scroll_frame)  # No fixed height - let it expand
        self.video_listbox.grid(row=0, column=0, sticky='nsew')
        
        # ADDED: Vertical scrollbar for video queue
        video_v_scrollbar = ttk.Scrollbar(video_scroll_frame, orient="vertical", command=self.video_listbox.yview)
        video_v_scrollbar.grid(row=0, column=1, sticky='ns')
        self.video_listbox.configure(yscrollcommand=video_v_scrollbar.set)
        
        self.video_listbox.bind("<<ListboxSelect>>", self.callbacks.on_video_select)
        
        # Video buttons
        ttk.Button(video_frame, text="Add Video(s)...", command=self.callbacks.add_videos).grid(row=1, column=0, sticky='ew')
        ttk.Button(video_frame, text="Remove", command=self.callbacks.remove_selected_video).grid(row=1, column=1, sticky='ew')
        ttk.Button(video_frame, text="Clear", command=self.callbacks.clear_video_queue).grid(row=1, column=2, sticky='ew')

        # === Image Folder Queue Frame ===
        folder_frame = ttk.LabelFrame(main_frame, text="Image Folder Queue", padding=5)
        folder_frame.grid(row=1, column=0, sticky='nsew', pady=(5, 0))  # Small gap between frames
        folder_frame.grid_rowconfigure(0, weight=1)
        folder_frame.grid_columnconfigure(0, weight=1)
        
        # Image folder listbox with scrollbars
        folder_scroll_frame = ttk.Frame(folder_frame)
        folder_scroll_frame.grid(row=0, column=0, columnspan=3, sticky='nsew', pady=(0, 5))
        folder_scroll_frame.grid_rowconfigure(0, weight=1)
        folder_scroll_frame.grid_columnconfigure(0, weight=1)
        
        self.image_folder_listbox = tk.Listbox(folder_scroll_frame)  # No fixed height - let it expand
        self.image_folder_listbox.grid(row=0, column=0, sticky='nsew')
        
        # ADDED: Vertical scrollbar for image folder queue
        folder_v_scrollbar = ttk.Scrollbar(folder_scroll_frame, orient="vertical", command=self.image_folder_listbox.yview)
        folder_v_scrollbar.grid(row=0, column=1, sticky='ns')
        self.image_folder_listbox.configure(yscrollcommand=folder_v_scrollbar.set)
        
        self.image_folder_listbox.bind("<<ListboxSelect>>", self.callbacks.on_image_folder_select)
        
        # Image folder buttons
        ttk.Button(folder_frame, text="Add Folder...", command=self.callbacks.add_image_folder).grid(row=1, column=0, sticky='ew')
        ttk.Button(folder_frame, text="Remove", command=self.callbacks.remove_selected_folder).grid(row=1, column=1, sticky='ew')
        ttk.Button(folder_frame, text="Clear", command=self.callbacks.clear_folder_queue).grid(row=1, column=2, sticky='ew')

    def _create_extraction_tab(self, parent):
        parent.grid_columnconfigure(0, weight=2)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        vis_container = ttk.Frame(parent)
        vis_container.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        vis_container.grid_rowconfigure(1, weight=1)
        vis_container.grid_columnconfigure(0, weight=1)
        
        self.source_canvas = tk.Canvas(vis_container, bg="black")
        self.source_canvas.grid(row=0, column=0, sticky="nw")
        
        gallery_container = ttk.Frame(vis_container)
        gallery_container.grid(row=1, column=0, sticky="nsew", pady=(10,0))
        gallery_container.grid_rowconfigure(0, weight=1)
        gallery_container.grid_columnconfigure(0, weight=1)
        
        self.gallery_canvas = tk.Canvas(gallery_container, bg="#f0f0f0", highlightthickness=0)
        self.gallery_scrollbar = ttk.Scrollbar(gallery_container, orient="vertical", command=self.gallery_canvas.yview)
        self.scrollable_gallery_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_canvas.create_window((0, 0), window=self.scrollable_gallery_frame, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=self.gallery_scrollbar.set)
        
        self.gallery_canvas.grid(row=0, column=0, sticky="nsew")
        self.gallery_scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Bind gallery scroll events
        self.scrollable_gallery_frame.bind("<Configure>", self._update_gallery_scroll_region)
        self.gallery_canvas.bind("<Configure>", self._configure_gallery_canvas_width)
        self.gallery_canvas.bind("<MouseWheel>", self._on_gallery_mousewheel)
        
        self.galleries_frame = self.scrollable_gallery_frame
        # Initialize thumbnail canvases dict
        self.thumbnail_canvases = {}

        settings_container = ttk.Frame(parent)
        settings_container.grid(row=0, column=1, sticky='nsew')
        settings_container.grid_rowconfigure(4, weight=1)  # Updated for 5 rows (4 accordions + live preview)
        settings_container.grid_columnconfigure(0, weight=1)

        # Frame extraction settings accordion
        frame_settings_accordion = AccordionFrame(settings_container, "Frame Extraction Settings", is_expanded=True)
        frame_settings_accordion.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        frame_settings = frame_settings_accordion.get_content_frame()
        frame_settings.grid_columnconfigure(1, weight=1)
        
        ttk.Label(frame_settings, text="Extraction Method:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        extraction_method_frame = ttk.Frame(frame_settings)
        extraction_method_frame.grid(row=0, column=1, columnspan=3, sticky='ew', padx=5, pady=2)
        ttk.Radiobutton(extraction_method_frame, text="Interval", variable=self.extraction_method_var, value="interval", command=self._update_extraction_ui).pack(side='left')
        ttk.Radiobutton(extraction_method_frame, text="Total Count", variable=self.extraction_method_var, value="count", command=self._update_extraction_ui).pack(side='left', padx=(10,0))
        
        # Interval frame
        self.interval_frame = ttk.Frame(frame_settings)
        self.interval_frame.grid(row=1, column=0, columnspan=4, sticky='ew', pady=5)
        self.interval_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(self.interval_frame, text="Interval:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(self.interval_frame, textvariable=self.interval_value_var, width=8).grid(row=0, column=1, padx=(0,5), pady=2, sticky='ew')
        ttk.Radiobutton(self.interval_frame, text="Seconds", variable=self.interval_unit_var, value="seconds").grid(row=0, column=2, padx=5, pady=2)
        ttk.Radiobutton(self.interval_frame, text="Frames", variable=self.interval_unit_var, value="frames").grid(row=0, column=3, padx=5, pady=2)
        
        # Count frame
        self.count_frame = ttk.Frame(frame_settings)
        self.count_frame.grid(row=2, column=0, columnspan=4, sticky='ew', pady=5)
        self.count_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(self.count_frame, text="Total Frames:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(self.count_frame, textvariable=self.frame_count_var, width=8).grid(row=0, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(self.count_frame, text="(evenly spaced)").grid(row=0, column=2, padx=5, pady=2, sticky='w')

        # Content info
        content_info_frame = ttk.Frame(frame_settings)
        content_info_frame.grid(row=3, column=0, columnspan=4, sticky='ew', pady=10)
        content_info_frame.grid_columnconfigure(1, weight=1)

        # Row 0: Selected Content
        ttk.Label(content_info_frame, text="Selected Content:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        ttk.Label(content_info_frame, textvariable=self.state.content_info_var, foreground="blue").grid(row=0, column=1, padx=5, pady=2, sticky='w')

        # Create a new, invisible Frame to hold both "Details:" and its value
        details_container = ttk.Frame(content_info_frame)
        details_container.grid(row=1, column=0, columnspan=2, sticky='w', padx=5, pady=2)

        # Pack the static "Details:" label inside the container
        ttk.Label(details_container, text="Details:").pack(side='left')

        # Pack the dynamic label right next to it, with no extra padding
        ttk.Label(
            details_container,
            textvariable=self.state.content_details_var,
            foreground="red"
        ).pack(side='left', padx=10)

        # Frame format selection
        format_frame = ttk.Frame(frame_settings)
        format_frame.grid(row=4, column=0, columnspan=4, sticky='ew', pady=5)  # Note: adjust row number
        ttk.Label(format_frame, text="Frame Format:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        ttk.Radiobutton(format_frame, text="JPEG (Fast)", variable=self.frame_format_var, value="jpg").grid(row=0, column=1, padx=5, pady=2)
        ttk.Radiobutton(format_frame, text="PNG (High Quality)", variable=self.frame_format_var, value="png").grid(row=0, column=2, padx=5, pady=2)
        
        # Initialize UI state
        self._update_extraction_ui()

        # 360° View settings accordion
        view_settings_accordion = AccordionFrame(settings_container, "360° View Extraction Settings", is_expanded=True)
        view_settings_accordion.grid(row=1, column=0, sticky='ew', pady=(0, 5))
        view_settings = view_settings_accordion.get_content_frame()
        view_settings.grid_columnconfigure(1, weight=1)
        ttk.Label(view_settings, text="Pitch Angles (comma-separated):").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        ttk.Entry(view_settings, textvariable=self.pitch_angles_str_var).grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        ttk.Label(view_settings, text="Yaw Steps (1-100):").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Entry(view_settings, textvariable=self.yaw_steps_var).grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        ttk.Label(view_settings, text="Field of View (30-160):").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        ttk.Entry(view_settings, textvariable=self.fov_var).grid(row=2, column=1, sticky='ew', padx=5, pady=2)

        # Overlay settings accordion
        overlay_settings_accordion = AccordionFrame(settings_container, "Overlay Appearance", is_expanded=False)
        overlay_settings_accordion.grid(row=2, column=0, sticky='ew', pady=(0, 5))
        self.overlay_settings = overlay_settings_accordion.get_content_frame()
        self.overlay_settings.grid_columnconfigure(1, weight=1)
        ttk.Label(self.overlay_settings, text="Opacity:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        ttk.Scale(self.overlay_settings, from_=0.0, to=1.0, variable=self.overlay_opacity_var, orient='horizontal').grid(row=0, column=1, sticky='ew', padx=5, pady=2)

        # Frame Navigator placeholder (will be created by extraction_frame_manager)
        # This ensures proper row spacing for the dynamically created navigator
        
        # Live preview (keep as fixed panel for maximum space)
        self.preview_frame = ttk.Labelframe(settings_container, text="360° Extracted View Preview", padding=10)
        self.preview_frame.grid(row=4, column=0, sticky='nsew', pady=10)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_frame.grid_columnconfigure(0, weight=1)
        
        # FIXED: Only bind to the frame, NOT the label
        self.preview_frame.bind("<Configure>", self.visuals.on_preview_resize)
        
        self.preview_label = ttk.Label(self.preview_frame, anchor="center")
        self.preview_label.pack(fill='both', expand=True)

    def _on_skip_realityscan_toggle(self):
        """Handle Skip RealityScan checkbox toggle and VGGT alignment option."""
        skip_enabled = self.skip_realityscan_var.get()
        
        if skip_enabled:
            # Show VGGT alignment option
            self.vggt_alignment_frame.pack(anchor='w', padx=10, pady=(5, 5))
            
            # Initially show warning (will be updated by feedback system)
            self.skip_warning_label.pack(anchor='w', padx=20, pady=(0, 5))
            
            # Handle Brush training state based on VGGT selection
            if self.run_vggt_var.get():
                # VGGT can output COLMAP, so re-enable Brush
                self.brush_checkbox.config(state='normal')
            else:
                # No alignment, disable Brush
                self.run_brush_var.set(False)
                self.brush_checkbox.config(state='disabled')
            
            # Hide RealityScan export options
            self.export_frame.pack_forget()
                
        else:
            # Hide VGGT alignment option
            self.vggt_alignment_frame.pack_forget()
            self.run_vggt_var.set(False)  # Clear VGGT when going back to RealityScan
            
            # Hide warning
            self.skip_warning_label.pack_forget()
            
            # Re-enable Brush training
            self.brush_checkbox.config(state='normal')
            
            # Show RealityScan export options
            self.export_frame.pack(fill="x", pady=(10, 0), anchor='n', 
                                before=self.export_frame.master.winfo_children()[-1])
        
        # Update feedback
        self.callbacks._update_alignment_tab_feedback()
        
    def _on_vggt_toggle(self, *args):
        """Handle VGGT checkbox toggle - enable/disable Brush training accordingly."""
        if self.skip_realityscan_var.get():  # Only when Skip RealityScan is enabled
            if self.run_vggt_var.get():
                # VGGT selected - enable Brush (VGGT can output COLMAP)
                self.brush_checkbox.config(state='normal')
            else:
                # VGGT deselected - disable Brush (no alignment available)
                self.run_brush_var.set(False)
                self.brush_checkbox.config(state='disabled')
        
        # Update memory warning
        self._update_vggt_memory_warning()
        
        # Update temporal/spatial controls state
        self._update_temporal_spatial_controls()
        
        # No button state management needed - 3D popup is automatic

    def _on_anchor_rig_toggle(self, *args):
        """Handle Anchor+Rig mode toggle - grey out temporal/spatial options when enabled."""
        self._update_temporal_spatial_controls()

    def _update_temporal_spatial_controls(self):
        """Update the state of temporal/spatial sequencing controls based on anchor+rig mode."""
        anchor_rig_enabled = self.vggt_use_anchor_rig_var.get()
        
        if anchor_rig_enabled:
            # Grey out temporal/spatial controls when anchor+rig is enabled
            state = 'disabled'
            label_text = "Image Sequencing (locked to temporal in anchor+rig mode):"
        else:
            # Enable temporal/spatial controls in normal mode
            state = 'normal'
            label_text = "Image Sequencing:"
        
        # Update the controls if they exist
        if hasattr(self, 'vggt_seq_label'):
            self.vggt_seq_label.config(text=label_text)
        if hasattr(self, 'vggt_temporal_radio'):
            self.vggt_temporal_radio.config(state=state)
        if hasattr(self, 'vggt_spatial_radio'):
            self.vggt_spatial_radio.config(state=state)

    def _update_vggt_memory_warning(self):
        """Update VGGT memory usage warning based on system RAM and estimated image count."""
        if not hasattr(self, 'vggt_memory_warning'):
            return  # Widget not created yet
            
        if not self.run_vggt_var.get():
            # VGGT not selected - hide warning
            self.vggt_memory_warning.config(text="")
            return
            
        try:
            import psutil
            
            # Get system memory
            total_memory_gb = psutil.virtual_memory().total / (1024**3)
            available_memory_gb = psutil.virtual_memory().available / (1024**3)
            
            # Estimate image count based on settings
            try:
                pitch_angles = [float(p.strip()) for p in self.pitch_angles_str_var.get().split(',')]
                yaw_steps = int(self.yaw_steps_var.get())
                
                # Get number of frames from queue if available
                num_frames = len(self.state.image_folder_queue) if hasattr(self.state, 'image_folder_queue') else 1
                
                # Estimate total images per frame
                images_per_frame = len(pitch_angles) * yaw_steps
                # Calculate total images across all frames
                total_images = images_per_frame * num_frames
                
                # Memory usage estimation (very rough)
                estimated_memory_gb = total_images * 0.05  # ~50MB per image for processing
                
                # Generate warning message
                warning_text = ""
                
                if available_memory_gb < 8:
                    warning_text = f"⚠️ Low RAM ({available_memory_gb:.1f}GB) - VGGT may be slow"
                elif estimated_memory_gb > available_memory_gb * 0.8:
                    warning_text = f"🚨 High memory usage expected (~{estimated_memory_gb:.1f}GB)"
                elif total_images > 100:
                    warning_text = f"⏳ Large dataset ({total_images} total views) - processing will take time"
                elif available_memory_gb > 16:
                    warning_text = f"✅ Good RAM ({available_memory_gb:.1f}GB) for VGGT processing"
                else:
                    warning_text = f"💾 RAM: {available_memory_gb:.1f}GB - batch processing will be used"
                    
                self.vggt_memory_warning.config(text=warning_text)
                
            except (ValueError, AttributeError):
                # Can't estimate - just show basic memory info
                if available_memory_gb < 8:
                    self.vggt_memory_warning.config(text=f"⚠️ Low RAM ({available_memory_gb:.1f}GB)")
                else:
                    self.vggt_memory_warning.config(text=f"💾 Available RAM: {available_memory_gb:.1f}GB")
                    
        except ImportError:
            # psutil not available
            self.vggt_memory_warning.config(text="💾 Memory info unavailable")
        except Exception:
            # Any other error
            self.vggt_memory_warning.config(text="")

    # def _update_vggt_point_estimation(self, *args):
    #     """Update estimated point count based on VGGT filter settings."""
    #     if not hasattr(self, 'vggt_estimated_points_var'):
    #         return  # Widget not created yet
            
    #     if not self.run_vggt_var.get():
    #         self.vggt_estimated_points_var.set("Points: VGGT disabled")
    #         return
            
    #     try:
    #         # Estimate image count based on settings
    #         pitch_angles = [float(p.strip()) for p in self.pitch_angles_str_var.get().split(',')]
    #         yaw_steps = int(self.yaw_steps_var.get())
    #         num_frames = len(self.state.image_folder_queue) if hasattr(self.state, 'image_folder_queue') else 1
            
    #         total_images = len(pitch_angles) * yaw_steps * num_frames
            
    #         # Rough estimation based on typical VGGT output
    #         # Each image produces ~518x518 points, filtered by confidence and other settings
    #         base_points_per_image = 518 * 518  # ~268k points per image
    #         total_raw_points = total_images * base_points_per_image
            
    #         # Apply filter estimates
    #         conf_threshold = self.vggt_conf_threshold_var.get()
    #         conf_factor = (100 - conf_threshold) / 100  # Higher threshold = fewer points
            
    #         # Sky filtering typically removes 20-40% of points
    #         sky_factor = 0.7 if self.vggt_mask_sky_var.get() else 1.0
            
    #         # Background filtering removes 5-15% typically
    #         bg_factor = 0.9 if (self.vggt_mask_black_bg_var.get() or self.vggt_mask_white_bg_var.get()) else 1.0
            
    #         estimated_points = int(total_raw_points * conf_factor * sky_factor * bg_factor)
            
    #         # Format the number nicely
    #         if estimated_points > 1000000:
    #             points_str = f"{estimated_points/1000000:.1f}M"
    #         elif estimated_points > 1000:
    #             points_str = f"{estimated_points/1000:.0f}K"
    #         else:
    #             points_str = str(estimated_points)
            
    #         self.vggt_estimated_points_var.set(f"Est. Points: ~{points_str}")
            
    #     except (ValueError, AttributeError):
    #         self.vggt_estimated_points_var.set("Points: Unknown")

    def _update_anchor_view_dropdown(self, *args):
        """Update anchor view dropdown values based on current yaw_steps setting."""
        try:
            # Get current yaw_steps value
            yaw_steps_str = self.yaw_steps_var.get().strip()
            if not yaw_steps_str:
                return
                
            yaw_steps = int(yaw_steps_str)
            
            # Generate anchor view options (y00, y01, y02, etc.)
            if yaw_steps <= 0:
                anchor_options = ["y00"]  # Minimum one option
            else:
                anchor_options = [f"y{i:02d}" for i in range(yaw_steps)]
            
            # Get current selection to preserve it if possible
            current_selection = self.vggt_anchor_view_var.get()
            
            # Update combobox values
            self.vggt_anchor_view_combo['values'] = anchor_options
            
            # Preserve current selection if it's still valid, otherwise default to first option
            if current_selection in anchor_options:
                self.vggt_anchor_view_var.set(current_selection)
            else:
                self.vggt_anchor_view_var.set(anchor_options[0])
                
        except (ValueError, AttributeError) as e:
            # On error, ensure at least one option exists
            self.vggt_anchor_view_combo['values'] = ["y00"]
            self.vggt_anchor_view_var.set("y00")

    def _update_extraction_ui(self):
        """ENHANCED: Show/hide extraction method UI with verification."""
        method = self.extraction_method_var.get()
        print(f"🔧 _update_extraction_ui called with method: '{method}'")
        
        if method == "interval":
            print("   📋 Showing interval UI, hiding count UI")
            self.interval_frame.grid()
            self.count_frame.grid_remove()
        elif method == "count":
            print("   📋 Showing count UI, hiding interval UI")
            self.interval_frame.grid_remove()
            self.count_frame.grid()
        else:
            print(f"   ⚠️ Unknown extraction method: '{method}' - defaulting to interval")
            self.extraction_method_var.set("interval")
            self.interval_frame.grid()
            self.count_frame.grid_remove()
        
        # Force UI refresh
        self.root.update_idletasks()

    def _update_gallery_scroll_region(self, event=None):
        """Update the scroll region when gallery content changes."""
        self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all"))
    
    def _configure_gallery_canvas_width(self, event=None):
        """Update the width of the scrollable frame to match the canvas."""
        canvas_width = self.gallery_canvas.winfo_width()
        if self.gallery_canvas.find_all():
            self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=canvas_width)
    
    def _on_gallery_mousewheel(self, event):
        """Handle mouse wheel scrolling in the gallery."""
        self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _create_rs_alignment_tab_content(self, parent):
        # Create vertical scrollable frame similar to postshot tab
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=20)
        
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # NEW: Skip RealityScan option (put this first)
        skip_frame = ttk.Labelframe(frame, text="Alignment Method", padding=10)
        skip_frame.pack(fill="x", anchor='n')

        ttk.Checkbutton(skip_frame, text="Skip RealityScan",
                    variable=self.skip_realityscan_var,
                    command=self._on_skip_realityscan_toggle).pack(anchor='w', padx=5, pady=2)

        ttk.Label(skip_frame, text="Toggle Skip RealityScan to enable alternative alignment methods (VGGT, Pycolmap, AnySplat).",
                    foreground="green").pack(anchor='w', padx=5, pady=(0, 5))
        
        # VGGT alignment option (only shown when Skip RealityScan is enabled)
        self.vggt_alignment_frame = ttk.Frame(skip_frame)
        ttk.Label(self.vggt_alignment_frame, text="Alternative Alignment Method:").pack(anchor='w', padx=20)
        self.vggt_alignment_checkbox = ttk.Checkbutton(self.vggt_alignment_frame, text="Use VGGT for camera pose estimation", 
                                            variable=self.run_vggt_var, command=self._on_vggt_toggle)
        self.vggt_alignment_checkbox.pack(anchor='w', padx=35, pady=2)
        
        
        # VGGT Advanced Filter Controls (from gradio demo)
        self.vggt_advanced_frame = ttk.LabelFrame(self.vggt_alignment_frame, text="Advanced VGGT Options", padding=5)
        self.vggt_advanced_frame.pack(anchor='w', padx=50, pady=(5, 2), fill='x')
        
        # Confidence threshold
        conf_frame = ttk.Frame(self.vggt_advanced_frame)
        conf_frame.pack(anchor='w', fill='x', pady=2)
        ttk.Label(conf_frame, text="Confidence Threshold:").pack(side='left')
        self.vggt_conf_scale = ttk.Scale(conf_frame, from_=0, to=100, orient='horizontal',
                                        variable=self.vggt_conf_threshold_var, length=150)
        self.vggt_conf_scale.pack(side='left', padx=(5, 5))
        self.vggt_conf_label = ttk.Label(conf_frame, text=f"{self.vggt_conf_threshold_var.get():.0f}%")
        self.vggt_conf_label.pack(side='left')
        
        # Update confidence label when scale changes
        def update_conf_label(*args):
            self.vggt_conf_label.config(text=f"{self.vggt_conf_threshold_var.get():.0f}%")
        self.vggt_conf_threshold_var.trace_add('write', update_conf_label)
        
        # Filter checkboxes row 1
        filter_frame1 = ttk.Frame(self.vggt_advanced_frame)
        filter_frame1.pack(anchor='w', fill='x', pady=2)
        ttk.Checkbutton(filter_frame1, text="Show Camera Frustums", variable=self.vggt_show_camera_var).pack(side='left', padx=(0, 10))
        ttk.Checkbutton(filter_frame1, text="Filter Sky", variable=self.vggt_mask_sky_var).pack(side='left', padx=(0, 10))
        ttk.Checkbutton(filter_frame1, text="Filter Black BG", variable=self.vggt_mask_black_bg_var).pack(side='left', padx=(0, 10))
        ttk.Checkbutton(filter_frame1, text="Filter White BG", variable=self.vggt_mask_white_bg_var).pack(side='left')
        
        # Sky sensitivity slider
        sky_sensitivity_frame = ttk.Frame(self.vggt_advanced_frame)
        sky_sensitivity_frame.pack(anchor='w', fill='x', pady=2, padx=20) # Indent it slightly
        ttk.Label(sky_sensitivity_frame, text="Sky Sensitivity:").pack(side='left')
        self.vggt_sky_sensitivity_scale = ttk.Scale(sky_sensitivity_frame, from_=8, to=128, orient='horizontal',
                                        variable=self.vggt_sky_sensitivity_threshold_var, length=120)
        self.vggt_sky_sensitivity_scale.pack(side='left', padx=(5, 5))
        self.vggt_sky_sensitivity_label = ttk.Label(sky_sensitivity_frame, text="32")
        self.vggt_sky_sensitivity_label.pack(side='left')
        
            # Update sensitivity label when scale changes
        def update_sensitivity_label(*args):
            self.vggt_sky_sensitivity_label.config(text=f"{self.vggt_sky_sensitivity_threshold_var.get()}")
        self.vggt_sky_sensitivity_threshold_var.trace('w', update_sensitivity_label)

        # Point Cloud Density Control
        sparse_frame = ttk.LabelFrame(self.vggt_advanced_frame, text="Point Cloud Density Control", padding=5)
        sparse_frame.pack(anchor='w', fill='x', pady=(5, 2))
        
        # Sparse filter checkbox
        ttk.Checkbutton(sparse_frame, text="Enable Sparse Point Cloud Filter", 
                       variable=self.vggt_enable_sparse_var).pack(anchor='w', pady=(0, 2))
        
        # Target points entry with validation
        points_frame = ttk.Frame(sparse_frame)
        points_frame.pack(anchor='w', fill='x', pady=2)
        ttk.Label(points_frame, text="Target Points:").pack(side='left')
        self.vggt_sparse_target_entry = ttk.Entry(points_frame, textvariable=self.vggt_sparse_target_var, width=10)
        self.vggt_sparse_target_entry.pack(side='left', padx=(5, 5))
        ttk.Label(points_frame, text="(10,000 - 6,000,000)").pack(side='left')
        
        # Anchor+Rig mode (experimental)
        rig_frame = ttk.LabelFrame(self.vggt_advanced_frame, text="Camera Rig Mode (Experimental)")
        rig_frame.pack(anchor='w', fill='x', pady=(10, 5))
        
        self.vggt_anchor_rig_checkbox = ttk.Checkbutton(
            rig_frame, 
            text="Enable Anchor+Rig Processing (6x faster, 1 anchor + 5 computed poses)",
            variable=self.vggt_use_anchor_rig_var,
            command=self._on_anchor_rig_toggle
        )
        self.vggt_anchor_rig_checkbox.pack(anchor='w', padx=10, pady=5)
        
        anchor_view_frame = ttk.Frame(rig_frame)
        anchor_view_frame.pack(anchor='w', padx=20, pady=2)
        ttk.Label(anchor_view_frame, text="Anchor View:").pack(side='left')
        self.vggt_anchor_view_combo = ttk.Combobox(
            anchor_view_frame,
            textvariable=self.vggt_anchor_view_var,
            values=["y00"],  # Will be updated dynamically based on yaw_steps
            state="readonly",
            width=8
        )
        self.vggt_anchor_view_combo.pack(side='left', padx=(5, 5))
        ttk.Label(anchor_view_frame, text="(which view to use as reference)").pack(side='left')
        
        # Rig optimization threshold
        rig_opt_frame = ttk.Frame(rig_frame)
        rig_opt_frame.pack(anchor='w', padx=20, pady=2)
        ttk.Label(rig_opt_frame, text="Optimization Threshold:").pack(side='left')
        self.vggt_rig_optimization_entry = ttk.Entry(rig_opt_frame, textvariable=self.vggt_rig_optimization_min_points_var, width=10)
        self.vggt_rig_optimization_entry.pack(side='left', padx=(5, 5))
        ttk.Label(rig_opt_frame, text="points (min points needed to trigger rig optimization)").pack(side='left')
        
        # Prediction mode
        pred_frame = ttk.Frame(self.vggt_advanced_frame)
        pred_frame.pack(anchor='w', fill='x', pady=2)
        ttk.Label(pred_frame, text="Prediction Mode:").pack(side='left')
        ttk.Radiobutton(pred_frame, text="Depthmap", variable=self.vggt_prediction_mode_var, 
                       value="Depthmap and Camera Branch").pack(side='left', padx=(5, 5))
        ttk.Radiobutton(pred_frame, text="Pointmap", variable=self.vggt_prediction_mode_var, 
                       value="Pointmap Branch").pack(side='left')
        
        # Image sequencing mode
        seq_frame = ttk.Frame(self.vggt_advanced_frame)
        seq_frame.pack(anchor='w', fill='x', pady=2)
        self.vggt_seq_label = ttk.Label(seq_frame, text="Image Sequencing:")
        self.vggt_seq_label.pack(side='left')
        
        self.vggt_temporal_radio = ttk.Radiobutton(seq_frame, text="Temporal (by viewpoint - VGGT recommended)", 
                                                  variable=self.vggt_temporal_sequencing_var, value=True)
        self.vggt_temporal_radio.pack(side='left', padx=(5, 5))
        
        self.vggt_spatial_radio = ttk.Radiobutton(seq_frame, text="Spatial (by frame)", 
                                                 variable=self.vggt_temporal_sequencing_var, value=False)
        self.vggt_spatial_radio.pack(side='left')
        
        # # Point estimation display
        # point_est_frame = ttk.Frame(self.vggt_advanced_frame)
        # point_est_frame.pack(anchor='w', fill='x', pady=2)
        # ttk.Label(point_est_frame, textvariable=self.vggt_estimated_points_var, 
        #          foreground="blue", font=('Arial', 8, 'italic')).pack(side='left')
        
        # Auto 3D visualization info
        auto_viz_frame = ttk.Frame(self.vggt_advanced_frame)
        auto_viz_frame.pack(anchor='w', fill='x', pady=2)
        ttk.Label(auto_viz_frame, text="🌐 3D preview will auto-open in browser window when VGGT completes", 
                 font=('Arial', 8), foreground="green").pack(side='left')
        
        # Memory usage warning for VGGT
        self.vggt_memory_warning = ttk.Label(self.vggt_alignment_frame, 
                                          text="", 
                                          foreground="orange", font=('Arial', 8))
        self.vggt_memory_warning.pack(anchor='w', padx=50, pady=2)
        
        # Warning label for Skip RealityScan
        self.skip_warning_label = ttk.Label(skip_frame, 
                                        text="⚠️ Note: Without RealityScan or VGGT alignment, Postshot will perform alignment and training", 
                                        foreground="orange", font=('Arial', 9))
        # Initially hidden - will be shown when skip is checked

        # Training options frame
        training_frame = ttk.Labelframe(frame, text="Training Options", padding=10)
        training_frame.pack(fill="x", pady=(10, 0), anchor='n')
        self.postshot_checkbox = ttk.Checkbutton(training_frame, text="Run Postshot Training", 
                                            variable=self.run_postshot_var)
        self.postshot_checkbox.pack(anchor='w', padx=5, pady=2)
        
        self.brush_checkbox = ttk.Checkbutton(training_frame, text="Run Brush Training", 
                                            variable=self.run_brush_var)
        self.brush_checkbox.pack(anchor='w', padx=5, pady=2)
        
        # Export options frame (only relevant when NOT skipping RealityScan)
        self.export_frame = ttk.Labelframe(frame, text="RealityScan Export Options", padding=10)
        self.export_frame.pack(fill="x", pady=(10, 0), anchor='n')
        ttk.Checkbutton(self.export_frame, text="Export XMP rig files (for RealityScan)", 
                    variable=self.export_xmp_var).pack(anchor='w', padx=5, pady=2)
        # Feedback Frame
        feedback_frame = ttk.Labelframe(frame, text="Alignment and Export Plan", padding=10)
        feedback_frame.pack(fill="x", pady=10, anchor='n')
        ttk.Label(feedback_frame, textvariable=self.alignment_export_info_var, wraplength=400, justify='left').pack(anchor='w')
        # Initialize UI state
        self._on_skip_realityscan_toggle()
        self.callbacks._update_alignment_tab_feedback()

    def _create_postshot_tab_content(self, parent):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=20)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        frame.grid_columnconfigure(1, weight=1)
        def create_entry(row, label, var):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=3, padx=5)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky='ew', pady=3, padx=5)
        ttk.Label(frame, text="Training Profile:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5, padx=5)
        ttk.Combobox(frame, textvariable=self.postshot_profile_var, values=["Splat MCMC", "Splat3", "Splat ADC"]).grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        create_entry(1, "Max Image Size (Default 3840):", self.postshot_max_size_var)
        create_entry(2, "Train Steps Limit (in ksteps - default 30):", self.postshot_steps_var)
        create_entry(3, "Max Splats (kSplats, MCMC only):", self.postshot_max_splats_var)
        toggles_frame = ttk.Labelframe(frame, text="Options", padding=10)
        toggles_frame.grid(row=4, column=0, columnspan=2, sticky='ew', pady=10, padx=5)
        ttk.Checkbutton(toggles_frame, text="Anti-Aliasing", variable=self.postshot_aa_var).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(toggles_frame, text="Show Train Error", variable=self.postshot_error_var).grid(row=0, column=1, sticky='w')
        ttk.Checkbutton(toggles_frame, text="Store Training Context", variable=self.postshot_context_var).grid(row=0, column=2, sticky='w')
        ttk.Checkbutton(toggles_frame, text="Export PLY file", variable=self.postshot_export_ply_var).grid(row=1, column=0, sticky='w')
        ttk.Checkbutton(toggles_frame, text="Treat Zero Alpha as Mask", variable=self.postshot_alpha_mask_var).grid(row=1, column=1, sticky='w')
        ttk.Checkbutton(toggles_frame, text="Create Sky Model", variable=self.postshot_sky_model_var).grid(row=1, column=2, sticky='w')

    def _create_brush_tab_content(self, parent):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=10)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(3, weight=1)
        def create_entry(row, col, label, var):
            ttk.Label(frame, text=label).grid(row=row, column=col, sticky='w', pady=3, padx=5)
            ttk.Entry(frame, textvariable=var, width=15).grid(row=row, column=col+1, sticky='ew', pady=3, padx=5)
        ttk.Label(frame, text="Main Training Options", font=('Arial', 10, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w', pady=10)
        create_entry(1, 0, "Total Steps:", self.brush_total_steps_var)
        create_entry(1, 2, "Max Splats:", self.brush_max_splats_var)
        create_entry(2, 0, "Max Resolution:", self.brush_max_resolution_var)
        create_entry(2, 2, "Seed:", self.brush_seed_var)
        ttk.Label(frame, text="Toggles", font=('Arial', 10, 'bold')).grid(row=5, column=0, columnspan=4, sticky='w', pady=10)
        ttk.Checkbutton(frame, text="Enable Rerun.io Logging", variable=self.brush_rerun_var).grid(row=6, column=0, columnspan=2, sticky='w', padx=5)
        ttk.Checkbutton(frame, text="Spawn Viewer", variable=self.brush_viewer_var).grid(row=6, column=2, columnspan=2, sticky='w', padx=5)

    def _create_config_tab_content(self, parent):
        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(1, weight=1)
        def create_path_entry(row, label_text, var, is_folder=False):
            ttk.Label(frame, text=label_text).grid(row=row, column=0, sticky='w', padx=5, pady=5)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky='ew', padx=5, pady=5)
            command = (lambda v=var: self.callbacks.browse_folder_path(v)) if is_folder else (lambda v=var: self.callbacks.browse_file_path(v))
            ttk.Button(frame, text="...", width=3, command=command).grid(row=row, column=2, sticky='w', padx=5, pady=5)
        
        create_path_entry(0, "FFmpeg Executable:", self.ffmpeg_path_var)
        create_path_entry(1, "RealityScan Executable:", self.rs_path_var)
        create_path_entry(2, "Postshot CLI Executable:", self.postshot_path_var)
        create_path_entry(3, "Brush CLI Executable:", self.brush_path_var)
        create_path_entry(4, "RS Settings Folder:", self.rs_settings_path_var, is_folder=True)
        create_path_entry(5, "VGGT Project Folder:", self.vggt_path_var, is_folder=True)
        create_path_entry(6, "VGGT Model Path:", self.vggt_model_path_var)
        
                # MODIFIED: The button now calls save_all_settings with the show_success_message flag.
        ttk.Button(frame, text="Save Configuration", 
                   command=lambda: self.callbacks.save_all_settings(show_success_message=True)
                  ).grid(row=7, column=0, columnspan=3, pady=20)

    def get_current_settings(self):
        """Gathers all UI settings into a dictionary."""
        settings = {}
        
        # Collect all tkinter variables
        for var_name, var in self.__dict__.items():
            if isinstance(var, (tk.StringVar, tk.IntVar, tk.DoubleVar, tk.BooleanVar)):
                # Remove '_var' suffix from variable names
                setting_name = var_name.replace('_var', '')
                settings[setting_name] = var.get()
        
        # IMPORTANT: Ensure project_dir is included
        if hasattr(self.state, 'project_dir'):
            settings['project_dir'] = self.state.project_dir.get()
        
        return settings

    def check_queues(self):
        """Enhanced queue checking with structured message handling."""
        try:
            while True:
                msg = self.state.progress_queue.get_nowait()
                if isinstance(msg, dict):
                    msg_type = msg.get('type')
                    
                    if msg_type == 'pipeline_complete':
                        self.callbacks.handle_pipeline_completion(msg)
                    elif msg_type == 'progress_update':
                        # Handle structured progress updates
                        current = msg.get('current', 0)
                        total = msg.get('total', 1)
                        details = msg.get('details', '')
                        
                        # Update the progress manager directly
                        self.progress_manager.update_stage_progress(current, total, details)
                        
                    elif msg_type == 'stage_start':
                        stage = msg.get('stage', 1)
                        details = msg.get('details', '')
                        self.progress_manager.start_stage(stage, details)
                        
                    elif msg_type == 'ui_update':
                        # Direct UI update
                        message = msg.get('message', '')
                        progress = msg.get('progress', 0)
                        
                        # Update the appropriate progress bar
                        if hasattr(self, 'current_pipe_progress'):
                            self.current_pipe_progress['value'] = progress
                        else:
                            self.progress_bar['value'] = progress
                        
                        # Update status text
                        self.state.progress_var.set(message)
                        
                else:
                    # Handle simple string messages (legacy support)
                    self.state.progress_var.set(str(msg))
                    
        except queue.Empty:
            pass

        try:
            while True:
                item_data = self.state.thumbnail_queue.get_nowait()
                self.visuals.process_thumbnail_item(item_data)
        except queue.Empty:
            pass

        self.root.after(100, self.check_queues)


class ConsoleWindow:
    def __init__(self, parent_app):
        self.parent_app = parent_app
        # Since console is now integrated, this can be simpler
        pass
    
    def toggle_console(self):
        """Redirect to integrated console"""
        self.parent_app.toggle_console()
    
