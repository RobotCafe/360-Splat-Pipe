# progress_manager.py

import queue
import datetime



"""
Enhanced Progress Management System for 360° Pipeline
Provides centralized progress tracking with support for both single and dual progress bars.
"""

class ProgressManager:
    """Enhanced progress tracking with dual progress bar support."""
    
    def __init__(self, progress_bar, progress_label, progress_queue, parent_gui=None):
        """
        Initialize progress manager.
        
        Args:
            progress_bar: tkinter Progressbar widget (current pipe progress)
            progress_label: tkinter Label widget for status text
            progress_queue: queue.Queue for progress messages
            parent_gui: Reference to PipelineGUI for batch progress updates
        """
        self.progress_bar = progress_bar
        self.progress_label = progress_label
        self.progress_queue = progress_queue
        self.parent_gui = parent_gui  # For accessing dual progress methods

        # Current stage/item tracking
        self.current_stage = None
        self.total_stages = 4
        self.stage_progress = 0
        self.overall_progress = 0

        # Overall pipeline tracking
        self.current_item_index = 0
        self.total_items = 0
        self.current_item_name = ""
        
        # Batch processing tracking
        self.is_batch_mode = False
        self.batch_total_items = 0
        self.batch_current_item = 0
        
        # Stage definitions
        self.stages = {
            1: "Video Frame Extraction",
            2: "360 View Extraction", 
            3: "Camera Pose Alignment",
            4: "Gaussian Neural Training"
        }
    
    def start_pipeline(self, total_items, is_batch=False):
        """Initialize progress for full pipeline."""
        self.progress_bar.config(mode='determinate', maximum=100)
        self.progress_bar['value'] = 0
        self.total_items = total_items
        self.current_item_index = 0
        self.is_batch_mode = is_batch and total_items > 1
        
        if self.is_batch_mode:
            self.batch_total_items = total_items
            self.batch_current_item = 0
            # Initialize batch progress if dual bars are enabled
            if self.parent_gui and hasattr(self.parent_gui, 'reset_batch_progress'):
                self.parent_gui.reset_batch_progress()
            
            message = f"Starting batch pipeline... Processing {total_items} items"
            self.update_display(message, 0)
        else:
            message = "Starting pipeline..." + (f" Processing {total_items} items" if total_items > 1 else "")
            self.update_display(message, 0)
    
    def start_item(self, item_name, item_index):
        """ENHANCED: Start item with detailed logging."""
        self.current_item_index = item_index  
        self.current_item_name = item_name
        self.current_stage = 0
        self.stage_progress = 0
        
        # === ITEM LOGGING: Start marker ===
        print("\n" + "🔥" * 60)
        print(f"📦 PROCESSING ITEM {item_index + 1}/{self.total_items}")
        print(f"🎯 Item: {item_name}")
        print(f"⏰ Started: {datetime.datetime.now().strftime('%H:%M:%S')}")
        print("🔥" * 60)
        
        # Update batch progress if in batch mode
        if self.is_batch_mode and self.parent_gui:
            if hasattr(self.parent_gui, 'update_batch_progress'):
                self.parent_gui.update_batch_progress(item_index, self.batch_total_items, item_name)
        
        # Show current item progress
        if self.total_items > 1:
            overall_info = f"[{item_index + 1}/{self.total_items}]"
            message = f"{overall_info} Processing: {item_name}"
        else:
            message = f"Processing: {item_name}"
            
        self.update_display(message, 0)
    
    def start_stage(self, stage_number, details=""):
        """Start a new pipeline stage."""
        self.current_stage = stage_number
        self.stage_progress = 0
        stage_name = self.stages.get(stage_number, f"Stage {stage_number}")

        # Include overall progress info
        if self.total_items > 1:
            overall_info = f"[{self.current_item_index + 1}/{self.total_items}]"
            message = f"{overall_info} Stage {stage_number}: {stage_name}"
        else:
            message = f"Stage {stage_number}: {stage_name}"
            
        if details:
            message += f" - {details}"
            
        self.update_display(message, self._calculate_current_item_progress())
    
    def update_stage_progress(self, current, total, details=""):
        """Update progress within current stage."""
        if total > 0:
            self.stage_progress = (current / total) * 100
        
        stage_name = self.stages.get(self.current_stage, f"Stage {self.current_stage}")
        
        # Include overall progress info
        if self.total_items > 1:
            overall_info = f"[{self.current_item_index + 1}/{self.total_items}]"
            message = f"{overall_info} Stage {self.current_stage}: {stage_name} - {current}/{total}"
        else:
            message = f"Stage {self.current_stage}: {stage_name} - {current}/{total}"
            
        if details:
            message += f" ({details})"
            
        self.update_display(message, self._calculate_current_item_progress())
    
    def update_stage_details(self, details):
        """Update stage details without changing progress."""
        stage_name = self.stages.get(self.current_stage, f"Stage {self.current_stage}")
        
        if self.total_items > 1:
            overall_info = f"[{self.current_item_index + 1}/{self.total_items}]"
            message = f"{overall_info} Stage {self.current_stage}: {stage_name} - {details}"
        else:
            message = f"Stage {self.current_stage}: {stage_name} - {details}"
            
        self.update_display(message, self._calculate_current_item_progress())
    
    def update_display(self, message, progress_value):
        """Update both progress bar and label."""
        self.progress_label.config(text=message)
        self.progress_bar['value'] = min(100, max(0, progress_value))
        
        # Also queue for potential logging
        self.progress_queue.put(message)
    
    def _calculate_current_item_progress(self):
        """Calculate progress for the current item only (for current pipe progress bar)."""
        if self.current_stage > 0:
            stage_base_progress = ((self.current_stage - 1) / self.total_stages) * 100
            stage_current_progress = (self.stage_progress / 100) * (100 / self.total_stages)
            return stage_base_progress + stage_current_progress
        return 0
    
    def _calculate_overall_progress(self):
        """Calculate overall pipeline progress (for batch progress bar)."""
        if self.total_items == 0:
            return 0
            
        # Progress per item
        item_progress = (self.current_item_index / self.total_items) * 100
        
        # Progress within current item
        within_item_progress = self._calculate_current_item_progress() / self.total_items
            
        return item_progress + within_item_progress
    
    def complete_stage(self):
        """Mark current stage as complete."""
        if self.current_stage:
            stage_name = self.stages.get(self.current_stage, f"Stage {self.current_stage}")
            message = f"Stage {self.current_stage}: {stage_name} - Complete"
            if self.total_items > 1:
                overall_info = f"[{self.current_item_index + 1}/{self.total_items}]"
                message = f"{overall_info} {message}"
            self.update_display(message, self._calculate_current_item_progress())
    
    def complete_item(self):
        """ENHANCED: Complete item with detailed logging."""
        # === ITEM LOGGING: Completion marker ===
        print("\n" + "✅" * 60)
        print(f"🎉 COMPLETED ITEM {self.current_item_index + 1}/{self.total_items}")
        print(f"🎯 Item: {self.current_item_name}")
        print(f"⏰ Completed: {datetime.datetime.now().strftime('%H:%M:%S')}")
        print("✅" * 60 + "\n")
        
        # Show completion with overall progress
        if self.total_items > 1:
            message = f"Completed {self.current_item_name} [{self.current_item_index + 1}/{self.total_items}]"
        else:
            message = f"Completed {self.current_item_name}"
            
        self.update_display(message, 100)
        
        # Update batch progress if in batch mode
        if self.is_batch_mode and self.parent_gui:
            if hasattr(self.parent_gui, 'update_batch_progress'):
                self.parent_gui.update_batch_progress(
                    self.current_item_index, 
                    self.batch_total_items, 
                    f"Completed {self.current_item_name}"
                )
    
    def complete_pipeline(self):
        """Mark entire pipeline as complete."""
        self.progress_bar['value'] = 100
        
        # Update batch progress if in batch mode
        if self.is_batch_mode and self.parent_gui:
            if hasattr(self.parent_gui, 'complete_batch_progress'):
                self.parent_gui.complete_batch_progress()
        else:
            # Show final completion message for single item
            if self.total_items > 1:
                self.progress_label.config(text=f"Pipeline completed! Processed {self.total_items} items successfully.")
            else:
                self.progress_label.config(text="Processing completed successfully!")
    
    def error_occurred(self, error_message):
        """Handle error state."""
        error_msg = f"Error: {error_message}"
        if self.total_items > 1:
            overall_info = f"[{self.current_item_index + 1}/{self.total_items}]"
            error_msg = f"{overall_info} {error_msg}"
        self.progress_label.config(text=error_msg)
        # Don't change progress bar value on error
    
    def reset(self):
        """Reset progress manager to initial state."""
        self.current_stage = None
        self.stage_progress = 0
        self.overall_progress = 0
        self.current_item_index = 0
        self.total_items = 0
        self.current_item_name = ""
        self.is_batch_mode = False
        self.batch_total_items = 0
        self.batch_current_item = 0
        self.progress_bar['value'] = 0
        self.progress_label.config(text="Ready")
        
        # Reset batch progress if available
        if self.parent_gui and hasattr(self.parent_gui, 'reset_batch_progress'):
            self.parent_gui.reset_batch_progress()


# === Enhanced Progress Callback Helpers ===

def create_frame_extraction_callback(progress_manager):
    """Create a callback function for frame extraction progress."""
    def callback(current_frame, total_frames, frame_time=None):
        details = f"Frame {current_frame}/{total_frames}"
        if frame_time:
            details += f" at {frame_time:.1f}s"
        progress_manager.update_stage_progress(current_frame, total_frames, details)
    return callback

def create_view_extraction_callback(progress_manager, frame_idx, total_frames):
    """Create a callback function for view extraction progress."""
    def callback(current_view, total_views):
        details = f"Frame {frame_idx + 1}/{total_frames}, View {current_view + 1}/{total_views}"
        # Calculate overall view progress across all frames
        views_per_frame = total_views
        total_operations = total_frames * views_per_frame
        current_operation = (frame_idx * views_per_frame) + current_view
        progress_manager.update_stage_progress(current_operation, total_operations, details)
    return callback

def parse_training_output(line, tool_name="Training"):
    """
    Parse training output lines for progress information.
    
    Args:
        line: Output line from training tool
        tool_name: Name of the training tool (e.g., "Postshot", "Brush")
    
    Returns:
        Formatted progress string
    """
    line = line.strip()
    if not line:
        return None
        
    # Common patterns for training progress
    if "step" in line.lower() and "/" in line:
        return f"{tool_name}: {line}"
    elif "%" in line:
        return f"{tool_name}: {line}"
    elif "epoch" in line.lower():
        return f"{tool_name}: {line}"
    elif "loss" in line.lower():
        return f"{tool_name}: {line}"
    else:
        return f"{tool_name}: {line}"