# extraction_frame_manager.py 
# Core class for managing extraction frame cache and navigation

import os
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

# Third-party imports
import numpy as np
from PIL import Image, ImageTk

# Local imports
import video_extraction

class ExtractionFrameManager:
    """
    Manages extraction frame cache and navigation for 360° preview.
    """
    
    def __init__(self, app, state, visuals):
        # === Core References ===
        self.app = app
        self.state = state
        self.visuals = visuals
        
        # === Current Context ===
        self.current_video_path = None
        self.video_duration = 0.0
        self.video_fps = 30.0
        self.video_info = {}
        
        # === Cache State ===
        self.cache_valid = False
        self.current_frame_index = 0
        self.total_extraction_frames = 0
        
        # === Extraction State ===
        self.extraction_in_progress = False
        self.extraction_progress = 0.0
        
        # === Settings Tracking ===
        self.last_extraction_settings_hash = None
        
        # === UI Elements ===
        self.frame_navigator = None
        self.frame_info_label = None
        self.navigator_controls_frame = None
        
        # === Performance & Memory ===
        self.gpu_available = None
        self.max_uncompressed_frames = 20
        self.frame_access_order = []
        
        # REMOVE - Use unified cache system instead:
        # self.cached_frames = {}        # ❌ Use state.extraction_frame_cache
        # self.compressed_frames = {}    # ❌ Use state.extraction_frame_cache  
        # self.extraction_timestamps = [] # ❌ Use state.extraction_frame_cache
        # self.button = None             # ❌ UNUSED
        
        print("🎬 ExtractionFrameManager initialized (Smart Cache Mode)")


    # --- debug ---
    def _debug_cache_state(self):
        """
        DEBUG: Print detailed cache state for current video.
        """
        if not self.current_video_path:
            print("🔍 DEBUG: No current video path set")
            return
            
        print(f"\n🔍 CACHE DEBUG for {os.path.basename(self.current_video_path)}:")
        print(f"{'='*50}")
        
        cache_entry = self._get_current_cache_entry()
        if not cache_entry:
            print("❌ No cache entry found")
            return
        
        print(f"Cache valid: {cache_entry.get('cache_valid', False)}")
        print(f"Content type: {cache_entry.get('content_type', 'unknown')}")
        print(f"Total frames: {cache_entry.get('total_frames', 0)}")
        print(f"Current index: {cache_entry.get('current_index', 0)}")
        print(f"Settings hash: {cache_entry.get('last_settings_hash', 'None')}")
        print(f"Extracted frames: {len(cache_entry.get('extracted_frames', {}))}")
        print(f"Compressed frames: {len(cache_entry.get('compressed_frames', {}))}")
        print(f"Ordered timestamps: {len(cache_entry.get('ordered_timestamps', []))}")
        
        # Show first few timestamps
        timestamps = cache_entry.get('ordered_timestamps', [])
        if timestamps:
            print(f"First 3 timestamps: {[f'{t:.1f}s' for t in timestamps[:3]]}")
            print(f"Last 3 timestamps: {[f'{t:.1f}s' for t in timestamps[-3:]]}")
        
        print(f"{'='*50}")



    def _get_current_cache_entry(self, create_if_missing=False):
        """Safely gets the cache entry for the current video."""
        if not self.current_video_path:
            return None
        
        if create_if_missing and self.current_video_path not in self.state.extraction_frame_cache:
            # Create a new, blank entry with the new timestamp-based structure
            self.state.extraction_frame_cache[self.current_video_path] = {
                'ordered_timestamps': [],      # An ordered list for the navigator
                'extracted_frames': {},        # A dict keyed by {timestamp: PIL.Image}
                'compressed_frames': {},       # A dict keyed by {timestamp: jpeg_bytes}
                'frame_access_order': [],      # For LRU compression, stores timestamps
                'total_frames': 0,
                'current_index': 0,
                'cache_valid': False,
                'content_type': 'video',
                'last_settings_hash': None  # ✅ ADD THIS LINE
            }
        
        return self.state.extraction_frame_cache.get(self.current_video_path)

    def on_video_selected(self, video_path):
        """Called when user selects a video. Now restores from cache if available."""
        print(f"📹 Loading video for extraction preview: {os.path.basename(video_path)}")
        self.current_video_path = video_path
        self.video_info = video_extraction.get_video_info(video_path, self.app.ffmpeg_path_var.get())
        if self.video_info.get('duration', 0) <= 0:
            self._update_status("❌ Could not get video information"); return False
        
        cache_entry = self._get_current_cache_entry()
        if cache_entry and cache_entry.get('cache_valid'):
            # Cache Hit (for frames): Restore the view using the cached frame.
            print(f"✅ Restoring {cache_entry['total_frames']} cached frames...")
            frame_to_show = self._get_frame_from_cache(cache_entry['current_index'])
            if frame_to_show:
                # Use the new master function to handle the view and its thumbnail cache
                self.visuals.load_view(video_path, frame_to_show)
                # self.visuals._initiate_new_preview_from_pil(frame_to_show)
                # self.visuals.update_visual_overlays()
            self._create_or_update_frame_navigator()
            self._enable_frame_navigator()
            self.navigate_to_frame(cache_entry['current_index'])
            self._update_status(f"✅ {cache_entry['total_frames']} frames restored from cache.")
            return True

        # --- CACHE MISS ---
        print(f"ⓘ No valid frame cache found for {os.path.basename(video_path)}. Ready to extract.")
        cache_entry = self._get_current_cache_entry(create_if_missing=True)
        
        # Tag the new cache entry as a 'video'.
        cache_entry['content_type'] = 'video'
        
        first_frame = self._extract_single_frame(video_path, 0.0)
        if first_frame:
            # Use the new master function to handle the view and its thumbnail cache
            self.visuals.load_view(video_path, first_frame)
            # self.visuals._initiate_new_preview_from_pil(first_frame)
            # self.visuals.update_visual_overlays()
            self._update_status(f"✅ First frame loaded. Configure and click 'Extract Frames'.")
            self.app.extraction_button.config(text="Extract Frames", state='normal')
            self._create_or_update_frame_navigator()
            return True
            
        self._update_status("❌ Could not extract first frame"); return False

    def extract_all_frames_async(self):
        """
        ENHANCED: Smart extraction with better settings validation and logging.
        """
        if self.extraction_in_progress:
            messagebox.showinfo("In Progress", "Frame extraction is already running.")
            return
        if not self.current_video_path:
            messagebox.showwarning("No Video", "Please select a video first.")
            return

        # Validate current settings before extraction
        try:
            current_settings = {
                'method': self.app.extraction_method_var.get(),
                'interval_value': self.app.interval_value_var.get(),
                'interval_unit': self.app.interval_unit_var.get(),
                'frame_count': self.app.frame_count_var.get(),
            }
            print(f"🔧 Current extraction settings:")
            for key, value in current_settings.items():
                print(f"   {key}: {value}")
        except Exception as e:
            messagebox.showerror("Settings Error", f"Invalid extraction settings: {e}")
            return

        cache_entry = self._get_current_cache_entry(create_if_missing=True)
        new_timestamps = self._calculate_extraction_timestamps()
        if not new_timestamps:
            messagebox.showwarning("Invalid Settings", "Invalid extraction settings, resulted in zero frames.")
            return

        existing_timestamps = set(cache_entry['extracted_frames'].keys())
        required_timestamps = set(new_timestamps)
        timestamps_to_add = list(required_timestamps - existing_timestamps)
        timestamps_to_remove = list(existing_timestamps - required_timestamps)

        print(f"🧠 Smart Extraction Plan for {os.path.basename(self.current_video_path)}:")
        print(f"   - ✅ New frames to extract: {len(timestamps_to_add)}")
        print(f"   - 🗑️ Old frames to remove: {len(timestamps_to_remove)}")
        print(f"   - 📊 Total frames after extraction: {len(new_timestamps)}")

        # Remove old frames that are no longer needed
        for ts in timestamps_to_remove:
            if ts in cache_entry['extracted_frames']:
                del cache_entry['extracted_frames'][ts]
            if ts in cache_entry['compressed_frames']:
                del cache_entry['compressed_frames'][ts]
            if ts in cache_entry['frame_access_order']:
                cache_entry['frame_access_order'].remove(ts)

        # Update cache structure
        cache_entry['ordered_timestamps'] = new_timestamps
        cache_entry['total_frames'] = len(new_timestamps)
        
        # Update settings hash to mark this configuration as current
        try:
            settings_hash = hash(str(sorted(current_settings.items())))
            cache_entry['last_settings_hash'] = settings_hash
            print(f"📝 Updated settings hash: {settings_hash}")
        except Exception as e:
            print(f"⚠️ Could not update settings hash: {e}")

        if not timestamps_to_add:
            # No new frames needed - just mark cache as valid
            cache_entry['cache_valid'] = True
            self._on_extraction_complete(0)
            print(f"✅ No new extraction needed - using existing {len(new_timestamps)} frames")
            return

        # Start extraction process
        self.extraction_in_progress = True
        self._update_status(f"Extracting {len(timestamps_to_add)} new frames...")
        self.app.extraction_button.config(text="Cancel Extraction", state='normal')     
        self._disable_frame_navigator()
        
        threading.Thread(target=self._extraction_worker, args=(timestamps_to_add,), daemon=True).start()
    
    def _extraction_worker(self, timestamps_to_extract):
        """Background worker now only extracts a specific list of frames."""
        try:
            cache_entry = self._get_current_cache_entry()
            if not cache_entry: return
            success_count, start_time = 0, time.time()
            total_to_extract = len(timestamps_to_extract)
            for i, timestamp in enumerate(timestamps_to_extract):
                if not self.extraction_in_progress: break
                frame = self._extract_single_frame(self.current_video_path, timestamp)
                if frame:
                    self._store_frame_in_cache(timestamp, frame)
                    success_count += 1
                progress_pct = int(((i + 1) / total_to_extract) * 100)
                if i % 5 == 0 or i == total_to_extract - 1:
                    self.app.root.after(0, lambda p=progress_pct, c=i+1, t=total_to_extract: 
                        self._update_status(f"Extracting {t} new frames... {p}% ({c}/{t})"))
            if success_count > 0:
                cache_entry['cache_valid'] = True
            self.app.root.after(0, lambda: self._on_extraction_complete(success_count))
        except Exception as e:
            self.app.root.after(0, lambda: self._on_extraction_error(str(e)))

    def _store_frame_in_cache(self, timestamp, pil_image):
        cache_entry = self._get_current_cache_entry()
        if not cache_entry: return
        cache_entry['extracted_frames'][timestamp] = pil_image
        cache_entry['frame_access_order'].append(timestamp)
        if len(cache_entry['extracted_frames']) > self.max_uncompressed_frames:
            oldest_timestamp = cache_entry['frame_access_order'].pop(0)
            if oldest_timestamp in cache_entry['extracted_frames'] and oldest_timestamp != timestamp:
                import io
                img_bytes = io.BytesIO()
                cache_entry['extracted_frames'][oldest_timestamp].save(img_bytes, format='JPEG', quality=95)
                cache_entry['compressed_frames'][oldest_timestamp] = img_bytes.getvalue()
                del cache_entry['extracted_frames'][oldest_timestamp]
    
    def _get_frame_from_cache(self, frame_index):
        cache_entry = self._get_current_cache_entry()
        if not cache_entry or frame_index >= len(cache_entry['ordered_timestamps']): return None
        timestamp = cache_entry['ordered_timestamps'][frame_index]
        if timestamp in cache_entry['extracted_frames']:
            if timestamp in cache_entry['frame_access_order']: cache_entry['frame_access_order'].remove(timestamp)
            cache_entry['frame_access_order'].append(timestamp)
            return cache_entry['extracted_frames'][timestamp]
        if timestamp in cache_entry['compressed_frames']:
            import io
            img_bytes = io.BytesIO(cache_entry['compressed_frames'][timestamp])
            pil_image = Image.open(img_bytes)
            pil_image.load()
            self._store_frame_in_cache(timestamp, pil_image)
            del cache_entry['compressed_frames'][timestamp]
            return pil_image
        return None

    def get_cached_frames_for_pipeline(self):
        """
        ENHANCED: Retrieves all frames for pipeline with better error handling and logging.
        """
        cache_entry = self._get_current_cache_entry()
        if not cache_entry:
            print(f"❌ No cache entry found for current video")
            return []
            
        if not cache_entry.get('cache_valid'):
            print(f"❌ Cache is not valid for current video")
            return []
        
        total_frames = cache_entry.get('total_frames', 0)
        if total_frames == 0:
            print(f"❌ No frames in cache for current video")
            return []
        
        print(f"🔍 Retrieving {total_frames} cached frames for pipeline...")
        
        frames = []
        failed_count = 0
        
        for i in range(total_frames):
            frame = self._get_frame_from_cache(i)
            if frame is not None:
                frames.append(frame)
            else:
                print(f"⚠️ Failed to retrieve frame {i} from cache")
                failed_count += 1
        
        if failed_count > 0:
            print(f"⚠️ Failed to retrieve {failed_count}/{total_frames} frames from cache")
        
        success_count = len(frames)
        print(f"✅ Successfully retrieved {success_count}/{total_frames} frames for pipeline")
        
        return frames

    def navigate_to_frame(self, frame_index):
        cache_entry = self._get_current_cache_entry()
        if not (cache_entry and cache_entry.get('cache_valid')): return
        frame_index = max(0, min(frame_index, cache_entry['total_frames'] - 1))
        frame = self._get_frame_from_cache(frame_index)
        if not frame: 
            print(f"⚠️ Frame {frame_index} not found in cache.")
            return
        cache_entry['current_index'] = frame_index
        timestamp = cache_entry['ordered_timestamps'][frame_index]
        self.visuals._initiate_new_preview_from_pil(frame)
        self._update_navigator_ui(frame_index, timestamp)
        # This call is now safe, because the feedback loop has been broken. but this does not work
        self.visuals.update_visual_overlays()
        # self.visuals._debounced_parameter_update(reason="frame_navigation")

    def on_extraction_settings_change(self):
        """FIXED: Proper per-video settings hash tracking."""
        cache_entry = self._get_current_cache_entry()
        if not cache_entry or cache_entry.get('content_type') == 'folder':
            return
            
        # Skip if settings are currently being loaded
        if hasattr(self.app.callbacks, '_settings_loading_in_progress') and \
           self.app.callbacks._settings_loading_in_progress:
            print("⏭️ Skipping settings change during loading")
            return

        try:
            current_settings = {
                'method': self.app.extraction_method_var.get(),
                'interval_value': self.app.interval_value_var.get(),
                'interval_unit': self.app.interval_unit_var.get(),
                'frame_count': self.app.frame_count_var.get(),
            }
            current_hash = hash(str(sorted(current_settings.items())))
        except tk.TclError:
            return

        # === CRITICAL FIX: Compare against THIS video's last hash ===
        last_hash_for_this_video = cache_entry.get('last_settings_hash')
        video_name = os.path.basename(self.current_video_path) if self.current_video_path else 'unknown'


        if last_hash_for_this_video is None:
            # First time settings for this video - just store the hash
            cache_entry['last_settings_hash'] = current_hash
            print(f"📝 Initial settings hash stored for {video_name}")
            return

        if last_hash_for_this_video != current_hash:
            print(f"⚠️ Settings changed for {video_name} - cache invalidated")
            print(f"   Previous hash: {last_hash_for_this_video}")
            print(f"   Current hash: {current_hash}")
            print(f"   Settings: {current_settings}")
            
            # Invalidate the cache for this specific video
            cache_entry['cache_valid'] = False
            cache_entry['last_settings_hash'] = current_hash
            
            # Clear the extracted frames since settings changed
            cache_entry['extracted_frames'].clear()
            cache_entry['compressed_frames'].clear()
            cache_entry['frame_access_order'].clear()
            cache_entry['ordered_timestamps'] = []
            cache_entry['total_frames'] = 0
            cache_entry['current_index'] = 0
            
            self._update_status("⚠️ Settings changed - click 'Extract Frames' to apply.")
            
            # Update UI to reflect that extraction is needed
            self.app.extraction_button.config(text="Extract Frames", state='normal')
            self._disable_frame_navigator()
        else:
            print(f"✅ Settings unchanged for {video_name}")
    
    def clear_cache(self):
        """
        MODIFIED: Clears the entire master frame cache and resets the navigator UI.
        This version does not ask for confirmation, as that is handled by the caller.
        """
        self.state.extraction_frame_cache.clear()
        self.current_video_path = None
        self._disable_frame_navigator()
        print("🧹 All extraction frame caches cleared")
    
    # -- Image Folder Funtions --

    def on_image_folder_selected(self, folder_path):
        """
        UPGRADED: Immediately loads the first image for a responsive preview
        and then loads the rest of the folder's images in the background.
        """
        print(f"🖼️ Loading image folder: {os.path.basename(folder_path)}")
        self.current_video_path = folder_path

        # 1. Check if a valid cache for this folder already exists.
        cache_entry = self._get_current_cache_entry()
        if cache_entry and cache_entry.get('cache_valid'):
            print(f"✅ Restoring {cache_entry['total_frames']} cached images for {os.path.basename(folder_path)}")
            
            # Restore the view from the cached image
            frame_to_show = self._get_frame_from_cache(cache_entry['current_index'])
            if frame_to_show:
                #use new method
                self.visuals.load_view(folder_path, frame_to_show)
                # self.visuals._initiate_new_preview_from_pil(frame_to_show)
                # self.visuals.update_visual_overlays()

            # Update and enable the navigator
            self._create_or_update_frame_navigator()
            self._enable_frame_navigator()
            self.navigate_to_frame(cache_entry['current_index']) # Syncs UI
            self._update_status(f"✅ {cache_entry['total_frames']} images restored from cache.")
            return True # Exit the function successfully

        # --- CACHE MISS ---
        # If no valid cache, proceed with the initial loading process from disk.
        print(f"ⓘ No valid image cache found for {os.path.basename(folder_path)}. Loading from disk.")

        # Find all valid image files
        image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff')
        image_files = sorted([
            os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if f.lower().endswith(image_extensions)
        ])

        if not image_files:
            messagebox.showwarning("No Images", "No valid image files found in the selected folder.")
            self.visuals._reset_preview_to_initial_state()
            return

        # --- NEW LOGIC: IMMEDIATE PREVIEW ---
        # 1. Immediately load the first image to provide instant feedback.
        first_image_path = image_files[0]
        try:
            with Image.open(first_image_path) as img:
                img.load()
                first_image_pil = img
        except Exception as e:
            messagebox.showerror("Image Load Error", f"Could not load the first image: {os.path.basename(first_image_path)}\n\nError: {e}")
            return

        # Use the new master function to handle the view and its thumbnail cache
        self.visuals.load_view(folder_path, first_image_pil)

        # 2. Display the first image and trigger overlay/thumbnail generation right away.
        # self.visuals._initiate_new_preview_from_pil(first_image_pil)
        # self.visuals.update_visual_overlays()
        # --- END NEW LOGIC ---

        # 3. Now, create the cache entry and start loading ALL images in the background.
        cache_entry = self._get_current_cache_entry(create_if_missing=True)
        cache_entry['content_type'] = 'folder' 
        cache_entry['ordered_timestamps'] = image_files
        cache_entry['total_frames'] = len(image_files)
        
        self.extraction_in_progress = True
        self._update_status(f"Loading {len(image_files)} images from folder...")
        self.app.extraction_button.config(text="Loading...", state='disabled')
        self._create_or_update_frame_navigator()
        self._disable_frame_navigator()

        threading.Thread(target=self._image_loader_worker, args=(image_files,), daemon=True).start()

    def _image_loader_worker(self, image_files_to_load):
        """Background worker to load images from a folder into the cache."""
        try:
            cache_entry = self._get_current_cache_entry()
            if not cache_entry: return

            success_count = 0
            total_to_load = len(image_files_to_load)
            
            for i, file_path in enumerate(image_files_to_load):
                if not self.extraction_in_progress: break
                try:
                    # Open the image and store it in the cache
                    with Image.open(file_path) as img:
                        img.load() # Force loading the image data
                        # The key is the timestamp, which is the file path
                        self._store_frame_in_cache(file_path, img)
                        success_count += 1
                except Exception as e:
                    print(f"❌ Could not load image {os.path.basename(file_path)}: {e}")

                if i % 5 == 0 or i == total_to_load - 1:
                    self.app.root.after(0, lambda c=i+1, t=total_to_load: 
                        self._update_status(f"Loading images... ({c}/{t})"))

            if success_count > 0:
                cache_entry['cache_valid'] = True
            
            # Use the same completion function as the frame extractor
            self.app.root.after(0, lambda: self._on_extraction_complete(success_count))
        except Exception as e:
            self.app.root.after(0, lambda: self._on_extraction_error(str(e)))

    # --- helper functions ---


    def _on_extraction_complete(self, success_count):
        """
        MODIFIED: Now intelligently sets the button state and text based
        on whether a video or an image folder has finished processing.
        """
        self.extraction_in_progress = False
        self._enable_frame_navigator()

        # Check the type of content that just finished loading.
        cache_entry = self._get_current_cache_entry()
        if cache_entry and cache_entry.get('content_type') == 'folder':
            # For an image folder, the process is complete. Keep the button disabled.
            self.app.extraction_button.config(state='disabled', text='Frames Loaded')
        else:
            # For a video, extraction is complete. Enable the button for another run.
            self.app.extraction_button.config(text="Extract Frames", state='normal')
        
        # Update the status message to be more specific
        if success_count > 0:
            if cache_entry and cache_entry.get('content_type') == 'folder':
                 self._update_status(f"✅ {success_count} images loaded. Ready to navigate.")
            else:
                 self._update_status(f"✅ {success_count} frames extracted. Ready to navigate.")
        else: # This happens for smart-extraction updates where 0 new frames are added
             self._update_status("✅ Frames updated. Ready to navigate.")
        # Navigate to the first frame to ensure the view is synchronized    
        self.navigate_to_frame(0)

    def _update_navigator_ui(self, frame_index, timestamp):
        """
        MODIFIED: Now handles both numeric timestamps (for videos) and
        string-based identifiers (for image folders).
        """
        cache_entry = self._get_current_cache_entry()
        if not cache_entry: return
        
        if self.frame_navigator:
            # This part is fine, it just sets the integer position of the slider
            self.frame_navigator.set(frame_index)
        
        if self.frame_info_label:
            info_text = ""
            
            # --- THE FIX ---
            # Check if the timestamp is a number or a string
            if isinstance(timestamp, (int, float)):
                # It's a video, so calculate and display the time
                minutes, seconds = int(timestamp // 60), int(timestamp % 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
                info_text = f"Frame {frame_index + 1}/{cache_entry['total_frames']} at {time_str}"
            elif isinstance(timestamp, str):
                # It's an image folder, so display the filename
                filename = os.path.basename(timestamp)
                info_text = f"Image {frame_index + 1}/{cache_entry['total_frames']}: {filename}"
            else:
                # A fallback for any unexpected data type
                info_text = f"Frame {frame_index + 1}/{cache_entry['total_frames']}"

            self.frame_info_label.config(text=info_text)

    def _calculate_extraction_timestamps(self):
        """
        ENHANCED: Calculate timestamps with better error handling and validation.
        """
        try:
            if not self.current_video_path:
                print(f"❌ No current video path set")
                return []
                
            # Get video info for this specific video
            video_info = video_extraction.get_video_info(self.current_video_path, self.app.ffmpeg_path_var.get())
            
            if not video_info or video_info.get('duration', 0) <= 0:
                print(f"❌ Invalid video info for {os.path.basename(self.current_video_path)}")
                return []
            
            duration = video_info.get('duration')
            fps = video_info.get('fps', 30)
            
            print(f"📹 Video info for timestamp calculation:")
            print(f"   Duration: {duration:.1f}s")
            print(f"   FPS: {fps:.1f}")
            
            # Get current extraction settings
            extraction_method = self.app.extraction_method_var.get()
            interval_value = self.app.interval_value_var.get()
            interval_unit = self.app.interval_unit_var.get()
            frame_count = self.app.frame_count_var.get()
            
            print(f"📋 Extraction parameters:")
            print(f"   Method: {extraction_method}")
            print(f"   Interval value: {interval_value}")
            print(f"   Interval unit: {interval_unit}")
            print(f"   Frame count: {frame_count}")
            
            timestamps = video_extraction.calculate_extraction_timestamps(
                video_duration=duration, 
                video_fps=fps, 
                extraction_method=extraction_method, 
                interval_value=interval_value, 
                interval_unit=interval_unit, 
                frame_count=frame_count
            )
            
            print(f"🎯 Calculated {len(timestamps)} timestamps: {[f'{t:.1f}s' for t in timestamps[:3]]}...{[f'{t:.1f}s' for t in timestamps[-3:]]}")
            
            return timestamps
            
        except Exception as e:
            print(f"❌ Error calculating extraction timestamps: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _enable_frame_navigator(self):
        cache_entry = self._get_current_cache_entry()
        if not self.navigator_controls_frame or not cache_entry: return
        for button in self.nav_buttons: button.config(state='normal')
        if self.frame_navigator: self.frame_navigator.config(state='normal', to=max(1, cache_entry['total_frames'] - 1))
        if self.frame_info_label: self.frame_info_label.config(text="Ready for navigation", foreground='darkgreen')

    def _on_extraction_error(self, error_msg):
        self.extraction_in_progress = False
        self.app.extraction_button.config(text="Extract Frames", state='normal')
        self._update_status(f"❌ Extraction failed: {error_msg}")
        messagebox.showerror("Extraction Error", f"Frame extraction failed:\n{error_msg}")

    def _extract_single_frame(self, video_path, timestamp):
        try:
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name
            try:
                success = video_extraction.extract_single_frame_gpu(video_path=video_path, timestamp=timestamp, output_path=temp_path, ffmpeg_path=self.app.ffmpeg_path_var.get(), use_gpu=True)
                if success and os.path.exists(temp_path):
                    frame = Image.open(temp_path)
                    frame.load()
                    return frame
                else:
                    return None
            finally:
                if os.path.exists(temp_path): os.unlink(temp_path)
        except Exception as e:
            print(f"❌ Error extracting frame at {timestamp:.1f}s: {e}")
            return None

    def _create_or_update_frame_navigator(self):
        extraction_tab = self.app.tabs['1. Frame & View Extraction']
        settings_container = None
        for child in extraction_tab.winfo_children():
            if isinstance(child, ttk.Frame):
                for grandchild in child.winfo_children():
                    if (isinstance(grandchild, ttk.Labelframe) and hasattr(grandchild, 'cget') and 'Preview' in grandchild.cget('text')):
                        settings_container = child
                        break
                if settings_container: break
        if not settings_container:
            print("⚠️ Could not find settings container for frame navigator")
            return
        # Clean up existing accordion
        if hasattr(self, 'navigator_accordion') and self.navigator_accordion:
            self.navigator_accordion.destroy()
        if self.navigator_controls_frame: 
            self.navigator_controls_frame.destroy()
        
        # Create accordion frame for Frame Navigator
        from app_gui import AccordionFrame
        self.navigator_accordion = AccordionFrame(settings_container, "🎬 Extracted Frame Navigator", is_expanded=False)
        self.navigator_accordion.grid(row=3, column=0, sticky='ew', pady=(0, 5))
        self.navigator_controls_frame = self.navigator_accordion.get_content_frame()
        self.navigator_controls_frame.grid_columnconfigure(1, weight=1)
        controls_frame = ttk.Frame(self.navigator_controls_frame)
        controls_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        controls_frame.grid_columnconfigure(2, weight=1)
        button_frame = ttk.Frame(controls_frame)
        button_frame.grid(row=0, column=0, sticky='w')
        ttk.Button(button_frame, text="⏮", width=3, command=lambda: self.navigate_to_frame(0), state='disabled').pack(side='left', padx=1)
        ttk.Button(button_frame, text="◀", width=3, command=lambda: self.navigate_to_frame(self._get_current_cache_entry().get('current_index', 0) - 1), state='disabled').pack(side='left', padx=1)
        ttk.Button(button_frame, text="▶", width=3, command=lambda: self.navigate_to_frame(self._get_current_cache_entry().get('current_index', 0) + 1), state='disabled').pack(side='left', padx=1)
        ttk.Button(button_frame, text="⏭", width=3, command=lambda: self.navigate_to_frame(self._get_current_cache_entry().get('total_frames', 1) - 1), state='disabled').pack(side='left', padx=1)
        self.nav_buttons = button_frame.winfo_children()
        self.frame_info_label = ttk.Label(controls_frame, text="Extract frames to enable navigation", font=('Arial', 9), foreground='Red')
        self.frame_info_label.grid(row=0, column=1, padx=10)
        self.extraction_progress_label = ttk.Label(controls_frame, text="", font=('Arial', 8), foreground='orange')
        self.extraction_progress_label.grid(row=0, column=2, sticky='e')
        scrubber_frame = ttk.Frame(self.navigator_controls_frame)
        scrubber_frame.grid(row=1, column=0, sticky='ew', pady=5)
        scrubber_frame.grid_columnconfigure(0, weight=1)
        self.frame_navigator = ttk.Scale(scrubber_frame, from_=0, to=1, orient='horizontal', command=self._on_navigator_change, state='disabled')
        self.frame_navigator.grid(row=0, column=0, sticky='ew')
        instructions_label = ttk.Label(self.navigator_controls_frame, text="💡 Navigate extracted frames to preview pitch, yaw and FOV settings.", font=('Arial', 8), foreground='blue')
        instructions_label.grid(row=2, column=0, pady=(5, 0))
        print("🎮 Frame navigator controls created")

    def _on_navigator_change(self, value):
        cache_entry = self._get_current_cache_entry()
        if not cache_entry or not cache_entry.get('cache_valid'): return
        try:
            frame_index = int(float(value))
            if frame_index != cache_entry.get('current_index'): self.navigate_to_frame(frame_index)
        except (ValueError, TypeError): pass

    def _disable_frame_navigator(self):
        if hasattr(self, 'nav_buttons'):
            for button in self.nav_buttons: button.config(state='disabled')
        if self.frame_navigator: self.frame_navigator.config(state='disabled')
        if self.frame_info_label: self.frame_info_label.config(text="Extract frames for preview...", foreground='Red')

    def _update_status(self, message): 
        self.state.progress_var.set(message)

    def cancel_extraction(self):
        if self.extraction_in_progress:
            self.extraction_in_progress = False
            self._update_status("🛑 Frame extraction cancelled")
            print("🛑 Frame extraction cancelled by user")

# Integration helpers for existing code:
def integrate_extraction_manager_with_visuals(visuals):
    """Add new method to VisualsManager for PIL image integration."""
    
    def _initiate_new_preview_from_pil(self, pil_image):
        """
        NEW: Initiate preview directly from PIL Image (for extraction frames).
        Bypasses file I/O for instant frame switching.
        """
        try:
            # Validate 2:1 aspect ratio
            w, h = pil_image.size
            if abs(w / h - 2.0) > 0.1:
                print(f"⚠️ Frame aspect ratio {w/h:.2f} is not 2:1 - may not be 360° content")
            
            # Store for thumbnail generation
            self.current_preview_source_np = np.array(pil_image)
            
            # Create display image with hemisphere swap (for 360° content)
            display_w, display_h = 800, int(800 * h / w)
            resized_img = pil_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
            
            # Apply hemisphere swap for 360° display
            center_split_point = resized_img.width // 2
            left_half = resized_img.crop((0, 0, center_split_point, resized_img.height))
            right_half = resized_img.crop((center_split_point, 0, resized_img.width, resized_img.height))
            
            self.base_display_img = Image.new('RGB', (resized_img.width, resized_img.height))
            self.base_display_img.paste(right_half, (0, 0))
            self.base_display_img.paste(left_half, (right_half.width, 0))
            
            # Display on canvas
            self.current_display_tk = ImageTk.PhotoImage(self.base_display_img)
            self.app.source_canvas.config(width=self.base_display_img.width, height=self.base_display_img.height)
            
            if self.canvas_image_id:
                self.app.source_canvas.itemconfig(self.canvas_image_id, image=self.current_display_tk)
            else:
                self.canvas_image_id = self.app.source_canvas.create_image(0, 0, anchor=tk.NW, image=self.current_display_tk)
            
        except Exception as e:
            print(f"❌ PIL integration error: {e}")
    
    # Add method to visuals instance
    import types
    visuals._initiate_new_preview_from_pil = types.MethodType(_initiate_new_preview_from_pil, visuals)


def setup_extraction_frame_system(app, state, visuals, callbacks):
    """
    MODIFIED: Simplified setup that no longer uses the conflicting
    integration helpers for callbacks and GUI.
    """
    print("🏗️ Setting up Extraction Frame System...")
    
    extraction_manager = ExtractionFrameManager(app, state, visuals)
    
    # This visual integration is still necessary
    integrate_extraction_manager_with_visuals(visuals)
    
    # Store references
    app.extraction_manager = extraction_manager
    callbacks.extraction_manager = extraction_manager
    visuals.extraction_manager = extraction_manager
    
    # Add the "Extract Frames" button directly from the GUI setup
    app.add_extraction_button()
    
    # The variable traces will be handled entirely by the GUI setup
    print("✅ Extraction Frame System setup complete!")
    return extraction_manager