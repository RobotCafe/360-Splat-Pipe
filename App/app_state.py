# app_state.py

import tkinter as tk
import queue
import threading

class AppState:
    """
    A centralized class to hold the shared state of the application.

    This includes core processing flags, input data queues, inter-thread
    communication queues, and essential tkinter variables that need to be
    accessed by different parts of the application.
    """
    def __init__(self):
        # === Core Processing State ===
        # Flag to indicate if the main pipeline is currently running
        self.processing = False
        # Threading event to signal cancellation to background tasks
        self.cancel_event = threading.Event()

        # === Input Data Queues ===
        # List to hold paths of videos to be processed
        self.video_queue = []
        # List to hold paths of image folders to be processed
        self.image_folder_queue = []
        # Combined list used when the pipeline is running
        self.combined_queue = []

        # === Inter-thread Communication Queues ===
        # Queue for results from the main pipeline worker
        self.result_queue = queue.Queue()
        # Queue for progress messages from background tasks to the GUI
        self.progress_queue = queue.Queue()
        # Queue for generated thumbnail images from the visual worker to the GUI
        self.thumbnail_queue = queue.Queue()

        # === Core Tkinter Variables ===
        # Holds the path to the main project directory
        self.project_dir = tk.StringVar()
        # Holds the main status message displayed at the bottom of the window
        self.progress_var = tk.StringVar(value="Ready")
        # Holds information about the currently selected video or image folder
        self.content_info_var = tk.StringVar(value="No content selected")
        # Holds details (duration, frame count, etc.) about the selected content
        self.content_details_var = tk.StringVar(value="--")

        # === UNIFIED CACHING SYSTEM ===
        self.video_info_cache = {}          # Video metadata (duration, fps)
        self.preview_image_cache = {}       # Extracted first frames  
        self.content_cache = {}             # Complete content awareness (thumbnails)
        self.per_video_settings_cache = {}  # NEW: For session-based per-video settings
        self.extraction_frame_cache = {}    # NEW: Master cache for extracted frames
        
        # Cache settings and tracking
        self.cache_max_size = 60            # Content cache size limit
        self.current_content_key = None     # Currently loaded content
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'extractions_saved': 0,
        }

    def get_setting(self, key, default=None):
        """
        Retrieve a setting value from the per-video settings cache.
        
        Args:
            key (str): The setting key to retrieve
            default: Default value to return if key not found
            
        Returns:
            The setting value if found, otherwise the default value
        """
        if self.current_content_key and self.current_content_key in self.per_video_settings_cache:
            cached_settings = self.per_video_settings_cache[self.current_content_key]
            return cached_settings.get(key, default)
        return default

