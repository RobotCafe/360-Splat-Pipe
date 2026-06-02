# status_utils.py - Robust global status system

import threading
import time
from typing import Optional, Any

# Global state with thread safety
_status_app: Optional[Any] = None
_status_lock = threading.Lock()
_last_message_time = 0
_message_throttle = 0.1  # Minimum time between messages (100ms)

def set_status_app(app):
    """
    Set the app reference for status updates.
    
    Args:
        app: PipelineGUI instance with status_print method
    """
    global _status_app
    with _status_lock:
        _status_app = app
        print(f"✅ Status app reference set: {type(app).__name__}")

def clear_status_app():
    """Clear the app reference (useful for cleanup/testing)"""
    global _status_app
    with _status_lock:
        _status_app = None
        print("🧹 Status app reference cleared")

def is_status_available():
    """Check if status updates are available"""
    with _status_lock:
        return _status_app is not None and hasattr(_status_app, 'status_print')

def status_print(message, category="INFO", duration=5000, force=False):
    """
    Global status print function with robust error handling.
    
    Args:
        message: Text to display
        category: Category for color coding ("INFO", "SUCCESS", "ERROR", "PROGRESS", "DEBUG")
        duration: How long to show in status (milliseconds), 0 = permanent
        force: If True, bypass throttling
    """
    global _last_message_time
    
    # Always print to console
    print(message)
    
    # Throttle rapid messages (unless forced)
    current_time = time.time()
    if not force and (current_time - _last_message_time) < _message_throttle:
        return
    
    _last_message_time = current_time
    
    # Try to update status bar
    with _status_lock:
        if _status_app and hasattr(_status_app, 'status_print'):
            try:
                _status_app.status_print(message, category, duration)
            except Exception as e:
                # Don't crash if status update fails
                print(f"⚠️ Status update failed: {e}")
                # Clear bad reference
                _status_app = None
        # If no app reference, just console output (which already happened)

# _try_auto_discover_app function removed - unnecessary GUI dependency fallback

# Convenience functions for different message types
def status_info(message, duration=5000):
    """Show info message"""
    status_print(message, "INFO", duration)

def status_success(message, duration=3000):
    """Show success message"""
    status_print(message, "SUCCESS", duration)

def status_error(message, duration=7000):
    """Show error message (longer duration)"""
    status_print(message, "ERROR", duration)

def status_progress(message, duration=0):
    """Show progress message (permanent until replaced)"""
    status_print(message, "PROGRESS", duration)

def status_debug(message, duration=10000):
    """Show debug message (longer duration)"""
    status_print(message, "DEBUG", duration)

# Context manager for status updates
class StatusContext:
    """Context manager for status updates with automatic cleanup"""
    
    def __init__(self, start_message, success_message=None, error_message=None):
        self.start_message = start_message
        self.success_message = success_message or "✅ Operation completed"
        self.error_message = error_message or "❌ Operation failed"
        
    def __enter__(self):
        status_progress(self.start_message)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            status_success(self.success_message)
        else:
            status_error(f"{self.error_message}: {exc_val}")

# Usage example for context manager:
# with StatusContext("Processing video...", "✅ Video processed", "❌ Video processing failed"):
#     # Your processing code here
#     process_video()

# Debug function
def debug_status_system():
    """Debug the status system state"""
    with _status_lock:
        print("\n🔍 STATUS SYSTEM DEBUG:")
        print(f"   App reference: {_status_app}")
        print(f"   App type: {type(_status_app).__name__ if _status_app else 'None'}")
        print(f"   Has status_print: {hasattr(_status_app, 'status_print') if _status_app else False}")
        print(f"   Available: {is_status_available()}")
        print(f"   Last message time: {_last_message_time}")
        print(f"   Message throttle: {_message_throttle}s")