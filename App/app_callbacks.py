# app_callbacks.py

# Standard library imports
import hashlib
import os
import subprocess
import tempfile
import threading
import time
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
import datetime
import shutil


# Third-party imports
import psutil

# Local imports
import _common_utils
import panorama_processing
import settings_manager
import video_extraction
from app_logging import PipelineLogger
from vggt_training import VGGTProcessor, write_colmap_files, save_ply, run_full_pipeline



# Remove: from typing import Any (unused)

class CallbacksManager:
    """
    Manages all application logic, event handling, and background processing.
    This class acts as the controller, responding to user input from the GUI.
    """
    def __init__(self, app, state, visuals):
        # === Core References ===
        self.app = app
        self.state = state
        self.visuals = visuals
        self.extraction_manager = None
        
        # === Timer Management ===
        self._visual_update_timer = None
        self._frame_estimate_timer = None
        
        # === State Flags (Prevent Circular Dependencies) ===
        self._settings_loading_in_progress = False
        self._trace_update_in_progress = False
        self._last_video_switch_time = 0
        
        # === Selection Tracking ===
        self._last_video_selection = {'index': None, 'path': None, 'timestamp': None}
        self._last_folder_selection = {'index': None, 'path': None, 'timestamp': None}
        self._current_active_queue = None

        # self._expected_extraction_method = None  # ❌ UNUSED
        # self._last_interaction_timestamp = None  # ❌ UNUSED
        
        # === Debug System ===
        self.debug_enabled = False
        self.trace_log = []



    # --- debugging ---
    def debug_extraction_cache_for_pipeline(self, video_path):
        """
        DEBUG: Check extraction cache status for pipeline processing.
        Call this from the pipeline worker before processing each video.
        """
        print(f"\n🔍 PIPELINE CACHE DEBUG for {os.path.basename(video_path)}:")
        
        # Check if extraction manager exists and is properly configured
        if not hasattr(self, 'extraction_manager') or not self.extraction_manager:
            print("❌ No extraction manager available")
            return False
        
        # Check if this video has a cache entry
        if video_path not in self.state.extraction_frame_cache:
            print("❌ No cache entry in extraction_frame_cache")
            return False
        
        cache_entry = self.state.extraction_frame_cache[video_path]
        print(f"✅ Cache entry found:")
        print(f"   Valid: {cache_entry.get('cache_valid', False)}")
        print(f"   Total frames: {cache_entry.get('total_frames', 0)}")
        print(f"   Content type: {cache_entry.get('content_type', 'unknown')}")
        
        # Temporarily set extraction manager to this video and try to get frames
        original_path = self.extraction_manager.current_video_path
        try:
            self.extraction_manager.current_video_path = video_path
            cached_frames = self.extraction_manager.get_cached_frames_for_pipeline()
            print(f"   Retrieved frames: {len(cached_frames)}")
            return len(cached_frames) > 0
        except Exception as e:
            print(f"❌ Error retrieving cached frames: {e}")
            return False
        finally:
            self.extraction_manager.current_video_path = original_path

    def debug_pipeline_settings_and_cache(self, item_path, item_type):
        """
        DEBUG: Print detailed information about settings and cache for an item.
        Call this before processing each item in the pipeline.
        """
        print(f"\n🔍 DEBUGGING PIPELINE ITEM: {os.path.basename(item_path)}")
        print(f"   Item type: {item_type}")
        
        # Check cached settings
        if item_path in self.state.per_video_settings_cache:
            cached = self.state.per_video_settings_cache[item_path]
            print(f"   ✅ Has cached settings:")
            print(f"      Extraction method: {cached.get('extraction_method', 'N/A')}")
            print(f"      Frame count: {cached.get('frame_count', 'N/A')}")
            print(f"      Interval: {cached.get('interval_value', 'N/A')} {cached.get('interval_unit', 'N/A')}")
        else:
            print(f"   ❌ No cached settings found")
        
        # Check cached frames
        if item_type == 'video' and item_path in self.state.extraction_frame_cache:
            cache_entry = self.state.extraction_frame_cache[item_path]
            print(f"   ✅ Has frame cache:")
            print(f"      Cache valid: {cache_entry.get('cache_valid', False)}")
            print(f"      Total frames: {cache_entry.get('total_frames', 0)}")
            print(f"      Content type: {cache_entry.get('content_type', 'unknown')}")
        else:
            print(f"   ❌ No frame cache found")
        
        # Check current UI settings
        current_settings = self.app.get_current_settings()
        print(f"   🎛️ Current UI settings:")
        print(f"      Extraction method: {current_settings.get('extraction_method', 'N/A')}")
        print(f"      Frame count: {current_settings.get('frame_count', 'N/A')}")
        print(f"      Interval: {current_settings.get('interval_value', 'N/A')} {current_settings.get('interval_unit', 'N/A')}")
        
        print(f"{'='*60}")

    def on_extraction_settings_change(self, *args):
        """FIXED: Handle extraction settings changes without circular loops."""
        print(f"🔍 TRACE FIRED: loading={self._settings_loading_in_progress}, updating={self._trace_update_in_progress}")
        
        # Ignore if we're currently loading settings
        if self._settings_loading_in_progress:
            print("⏭️ Ignoring trace - settings loading in progress")
            return
            
        # Ignore if we're already processing a trace update
        if self._trace_update_in_progress:
            print("⏭️ Ignoring trace - update already in progress")
            return
            
        print("✅ Processing user input trace")
        self._trace_update_in_progress = True
        
        try:
            # Notify extraction manager of settings change
            if self.extraction_manager:
                self.extraction_manager.on_extraction_settings_change()
            
            # Update frame estimate with slight delay
            print("⏰ Scheduling frame estimate update in 10ms")
            self.app.root.after(10, self._debounced_frame_estimate_update)
            
        finally:
            # Reset flag after a delay to prevent rapid firing
            self.app.root.after(100, lambda: setattr(self, '_trace_update_in_progress', False))

    def debug_cache_performance(self):
        """Comprehensive cache performance analysis."""
        import time
        import sys
        
        print("\n🔍 CACHE PERFORMANCE ANALYSIS:")
        print("="*60)
        
        # Video Info Cache Analysis
        video_cache = self.state.video_info_cache
        print(f"📹 VIDEO INFO CACHE:")
        print(f"  Size: {len(video_cache)} entries")
        
        if video_cache:
            # Calculate memory usage estimate
            total_keys_length = sum(len(key) for key in video_cache.keys())
            total_values_size = sum(len(str(value)) for value in video_cache.values())
            
            print(f"  Key length total: {total_keys_length} chars")
            print(f"  Values size estimate: {total_values_size} chars")
            print(f"  Average key length: {total_keys_length/len(video_cache):.1f} chars")
            
            # Show cache contents
            print(f"  Cache entries:")
            for i, (key, value) in enumerate(video_cache.items()):
                duration = value.get('duration', 'N/A')
                fps = value.get('fps', 'N/A')
                print(f"    [{i}] {key[-50:]}... → Duration:{duration}, FPS:{fps}")
                if i >= 5:  # Limit output
                    print(f"    ... and {len(video_cache)-6} more entries")
                    break
        
        # Preview Cache Analysis
        preview_cache = self.state.preview_image_cache
        print(f"\n🖼️ PREVIEW IMAGE CACHE:")
        print(f"  Size: {len(preview_cache)} entries")
        print(f"  Max size: {getattr(self.state, 'cache_max_size', 'Unknown')}")
        
        if preview_cache:
            # Check file existence and sizes
            total_file_size = 0
            missing_files = 0
            
            for cache_key, file_path in preview_cache.items():
                try:
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        total_file_size += file_size
                    else:
                        missing_files += 1
                except Exception:
                    missing_files += 1
            
            print(f"  Total disk usage: {total_file_size/1024/1024:.1f} MB")
            print(f"  Missing files: {missing_files}")
            
            # Show recent entries
            preview_items = list(preview_cache.items())[:3]
            for i, (key, path) in enumerate(preview_items):
                exists = "✅" if os.path.exists(path) else "❌"
                print(f"    [{i}] {key[:30]}... → {exists} {os.path.basename(path)}")
        
        # Content Cache Analysis  
        content_cache = getattr(self.state, 'content_cache', {})
        print(f"\n📦 CONTENT CACHE:")
        print(f"  Size: {len(content_cache)} entries")
        
        # Cache Stats
        cache_stats = getattr(self.state, 'cache_stats', {})
        print(f"\n📊 CACHE STATISTICS:")
        for stat_name, stat_value in cache_stats.items():
            print(f"  {stat_name}: {stat_value}")
        
        # Memory usage estimate
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            print(f"\n💾 PROCESS MEMORY: {memory_mb:.1f} MB")
        except ImportError:
            print(f"\n💾 PROCESS MEMORY: Install psutil for memory info")
        
        print("="*60)

    def benchmark_cache_operations(self):
        """Benchmark cache read/write performance."""
        import time
        
        print("\n⏱️ CACHE PERFORMANCE BENCHMARK:")
        print("="*50)
        
        # Test video info cache performance
        if self.state.video_queue:
            video_path = self.state.video_queue[0]
            cache_key = f"video_info_{video_path}"
            
            # Test cache read speed
            start_time = time.time()
            for i in range(100):
                _ = self.state.video_info_cache.get(cache_key)
            read_time = time.time() - start_time
            
            print(f"📹 Video Info Cache:")
            print(f"  100 reads: {read_time*1000:.2f}ms ({read_time*10:.2f}ms per read)")
            
            # Test cache write speed
            test_data = {'duration': 120.0, 'fps': 30.0, 'test': True}
            start_time = time.time()
            for i in range(100):
                self.state.video_info_cache[f"test_key_{i}"] = test_data.copy()
            write_time = time.time() - start_time
            
            print(f"  100 writes: {write_time*1000:.2f}ms ({write_time*10:.2f}ms per write)")
            
            # Cleanup test data
            for i in range(100):
                self.state.video_info_cache.pop(f"test_key_{i}", None)
        
        # Test string operations that might slow down cache
        long_path = "C:/Very/Long/Path/That/Might/Cause/Performance/Issues/video.mp4"
        start_time = time.time()
        for i in range(1000):
            _ = f"video_info_{long_path}"
        string_time = time.time() - start_time
        
        print(f"🔤 String Operations:")
        print(f"  1000 key generations: {string_time*1000:.2f}ms")
        
        print("="*50)

    def debug_cache_timing(self, operation_name):
        """Decorator-style timing for cache operations."""
        import time
        start_time = time.time()
        
        def end_timing():
            elapsed = (time.time() - start_time) * 1000
            if elapsed > 10:  # Only log if > 10ms
                self.debug_trace("CACHE_TIMING", f"{operation_name}: {elapsed:.1f}ms")
        
        return end_timing
    
    def debug_trace(self, method_name, details="", **kwargs):
        """Simple debug tracing."""
        if not self.debug_enabled:
            return
            
        timestamp = time.time()
        trace_entry = {
            'timestamp': timestamp,
            'method': method_name,
            'details': details,
            'thread': threading.current_thread().name,
            **kwargs
        }
        self.trace_log.append(trace_entry)
        print(f"🔍 {method_name}: {details}")

    def save_debug_log(self, filename="debug_trace.txt"):
        """Save debug log to file."""
        try:
            with open(filename, 'w') as f:
                f.write("DEBUG TRACE LOG\n")
                f.write("="*50 + "\n")
                for entry in self.trace_log:
                    f.write(f"{entry['timestamp']:.3f}: {entry['method']} - {entry['details']}\n")
            print(f"✅ Debug log saved to {filename}")
        except Exception as e:
            print(f"❌ Failed to save debug log: {e}")

    def debug_multi_queue_state(self):
        """ENHANCED: Complete multi-queue state debugging."""
        print("\n🔍 MULTI-QUEUE STATE DEBUG:")
        print("="*60)
        
        import time
        current_time = time.time()
        
        # Video queue state
        print(f"📹 VIDEO QUEUE ({len(self.state.video_queue)} items):")
        for i, video_path in enumerate(self.state.video_queue):
            video_name = os.path.basename(video_path)
            markers = []
            
            if i in self.app.video_listbox.curselection():
                markers.append("🔵 UI_SELECTED")
            if i == self._last_video_selection.get('index'):
                age = current_time - (self._last_video_selection.get('timestamp') or 0)
                markers.append(f"👤 USER_CHOICE({age:.1f}s ago)")
            if not markers:
                markers.append("⚪")
                
            print(f"  [{i}] {video_name} {' '.join(markers)}")
        
        # Folder queue state
        print(f"\n📁 FOLDER QUEUE ({len(self.state.image_folder_queue)} items):")
        for i, folder_path in enumerate(self.state.image_folder_queue):
            folder_name = os.path.basename(folder_path)
            markers = []
            
            if i in self.app.image_folder_listbox.curselection():
                markers.append("🔵 UI_SELECTED")
            if i == self._last_folder_selection.get('index'):
                age = current_time - (self._last_folder_selection.get('timestamp') or 0)
                markers.append(f"👤 USER_CHOICE({age:.1f}s ago)")
            if not markers:
                markers.append("⚪")
                
            print(f"  [{i}] {folder_name} {' '.join(markers)}")
        
        # Current state
        print(f"\n🎯 CURRENT STATE:")
        print(f"  Active Queue: {self._current_active_queue}")
        print(f"  Last Video Selection: {self._last_video_selection}")
        print(f"  Last Folder Selection: {self._last_folder_selection}")
        
        # Display state
        print(f"\n📺 DISPLAY STATE:")
        print(f"  Content Info: '{self.state.content_info_var.get()}'")
        print(f"  Content Details: '{self.state.content_details_var.get()}'")
        
        print("="*60)

    def test_queue_switching_scenarios(self):
        """Test various queue switching scenarios."""
        print("\n🧪 TESTING QUEUE SWITCHING SCENARIOS:")
        print("="*50)
        
        # Save current state
        original_video_sel = self.app.video_listbox.curselection()
        original_folder_sel = self.app.image_folder_listbox.curselection()
        
        scenarios = [
            "Clear all selections (simulate field interaction)",
            "Test smart restoration", 
            "Verify correct queue is restored"
        ]
        
        for i, scenario in enumerate(scenarios, 1):
            print(f"\nTest {i}: {scenario}")
            
            if i == 1:
                # Clear all selections
                self.app.video_listbox.selection_clear(0, tk.END)
                self.app.image_folder_listbox.selection_clear(0, tk.END)
                print(f"  Cleared all selections")
                
            elif i == 2:
                # Test restoration
                success = self._smart_restore_last_selection()
                print(f"  Restoration success: {success}")
                print(f"  Active queue after restore: {self._current_active_queue}")
                
            elif i == 3:
                # Verify results
                new_video_sel = self.app.video_listbox.curselection()
                new_folder_sel = self.app.image_folder_listbox.curselection()
                
                print(f"  Original video: {list(original_video_sel) if original_video_sel else 'None'}")
                print(f"  Restored video: {list(new_video_sel) if new_video_sel else 'None'}")
                print(f"  Original folder: {list(original_folder_sel) if original_folder_sel else 'None'}")
                print(f"  Restored folder: {list(new_folder_sel) if new_folder_sel else 'None'}")
                
                # Determine success
                if original_video_sel and new_video_sel and original_video_sel[0] == new_video_sel[0]:
                    print("  ✅ SUCCESS: Video selection correctly restored")
                elif original_folder_sel and new_folder_sel and original_folder_sel[0] == new_folder_sel[0]:
                    print("  ✅ SUCCESS: Folder selection correctly restored")
                elif not original_video_sel and not original_folder_sel:
                    print("  ℹ️  INFO: No original selection to restore")
                else:
                    print("  ❌ FAIL: Selection not restored correctly")
        
        print("="*50)

    def debug_cache_state(self):
        """Debug the cache corruption issue."""
        print("\n🔍 CACHE CORRUPTION DIAGNOSTIC:")
        print("="*50)
        
        if self.state.video_queue and self.app.video_listbox.curselection():
            video_path = self.state.video_queue[self.app.video_listbox.curselection()[0]]
            cache_key = f"video_info_{video_path}"
            
            print(f"📹 Current video: {os.path.basename(video_path)}")
            print(f"🔑 Cache key: {cache_key}")
            print(f"💾 Cache exists: {cache_key in self.state.video_info_cache}")
            
            if cache_key in self.state.video_info_cache:
                video_info = self.state.video_info_cache[cache_key]
                print(f"📊 Cache content: {video_info}")
                print(f"✅ Cache valid: {self._is_video_info_valid(video_info)}")
                
                if video_info:
                    duration = video_info.get('duration')
                    fps = video_info.get('fps')
                    print(f"⏱️  Duration: {duration}")
                    print(f"🎬 FPS: {fps}")
            
            # Test if we can recover
            print("\n🔧 Testing cache recovery...")
            if self._recover_video_info_cache(video_path):
                print("✅ Cache recovery successful")
            else:
                print("❌ Cache recovery failed")
        
        print("="*50)

    def debug_variable_change(self, var_name, new_value, exception=None):
        """Track variable changes."""
        if not self.debug_enabled:
            return
            
        status = f"ERROR: {exception}" if exception else "OK"
        self.debug_trace("VAR_CHANGE", f"{var_name} = {new_value} ({status})", 
                        variable=var_name, value=new_value, error=exception)

    def debug_cache_operation(self, operation, key, success=True, details=""):
        """Track cache operations."""
        if not self.debug_enabled:
            return
            
        status = "SUCCESS" if success else "FAILED"
        self.debug_trace("CACHE", f"{operation} {key} - {status} {details}",
                        operation=operation, key=key, success=success)

    def debug_display_state_with_cache(self):
        """Enhanced display state with cache performance info."""
        # Call the basic debug first
        self.debug_display_state()
        
        # Then add cache analysis
        self.debug_cache_performance()

    def debug_display_state(self):
        """Debug current display state - call this anytime."""
        print("\n🔍 DISPLAY STATE DEBUG:")
        print("="*50)
        try:
            print(f"Content Info: '{self.state.content_info_var.get()}'")
            print(f"Content Details: '{self.state.content_details_var.get()}'")
        except Exception as e:
            print(f"Error reading display vars: {e}")
        
        if self.state.video_queue and self.app.video_listbox.curselection():
            try:
                video_path = self.state.video_queue[self.app.video_listbox.curselection()[0]]
                cache_key = f"video_info_{video_path}"
                video_info = self.state.video_info_cache.get(cache_key, {})
                
                print(f"Video: {os.path.basename(video_path)}")
                print(f"Cache Valid: {self._is_video_info_valid(video_info)}")
                
                if video_info:
                    duration = video_info.get('duration', 'N/A')
                    fps = video_info.get('fps', 'N/A')
                    print(f"Cached Duration: {duration}, FPS: {fps}")
            except Exception as e:
                print(f"Error reading video info: {e}")
        
        try:
            extraction_method = self.app.extraction_method_var.get()
            print(f"Extraction Method: {extraction_method}")
            
            if extraction_method == "count":
                frame_count = self.app.frame_count_var.get()
                print(f"Frame Count: {frame_count} (type: {type(frame_count)})")
            else:
                interval_value = self.app.interval_value_var.get()
                interval_unit = self.app.interval_unit_var.get()
                print(f"Interval: {interval_value} {interval_unit} (type: {type(interval_value)})")
                
            print(f"Inputs Valid: {self._are_extraction_inputs_valid()}")
        except Exception as e:
            print(f"Error reading input fields: {e}")
        
        print(f"Timer Active: {self._frame_estimate_timer is not None}")
        print(f"Debug Log Entries: {len(self.trace_log)}")
        print("="*50)

    # --- Cache handling ---
    def _manage_cache_size(self):
        """Manage cache size to prevent unlimited growth."""
        if len(self.state.preview_image_cache) <= self.state.cache_max_size:
            return
        
        print(f"🧹 Cache size ({len(self.state.preview_image_cache)}) exceeds limit ({self.state.cache_max_size}), cleaning up...")
        
        # Get file modification times to find oldest cached files
        cache_items = []
        for cache_key, file_path in self.state.preview_image_cache.items():
            if os.path.exists(file_path):
                mtime = os.path.getmtime(file_path)
                cache_items.append((mtime, cache_key, file_path))
            else:
                # File doesn't exist, mark for removal
                cache_items.append((0, cache_key, file_path))
        
        # Sort by modification time (oldest first)
        cache_items.sort(key=lambda x: x[0])
        
        # Remove oldest items
        items_to_remove = len(cache_items) - self.state.cache_max_size + 5  # Remove a few extra
        
        for i in range(items_to_remove):
            mtime, cache_key, file_path = cache_items[i]
            
            # Remove from cache
            del self.state.preview_image_cache[cache_key]
            
            # Delete file if it exists
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"   Removed: {os.path.basename(file_path)}")
                except Exception as e:
                    print(f"   Failed to remove {file_path}: {e}")
        
        print(f"✅ Cache cleaned. Size: {len(self.state.preview_image_cache)}")

    def _get_preview_cache_dir(self):
        """Get the preview cache directory."""
        if self.state.project_dir.get():
            # Use project directory if set
            cache_dir = os.path.join(self.state.project_dir.get(), ".splatpipe_cache", "previews")
        else:
            # Use user's cache directory
            import tempfile
            cache_dir = os.path.join(tempfile.gettempdir(), "splatpipe_cache", "previews")
        
        return cache_dir
    
    def maintenance_cleanup_cache(self):
        """Periodic cache maintenance - call this occasionally."""
        print("🧹 Running cache maintenance...")
        
        # Clean up orphaned preview files
        cache_dir = self._get_preview_cache_dir()
        if os.path.exists(cache_dir):
            cached_files = set(self.state.preview_image_cache.values())
            actual_files = set(os.path.join(cache_dir, f) for f in os.listdir(cache_dir))
            
            orphaned_files = actual_files - cached_files
            for orphan in orphaned_files:
                try:
                    os.remove(orphan)
                    print(f"   Removed orphaned file: {os.path.basename(orphan)}")
                except Exception as e:
                    print(f"   Failed to remove {orphan}: {e}")
        
        # Clean up stale video info cache
        valid_videos = set(self.state.video_queue)
        stale_keys = [k for k in self.state.video_info_cache.keys() 
                    if k.startswith('video_info_') and 
                        k.replace('video_info_', '') not in valid_videos]
        
        for key in stale_keys:
            del self.state.video_info_cache[key]
        
        print(f"✅ Cache maintenance complete. Removed {len(stale_keys)} stale entries.")

    def get_enhanced_cache_stats(self):
        """Enhanced cache statistics with performance metrics."""
        total_requests = self.state.cache_stats['hits'] + self.state.cache_stats['misses']
        hit_rate = (self.state.cache_stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        # Calculate cache efficiency
        preview_cache_size_mb = 0
        cache_dir = self._get_preview_cache_dir()
        if os.path.exists(cache_dir):
            for file in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, file)
                if os.path.isfile(file_path):
                    preview_cache_size_mb += os.path.getsize(file_path)
            preview_cache_size_mb = preview_cache_size_mb / (1024 * 1024)  # Convert to MB
        
        return {
            'preview_cache_entries': len(self.state.preview_image_cache),
            'preview_cache_size_mb': f"{preview_cache_size_mb:.1f} MB",
            'content_cache_entries': len(getattr(self.state, 'content_cache', {})),
            'cache_hit_rate': f"{hit_rate:.1f}%",
            'extractions_saved': self.state.cache_stats['extractions_saved'],
            'estimated_time_saved': f"{self.state.cache_stats['extractions_saved'] * 2:.1f} seconds",
            'cache_directory': cache_dir
        }

    def clear_preview_cache(self):
        """Clear the preview image cache and delete cached files."""
        cache_dir = self._get_preview_cache_dir()   
        # Remove files
        removed_count = 0
        for cache_key, file_path in list(self.state.preview_image_cache.items()):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    removed_count += 1
            except Exception as e:
                print(f"Error removing cached file {file_path}: {e}")    
        # Clear cache dictionary
        self.state.preview_image_cache.clear()     
        # Try to remove cache directory if empty
        try:
            if os.path.exists(cache_dir) and not os.listdir(cache_dir):
                os.rmdir(cache_dir)
        except Exception:
            pass   
        print(f"✅ Preview cache cleared. Removed {removed_count} files.")       
        # Update cache stats
        self.state.cache_stats = {'hits': 0, 'misses': 0, 'extractions_saved': 0}

    def _recover_video_info_cache(self, video_path):
        """Emergency function to recover corrupted cache."""
        cache_key = f"video_info_{video_path}"
        
        try:
            print(f"🔄 Recovering cache for {os.path.basename(video_path)}")
            import video_extraction
            video_info = video_extraction.get_video_info(video_path, self.app.ffmpeg_path_var.get())
            
            if self._is_video_info_valid(video_info):
                self.state.video_info_cache[cache_key] = video_info
                print("✅ Cache recovered successfully")
                return True
            else:
                print("❌ Could not recover valid video info")
                return False
                
        except Exception as e:
            print(f"❌ Cache recovery failed: {e}")
            return False

    def _debounced_save_per_video_settings(self, *args):
        """Debounces the saving action for any content editing."""
        if self._frame_estimate_timer:
            self.app.root.after_cancel(self._frame_estimate_timer)
        self._frame_estimate_timer = self.app.root.after(750, lambda: self._debounced_save_per_video_settings(self._get_active_content_path()))

    def _load_settings_from_cache(self, content_path):
        """FIXED: Extraction method restoration with proper UI synchronization."""
        cached_settings = self.state.per_video_settings_cache.get(content_path)
        
        if not cached_settings:
            print(f"ⓘ No cached settings found for: {os.path.basename(content_path)}")
            return
        
        extraction_method = cached_settings.get('extraction_method', 'interval')
        print(f"⚙️ Restoring settings for: {os.path.basename(content_path)}")
        print(f"   📋 Cached extraction method: {extraction_method}")
        
        # === CRITICAL FIX: Prevent circular updates ===
        self._settings_loading_in_progress = True
        
        try:
            # Disable ALL traces temporarily
            self.app._disable_all_visual_traces()
            
            # === STEP 1: Set extraction method FIRST ===
            print(f"   🔧 Setting extraction method to: {extraction_method}")
            self.app.extraction_method_var.set(extraction_method)
            
            # === STEP 2: Immediately update UI to show correct method ===
            self.app._update_extraction_ui()
            
            # === STEP 3: Set values based on method ===
            if extraction_method == 'count':
                frame_count = cached_settings.get('frame_count', 30)
                print(f"   🔧 Setting frame count to: {frame_count}")
                self.app.frame_count_var.set(frame_count)
            else:  # interval method
                interval_value = cached_settings.get('interval_value', 1.0)
                interval_unit = cached_settings.get('interval_unit', 'seconds')
                print(f"   🔧 Setting interval to: {interval_value} {interval_unit}")
                self.app.interval_value_var.set(interval_value)
                self.app.interval_unit_var.set(interval_unit)
            
            # === STEP 4: Set other settings ===
            self.app.pitch_angles_str_var.set(cached_settings.get('pitch_angles_str', '-50, -7'))
            self.app.yaw_steps_var.set(cached_settings.get('yaw_steps', '6'))
            self.app.fov_var.set(cached_settings.get('fov', '94.6'))
            self.app.overlay_opacity_var.set(cached_settings.get('overlay_opacity', 0.6))
            self.app.frame_format_var.set(cached_settings.get('frame_format', 'jpg'))
            
            # === STEP 5: Force UI update again after all values are set ===
            self.app.root.update_idletasks()  # Force immediate UI refresh
            self.app._update_extraction_ui()  # Ensure UI matches the method
            
            # === STEP 6: Delayed completion with verification ===
            # PASS extraction_method as parameter to the completion method
            self.app.root.after(100, lambda: self._finish_settings_load(expected_method=extraction_method))
            
        except Exception as e:
            print(f"❌ Error loading settings: {e}")
            self._settings_loading_in_progress = False
            self.app._enable_all_visual_traces()

    def _finish_settings_load(self, expected_method):
        """FIXED: Complete settings loading with verification that method was restored."""
        try:
            # === VERIFICATION: Check if method was actually restored ===
            actual_method = self.app.extraction_method_var.get()
            
            if actual_method != expected_method:
                print(f"❌ EXTRACTION METHOD RESTORE FAILED!")
                print(f"   Expected: {expected_method}")
                print(f"   Actual: {actual_method}")
                print(f"   🔧 Attempting forced restoration...")
                
                # Force set again
                self.app.extraction_method_var.set(expected_method)
                self.app._update_extraction_ui()
                self.app.root.update_idletasks()
                
                # Check again
                final_method = self.app.extraction_method_var.get()
                print(f"   Final result: {final_method}")
            else:
                print(f"✅ Extraction method correctly restored: {actual_method}")
            
            self._settings_loading_in_progress = False
            self.app._enable_all_visual_traces()
            
            # Force immediate frame estimation update
            self.app.root.after(50, self._update_frame_estimate)
            print("✅ Settings loading completed with verification")
            
        except Exception as e:
            print(f"❌ Error in settings verification: {e}")
            self._settings_loading_in_progress = False
            self.app._enable_all_visual_traces()


    # --- Queue Management Callbacks ---
    def add_videos(self):
        """ENHANCED: Add videos with optional preview preloading."""
        files = filedialog.askopenfilenames(title="Select Video Files", filetypes=[("Video files", "*.mp4 *.mov *.avi")])
        if files:
            added_count = 0
            for f in files:
                if f not in self.state.video_queue:
                    self.state.video_queue.append(f)
                    self.app.video_listbox.insert(tk.END, os.path.basename(f))
                added_count += 1
            
            print(f"✅ Added {added_count} video(s) to queue")
            
            if self.state.video_queue:
                last_index = self.app.video_listbox.size() - 1
                self.app.video_listbox.selection_clear(0, tk.END)
                self.app.video_listbox.selection_set(last_index)
                self.app.video_listbox.see(last_index)
                self.on_video_select()

            # Preload previews for all queued videos in background
            #self._preload_video_previews_async()
            # UPDATE: Dynamic status and progress bar update
            self.app.update_queue_status_and_progress_bars()
        
    def _preload_video_previews_async(self):
        """FIXED: Smart preloading that respects video mode."""
        def preload_worker():
            # Check which videos need preloading vs are in video mode
            videos_to_preload = []
                   
            # Only preload videos that actually need it
            if videos_to_preload:
                print(f"🚀 Preloading {len(videos_to_preload)} videos (excluding video mode)")
                
                for video_path in videos_to_preload:
                    print(f"🔄 Preloading preview: {os.path.basename(video_path)}")
                    try:
                        self.preview_first_frame_of_video(video_path)
                    except Exception as e:
                        print(f"❌ Preload failed for {video_path}: {e}")
            else:
                print(f"✅ No preloading needed - all videos cached or in video mode")
        
        # Start preloading thread
        threading.Thread(target=preload_worker, daemon=True).start()

    def preview_first_frame_of_video(self, video_path):
        """ENHANCED: Cache extracted preview frames to avoid repeated FFmpeg calls."""

        # Check if we already have this preview cached
        cache_key = f"preview_{video_path}"
        
        if cache_key in self.state.preview_image_cache:
            print(f"✅ Using cached preview for {os.path.basename(video_path)}")
            self.state.cache_stats['hits'] += 1
            self.state.cache_stats['extractions_saved'] += 1
            
            # Use cached preview path
            cached_preview_path = self.state.preview_image_cache[cache_key]
            
            # Verify cached file still exists
            if os.path.exists(cached_preview_path):
                self.visuals._initiate_new_preview(cached_preview_path)
                return
            else:
                # Cache is stale, remove entry
                print(f"⚠️  Cached preview file missing, re-extracting...")
                del self.state.preview_image_cache[cache_key]
        
        # Cache miss - need to extract frame
        print(f"🔄 Extracting preview for {os.path.basename(video_path)}")
        self.state.cache_stats['misses'] += 1
        
        # Create persistent cache directory (not temp)
        cache_dir = self._get_preview_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        
        # Generate cache-friendly filename
        video_hash = hashlib.md5(video_path.encode()).hexdigest()[:12]
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        safe_name = "".join(c for c in video_name if c.isalnum() or c in '-_')[:30]
        preview_filename = f"{safe_name}_{video_hash}_preview.png"
        preview_path = os.path.join(cache_dir, preview_filename)
        
        try:
            # Extract first frame using FFmpeg
            ffmpeg_cmd = [
                self.app.ffmpeg_path_var.get(), 
                "-i", video_path, 
                "-vframes", "1", 
                "-q:v", "2",  # High quality
                "-y", preview_path
            ]
            
            result = subprocess.run(
                ffmpeg_cmd, 
                check=True, 
                capture_output=True, 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=30  # Prevent hanging
            )
            
            # Cache the extracted preview
            self.state.preview_image_cache[cache_key] = preview_path
            self._manage_cache_size()  # Prevent cache from growing too large
            
            print(f"✅ Preview extracted and cached: {preview_filename}")
            self.visuals._initiate_new_preview(preview_path)
            
        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout", f"Preview extraction timed out for {os.path.basename(video_path)}")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("FFmpeg Error", f"Could not extract preview:\n{e.stderr}")
        except Exception as e:
            messagebox.showerror("Preview Error", f"Unexpected error during preview extraction:\n{e}")

    def remove_selected_video(self):
        """ENHANCED: Remove videos with dynamic status updates."""
        indices = self.app.video_listbox.curselection()
        if not indices: 
            return
            
        removed_count = 0
        for i in sorted(indices, reverse=True):
            removed_path = self.state.video_queue.pop(i)
            self.app.video_listbox.delete(i)
            # Use shared cache:
            #self.state.video_info_cache.pop(f"video_info_{removed_path}", None)

            removed_count += 1
            
        print(f"🗑️ Removed {removed_count} video(s) from queue")
        
        self._update_preview_to_top_item()
        
        # UPDATE: Dynamic status and progress bar update
        self.app.update_queue_status_and_progress_bars()

    def clear_video_queue(self):
        """
        MODIFIED: Now correctly triggers a full UI and cache reset
        if both queues become empty.
        """
        cleared_count = len(self.state.video_queue)
        self.app.video_listbox.delete(0, tk.END)
        self.state.video_queue.clear()
        print(f"🧹 Cleared {cleared_count} video(s) from queue")

        # If both queues are now empty, perform a master reset.
        if not self.state.video_queue and not self.state.image_folder_queue:
            self._reset_all_previews_and_caches()
        
        self.app.update_queue_status_and_progress_bars()

    def clear_folder_queue(self):
        """
        MODIFIED: Now correctly triggers a full UI and cache reset
        if both queues become empty.
        """
        cleared_count = len(self.state.image_folder_queue)
        self.app.image_folder_listbox.delete(0, tk.END)
        self.state.image_folder_queue.clear()
        print(f"🧹 Cleared {cleared_count} folder(s) from queue")

        # If both queues are now empty, perform a master reset.
        if not self.state.video_queue and not self.state.image_folder_queue:
            self._reset_all_previews_and_caches()

        self.app.update_queue_status_and_progress_bars()

    def add_image_folder(self):
        """ENHANCED: Add folders with dynamic status updates."""
        folder = filedialog.askdirectory(title="Select an Image Folder")
        if folder:
            if folder not in self.state.image_folder_queue:
                self.state.image_folder_queue.append(folder)
                self.app.image_folder_listbox.insert(tk.END, os.path.basename(folder))
                print(f"✅ Added folder to queue: {os.path.basename(folder)}")
            else:
                print(f"⚠️ Folder already in queue: {os.path.basename(folder)}")
                
            if self.state.image_folder_queue:
                self.app.image_folder_listbox.selection_clear(0, tk.END)
                self.app.image_folder_listbox.selection_set(tk.END)
                self.app.image_folder_listbox.see(tk.END)
                self.on_image_folder_select()
        
        # UPDATE: Dynamic status and progress bar update
        self.app.update_queue_status_and_progress_bars()

    def remove_selected_folder(self):
        """ENHANCED: Remove folders with dynamic status updates."""
        indices = self.app.image_folder_listbox.curselection()
        if not indices: 
            return
            
        removed_count = 0
        for i in sorted(indices, reverse=True):
            removed_path = self.state.image_folder_queue.pop(i)
            self.app.image_folder_listbox.delete(i)
            removed_count += 1
            
        print(f"🗑️ Removed {removed_count} folder(s) from queue")
        
        self._update_preview_to_top_item()
        
        # UPDATE: Dynamic status and progress bar update
        self.app.update_queue_status_and_progress_bars()

    def on_video_select(self, event=None):
        """FIXED: Handles video selection with proper trace management."""
        if not self.app.video_listbox.curselection(): 
            return
        
        import time
        current_time = time.time()
        
        # Prevent rapid video switching issues
        if current_time - self._last_video_switch_time < 0.1:
            print("⚠️ Rapid video switching detected, ignoring")
            return
        self._last_video_switch_time = current_time
        
        previous_content_path = self._get_active_content_path()
        new_video_index = self.app.video_listbox.curselection()[0]
        new_video_path = self.state.video_queue[new_video_index]

        print(f"🎯 Video selection: {os.path.basename(new_video_path)}")

        # === CRITICAL: Save previous settings BEFORE switching ===
        if (previous_content_path and 
            previous_content_path != new_video_path and 
            not self._settings_loading_in_progress):
            
            print(f"💾 Saving settings for previous video: {os.path.basename(previous_content_path)}")
            self._save_settings_for_content(previous_content_path)
            
        # Clear other selections
        self.app.image_folder_listbox.selection_clear(0, tk.END)
        
        # === CRITICAL: Load settings for new video ===
        cached_settings = self.state.per_video_settings_cache.get(new_video_path)
        if cached_settings:
            print(f"⚙️ Found cached settings for: {os.path.basename(new_video_path)}")
            print(f"   Extraction method: {cached_settings.get('extraction_method', 'unknown')}")
            self._load_settings_from_cache(new_video_path)
        else:
            print(f"ⓘ No cached settings for: {os.path.basename(new_video_path)} - using current UI settings")
        
        # Update tracking
        self._last_video_selection = {
            'index': new_video_index, 
            'path': new_video_path, 
            'timestamp': current_time
        }
        self._current_active_queue = 'video'

        # This is the correct signature for the button
        if hasattr(self.app, 'extraction_button') and self.app.extraction_button:
            self.app.extraction_button.config(state='normal', text='Extract Frames')

        # Update extraction manager
        if self.extraction_manager:
            if self.extraction_manager.on_video_selected(new_video_path):
                # Force immediate content info update
                self.app.root.after(10, self._update_content_info_display)
        
    def on_extraction_settings_change(self, *args):
        """FIXED: Handle extraction settings changes without circular loops."""
        # Ignore if we're currently loading settings
        if self._settings_loading_in_progress:
            return
            
        # Ignore if we're already processing a trace update
        if self._trace_update_in_progress:
            return
            
        self._trace_update_in_progress = True
        
        try:
            # Notify extraction manager of settings change
            if self.extraction_manager:
                self.extraction_manager.on_extraction_settings_change()
            
            # Update frame estimate with slight delay
            self.app.root.after(10, self._debounced_frame_estimate_update)
            
        finally:
            # Reset flag after a delay to prevent rapid firing
            self.app.root.after(100, lambda: setattr(self, '_trace_update_in_progress', False))
        
    def on_image_folder_select(self, event=None):
        """Handles selecting an image folder, saving the previous state, and loading the new state."""
        if not self.app.image_folder_listbox.curselection(): return

        previous_content_path = self._get_active_content_path()
        new_folder_index = self.app.image_folder_listbox.curselection()[0]
        new_folder_path = self.state.image_folder_queue[new_folder_index]

        if previous_content_path and previous_content_path != new_folder_path:
            self._save_settings_for_content(previous_content_path)

        self.app.video_listbox.selection_clear(0, tk.END)
        self._load_settings_from_cache(new_folder_path)
        
        self._last_folder_selection = {'index': new_folder_index, 'path': new_folder_path, 'timestamp': time.time()}
        self._current_active_queue = 'folder'
        
        # This is the correct signature for the button
        if hasattr(self.app, 'extraction_button') and self.app.extraction_button:
            self.app.extraction_button.config(state='disabled', text='Frames Loaded')

        # This now calls the modern manager instead of the old, legacy function
        if self.extraction_manager:
            self.extraction_manager.on_image_folder_selected(new_folder_path)
            self._update_content_info_display()

    # --- UI Update and Logic Callbacks ---

    def _get_active_content_path(self):
        """
        Reliably gets the path of the currently active content (video or folder).
        """
        if self._current_active_queue == 'video':
            # Fallback to the last clicked video if listbox focus is lost
            if self.app.video_listbox.curselection():
                return self.state.video_queue[self.app.video_listbox.curselection()[0]]
            return self._last_video_selection.get('path')
        elif self._current_active_queue == 'folder':
            # Fallback to the last clicked folder
            if self.app.image_folder_listbox.curselection():
                return self.state.image_folder_queue[self.app.image_folder_listbox.curselection()[0]]
            return self._last_folder_selection.get('path')
        return None

    def _save_settings_for_content(self, content_path):
        """FIXED: Enhanced settings saving with verification."""
        if not content_path or self._settings_loading_in_progress:
            return
            
        try:
            settings = self.app.get_current_settings()
            self.state.per_video_settings_cache[content_path] = settings
            
            # === DEBUG: Show what was saved ===
            extraction_method = settings.get('extraction_method', 'unknown')
            print(f"💾 Saved settings for: {os.path.basename(content_path)}")
            print(f"   Extraction method: {extraction_method}")
            
            if extraction_method == 'count':
                frame_count = settings.get('frame_count', 'unknown')
                print(f"   Frame count: {frame_count}")
            else:
                interval_value = settings.get('interval_value', 'unknown')
                interval_unit = settings.get('interval_unit', 'unknown')
                print(f"   Interval: {interval_value} {interval_unit}")
                
        except Exception as e:
            print(f"❌ Error saving settings: {e}")

    def _smart_restore_last_selection(self):
        """ENHANCED: Intelligently restore based on what user was actually working with."""
        
        # Determine what the user was most recently working with
        video_time = self._last_video_selection.get('timestamp', 0) or 0
        folder_time = self._last_folder_selection.get('timestamp', 0) or 0
        
        self.debug_trace("RESTORE_ANALYSIS", 
                        f"Video time: {video_time}, Folder time: {folder_time}, "
                        f"Active queue: {self._current_active_queue}")
        
        # Restore based on most recent interaction or current active queue
        if self._current_active_queue == 'video' or (video_time > folder_time and video_time > 0):
            return self._restore_video_selection()
        elif self._current_active_queue == 'folder' or (folder_time > video_time and folder_time > 0):
            return self._restore_folder_selection()
        else:
            # No clear preference, try video first, then folder
            return self._restore_video_selection() or self._restore_folder_selection()
        
    def _restore_video_selection(self):
        """Restore video selection if videos are available."""
        if not self.state.video_queue:
            self.debug_trace("RESTORE_VIDEO", "No videos available")
            return False
        
        video_sel = self._last_video_selection
        
        # Try to restore to exact video user had selected
        if (video_sel['index'] is not None and 
            video_sel['index'] < len(self.state.video_queue) and
            video_sel['path'] and 
            self.state.video_queue[video_sel['index']] == video_sel['path']):
            
            try:
                # Clear folder selection first
                self.app.image_folder_listbox.selection_clear(0, tk.END)
                
                # Restore video selection
                self.app.video_listbox.selection_set(video_sel['index'])
                self._current_active_queue = 'video'
                
                video_name = os.path.basename(video_sel['path'])
                self.debug_trace("RESTORE_VIDEO", f"Restored to video {video_sel['index']}: {video_name}")
                return True
                
            except Exception as e:
                self.debug_trace("RESTORE_VIDEO_FAILED", f"Failed to restore video {video_sel['index']}: {e}")
        
        # Try to find same video by path
        if video_sel['path']:
            try:
                new_index = self.state.video_queue.index(video_sel['path'])
                self.app.image_folder_listbox.selection_clear(0, tk.END)
                self.app.video_listbox.selection_set(new_index)
                self._last_video_selection['index'] = new_index
                self._current_active_queue = 'video'
                self.debug_trace("RESTORE_VIDEO", f"Found video at new index: {new_index}")
                return True
            except (ValueError, Exception) as e:
                self.debug_trace("RESTORE_VIDEO_FAILED", f"Could not find video by path: {e}")
        
        # Fallback to first video
        try:
            self.app.image_folder_listbox.selection_clear(0, tk.END)
            self.app.video_listbox.selection_set(0)
            self._last_video_selection = {
                'index': 0,
                'path': self.state.video_queue[0],
                'timestamp': time.time()
            }
            self._current_active_queue = 'video'
            self.debug_trace("RESTORE_VIDEO", "Fallback: restored to first video")
            return True
        except Exception as e:
            self.debug_trace("RESTORE_VIDEO_FAILED", f"Fallback failed: {e}")
            return False

    def _restore_folder_selection(self):
        """Restore folder selection if folders are available."""
        if not self.state.image_folder_queue:
            self.debug_trace("RESTORE_FOLDER", "No folders available")
            return False
        
        folder_sel = self._last_folder_selection
        
        # Try to restore to exact folder user had selected
        if (folder_sel['index'] is not None and 
            folder_sel['index'] < len(self.state.image_folder_queue) and
            folder_sel['path'] and 
            self.state.image_folder_queue[folder_sel['index']] == folder_sel['path']):
            
            try:
                # Clear video selection first
                self.app.video_listbox.selection_clear(0, tk.END)
                
                # Restore folder selection
                self.app.image_folder_listbox.selection_set(folder_sel['index'])
                self._current_active_queue = 'folder'
                
                folder_name = os.path.basename(folder_sel['path'])
                self.debug_trace("RESTORE_FOLDER", f"Restored to folder {folder_sel['index']}: {folder_name}")
                return True
                
            except Exception as e:
                self.debug_trace("RESTORE_FOLDER_FAILED", f"Failed to restore folder {folder_sel['index']}: {e}")
        
        # Try to find same folder by path
        if folder_sel['path']:
            try:
                new_index = self.state.image_folder_queue.index(folder_sel['path'])
                self.app.video_listbox.selection_clear(0, tk.END)
                self.app.image_folder_listbox.selection_set(new_index)
                self._last_folder_selection['index'] = new_index
                self._current_active_queue = 'folder'
                self.debug_trace("RESTORE_FOLDER", f"Found folder at new index: {new_index}")
                return True
            except (ValueError, Exception) as e:
                self.debug_trace("RESTORE_FOLDER_FAILED", f"Could not find folder by path: {e}")
        
        # Fallback to first folder
        try:
            import time
            self.app.video_listbox.selection_clear(0, tk.END)
            self.app.image_folder_listbox.selection_set(0)
            self._last_folder_selection = {
                'index': 0,
                'path': self.state.image_folder_queue[0],
                'timestamp': time.time()
            }
            self._current_active_queue = 'folder'
            self.debug_trace("RESTORE_FOLDER", "Fallback: restored to first folder")
            return True
        except Exception as e:
            self.debug_trace("RESTORE_FOLDER_FAILED", f"Fallback failed: {e}")
            return False

    def _update_preview_to_top_item(self):
        if self.state.video_queue:
            self.app.video_listbox.selection_set(0)
            self.on_video_select()
        elif self.state.image_folder_queue:
            self.app.image_folder_listbox.selection_set(0)
            self.on_image_folder_select()
        else:
            self.visuals._reset_preview_to_initial_state()
        self.check_if_ready()

    def _update_content_info_display(self):
        """Enhanced content info display for both videos and image folders."""
        # Check what's currently selected
        video_selected = bool(self.state.video_queue and self.app.video_listbox.curselection())
        folder_selected = bool(self.state.image_folder_queue and self.app.image_folder_listbox.curselection())
        
        if video_selected:
            self._debounced_frame_estimate_update()  # This will handle video info + frame estimation
        elif folder_selected:
            self._update_image_folder_info_display()
        else:
            self.state.content_info_var.set("No content selected")
            self.state.content_details_var.set("--")

    def _update_image_folder_info_display(self):
        """Image folder info display without file size."""
        if not self.state.image_folder_queue:
            self.state.content_info_var.set("No image folder selected")
            self.state.content_details_var.set("--")
            return
        
        selected_indices = self.app.image_folder_listbox.curselection()
        if not selected_indices:
            self.state.content_info_var.set("No image folder selected")
            self.state.content_details_var.set("--")
            return
        
        folder_path = self.state.image_folder_queue[selected_indices[0]]
        folder_name = os.path.basename(folder_path)
        
        try:
            # Count images in the folder
            image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif')
            image_files = [f for f in os.listdir(folder_path) 
                        if f.lower().endswith(image_extensions)]
            image_count = len(image_files)
            
            self.state.content_info_var.set(f"{folder_name}")
            self.state.content_details_var.set(f"Image Count: {image_count} images")
            
        except Exception as e:
            print(f"Error getting folder info: {e}")
            self.state.content_info_var.set(f"{folder_name}")
            self.state.content_details_var.set("Count unavailable")

    def _attempt_display_recovery(self):
        """Try to recover display state when inputs become valid again."""
        try:
            if (self.state.video_queue and self.app.video_listbox.curselection() and 
                self.state.content_details_var.get() == "--"):
                
                video_path = self.state.video_queue[self.app.video_listbox.curselection()[0]]
                cache_key = f"video_info_{video_path}"
                video_info = self.state.video_info_cache.get(cache_key, {})
                
                # If we have cached video info, restore the display
                if self._is_video_info_valid(video_info):
                    print("🔄 Attempting display recovery with cached info")
                    self._show_video_info_with_frame_estimate(video_path, "Recovered display", video_info)
                    return True
        except Exception as e:
            print(f"Display recovery failed: {e}")
        
        return False

    def _debounced_frame_estimate_update(self, *args):
        """FIXED: Frame estimate update with safe timer handling."""
        # === SAFE TIMER CANCELLATION ===
        if self._frame_estimate_timer is not None:
            try:
                self.app.root.after_cancel(self._frame_estimate_timer)
            except (ValueError, tk.TclError):
                pass  # Timer already cancelled or invalid
            finally:
                self._frame_estimate_timer = None
        
        # Set new timer with shorter delay for responsiveness
        self._frame_estimate_timer = self.app.root.after(250, self._update_frame_estimate_safe)

    def _update_frame_estimate_safe(self):
        """Safe wrapper for frame estimate update."""
        try:
            self._update_frame_estimate()
        finally:
            # Always clear timer reference
            self._frame_estimate_timer = None

    def _update_frame_estimate(self):
        """
        Calculates the estimated number of frames and updates the UI display.
        This is the final, robust version of this logic.
        """
        self._frame_estimate_timer = None
        content_path = self._get_active_content_path()
        
        # Only perform estimation if a video is the active content
        if not content_path or self._current_active_queue != 'video':
            self.state.content_details_var.set("--")
            if self._current_active_queue == 'folder':
                self._update_image_folder_info_display()
            return
            
        video_path = content_path
        video_info = self._get_video_info_safely(video_path, f"video_info_{video_path}")
        
        if not self._is_video_info_valid(video_info):
            self._show_video_info_with_frame_estimate(video_path, "Video info unavailable", video_info)
            return

        frame_info_text = "Invalid input"
        try:
            extraction_method = self.app.extraction_method_var.get()
            if extraction_method == "count":
                frame_count = self.app.frame_count_var.get()
                if frame_count > 0:
                    frame_info_text = f"Estimated Frames: {frame_count}"
            else: # interval
                interval_value = self.app.interval_value_var.get()
                if interval_value > 0:
                    duration = video_info.get('duration')
                    fps = video_info.get('fps', 30)
                    if self.app.interval_unit_var.get() == "seconds":
                        estimated = max(1, int(duration / interval_value))
                    else: # frames
                        estimated = max(1, int((duration * fps) / interval_value))
                    frame_info_text = f"Estimated Frames: ~{estimated}"
        except (tk.TclError, ValueError):
            # This happens if the user has typed non-numeric input.
            # "Invalid input" is a safe fallback.
            pass
        
        self._show_video_info_with_frame_estimate(video_path, frame_info_text, video_info)

    def _get_video_info_safely_timed(self, video_path, cache_key):
        """ENHANCED: Video info with performance timing."""
        
        # Start timing
        end_timing = self.debug_cache_timing("get_video_info_safely")
        
        # Check if we have existing valid cache
        cache_start = time.time()
        existing_cache = self.state.video_info_cache.get(cache_key)
        cache_lookup_time = (time.time() - cache_start) * 1000
        
        if cache_lookup_time > 5:  # Log slow cache lookups
            self.debug_trace("CACHE_SLOW", f"Cache lookup took {cache_lookup_time:.1f}ms for {len(cache_key)} char key")
        
        existing_is_valid = existing_cache and self._is_video_info_valid(existing_cache)
        
        if existing_is_valid:
            self.debug_trace("CACHE_HIT", f"Using cached video info for {os.path.basename(video_path)}")
            end_timing()
            return existing_cache
        
        # Cache miss - need to extract fresh info
        self.debug_trace("CACHE_MISS", f"Extracting fresh video info for {os.path.basename(video_path)}")
        
        try:
            extract_start = time.time()
            import video_extraction
            fresh_info = video_extraction.get_video_info(video_path, self.app.ffmpeg_path_var.get())
            extract_time = (time.time() - extract_start) * 1000
            
            if extract_time > 100:  # Log slow extractions
                self.debug_trace("EXTRACT_SLOW", f"Video info extraction took {extract_time:.1f}ms")
            
            if self._is_video_info_valid(fresh_info):
                # Cache the result
                cache_write_start = time.time()
                self.state.video_info_cache[cache_key] = fresh_info
                cache_write_time = (time.time() - cache_write_start) * 1000
                
                if cache_write_time > 5:
                    self.debug_trace("CACHE_WRITE_SLOW", f"Cache write took {cache_write_time:.1f}ms")
                
                end_timing()
                return fresh_info
            else:
                self.debug_trace("EXTRACT_INVALID", "Fresh video info was invalid")
                end_timing()
                return {}
                
        except Exception as e:
            self.debug_trace("EXTRACT_ERROR", f"Video info extraction failed: {e}")
            end_timing()
            return {}

    def _get_video_info_safely(self, video_path, cache_key):
        """🔧 ENHANCED: Video info and cache protection."""
        # Check if we have existing valid cache
        existing_cache = self.state.video_info_cache.get(cache_key)
        
        if existing_cache and self._is_video_info_valid(existing_cache):
            # We have good cache - try to refresh but protect it
            try:
                import video_extraction
                fresh_info = video_extraction.get_video_info(video_path, self.app.ffmpeg_path_var.get())
                
                if self._is_video_info_valid(fresh_info):
                    # Only update cache with valid fresh data
                    self.state.video_info_cache[cache_key] = fresh_info
                    return fresh_info
                else:
                    # Fresh data invalid, keep existing cache
                    print("⚠️ Fresh video info invalid, using cached")
                    return existing_cache
                    
            except Exception as e:
                # Extraction failed, keep existing cache
                print(f"⚠️ Video info extraction failed, using cached: {e}")
                return existing_cache
        
        else:
            # No valid cache, must get fresh
            try:
                import video_extraction
                fresh_info = video_extraction.get_video_info(video_path, self.app.ffmpeg_path_var.get())
                
                if self._is_video_info_valid(fresh_info):
                    self.state.video_info_cache[cache_key] = fresh_info
                    return fresh_info
                else:
                    print("❌ Could not get valid video info")
                    return {}  # Empty but don't cache it
                    
            except Exception as e:
                print(f"❌ Video info extraction failed: {e}")
                return {}  # Empty but don't cache it

    def _is_video_info_valid(self, video_info):
        """Check if video_info contains essential data."""
        if not isinstance(video_info, dict) or not video_info:
            return False
        
        duration = video_info.get('duration')
        fps = video_info.get('fps')
        
        return (duration is not None and duration > 0 and 
                fps is not None and fps > 0)

    def _are_extraction_inputs_valid(self):
        """Enhanced input validation - less strict than your original."""
        try:
            extraction_method = self.app.extraction_method_var.get()
            
            if extraction_method == "count":
                frame_count = self.app.frame_count_var.get()
                # Allow 0 (empty field) - let calculation handle validation
                return isinstance(frame_count, int) and frame_count >= 0
            else:
                interval_value = self.app.interval_value_var.get()
                # Allow 0.0 (empty field) - let calculation handle validation  
                return isinstance(interval_value, (int, float)) and interval_value >= 0
                
        except (tk.TclError, ValueError, TypeError):
            # Input fields contain invalid data (letters, etc.)
            return False
        
    def _calculate_frame_estimate_safely(self, extraction_method, video_info):
        """🔧 FIX 3: Safe frame estimation calculation."""
        if extraction_method == "count":
            # Count method - always use the current value from the field
            frame_count = self.app.frame_count_var.get()
            return f"Estimated Frames: {frame_count}"
        
        else:
            # Interval method calculation
            interval_value = self.app.interval_value_var.get()
            interval_unit = self.app.interval_unit_var.get()
            
            duration = video_info.get('duration')
            fps = video_info.get('fps', 30)
            
            if duration is None:
                return "Duration unknown"
            
            if interval_unit == "seconds":
                estimated_frames = max(1, int(duration / interval_value))
                return f"Estimated Frames: ~{estimated_frames}"
            else:  # frames
                estimated_total_frames = duration * fps
                estimated_frames = max(1, int(estimated_total_frames / interval_value))
                return f"Estimated Frames: ~{estimated_frames}"

    def _show_video_info_with_frame_estimate(self, video_path, frame_info, video_info=None):
        """ENHANCED: More robust video info display."""
        video_name = os.path.basename(video_path)
        
        # Use provided video_info or get from cache as fallback
        if video_info is None:
            cache_key = f"video_info_{video_path}"
            video_info = self.state.video_info_cache.get(cache_key, {})
        
        # Extract video properties with defaults
        duration = video_info.get('duration')
        fps = video_info.get('fps')
        
        try:
            self.state.content_info_var.set(f"{video_name}")
            
            if duration is not None and duration > 0:
                # Format duration as MM:SS
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                duration_str = f"{minutes}:{seconds:02d}"
                
                # Format FPS
                if fps is not None and fps > 0:
                    if fps == int(fps):
                        fps_str = f"{int(fps)} FPS"
                    else:
                        fps_str = f"{fps:.1f} FPS"
                else:
                    fps_str = "Unknown FPS"
                
                self.state.content_details_var.set(f"Duration: {duration_str} | {fps_str} | {frame_info}")
            else:
                self.state.content_details_var.set(f"Duration unknown | {frame_info}")
                
        except Exception as e:
            print(f"Error formatting video info: {e}")
            self.state.content_info_var.set(f"Selected Video: {video_name}")
            self.state.content_details_var.set(f"Basic info | {frame_info}")

    def check_if_ready(self):
        state = tk.NORMAL if self.state.video_queue or self.state.image_folder_queue else tk.DISABLED
        self.app.run_pipeline_button.config(state=state)

    def _update_alignment_tab_feedback(self, *args):
        skip_rs = self.app.skip_realityscan_var.get()
        
        if skip_rs:
            # Skip RealityScan mode
            vggt_enabled = self.app.run_vggt_var.get()
            
            if vggt_enabled:
                # VGGT Alignment Mode
                training_methods = []
                if self.app.run_postshot_var.get():
                    training_methods.append("Postshot")
                if self.app.run_brush_var.get():
                    training_methods.append("Brush")
                
                text = ("VGGT Alignment Mode:\n\n"
                       "• VGGT will estimate camera poses from perspective views\n"
                       "• Outputs COLMAP format for training compatibility\n"
                       f"• Training methods: {', '.join(training_methods) if training_methods else 'None selected'}\n"
                       "• Both Postshot and Brush training available")
            else:
                # Direct Postshot Mode (no alignment)
                if self.app.run_postshot_var.get():
                    text = ("Direct Postshot Mode:\n\n"
                           "• 360° views passed directly to Postshot\n"
                           "• Postshot handles alignment and training internally\n"
                           "• Brush training disabled (requires camera alignment)")
                else:
                    text = ("Skip RealityScan Mode:\n\n"
                           "⚠️ No processing method selected.\n"
                           "Please enable VGGT alignment or Postshot training.")
        else:
            # Normal RealityScan mode
            exports = []
            if self.app.run_postshot_var.get(): 
                exports.append(".PLY point cloud and .CSV registration (for Postshot)")
            if self.app.run_brush_var.get(): 
                exports.append("COLMAP format (for Brush)")
            if self.app.run_vggt_var.get():
                exports.append("VGGT camera poses and 3D reconstruction")
            if self.app.export_xmp_var.get():
                exports.append("XMP rig files (for RealityScan)")
            
            if not exports: 
                text = "No training selected. RealityScan will only align and save the project."
            else: 
                text = "RealityScan will export:\n\n• " + "\n• ".join(exports)
        
        self.app.alignment_export_info_var.set(text)

    def _debounced_visual_update(self, *args):
        """
        NEW: A simple debouncer that correctly triggers a full visual update
        after a short delay when view parameters are changed.
        """
        if self._visual_update_timer:
            self.app.root.after_cancel(self._visual_update_timer)
        self._visual_update_timer = self.app.root.after(500, self.visuals.update_visual_overlays)

    # --- Main Pipeline Execution ---
    def _save_cached_frames(self, frames, frames_dir, frame_format='jpg'):
        """Saves a list of cached PIL images to the specified directory."""
        total_frames = len(frames)
        self.app.progress_manager.start_stage(1, f"Saving {total_frames} cached frames...")
        
        for i, frame in enumerate(frames):
            if self.state.cancel_event.is_set():
                print("🛑 Frame saving cancelled.")
                return False
            
            try:
                filename = f"frame_{i+1:06d}.{frame_format}"
                filepath = os.path.join(frames_dir, filename)
                frame.save(filepath, quality=95 if frame_format == 'jpg' else None)
                
                # Update progress
                details = f"Saving frame {i+1}/{total_frames}"
                self.app.progress_manager.update_stage_progress(i + 1, total_frames, details)
            except Exception as e:
                print(f"❌ Failed to save cached frame {i+1}: {e}")
                return False
        
        print(f"✅ Saved {total_frames} cached frames to {frames_dir}")
        self.app.progress_manager.complete_stage()
        return True

    def run_full_pipeline(self):
        """ENHANCED: Pipeline with comprehensive batch logging."""
        if self.state.processing:
            messagebox.showinfo("In Progress", "A pipeline is already running.")
            return
        
        self.state.combined_queue = [('video', p) for p in self.state.video_queue] + [('folder', p) for p in self.state.image_folder_queue]
        if not self.state.combined_queue:
            messagebox.showinfo("Empty Queue", "Please add items to a queue first.")
            return
        
        # === BATCH LOGGING: Session start marker ===
        total_items = len(self.state.combined_queue)
        print("\n" + "=" * 80)
        print(f"🚀 BATCH PROCESSING SESSION STARTED")
        print(f"📅 Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📦 Total items in batch: {total_items}")
        print(f"🎬 Videos: {len(self.state.video_queue)}")
        print(f"📁 Folders: {len(self.state.image_folder_queue)}")
        print("=" * 80)
        
        # Log each item in the batch
        print("📋 BATCH QUEUE CONTENTS:")
        for i, (item_type, item_path) in enumerate(self.state.combined_queue):
            item_name = os.path.basename(item_path)
            print(f"   [{i+1}] {item_type.upper()}: {item_name}")
        print("=" * 80 + "\n")

        # NEW: Check and enable dual progress bars for batch processing
        self.app.check_and_enable_dual_progress(total_items)
        
        self.state.processing = True
        self.state.cancel_event.clear()
        self.app.run_pipeline_button.config(state='disabled')
        self.app.cancel_pipeline_button.config(state='normal') 
        
        # MODIFIED: Pass is_batch flag to indicate batch processing mode
        self.app.progress_manager.start_pipeline(total_items, is_batch=(total_items > 1))
        
        threading.Thread(target=self._pipeline_thread_worker, daemon=True).start()

    def handle_extraction_button_click(self):
        """
        Handles a click on the main extraction button.
        Starts extraction if not running, cancels it if it is running.
        """
        if self.extraction_manager:
            if self.extraction_manager.extraction_in_progress:
                self.extraction_manager.cancel_extraction()
            else:
                self.extraction_manager.extract_all_frames_async()
        else:
            messagebox.showwarning("System Error", "Extraction manager not initialized.")    

    def cancel_pipeline(self):
        """Enhanced cancellation with immediate feedback."""
        if not self.state.processing:
            return
        
        result = messagebox.askyesno("Cancel Pipeline", 
                                    "Are you sure you want to cancel the running pipeline?\n\n"
                                    "This will stop the current operation and may leave partial files.")
        if result:
            print("🛑 User requested pipeline cancellation")
            
            # Set the cancel event (this is the key fix)
            self.state.cancel_event.set()
            
            # Update UI immediately
            self.state.progress_queue.put({
                'type': 'ui_update',
                'message': '⏳ Cancelling pipeline...',
                'progress': 0
            })
            
            # Disable cancel button temporarily
            self.app.cancel_pipeline_button.config(state='disabled', text='Cancelling...')
            
            # Monitor cancellation completion
            def check_completion():
                if not self.state.processing:
                    # Reset UI after cancellation
                    self.app.run_pipeline_button.config(state='normal')
                    self.app.cancel_pipeline_button.config(state='disabled', text='Cancel Pipeline')
                    self.state.progress_queue.put({
                        'type': 'ui_update',
                        'message': 'Pipeline cancelled by user',
                        'progress': 0
                    })
                    print("✅ Pipeline cancellation completed")
                else:
                    # Check again in 500ms
                    self.app.root.after(500, check_completion)
            
            # Start monitoring
            self.app.root.after(100, check_completion)

    def _pipeline_thread_worker(self):
        """
        FINAL VERSION: Combines all features including robust error handling,
        the "cache-first" strategy, and the "Skip RealityScan" workflow.
        """
        logger = None
        total_items = len(self.state.combined_queue)
        successful_items = 0
        failed_items = []
        
        try:
            for i, (item_type, item_path) in enumerate(self.state.combined_queue):
                if self.state.cancel_event.is_set():
                    print(f"🛑 Pipeline cancelled during item setup ({i+1}/{total_items})")
                    break
                    
                raw_basename = Path(item_path).stem
                item_basename = self._sanitize_project_name(raw_basename)
                
                print(f"\n{'='*60}")
                print(f"📦 PROCESSING ITEM {i+1}/{total_items}: {item_basename}")
                print(f"{'='*60}")
                
                try:

                    # --- CRITICAL FIX: Get settings for THIS specific item ---
                    settings = self._get_settings_for_item(item_path, item_type)

                    print(f"🎯 Using settings for {item_basename}:")
                    print(f"   Extraction method: {settings.get('extraction_method', 'unknown')}")
                    if settings.get('extraction_method') == 'count':
                        print(f"   Frame count: {settings.get('frame_count', 'unknown')}")
                    else:
                        print(f"   Interval: {settings.get('interval_value', 'unknown')} {settings.get('interval_unit', 'unknown')}")

                    # --- ITEM INITIALIZATION ---
                    self.app.progress_manager.start_item(item_basename, i)
                    settings = self.app.get_current_settings()
                    skip_realityscan = settings.get('skip_realityscan', False)
                    pipeline_mode = "Skip RealityScan Mode" if skip_realityscan else "Full Pipeline Mode"
                    print(f"🎯 Pipeline Mode: {pipeline_mode}")
                    
                    project_root = settings.get('project_dir') or Path(item_path).parent
                    current_project_dir = Path(project_root) / item_basename
                    logger = PipelineLogger(item_basename, str(current_project_dir))
                    logger.log_settings(settings)
                    
                    frames_dir = (current_project_dir / "01_frames").as_posix()
                    views_dir = (current_project_dir / "02_views").as_posix()
                    alignment_dir = (current_project_dir / "03_alignment").as_posix()
                    training_dir = (current_project_dir / "04_training").as_posix()
                    
                    for d in [frames_dir, views_dir, alignment_dir, training_dir]:
                        os.makedirs(d, exist_ok=True)

                    # --- STAGE 1: FRAME GENERATION ---
                    print(f"🎬 Starting Stage 1: Frame Generation")
                    logger.start_stage("1. Frame Generation")
                    try:
                        source_dir = None

                        # FIXED: Check for cached frames using the correct item path
                        cached_frames = self._get_cached_frames_for_item(item_path, item_type)       

                        if cached_frames:
                            print(f"🧠 Found {len(cached_frames)} cached frames for {item_basename}. Saving to disk...")
                            if self._save_cached_frames(cached_frames, frames_dir, settings.get('frame_format', 'jpg')):
                                source_dir = frames_dir
                                print(f"✅ Successfully used cached frames for {item_basename}")
                            else:
                                raise RuntimeError("Failed to save cached frames.")
                        else:
                            print(f"ⓘ No cached frames found for {item_basename}. Processing from source.")
                            if item_type == 'folder':
                                source_dir = item_path
                            else: # item_type == 'video'
                                # FIXED: Pass the item-specific settings to extraction
                                source_dir = self._run_frame_extraction_with_settings(
                                    item_path, frames_dir, settings, i)
                        
                        if not source_dir or self.state.cancel_event.is_set():
                            raise RuntimeError("Frame generation failed or was cancelled.")
                        
                        logger.end_stage(True)
                        print(f"✅ Stage 1 completed successfully")
                    except Exception as e:
                        logger.end_stage(False, f"Frame generation error: {e}")
                        raise RuntimeError(f"Frame generation failed: {e}")

                    # --- STAGE 2: VIEW EXTRACTION ---
                    print(f"🌐 Starting Stage 2: View Extraction")
                    logger.start_stage("2. View Extraction", f"FOV: {settings.get('fov')}°, Yaw: {settings.get('yaw_steps')}")
                    try:
                        if not self._run_view_extraction(source_dir, views_dir, settings, i) or self.state.cancel_event.is_set():
                            raise RuntimeError("View extraction failed or was cancelled.")
                        logger.end_stage(True)
                        print(f"✅ Stage 2 completed successfully")
                    except Exception as e:
                        logger.end_stage(False, f"View extraction error: {e}")
                        raise RuntimeError(f"View extraction failed: {e}")

                    # --- STAGE 3: ALIGNMENT (Conditional) ---
                    if skip_realityscan:
                        vggt_enabled = settings.get('run_vggt', False)
                        if vggt_enabled:
                            print(f"🌐 Starting Stage 3: VGGT Alignment")
                            logger.start_stage("3. VGGT Alignment")
                            try:
                                if not self._run_vggt_alignment(views_dir, alignment_dir, settings, i) or self.state.cancel_event.is_set():
                                    raise RuntimeError("VGGT alignment failed or was cancelled.")
                                logger.end_stage(True)
                                print(f"✅ Stage 3 completed successfully")
                            except Exception as e:
                                logger.end_stage(False, f"VGGT alignment error: {e}")
                                raise RuntimeError(f"VGGT alignment failed: {e}")
                        else:
                            print(f"⏭️  Skipping Stage 3: No alignment method selected (direct Postshot mode)")
                            logger.start_stage("3. Alignment", "Skipped - Postshot will handle alignment")
                            logger.end_stage(True)
                            alignment_dir = None
                    else:
                        print(f"📐 Starting Stage 3: RealityScan Alignment")
                        logger.start_stage("3. RealityScan Alignment")
                        try:
                            if not self._run_rs_alignment(views_dir, alignment_dir, settings, i) or self.state.cancel_event.is_set():
                                raise RuntimeError("RealityScan alignment failed or was cancelled.")
                            logger.end_stage(True)
                            print(f"✅ Stage 3 completed successfully")
                        except Exception as e:
                            logger.end_stage(False, f"Alignment error: {e}")
                            raise RuntimeError(f"RealityScan alignment failed: {e}")

                    # --- STAGE 4: TRAINING ---
                    print(f"🧠 Starting Stage 4: Neural Training")
                    logger.start_stage("4. Neural Training", f"Postshot: {settings.get('run_postshot')}, Brush: {settings.get('run_brush')}")
                    try:
                        if not self._run_training(views_dir, alignment_dir, training_dir, settings, i, skip_realityscan) or self.state.cancel_event.is_set():
                            raise RuntimeError("Neural training failed or was cancelled.")
                        logger.end_stage(True)
                        print(f"✅ Stage 4 completed successfully")
                    except Exception as e:
                        logger.end_stage(False, f"Training error: {e}")
                        raise RuntimeError(f"Neural training failed: {e}")

                    # --- ITEM SUCCESS ---
                    self.app.progress_manager.complete_item()
                    successful_items += 1
                    print(f"🎉 ITEM {i+1}/{total_items} COMPLETED SUCCESSFULLY: {item_basename}")
                    if logger:
                        logger.finalize()
                        logger = None
                        
                except Exception as item_error:
                    # --- ITEM FAILURE ---
                    error_msg = str(item_error)
                    failed_items.append({'index': i+1, 'name': item_basename, 'error': error_msg})
                    print(f"❌ ITEM {i+1}/{total_items} FAILED: {item_basename}")
                    print(f"   Error: {error_msg}")
                    if logger:
                        logger.end_stage(False, f"Item failed: {error_msg}")
                        logger.finalize()
                        logger = None
                    self.app.progress_manager.error_occurred(f"Item {i+1} failed")
                    time.sleep(1)
                    print(f"🔄 Continuing to next item in queue...")
                    continue
            
            # --- PIPELINE COMPLETION SUMMARY ---
            print(f"\n{'='*60}\n📊 BATCH PIPELINE COMPLETED\n{'='*60}")
            print(f"✅ Successful items: {successful_items}/{total_items}")
            print(f"❌ Failed items: {len(failed_items)}/{total_items}")
            if failed_items:
                print(f"\n📋 FAILED ITEMS SUMMARY:")
                for item in failed_items:
                    print(f"   [{item['index']}] {item['name']}: {item['error']}")
            
            if not self.state.cancel_event.is_set():
                if successful_items > 0:
                    self.app.progress_manager.complete_pipeline()
                else:
                    self.app.progress_manager.error_occurred("All items failed")
            else:
                print(f"🛑 Pipeline cancelled by user")
                
        except Exception as pipeline_error:
            # --- CATASTROPHIC FAILURE ---
            error_msg = str(pipeline_error)
            print(f"💥 CATASTROPHIC PIPELINE FAILURE: {error_msg}")
            traceback.print_exc()
            if logger:
                logger.finalize()
            self.app.progress_manager.error_occurred("Catastrophic failure!")
            
        finally:
            # --- FINAL CLEANUP ---
            if logger:
                logger.finalize()
            self.state.processing = False
            self.app.root.after(0, lambda: [
                self.app.run_pipeline_button.config(state='normal'),
                self.app.cancel_pipeline_button.config(state='disabled'),
                self.check_if_ready()
            ])

    def _get_settings_for_item(self, item_path, item_type):
        """
        NEW: Get the correct settings for a specific item, prioritizing cached per-video settings.
        
        Args:
            item_path: Path to the video file or image folder
            item_type: 'video' or 'folder'
        
        Returns:
            Dictionary of settings to use for this specific item
        """
        # Start with current UI settings as baseline
        base_settings = self.app.get_current_settings()
        
        # For videos, try to get cached per-video settings
        if item_type == 'video' and item_path in self.state.per_video_settings_cache:
            cached_settings = self.state.per_video_settings_cache[item_path]
            
            print(f"📋 Found cached settings for: {os.path.basename(item_path)}")
            print(f"   Cached extraction method: {cached_settings.get('extraction_method', 'unknown')}")
            
            # Merge cached settings with base settings
            # Cached settings take priority for video-specific parameters
            video_specific_keys = [
                'extraction_method', 'interval_value', 'interval_unit', 'frame_count',
                'pitch_angles_str', 'yaw_steps', 'fov', 'overlay_opacity', 'frame_format', 'vggt_sky_sensitivity_threshold'
            ]
            
            for key in video_specific_keys:
                if key in cached_settings:
                    base_settings[key] = cached_settings[key]
            
            print(f"✅ Using cached settings: {cached_settings.get('extraction_method', 'unknown')} method")
            
        else:
            print(f"ℹ️ No cached settings found for {os.path.basename(item_path)}, using current UI settings")
        
        return base_settings

    def _get_cached_frames_for_item(self, item_path, item_type):
        """
        NEW: Get cached frames for a specific item.
        
        Args:
            item_path: Path to the video file or image folder
            item_type: 'video' or 'folder'
        
        Returns:
            List of PIL Images if cached frames exist, empty list otherwise
        """
        if item_type != 'video':
            return []
        
        # Check if this video has cached frames AND if the cache is valid
        if (hasattr(self, 'extraction_manager') and 
            self.extraction_manager and 
            item_path in self.state.extraction_frame_cache):
            
            cache_entry = self.state.extraction_frame_cache[item_path]
            
            # Verify cache is valid and has frames
            if (cache_entry.get('cache_valid', False) and 
                cache_entry.get('total_frames', 0) > 0):
                
                print(f"🔍 Checking cached frames for: {os.path.basename(item_path)}")
                print(f"   Cache entry has {cache_entry['total_frames']} frames")
                
                # Temporarily set the extraction manager's current video to this item
                # so it can retrieve the cached frames
                original_video_path = getattr(self.extraction_manager, 'current_video_path', None)
                try:
                    self.extraction_manager.current_video_path = item_path
                    cached_frames = self.extraction_manager.get_cached_frames_for_pipeline()
                    
                    if cached_frames:
                        print(f"✅ Retrieved {len(cached_frames)} cached frames for pipeline")
                        return cached_frames
                    else:
                        print(f"⚠️ Cache entry exists but no frames could be retrieved")
                        
                finally:
                    # Restore original video path
                    if original_video_path:
                        self.extraction_manager.current_video_path = original_video_path
        
        return []

    def _run_frame_extraction_with_settings(self, video_path, frames_dir, settings, item_idx):
        """
        FIXED: Frame extraction that uses the provided settings instead of current UI settings.
        
        Args:
            video_path: Path to video file
            frames_dir: Output directory for frames
            settings: Dictionary of settings to use (from _get_settings_for_item)
            item_idx: Index of current item
        
        Returns:
            frames_dir if successful, None if failed
        """
        self.app.progress_manager.start_stage(1, f"Extracting frames...")
        
        def frame_progress_callback(current_frame, total_frames, frame_time=None):
            details = f"Frame {current_frame}/{total_frames}"
            if frame_time:
                details += f" at {frame_time:.1f}s"

            self.state.progress_queue.put({
                'type': 'progress_update',
                'current': current_frame,
                'total': total_frames,
                'details': details
            })
        
        # CRITICAL FIX: Use the provided settings, not current UI settings
        print(f"🔧 Extracting frames using specific settings:")
        print(f"   Method: {settings.get('extraction_method', 'interval')}")
        print(f"   Interval Value: {settings.get('interval_value', 1.0)}")
        print(f"   Interval Unit: {settings.get('interval_unit', 'seconds')}")
        print(f"   Frame Count: {settings.get('frame_count', 30)}")
        print(f"   Frame Format: {settings.get('frame_format', 'jpg')}")
        
        success = video_extraction.extract_frames_for_video(
            video_path=video_path, 
            output_folder=frames_dir,
            # FIXED: Use settings from the specific video, not current UI
            extraction_method=settings.get('extraction_method', 'interval'),
            interval_value=settings.get('interval_value', 1.0),
            interval_unit=settings.get('interval_unit', 'seconds'),
            frame_count=settings.get('frame_count', 30),
            frame_format=settings.get('frame_format', 'jpg'),
            progress_callback=frame_progress_callback,
            ffmpeg_path=settings.get('ffmpeg_path', 'ffmpeg'),
            cancel_event=self.state.cancel_event 
        )
        
        self.app.progress_manager.complete_stage()
        
        if success:
            print(f"✅ Frame extraction completed using {settings.get('extraction_method')} method")
        else:
            print(f"❌ Frame extraction failed")
        
        return frames_dir if success else None

    def _run_view_extraction(self, source_dir, views_dir, settings, item_idx):
        self.app.progress_manager.start_stage(2, "Rendering 360° views...")
        
        try:
            frame_paths = sorted([os.path.join(source_dir, f) for f in os.listdir(source_dir) 
                                if f.lower().endswith(('.png', '.jpg'))])
            if not frame_paths: 
                raise FileNotFoundError("No frames found in input folder.")
            
            pitch_angles = [float(p.strip()) for p in settings['pitch_angles_str'].split(',')]
            yaw_steps = int(settings['yaw_steps'])
            fov = float(settings['fov'])
            export_xmp = settings.get('export_xmp', False)
            
            # Disable XMP export when VGGT alignment will be used
            skip_realityscan = settings.get('skip_realityscan', False)
            vggt_will_be_used = skip_realityscan and settings.get('run_vggt', False)
            if vggt_will_be_used and export_xmp:
                print("📋 Disabling XMP export - VGGT will generate its own camera poses")
                export_xmp = False
            
            total_operations = len(frame_paths) * len(pitch_angles) * yaw_steps
            current_operation = 0
            
            for frame_idx, frame_path in enumerate(frame_paths):
                def view_progress_callback(current_view, total_views):
                    nonlocal current_operation
                    current_operation += 1
                    details = f"Frame {frame_idx + 1}/{len(frame_paths)}, View {current_view + 1}/{total_views}"
                    self.app.progress_manager.update_stage_progress(current_operation, total_operations, details)
                
                panorama_processing.render_views(
                    pano_path=frame_path, out_root=views_dir, fov_deg=fov, yaw_steps=yaw_steps,
                    pitch_angles=pitch_angles, export_xmp=False, save_images=True, 
                    cancel_event=self.state.cancel_event, progress_callback=view_progress_callback)
            
                    # NEW: Generate XMP files after all views are rendered
            if export_xmp:
                print("🎯 Generating XMP rig files...")
                try:
                    import xmp_rig_export  # Import your new module
                    xmp_rig_export.export_all_frame_rigs(views_dir, pitch_angles, yaw_steps)
                    print("✅ XMP rig files generated successfully")
                except Exception as e:
                    print(f"⚠️ XMP export failed: {e}")
                    # Continue with pipeline even if XMP export fails

            self.app.progress_manager.complete_stage()
            return True
            
        except Exception as e:
            print(f"View extraction error: {e}")
            return False

    def _run_rs_alignment(self, views_dir, alignment_dir, settings, item_idx):
        self.app.progress_manager.start_stage(3, "RealityScan alignment...")
        """FIXED: RealityScan alignment with proper path handling."""
        try:
            rs_exe = settings['rs_path']
            rs_settings_folder = settings['rs_settings_path']
            
            if not os.path.exists(rs_exe): 
                raise FileNotFoundError("RealityScan executable not found.")
            
            # FIXED: Use consistent path separators for RealityScan (Windows prefers backslashes)
            if os.name == 'nt':  # Windows
                project_file = os.path.join(alignment_dir, "RS.rcproj").replace('/', '\\')
                views_dir_rs = views_dir.replace('/', '\\')
                alignment_dir_rs = alignment_dir.replace('/', '\\')
            else:  # Unix-like systems
                project_file = os.path.join(alignment_dir, "RS.rcproj")
                views_dir_rs = views_dir
                alignment_dir_rs = alignment_dir
            
            command = [rs_exe, "-addFolder", views_dir_rs, "-align", "-save", project_file]
            
            # Add export commands with consistent paths
            if settings['run_postshot']:
                if os.name == 'nt':
                    reg_export_file = os.path.join(views_dir, "registration.csv").replace('/', '\\')
                    ply_export_file = os.path.join(views_dir, "pointcloud.ply").replace('/', '\\')
                    reg_xml = os.path.join(rs_settings_folder, "360_pipe_reg.xml").replace('/', '\\')
                    ply_xml = os.path.join(rs_settings_folder, "360_pipe_ply.xml").replace('/', '\\')
                else:
                    reg_export_file = os.path.join(views_dir, "registration.csv")
                    ply_export_file = os.path.join(views_dir, "pointcloud.ply")
                    reg_xml = os.path.join(rs_settings_folder, "360_pipe_reg.xml")
                    ply_xml = os.path.join(rs_settings_folder, "360_pipe_ply.xml")
                    
                command.extend(["-exportRegistration", reg_export_file, reg_xml])
                command.extend(["-exportSparsePointCloud", ply_export_file, ply_xml])
            
            if settings['run_brush']:
                if os.name == 'nt':
                    colmap_export_folder = os.path.join(alignment_dir, "COLMAP_for_Brush").replace('/', '\\')
                else:
                    colmap_export_folder = os.path.join(alignment_dir, "COLMAP_for_Brush")
                
                try:
                    os.makedirs(colmap_export_folder, exist_ok=True)
                    
                    if os.name == 'nt':
                        colmap_xml_path = os.path.join(rs_settings_folder, "360_Pipe_COLMAP.xml").replace('/', '\\')
                        COLMAP_Export_file = os.path.join(colmap_export_folder, "RS.txt").replace('/', '\\')
                    else:
                        colmap_xml_path = os.path.join(rs_settings_folder, "360_Pipe_COLMAP.xml")
                        COLMAP_Export_file = os.path.join(colmap_export_folder, "RS.txt")
                        
                    command.extend(["-exportRegistration", COLMAP_Export_file, colmap_xml_path])
                    
                except Exception as e:
                    print(f"Warning: COLMAP export setup failed: {e}")
            
            command.append("-quit")
            
            print(f"Running RealityScan: {' '.join(command)}")
            
            # Run process
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                    text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    if "access is denied" in line.lower() or "permission denied" in line.lower():
                        print(f"🚨 Permission Error: {line}")
                    elif "error" in line.lower():
                        print(f"⚠️ RS Error: {line}")
                    else:
                        self.app.progress_manager.update_stage_details(f"RS: {line}")
            
            process.stdout.close()
            return_code = process.wait()
            
            if return_code != 0: 
                raise RuntimeError(f"RealityScan process exited with code {return_code}")
            
            self.app.progress_manager.complete_stage()
            return True
            
        except Exception as e:
            print(f"RealityScan alignment error: {e}")
            return False

    def _run_vggt_alignment(self, views_dir, alignment_dir, settings, item_idx):
        """Run VGGT alignment to replace RealityScan - generates camera poses and COLMAP format."""
        self.app.progress_manager.start_stage(3, "VGGT alignment...")
        
        try:
            # 1. IMMEDIATE INFO FILE CREATION (Placeholder)
            try:
                from datetime import datetime
                from pathlib import Path
                info_file_path = os.path.join(alignment_dir, "VGGT_Alignment_Info.txt")
                with open(info_file_path, 'w') as f:
                    f.write("VGGT Alignment In Progress...\n")
                    f.write("=====================================\n\n")
                    f.write(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                print(f"📄 Created placeholder info file: {info_file_path}")
            except Exception as e:
                print(f"⚠️ Could not create placeholder info file: {e}")
                
            try:
                # Check VGGT availability using the processor's initialize method
                processor_instance = VGGTProcessor()
                available, status_msg = processor_instance.initialize()         
                if not available:
                    print(f"❌ VGGT not available: {status_msg}")
                    return False
                    
                print(f"✅ {status_msg}")
                    
            except Exception as e:
                print(f"❌ Failed to initialize VGGTProcessor for check: {e}")
                return False
            
            print(f"\n🌐 VGGT ALIGNMENT:")
            print(f"   Input views: {views_dir}")
            print(f"   Output directory: {alignment_dir}")
            
            def progress_callback(message):
                """Callback to report VGGT progress to the GUI"""
                print(f"   {message}")
                self.app.progress_manager.update_stage_details(message)
                
                # Check for cancellation
                return not self.state.cancel_event.is_set()
            
            # Create output directories based on training selection
            project_dir = os.path.dirname(alignment_dir)
            training_dir = os.path.join(project_dir, "04_training")
            
            # Create appropriate output directories based on training selection
            run_postshot = settings.get('run_postshot', False)
            run_brush = settings.get('run_brush', False)
            
            if run_postshot:
                # Create postshot_input for Postshot training
                vggt_output_dir = os.path.join(training_dir, "postshot_input")
                os.makedirs(vggt_output_dir, exist_ok=True)
                print(f"📁 Created postshot_input directory for Postshot training")
            elif run_brush:
                # Create brush_input directly for Brush-only mode
                vggt_output_dir = os.path.join(training_dir, "brush_input")
                os.makedirs(vggt_output_dir, exist_ok=True)
                print(f"📁 Created brush_input directory for Brush training")
            else:
                # Fallback for neither training mode selected
                vggt_output_dir = os.path.join(training_dir, "vggt_output")
                os.makedirs(vggt_output_dir, exist_ok=True)
                print(f"📁 Created vggt_output directory")
            
            colmap_images_dir = os.path.join(vggt_output_dir, "images")
            os.makedirs(colmap_images_dir, exist_ok=True)
            
            # For backward compatibility, set postshot_input_dir to the actual output dir
            postshot_input_dir = vggt_output_dir

            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
            copied_image_count = 0

            print(f"📁 Copying images from '{views_dir}' to '{colmap_images_dir}' for COLMAP...")
            for root, _, files in os.walk(views_dir):
                for file in files:
                    if Path(file).suffix.lower() in image_extensions:
                        src_path = os.path.join(root, file)
                        dest_path = os.path.join(colmap_images_dir, file)
                        try:
                            import shutil
                            if not os.path.exists(dest_path): # Avoid re-copying if already there
                                shutil.copy2(src_path, dest_path)
                                copied_image_count += 1
                        except Exception as e:
                            print(f"⚠️ Failed to copy image {file}: {e}")
            print(f"✅ Copied {copied_image_count} images to COLMAP input.")

            # Get GUI filter settings
            conf_thres = settings.get('vggt_conf_threshold', 50.0)
            mask_sky = settings.get('vggt_mask_sky', True)
            mask_black_bg = settings.get('vggt_mask_black_bg', False)
            mask_white_bg = settings.get('vggt_mask_white_bg', False)
            prediction_mode = settings.get('vggt_prediction_mode', 'Depthmap and Camera Branch')
            temporal_sequencing = settings.get('vggt_temporal_sequencing', True)
            enable_sparse = settings.get('vggt_enable_sparse', False)
            sparse_target_points = settings.get('vggt_sparse_target', 150000)
            use_anchor_rig = settings.get('vggt_use_anchor_rig', False)
            anchor_view = settings.get('vggt_anchor_view', 'y00')
            rig_optimization_min_points = settings.get('vggt_rig_optimization_min_points', 500000)
            show_camera = settings.get('vggt_show_camera', True)
            sky_sensitivity_threshold = settings.get('vggt_sky_sensitivity_threshold', 32)
            
            print(f"   🎯 Filter settings: conf={conf_thres}%, sky={mask_sky}, black_bg={mask_black_bg}, white_bg={mask_white_bg}")
            print(f"   📊 Prediction mode: {prediction_mode}")
            print(f"   🔄 Image sequencing: {'Temporal (by viewpoint)' if temporal_sequencing else 'Spatial (by frame)'}")
            print(f"   🎲 Sparse filtering: {'Enabled' if enable_sparse else 'Disabled'} (target: {sparse_target_points:,} points)")
            print(f"   ☁️ Sky sensitivity threshold: {sky_sensitivity_threshold}")
            print(f"   📁 COLMAP output: {postshot_input_dir}")
            
            # 🎯 DYNAMIC EXTRACTION PARAMETERS: Get from cached settings
            # Parse cached pitch angles and yaw steps from user's extraction settings
            pitch_angles_str = settings.get('pitch_angles_str', '-30.0')
            yaw_steps_str = settings.get('yaw_steps', '6') 
            #fov_str = settings.get('fov', '90.0')
            
            try:
                pitch_angles = [float(p.strip()) for p in pitch_angles_str.split(',')]
                yaw_steps = int(yaw_steps_str)
                # fov is not directly passed to run_full_pipeline, but used in panorama_processing
                # For this pipeline, we'll assume the images were rendered with the correct FOV.
                # If run_full_pipeline needs FOV, it should be passed.
                # For now, it's not a direct parameter to run_full_pipeline.
                # fov = float(fov_str) 
                print(f"   🎯 DYNAMIC EXTRACTION PARAMS: pitch_angles={pitch_angles}, yaw_steps={yaw_steps}") # Removed FOV
            except (ValueError, AttributeError) as e:
                print(f"   ⚠️ Failed to parse extraction params, using defaults: {e}")
                pitch_angles = [0.0]  # Fallback
                yaw_steps = 6  # Fallback
                # fov = 90.0  # Fallback

            # Run VGGT pipeline with GUI filter settings and configured path


            # Get actual image dimensions from first available image
            import glob
            try:
                from PIL import Image
                image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
                first_image_path = None
                for ext in image_extensions:
                    image_files = glob.glob(os.path.join(views_dir, '**', ext), recursive=True)
                    if image_files:
                        first_image_path = image_files[0]
                        break
                
                if first_image_path:
                    with Image.open(first_image_path) as img:
                        colmap_image_width, colmap_image_height = img.size
                    print(f"   📏 Detected image dimensions: {colmap_image_width}x{colmap_image_height}")
                else:
                    # Fallback to default values
                    colmap_image_width, colmap_image_height = 1920, 1920
                    print(f"   ⚠️ No images found for dimension detection, using default: {colmap_image_width}x{colmap_image_height}")
            except Exception as e:
                # Fallback to default values in case of error
                colmap_image_width, colmap_image_height = 1920, 1920
                print(f"   ⚠️ Could not detect image dimensions ({e}), using default: {colmap_image_width}x{colmap_image_height}")

            results = run_full_pipeline(
                image_dir=views_dir, # Input directory for images
                output_dir=postshot_input_dir, # Output directory for GLB/COLMAP
                progress_callback=progress_callback,
                cancel_event=self.state.cancel_event,
                conf_thres=conf_thres,
                mask_sky=mask_sky,
                mask_black_bg=mask_black_bg,
                mask_white_bg=mask_white_bg,
                prediction_mode=prediction_mode,
                temporal_sequencing=temporal_sequencing,  # FIXED: Now properly passed
                enable_sparse=enable_sparse,              # FIXED: Added missing parameter
                sparse_target_points=sparse_target_points, # FIXED: Added missing parameter
                sky_sensitivity_threshold=sky_sensitivity_threshold, # FIXED: Added missing parameter
                use_anchor_rig=use_anchor_rig,
                anchor_view=anchor_view,
                rig_optimization_min_points=rig_optimization_min_points,
                show_camera=show_camera,
                pitch_angles=pitch_angles, # Pass dynamic pitch angles
                yaw_steps=yaw_steps,       # Pass dynamic yaw steps
                colmap_image_width=colmap_image_width,
                colmap_image_height=colmap_image_height
            )
            
            # UPDATE INFO FILE with final details
            if results.get('success', False):
                print(f"✅ VGGT full pipeline completed successfully!")
                
                # UPDATE INFO FILE with final details
                try:
                    from datetime import datetime
                    from pathlib import Path
                    
                    current_project_dir = Path(alignment_dir).parent
                                        # Use paths returned by run_full_pipeline

                    info_file_path = os.path.join(alignment_dir, "VGGT_Alignment_Info.txt")
                    # Use appropriate folder based on training selection
                    run_postshot = settings.get('run_postshot', False)
                    run_brush = settings.get('run_brush', False)
                    
                    if run_postshot:
                        output_folder = "postshot_input"
                    elif run_brush:
                        output_folder = "brush_input"
                    else:
                        output_folder = "vggt_output"
                    
                    training_colmap_path = os.path.join(current_project_dir.as_posix(), "04_training", output_folder)
                    conf_thres = settings.get('vggt_conf_threshold', 50.0)
                    mask_sky = settings.get('vggt_mask_sky', True)
                    mask_black_bg = settings.get('vggt_mask_black_bg', False)
                    mask_white_bg = settings.get('vggt_mask_white_bg', False)
                    
                    with open(info_file_path, 'w') as f: # 'w' overwrites the placeholder
                        f.write("VGGT Alignment Completed Successfully\n")
                        f.write("=====================================\n\n")
                        f.write(f"Completion Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write("When using VGGT for alignment, COLMAP files are saved directly to:\n")
                        f.write(f"{training_colmap_path}\n\n")
                        f.write("Files generated:\n")
                        f.write("- cameras.txt\n")
                        f.write("- images.txt\n")
                        f.write("- points3D.txt\n\n")
                        f.write("Processing Details:\n")
                        f.write(f"- Confidence threshold: {conf_thres}%\n")
                        f.write(f"- Sky masking: {mask_sky}\n")
                        f.write(f"- Black background masking: {mask_black_bg}\n")
                        f.write(f"- White background masking: {mask_white_bg}\n\n")
                        f.write("These files are ready for use in the training pipeline.\n\n")
                        f.write("Note: This is the standard workflow when Skip RealityScan is enabled.\n")
                    
                    print(f"📄 Updated alignment info file with final details.")
                    
                except Exception as e:
                    print(f"⚠️ Warning: Could not update alignment info file: {e}")

            # 1. IMMEDIATE PLY CREATION
            # The PLY file can be created instantly since we have the filtered points.
            if results.get('success', False):
                print("⚡ Instantly creating PLY file from filtered points...")
                ply_dest_path = os.path.join(alignment_dir, "point_cloud_filtered.ply")
                try:
                    save_ply(
                        results['filtered_points'],
                        results['filtered_colors'],
                        ply_dest_path
                    )
                    print(f"✅ Created point_cloud_filtered.ply in 03_alignment")
                except Exception as e:
                    print(f"⚠️ Could not create immediate PLY file: {e}")

            # 2. PREVIEW FILE HANDLING
            # Move GLB, then launch the server and browser from the correct final location.
            source_glb_path = results.get('glb_path')  # Use actual GLB path from run_full_pipeline
            dest_alignment_dir = alignment_dir

            if source_glb_path and os.path.exists(source_glb_path):
                try:
                    # Define final paths in the correct 03_alignment directory
                    final_glb_path = os.path.join(dest_alignment_dir, "quick_preview.glb")
                    final_html_path = os.path.join(dest_alignment_dir, "quick_preview.html")

                    # 1. Move the GLB file first
                    os.rename(source_glb_path, final_glb_path)
                    print(f"✅ Moved {os.path.basename(source_glb_path)} to 03_alignment folder as quick_preview.glb")

                    # 2. Create BOTH viewers - Three.js and Gradio
                    from vggt_training import create_simple_glb_viewer #create_gradio_glb_viewer
                    title = f"VGGT Preview ({os.path.basename(alignment_dir)})"
                    
                    # 📱 Also create Three.js viewer (backup/comparison)
                    print("🔧 Starting Three.js viewer (backup viewer)...")
                    create_simple_glb_viewer(final_glb_path, final_html_path, title)

                    # 3. Open browsers for both viewers
                    import webbrowser
                    # if gradio_success:
                    #     print("🌐 Opening Gradio viewer (port 7864) - this should show colors correctly")
                    #     # Gradio opens automatically with inbrowser=True
                    
                    print("🌐 Opening Three.js viewer (port 8089) - for comparison")
                    webbrowser.open("http://localhost:8089/quick_preview.html")
                    print(f"✅ 3D preview opened from: {final_html_path}")

                except Exception as e:
                    print(f"⚠️ Could not move or launch preview: {e}")
            else:
                if source_glb_path:
                    print(f"⚠️ GLB file not found at expected path: {source_glb_path}")
                else:
                    print(f"⚠️ No GLB path returned from pipeline")

            # 3. SLOW COLMAP EXPORT
            # Now, run the slow COLMAP export process
            if results.get('success', False) and training_colmap_path: # Ensure COLMAP output dir exists
                print(f"📊 Exporting COLMAP with {len(results['filtered_points']):,} pre-filtered points...")
                
                # 🎯 Get anchor+rig mode setting
                use_anchor_rig_setting = settings.get('vggt_use_anchor_rig', False)
                
                # Pass the full predictions_dict and use_anchor_rig flag
                write_colmap_files(
                    training_colmap_path, # Use the final COLMAP output directory
                    results['filtered_points'],
                    results['filtered_colors'],
                    results['num_cameras_processed_poses_c2w'], # This should be the final camera poses array
                    results['final_intrinsic'], # This should be the final intrinsic array
                    results['expanded_image_names'], # This should be the expanded image names
                    progress_callback=progress_callback,
                    use_anchor_rig=use_anchor_rig_setting, # Pass the flag
                    predictions_dict=results['raw_predictions'] # Pass the original raw predictions for rig info
                )

            if not results.get('success', False):
                error_msg = results.get('error', 'Unknown error')
                print(f"❌ VGGT alignment failed: {error_msg}")
                return False
            
            # COLMAP files are now in the appropriate output directory
            colmap_dir = results.get('colmap_path')
            if colmap_dir and os.path.exists(colmap_dir):
                if run_postshot:
                    output_folder_name = "postshot_input"
                    print(f"✅ COLMAP format created in {output_folder_name}: {colmap_dir}")
                    print(f"✅ Postshot will automatically find COLMAP files in: {vggt_output_dir}")
                    
                    # Create unified training folders for Postshot (and Brush if both selected)
                    try:
                        self._create_unified_training_folders(colmap_images_dir, colmap_dir, training_dir, settings)
                    except Exception as e:
                        print(f"⚠️ Warning: Could not create unified training folders: {e}")
                elif run_brush:
                    output_folder_name = "brush_input"
                    print(f"✅ COLMAP format created directly in {output_folder_name}: {colmap_dir}")
                    print(f"✅ Brush will find COLMAP files and images in: {vggt_output_dir}")
                    # No need for _create_unified_training_folders since we created brush_input directly
                else:
                    output_folder_name = "vggt_output"
                    print(f"✅ COLMAP format created in {output_folder_name}: {colmap_dir}")
                
                # Report filter results
                total_points = results.get('total_points', 0)
                print(f"✅ Filtered point cloud: {total_points:,} points with applied filters")
                print(f"   🎯 Filters applied: conf_thres={conf_thres}%, sky={mask_sky}, black_bg={mask_black_bg}, white_bg={mask_white_bg}")
                
                # 3D visualization popup now happens earlier during processing
                print(f"🌐 3D visualization already shown during processing")
            
            print(f"✅ VGGT alignment completed successfully!")

            self.app.progress_manager.complete_stage()
            return True
            
        except Exception as e:
            print(f"❌ VGGT alignment error: {e}")
            print(f"   {traceback.format_exc()}")
            return False

    def _create_unified_training_folders(self, views_dir, colmap_dir, training_dir, settings):
        """Create unified input folders for Brush and Postshot training with COLMAP files + images."""
        try:
            import shutil
            import glob
            from pathlib import Path
            
            print(f"\n📁 Creating unified training input folders...")
            
            # Get all image files from views directory (search in frame subdirectories only)
            
            image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
            image_files = []
            views_path = Path(views_dir)
            
            # Look for frame_XXXXX subdirectories specifically
            frame_dirs = list(views_path.glob("frame_*"))
            
            print(f"   🔍 DEBUG: Found frame directories: {[d.name for d in frame_dirs]}")
            print(f"   🔍 DEBUG: Views directory contents: {list(os.listdir(views_dir)) if os.path.exists(views_dir) else 'Directory not found'}")
            
            if frame_dirs:
                # If we have frame subdirectories, search only in those
                print(f"   📁 Searching in {len(frame_dirs)} frame subdirectories...")
                for frame_dir in frame_dirs:
                    if frame_dir.is_dir():
                        frame_images_before = len(image_files)
                        for ext in image_extensions:
                            image_files.extend(glob.glob(os.path.join(str(frame_dir), ext)))
                            image_files.extend(glob.glob(os.path.join(str(frame_dir), ext.upper())))
                        frame_images_added = len(image_files) - frame_images_before
                        print(f"      📂 {frame_dir.name}: Found {frame_images_added} images")
            else:
                # Fallback: search recursively if no frame directories found
                print(f"   🔍 No frame_* directories found, searching recursively...")
                recursive_images_before = len(image_files)
                for ext in image_extensions:
                    image_files.extend(glob.glob(os.path.join(views_dir, "**", ext), recursive=True))
                    image_files.extend(glob.glob(os.path.join(views_dir, "**", ext.upper()), recursive=True))
                recursive_images_added = len(image_files) - recursive_images_before
                print(f"   📂 Recursive search found {recursive_images_added} images")
            
            # Remove duplicates
            image_files = list(set(image_files))
            
            print(f"   📊 FINAL: Found {len(image_files)} unique images total")
            if len(image_files) > 0:
                print(f"   📝 Sample image paths:")
                for i, img_path in enumerate(image_files[:5]):  # Show first 5
                    print(f"      {i+1}. {img_path}")
                if len(image_files) > 5:
                    print(f"      ... and {len(image_files) - 5} more")
            
            # Create Brush input folder (if Brush training is enabled)
            if settings.get('run_brush', False):
                # Ensure training_dir (04_training) exists first
                os.makedirs(training_dir, exist_ok=True)
                brush_input_dir = os.path.join(training_dir, "brush_input")
                os.makedirs(brush_input_dir, exist_ok=True)
                
                # Copy COLMAP files (check for both .bin and .txt formats)
                colmap_files_to_copy = []
                
                # Check for .bin files first (VGGT format), then fallback to .txt (RealityScan format)
                for base_name in ['cameras', 'images', 'points3D']:
                    bin_file = os.path.join(colmap_dir, f"{base_name}.bin")
                    txt_file = os.path.join(colmap_dir, f"{base_name}.txt")
                    
                    if os.path.exists(bin_file):
                        colmap_files_to_copy.append((bin_file, f"{base_name}.bin"))
                    elif os.path.exists(txt_file):
                        colmap_files_to_copy.append((txt_file, f"{base_name}.txt"))
                
                for src_file, filename in colmap_files_to_copy:
                    dst_file = os.path.join(brush_input_dir, filename)
                    shutil.copy2(src_file, dst_file)
                
                # Copy all images
                for img_file in image_files:
                    dst_file = os.path.join(brush_input_dir, os.path.basename(img_file))
                    shutil.copy2(img_file, dst_file)
                
                print(f"   ✅ Created unified Brush input: {brush_input_dir}")
                print(f"      - {len(colmap_files_to_copy)} COLMAP files + {len(image_files)} images")
            
            # Create Postshot input folder (if Postshot training is enabled)
            if settings.get('run_postshot', False):
                postshot_input_dir = os.path.join(training_dir, "postshot_input")
                os.makedirs(postshot_input_dir, exist_ok=True)
                
                # Copy COLMAP files (check for both .bin and .txt formats)
                colmap_files_to_copy = []
                
                # Check for .bin files first (VGGT format), then fallback to .txt (RealityScan format)
                for base_name in ['cameras', 'images', 'points3D']:
                    bin_file = os.path.join(colmap_dir, f"{base_name}.bin")
                    txt_file = os.path.join(colmap_dir, f"{base_name}.txt")
                    
                    if os.path.exists(bin_file):
                        colmap_files_to_copy.append((bin_file, f"{base_name}.bin"))
                    elif os.path.exists(txt_file):
                        colmap_files_to_copy.append((txt_file, f"{base_name}.txt"))
                
                for src_file, filename in colmap_files_to_copy:
                    dst_file = os.path.join(postshot_input_dir, filename)
                    shutil.copy2(src_file, dst_file)
                
                # Copy all images
                copied_images = 0
                print(f"   📋 Copying {len(image_files)} images to postshot_input...")
                for img_file in image_files:
                    dst_file = os.path.join(postshot_input_dir, os.path.basename(img_file))
                    try:
                        shutil.copy2(img_file, dst_file)
                        copied_images += 1
                    except Exception as e:
                        print(f"      ⚠️ Failed to copy {img_file}: {e}")
                
                print(f"   ✅ Created unified Postshot input: {postshot_input_dir}")
                print(f"      - {len(colmap_files_to_copy)} COLMAP files + {copied_images}/{len(image_files)} images copied successfully")
                
        except Exception as e:
            print(f"   ⚠️ Warning: Failed to create unified training folders: {e}")

    def _run_training(self, views_dir, alignment_dir, training_dir, settings, item_idx, skip_realityscan=False):
        """ENHANCED: Training with Skip RealityScan support and independent execution of Postshot and Brush."""
        self.app.progress_manager.start_stage(4, "Training networks...")
        
        try:
            # Track results independently
            postshot_success = True  # Default to True if not running
            brush_success = True     # Default to True if not running
            
            # Check what the user wants to run
            run_postshot = settings.get('run_postshot', False)
            run_brush = settings.get('run_brush', False)
            vggt_was_used_for_alignment = skip_realityscan and settings.get('run_vggt', False)
            
            # NEW: Handle Skip RealityScan mode restrictions
            if skip_realityscan and run_brush and not vggt_was_used_for_alignment:
                print("⚠️ Skip RealityScan Mode: Brush training disabled (requires alignment)")
                run_brush = False  # Force disable Brush without alignment
            elif skip_realityscan and run_brush and vggt_was_used_for_alignment:
                print("✅ VGGT provided alignment - Brush training enabled")
            
            # Log the training mode
            if skip_realityscan:
                if vggt_was_used_for_alignment:
                    print(f"🎯 Training Mode: VGGT Alignment (Postshot + Brush available)")
                else:
                    print(f"🎯 Training Mode: Direct Postshot (no alignment)")
            else:
                print(f"🎯 Training Mode: RealityScan Pipeline (Postshot + Brush available)")
            
            # === CREATE UNIFIED TRAINING FOLDERS ===
            # For RealityScan mode: RealityScan already exports undistorted images + COLMAP to COLMAP_for_Brush
            # We just need to copy this to brush_input for consistency
            if not skip_realityscan and run_brush:
                try:
                    print("📁 Creating Brush input from RealityScan output...")
                    colmap_source_dir = os.path.join(alignment_dir, "COLMAP_for_Brush") if alignment_dir else None
                    if colmap_source_dir and os.path.exists(colmap_source_dir):
                        # Ensure training_dir (04_training) exists first
                        os.makedirs(training_dir, exist_ok=True)
                        brush_input_dir = os.path.join(training_dir, "brush_input")
                        import shutil
                        if os.path.exists(brush_input_dir):
                            shutil.rmtree(brush_input_dir)
                        shutil.copytree(colmap_source_dir, brush_input_dir)
                        print(f"✅ Copied RealityScan COLMAP + undistorted images to: {brush_input_dir}")
                    else:
                        print("⚠️ Warning: RealityScan COLMAP output not found")
                except Exception as e:
                    print(f"⚠️ Warning: Could not create Brush input from RealityScan: {e}")
            
            # For RealityScan + Postshot: Create postshot_input if needed  
            if not skip_realityscan and run_postshot:
                try:
                    print("📁 Creating Postshot input folder...")
                    postshot_input_dir = os.path.join(training_dir, "postshot_input")
                    os.makedirs(postshot_input_dir, exist_ok=True)
                    # Postshot uses registration.csv and pointcloud.ply (already in views_dir)
                    print(f"✅ Postshot input ready: {postshot_input_dir}")
                except Exception as e:
                    print(f"⚠️ Warning: Could not create Postshot input: {e}")
            
            if not run_postshot and not run_brush:
                # User didn't select either training method (or Brush was disabled)
                if skip_realityscan:
                    print("⚠️ Skip RealityScan Mode: No training methods available - Postshot must be enabled")
                    self.app.progress_manager.update_stage_details("Skip mode requires Postshot training")
                    self.app.progress_manager.complete_stage()
                    return False  # This is an error in skip mode
                else:
                    print("⚠️ No training methods selected - skipping training stage")
                    self.app.progress_manager.update_stage_details("No training methods selected")
                    self.app.progress_manager.complete_stage()
                    return True  # This is not an error, just user choice
            
            # === POSTSHOT TRAINING (Independent) ===
            if run_postshot:
                if skip_realityscan:
                    print("🚀 Starting Postshot training (Skip RealityScan mode - direct from views)")
                else:
                    print("🚀 Starting Postshot training (standard mode)")
                
                self.app.progress_manager.update_stage_details("Starting Postshot training...")
                
                try:
                    postshot_success = self._run_postshot_training(views_dir, training_dir, settings, skip_realityscan)
                    if postshot_success:
                        if skip_realityscan:
                            print("✅ Postshot training completed successfully (with internal alignment)")
                        else:
                            print("✅ Postshot training completed successfully")
                    else:
                        print("❌ Postshot training failed")
                except Exception as e:
                    print(f"❌ Postshot training error: {e}")
                    postshot_success = False
            else:
                if skip_realityscan:
                    print("❌ Skip RealityScan mode requires Postshot training")
                else:
                    print("⏩ Skipping Postshot training (not selected)")
            
            # === BRUSH TRAINING (Independent) ===
            if run_brush and (not skip_realityscan or vggt_was_used_for_alignment):
                print("🖌️ Starting Brush training (standard mode)")
                self.app.progress_manager.update_stage_details("Starting Brush training...")
                
                try:
                    brush_success = self._run_brush_training(alignment_dir, training_dir, settings)
                    if brush_success:
                        print("✅ Brush training completed successfully")
                    else:
                        print("❌ Brush training failed")
                except Exception as e:
                    print(f"❌ Brush training error: {e}")
                    brush_success = False
            elif run_brush and skip_realityscan:
                # This shouldn't happen due to GUI logic, but handle it gracefully
                print("🚫 Brush training skipped - requires RealityScan alignment (not available in skip mode)")
                brush_success = True  # Don't count this as a failure
            else:
                print("⏩ Skipping Brush training (not selected)")
            
            # === DETERMINE OVERALL SUCCESS ===
            # Success criteria: At least one selected method must succeed
            selected_methods = []
            successful_methods = []
            
            if run_postshot:
                selected_methods.append("Postshot")
                if postshot_success:
                    successful_methods.append("Postshot")
            
            if run_brush and (not skip_realityscan or vggt_was_used_for_alignment):
                selected_methods.append("Brush")
                if brush_success:
                    successful_methods.append("Brush")
            
            # Calculate overall success
            overall_success = len(successful_methods) > 0
            
            # === DETAILED RESULT REPORTING ===
            print(f"\n📊 TRAINING STAGE RESULTS:")
            if skip_realityscan:
                print(f"   Mode: Skip RealityScan (Postshot only)")
            print(f"   Selected methods: {', '.join(selected_methods) if selected_methods else 'None'}")
            print(f"   Successful methods: {', '.join(successful_methods) if successful_methods else 'None'}")
            
            if skip_realityscan and run_brush:
                print(f"   Note: Brush was disabled due to Skip RealityScan mode")
            
            if overall_success:
                if len(successful_methods) == len(selected_methods):
                    if skip_realityscan:
                        result_msg = f"Skip RealityScan training completed successfully ({', '.join(successful_methods)})"
                    else:
                        result_msg = f"All training methods completed successfully ({', '.join(successful_methods)})"
                    print(f"✅ {result_msg}")
                    self.app.progress_manager.update_stage_details(result_msg)
                else:
                    failed_methods = [m for m in selected_methods if m not in successful_methods]
                    result_msg = f"Partial success: {', '.join(successful_methods)} succeeded, {', '.join(failed_methods)} failed"
                    print(f"⚠️ {result_msg}")
                    self.app.progress_manager.update_stage_details(result_msg)
            else:
                if skip_realityscan and not run_postshot:
                    result_msg = "Skip RealityScan mode requires Postshot training"
                elif selected_methods:
                    result_msg = f"All training methods failed ({', '.join(selected_methods)})"
                else:
                    result_msg = "No training methods available"
                print(f"❌ {result_msg}")
                self.app.progress_manager.update_stage_details(result_msg)
            
            self.app.progress_manager.complete_stage()
            return overall_success
            
        except Exception as e:
            print(f"❌ Training coordination error: {e}")
            self.app.progress_manager.update_stage_details(f"Training error: {e}")
            return False

    def _run_postshot_training(self, views_dir, training_dir, settings, skip_realityscan=False):
        """ENHANCED: Postshot training with Skip RealityScan support, file-based success criteria and forced termination."""
        try:
            postshot_exe = settings['postshot_path'].replace('/', '\\')
            if not os.path.exists(postshot_exe): 
                raise FileNotFoundError(f"postshot-cli.exe not found at: {postshot_exe}")
            
            project_name = Path(training_dir).parent.name
            training_dir_clean = training_dir.replace('/', '\\')
            
            # Check if VGGT was used for alignment to determine input folder
            vggt_was_used = skip_realityscan and settings.get('run_vggt', False)
            if vggt_was_used:
                # Use unified folder created by VGGT alignment
                views_dir_clean = os.path.join(training_dir, "postshot_input").replace('/', '\\')
                print(f"🚀 Using VGGT unified input folder: {views_dir_clean}")
            else:
                # Use standard views directory
                views_dir_clean = views_dir.replace('/', '\\')
            
            # Expected output files
            postshot_file = f"{training_dir_clean}\\{project_name}_postshot.psht"
            ply_file = f"{training_dir_clean}\\{project_name}_postshot.ply" if settings.get('postshot_export_ply') else None
            
            print(f"\n🚀 POSTSHOT TRAINING:")
            print(f"   Mode: {'Skip RealityScan (Direct)' if skip_realityscan else 'Standard (with RealityScan alignment)'}")
            print(f"   Views directory: {views_dir_clean}")
            print(f"   Expected PSHT file: {os.path.basename(postshot_file)}")
            if ply_file:
                print(f"   Expected PLY file: {os.path.basename(ply_file)}")
            else:
                print(f"   PLY export: disabled")
            
            # NEW: Check input requirements based on mode
            if skip_realityscan:
                if vggt_was_used:
                    print("   🎯 VGGT Mode - Checking unified input folder...")
                    # Check for unified input folder with COLMAP files + images
                    if not os.path.exists(views_dir_clean):
                        raise FileNotFoundError(f"VGGT unified input folder not found: {views_dir_clean}")
                    
                    # Check for COLMAP files (either .bin or .txt format)
                    # Look in both the root directory and sparse/ subdirectory
                    required_colmap_files = ['cameras', 'images', 'points3D']
                    missing_files = []
                    found_format = None  # Track whether we found .bin or .txt files
                    sparse_dir = os.path.join(views_dir_clean, "sparse")
                    
                    for base_name in required_colmap_files:
                        # Check root directory first
                        bin_file = os.path.join(views_dir_clean, f"{base_name}.bin")
                        txt_file = os.path.join(views_dir_clean, f"{base_name}.txt")
                        
                        # Check sparse subdirectory if not found in root
                        bin_file_sparse = os.path.join(sparse_dir, f"{base_name}.bin")
                        txt_file_sparse = os.path.join(sparse_dir, f"{base_name}.txt")
                        
                        if os.path.exists(bin_file) or os.path.exists(bin_file_sparse):
                            if found_format is None:
                                found_format = '.bin'
                            elif found_format != '.bin':
                                missing_files.append(f"Mixed formats detected - expected all {found_format}")
                        elif os.path.exists(txt_file) or os.path.exists(txt_file_sparse):
                            if found_format is None:
                                found_format = '.txt'
                            elif found_format != '.txt':
                                missing_files.append(f"Mixed formats detected - expected all {found_format}")
                        else:
                            missing_files.append(f"{base_name}.bin or {base_name}.txt")
                    
                    if missing_files:
                        raise FileNotFoundError(f"Missing COLMAP files in unified folder: {missing_files}")
                    
                    print(f"   ✅ Found COLMAP files in {found_format} format")
                    
                    # Check for images (both root directory and images/ subdirectory)
                    import glob
                    image_files = []
                    images_dir = os.path.join(views_dir_clean, "images")
                    
                    for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
                        # Check root directory
                        image_files.extend(glob.glob(os.path.join(views_dir_clean, ext)))
                        # Check images subdirectory
                        if os.path.exists(images_dir):
                            image_files.extend(glob.glob(os.path.join(images_dir, ext)))
                    
                    if not image_files:
                        raise FileNotFoundError(f"No images found in unified input folder (checked root and images/ subdirectory): {views_dir_clean}")
                    
                    print(f"   ✅ Found {len(image_files)} images in unified folder")
                    print(f"   📋 Postshot will use VGGT alignment data")
                else:
                    print("   🎯 'Skip PreAlignment' Mode - Checking for extracted views...")
                    # Check for extracted views instead of registration files (original views_dir, not views_dir_clean)
                    frame_dirs = [d for d in Path(views_dir).iterdir() if d.is_dir()]
                    if not frame_dirs:
                        raise FileNotFoundError(f"No frame directories found in views directory: {views_dir}")
                    
                    print(f"   ✅ Found {len(frame_dirs)} frame directories with extracted views")
                    
                    # Check for actual view images in the first frame directory
                    sample_frame_dir = frame_dirs[0]
                    view_images = list(sample_frame_dir.glob("*.jpg")) + list(sample_frame_dir.glob("*.png"))
                    if not view_images:
                        raise FileNotFoundError(f"No view images found in frame directory: {sample_frame_dir}")
                    
                    print(f"   ✅ Sample frame has {len(view_images)} view images")
                    print(f"   📋 Postshot will handle alignment and reconstruction internally")
                
            else:
                print("   📐 Standard Mode - Checking for RealityScan outputs...")
                # Check required files from RealityScan (existing logic)
                registration_file = os.path.join(views_dir_clean, "registration.csv")
                pointcloud_file = os.path.join(views_dir_clean, "pointcloud.ply")
                
                print(f"   registration.csv: {'✅' if os.path.exists(registration_file) else '❌'}")
                print(f"   pointcloud.ply: {'✅' if os.path.exists(pointcloud_file) else '❌'}")
                
                if not os.path.exists(registration_file):
                    raise FileNotFoundError(f"Required registration.csv not found: {registration_file}")
                if not os.path.exists(pointcloud_file):
                    raise FileNotFoundError(f"Required pointcloud.ply not found: {pointcloud_file}")
            
            # Build command (same for both modes - Postshot auto-detects input type)
            command = [
                postshot_exe, "train",
                "--import", views_dir_clean,  # Postshot handles both registration files and raw views
                "--output", postshot_file,
                "--gpu", "0",
                "--profile", settings['postshot_profile'],
                "--max-image-size", str(settings['postshot_max_size']),
                "--train-steps-limit", str(settings['postshot_steps']),
                "--max-num-splats", str(settings['postshot_max_splats'])
            ]
            
            # Add optional flags
            if settings.get('postshot_aa'): command.append("--anti-aliasing=true")
            if settings.get('postshot_error'): command.append("--show-train-error")
            if settings.get('postshot_context'): command.append("--store-training-context")
            if settings.get('postshot_alpha_mask'): command.append("--treat-zero-alpha-as-mask=true")
            if settings.get('postshot_sky_model'): command.append("--create-sky-model")
            
            # Add PLY export if enabled
            if settings.get('postshot_export_ply'):
                command.extend(["--export-splat-ply", ply_file])
            
            # NEW: Add mode-specific information to command display
            mode_info = " (Skip RealityScan - VGGT mode)" if skip_realityscan else " (Standard)"
            print(f"   Starting Postshot process{mode_info}...")
            
            # Display command for debugging (optional)
            if skip_realityscan:
                print(f"   💡 Command will process raw 360° views directly, either VGGT or Postshot internally")
            else:
                print(f"   💡 Command will use RealityScan registration and point cloud")
            
            # Start process
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # Monitor process output and check for files periodically
            training_complete = False
            check_interval = 5  # Check files every 5 seconds
            last_file_check = time.time()
            
            try:
                # Read output line by line with timeout
                for line in iter(process.stdout.readline, ''):
                    if self.state.cancel_event.is_set():
                        print("🛑 Cancelling Postshot training...")
                        process.terminate()
                        return False
                        
                    line = line.strip()
                    if line:
                        # NEW: Add mode prefix to output for clarity
                        mode_prefix = "Postshot(Skip)" if skip_realityscan else "Postshot"
                        print(f"   {mode_prefix}: {line}")
                        self.app.progress_manager.update_stage_details(f"{mode_prefix}: {line}")
                    
                    # Periodic file check
                    current_time = time.time()
                    if current_time - last_file_check >= check_interval:
                        if self._check_postshot_completion(postshot_file, ply_file):
                            completion_msg = "Skip mode training complete!" if skip_realityscan else "Standard training complete!"
                            print(f"   🎯 Postshot files detected - {completion_msg}")
                            training_complete = True
                            break
                        last_file_check = current_time
                
                # Final file check if not already detected
                if not training_complete:
                    training_complete = self._check_postshot_completion(postshot_file, ply_file)
            
            except Exception as e:
                print(f"   ❌ Error during Postshot monitoring: {e}")
            
            # Wait up to 30 seconds for process to finish, then force kill
            print(f"   ⏱️ Waiting up to 30 seconds for process completion...")
            try:
                return_code = process.wait(timeout=30)
                print(f"   ✅ Process completed with exit code: {return_code}")
            except subprocess.TimeoutExpired:
                print(f"   ⏰ 30-second timeout reached - force killing process...")
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"   🔪 Process killed forcefully")
            
            # Final success check based on files only
            final_success = self._check_postshot_completion(postshot_file, ply_file)
            
            if final_success:
                if skip_realityscan:
                    print("   ✅ Postshot training completed successfully (with internal alignment)!")
                else:
                    print("   ✅ Postshot training completed successfully!")
            else:
                error_msg = "Skip mode training failed" if skip_realityscan else "Standard training failed"
                print(f"   ❌ {error_msg} - required files not found")
            
            return final_success
                
        except Exception as e:
            mode_context = " (Skip RealityScan mode)" if skip_realityscan else " (Standard mode)"
            print(f"❌ Postshot training error{mode_context}: {e}")
            return False

    def _check_postshot_completion(self, postshot_file, ply_file):
        """Check if Postshot has completed successfully based on output files."""
        success = True
        
        # Check required PSHT file
        if os.path.exists(postshot_file):
            psht_size = os.path.getsize(postshot_file)
            print(f"   ✅ PSHT file found: {os.path.basename(postshot_file)} ({psht_size:,} bytes)")
        else:
            print(f"   ❌ PSHT file missing: {os.path.basename(postshot_file)}")
            success = False
        
        # Check PLY file if required
        if ply_file:  # PLY export was enabled
            if os.path.exists(ply_file):
                ply_size = os.path.getsize(ply_file)
                print(f"   ✅ PLY file found: {os.path.basename(ply_file)} ({ply_size:,} bytes)")
            else:
                print(f"   ❌ PLY file missing: {os.path.basename(ply_file)}")
                success = False
        
        return success

    def _run_brush_training(self, alignment_dir, training_dir, settings):
        """FIXED: Brush training with non-blocking monitoring and proper process cleanup."""
        
        # Store process references before starting
        rerun_processes_before = self._get_rerun_processes()
        brush_processes_before = self._get_brush_processes()
        
        if brush_processes_before:
            print(f"📋 Detected {len(brush_processes_before)} existing Brush process(es)")
        
        try:
            brush_exe = settings['brush_path'].replace('/', '\\')
            if not os.path.exists(brush_exe): 
                raise FileNotFoundError(f"brush_app.exe not found at: {brush_exe}")
            
            project_name = Path(training_dir).parent.name
            
            # Always use unified brush_input folder (created by _create_unified_training_folders)
            colmap_folder = os.path.join(training_dir, "brush_input").replace('/', '\\')
            print(f"🖌️ Using unified Brush input folder: {colmap_folder}")
            training_dir_clean = training_dir.replace('/', '\\')
            
            # Get training parameters
            total_steps = settings.get('brush_total_steps', 30000)
            export_every = settings.get('brush_export_every', 5000)
            show_viewer = settings.get('brush_viewer', False)
            
            # Calculate expected final file
            export_name_template = settings.get('brush_export_name', f"{project_name}_brush_{{iter}}.ply")
            final_step_file = export_name_template.format(iter=total_steps)
            final_file_path = os.path.join(training_dir_clean, final_step_file)
            
            print(f"\n🖌️ BRUSH TRAINING:")
            print(f"   Total steps: {total_steps}")
            print(f"   Export every: {export_every} steps")
            print(f"   Expected final file: {final_step_file}")
            print(f"   Viewer mode: {'📺 ENABLED' if show_viewer else '🤖 HEADLESS'}")

            # Build command
            command = [
                brush_exe, colmap_folder,
                "--total-steps", str(total_steps),
                "--max-splats", str(settings.get('brush_max_splats', 100000)), 
                "--max-resolution", str(settings.get('brush_max_resolution', 1920)),
                "--seed", str(settings.get('brush_seed', 42)),
                "--export-path", training_dir_clean,
                "--export-every", str(export_every),
                "--export-name", export_name_template
            ]
            
            # Add optional flags
            if settings.get('brush_rerun', False): 
                command.append("--rerun-enabled")
            
            if show_viewer:
                command.append("--with-viewer")
            
            print(f"   Starting Brush process...")
            
            # Start process
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                cwd=training_dir_clean
            )
            
            print(f"   ✅ Brush process started (PID: {process.pid})")
            
            # FIXED: Use non-blocking monitoring
            check_interval = 10 if show_viewer else 5
            training_complete = self._monitor_brush_nonblocking(
                process, final_file_path, total_steps, check_interval
            )
            
            # FIXED: Force close viewer windows if training completed
            if training_complete:
                if show_viewer:
                    print(f"   🪟 Training completed - closing viewer windows...")
                    self._close_brush_viewer_windows()
                    time.sleep(5)  # Give viewer time to close
                else:
                    print(f"   ✅ Training completed in headless mode")
            
            # Wait briefly for process to finish naturally
            timeout_duration = 30
            print(f"   ⏱️ Waiting up to {timeout_duration} seconds for process completion...")
            
            try:
                return_code = process.wait(timeout=timeout_duration)
                print(f"   ✅ Process completed with exit code: {return_code}")
            except subprocess.TimeoutExpired:
                print(f"   ⏰ Timeout reached - force killing process...")
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"   🔪 Process killed forcefully")
            
            # FIXED: Clean up ALL brush and rerun processes
            print(f"   🧹 Cleaning up processes...")
            self._terminate_brush_processes(brush_processes_before)
            self._terminate_rerun_processes(rerun_processes_before)
            
            # Final success check
            final_success = self._check_brush_completion(final_file_path, total_steps)
            
            if final_success:
                print("   ✅ Brush training completed successfully!")
            else:
                print("   ❌ Brush training failed - final PLY file not found")
            
            return final_success
                
        except Exception as e:
            print(f"❌ Brush training error: {e}")
            return False
        
    def _check_brush_completion(self, final_file_path, total_steps):
        """Check if Brush has completed successfully based on final PLY file."""
        if os.path.exists(final_file_path):
            file_size = os.path.getsize(final_file_path)
            if file_size > 1000:  # At least 1KB
                print(f"   ✅ Final PLY file found: {os.path.basename(final_file_path)} ({file_size:,} bytes)")
                print(f"   🎯 Brush training completed at {total_steps} steps")
                return True
            else:
                print(f"   ❌ Final PLY file too small: {file_size} bytes")
                return False
        else:
            print(f"   ❌ Final PLY file not found: {os.path.basename(final_file_path)}")
            return False

    def cleanup_brush_processes(self, brush_exe_path):
        """Enhanced cleanup for brush processes, especially with viewer mode."""
        try:
            brush_name = os.path.basename(brush_exe_path).lower()
            killed_count = 0
            
            print(f"   🔍 Looking for brush processes to clean up...")
            
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    proc_info = proc.info
                    
                    # Check if this is a brush process
                    is_brush_process = False
                    
                    if proc_info['name'] and brush_name in proc_info['name'].lower():
                        is_brush_process = True
                    elif proc_info['exe'] and brush_exe_path.lower() in proc_info['exe'].lower():
                        is_brush_process = True
                    elif proc_info['cmdline']:
                        cmdline_str = ' '.join(proc_info['cmdline']).lower()
                        if brush_name in cmdline_str or 'brush' in cmdline_str:
                            is_brush_process = True
                    
                    if is_brush_process:
                        print(f"   🗑️ Terminating brush process: PID {proc_info['pid']} ({proc_info['name']})")
                        proc.terminate()
                        
                        # Wait for graceful shutdown
                        try:
                            proc.wait(timeout=5)
                            killed_count += 1
                            print(f"   ✅ Process {proc_info['pid']} terminated gracefully")
                        except psutil.TimeoutExpired:
                            print(f"   🔪 Force killing stubborn process: PID {proc_info['pid']}")
                            proc.kill()
                            killed_count += 1
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    pass
            
            if killed_count > 0:
                print(f"   ✅ Cleaned up {killed_count} brush process(es)")
            else:
                print(f"   ℹ️ No brush processes found to clean up")
                    
            time.sleep(2)  # Brief pause to ensure cleanup
            
        except Exception as e:
            print(f"   ⚠️ Viewer cleanup warning: {e}")

    def _get_brush_processes(self):
        """Get all currently running Brush-related processes."""
        import psutil
        brush_processes = []
        
        # Based on observation: brush_app.exe (main) with "Brush" subprocess
        brush_indicators = [
            'brush_app.exe',
            'brush_app',
            'brush.exe', 
            'brush'
        ]
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    proc_info = proc.info
                    is_brush_process = False
                    
                    # Check process name
                    if proc_info['name']:
                        for indicator in brush_indicators:
                            if indicator.lower() in proc_info['name'].lower():
                                is_brush_process = True
                                break
                    
                    # Check executable path  
                    if not is_brush_process and proc_info['exe']:
                        exe_name = os.path.basename(proc_info['exe']).lower()
                        for indicator in brush_indicators:
                            if indicator.lower() in exe_name:
                                is_brush_process = True
                                break
                    
                    if is_brush_process:
                        brush_processes.append(proc.pid)
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        
        except Exception as e:
            print(f"⚠️ Warning: Could not enumerate Brush processes: {e}")
        
        return list(set(brush_processes))

    def _terminate_brush_processes(self, processes_before):
        """Terminate new Brush processes using same method as Rerun cleanup."""
        import psutil
        
        current_brush_processes = self._get_brush_processes()
        new_brush_processes = [pid for pid in current_brush_processes if pid not in processes_before]
        
        if not new_brush_processes:
            print("ℹ️ No new Brush processes to terminate")
            return
        
        print(f"🧹 Terminating {len(new_brush_processes)} Brush process(es)")
        
        terminated_count = 0
        for pid in new_brush_processes:
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                print(f"   🗑️ Terminating Brush process: PID {pid} ({proc_name})")
                
                # Try graceful termination first
                proc.terminate()  # SIGTERM
                
                try:
                    proc.wait(timeout=5)  # Wait up to 5 seconds
                    terminated_count += 1
                    print(f"   ✅ Process {pid} terminated gracefully")
                except psutil.TimeoutExpired:
                    print(f"   🔪 Force killing stubborn process: PID {pid}")
                    proc.kill()  # SIGKILL
                    terminated_count += 1
                    
            except psutil.NoSuchProcess:
                print(f"   ℹ️ Process {pid} already terminated")
                terminated_count += 1
            except psutil.AccessDenied:
                print(f"   ⚠️ Access denied to terminate process {pid}")
            except Exception as e:
                print(f"   ❌ Error terminating process {pid}: {e}")
        
        if terminated_count > 0:
            print(f"✅ Cleaned up {terminated_count} Brush process(es)")

    def _monitor_brush_nonblocking(self, process, final_file_path, total_steps, check_interval):
        """
        FIXED: Non-blocking monitoring that doesn't hang waiting for stdout.
        Monitors file completion while optionally reading available output.
        """
        import queue
        import threading
        
        training_complete = False
        last_file_check = time.time()
        output_queue = queue.Queue()
        
        def read_output():
            """Background thread to read process output without blocking main thread."""
            try:
                for line in iter(process.stdout.readline, ''):
                    if line.strip():
                        output_queue.put(line.strip())
                output_queue.put("PROCESS_OUTPUT_ENDED")
            except Exception as e:
                output_queue.put(f"OUTPUT_ERROR: {e}")
        
        # Start output reader thread
        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()
        
        print(f"   🎯 Monitoring Brush training progress...")
        
        # Main monitoring loop - checks both output and file completion
        while process.poll() is None:  # While process is still running
            # Check for cancellation
            if self.state.cancel_event.is_set():
                print("🛑 Cancelling Brush training...")
                return False
            
            # Read any available output (non-blocking)
            try:
                while True:
                    line = output_queue.get_nowait()
                    if line == "PROCESS_OUTPUT_ENDED":
                        print(f"   📝 Brush output stream ended")
                        break
                    elif line.startswith("OUTPUT_ERROR:"):
                        print(f"   ⚠️ {line}")
                    else:
                        print(f"   Brush: {line}")
                        self.app.progress_manager.update_stage_details(f"Brush: {line}")
            except queue.Empty:
                pass
            
            # CRITICAL: Check for completion file regularly
            current_time = time.time()
            if current_time - last_file_check >= check_interval:
                if self._check_brush_completion(final_file_path, total_steps):
                    print(f"   🎯 Brush completion file detected!")
                    training_complete = True
                    break
                else:
                    # Show progress update even without console output
                    progress_info = self._get_brush_progress_info(final_file_path, total_steps)
                    if progress_info:
                        print(f"   📊 {progress_info}")
                        
                last_file_check = current_time
            
            # Small sleep to prevent busy waiting
            time.sleep(2)
        
        return training_complete

    def _get_brush_progress_info(self, final_file_path, total_steps):
        """Get progress information from intermediate files."""
        try:
            training_dir = os.path.dirname(final_file_path)
            if not os.path.exists(training_dir):
                return None
                
            ply_files = [f for f in os.listdir(training_dir) if f.endswith('.ply')]
            
            if not ply_files:
                return "No PLY files found yet"
            
            # Look for files with step numbers
            max_step = 0
            latest_file = None
            for ply_file in ply_files:
                import re
                step_match = re.search(r'_(\d+)\.ply$', ply_file)
                if step_match:
                    step = int(step_match.group(1))
                    if step > max_step:
                        max_step = step
                        latest_file = ply_file
            
            if max_step > 0:
                progress_pct = (max_step / total_steps) * 100
                return f"Progress: ~{max_step}/{total_steps} steps ({progress_pct:.1f}%) - Latest: {latest_file}"
            else:
                return f"Found {len(ply_files)} PLY file(s), checking for step numbers..."
                
        except Exception as e:
            return f"Progress check error: {e}"

    def _close_brush_viewer_windows(self):
        """Force close Brush viewer windows to prevent hanging."""
        try:
            if os.name == 'nt':  # Windows
                # Try using tasklist/taskkill for Windows
                try:
                    import subprocess
                    # Kill any windows with "brush" in the title
                    subprocess.run(['taskkill', '/F', '/IM', 'brush*'], 
                                capture_output=True, timeout=10)
                    print(f"   🪟 Attempted to close Brush viewer windows")
                except Exception as e:
                    print(f"   ⚠️ Could not close viewer windows: {e}")
            else:
                # Linux/Mac - try to close brush-related windows
                try:
                    subprocess.run(['pkill', '-f', 'brush'], capture_output=True, timeout=10)
                    print(f"   🪟 Attempted to close Brush processes")
                except Exception as e:
                    print(f"   ⚠️ Could not close processes: {e}")
        except Exception as e:
            print(f"   ⚠️ Viewer window cleanup failed: {e}")

    def _get_rerun_processes(self):
        """Get all currently running Rerun-related processes."""
        import psutil
        rerun_processes = []
        
        # Based on Task Manager observation: rerun.exe (main) with "rerun viewer" subprocesses
        rerun_indicators = [
            'rerun.exe',
            'rerun',
            'rerun viewer',
            'rerun_viewer'
        ]
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    proc_info = proc.info
                    is_rerun_process = False
                    
                    # Check process name
                    if proc_info['name']:
                        for indicator in rerun_indicators:
                            if indicator.lower() in proc_info['name'].lower():
                                is_rerun_process = True
                                break
                    
                    # Check executable path
                    if not is_rerun_process and proc_info['exe']:
                        exe_name = os.path.basename(proc_info['exe']).lower()
                        for indicator in rerun_indicators:
                            if indicator.lower() in exe_name:
                                is_rerun_process = True
                                break
                    
                    # Check command line
                    if not is_rerun_process and proc_info['cmdline']:
                        cmdline_str = ' '.join(proc_info['cmdline']).lower()
                        for indicator in rerun_indicators:
                            if indicator.lower() in cmdline_str:
                                is_rerun_process = True
                                break
                    
                    if is_rerun_process:
                        rerun_processes.append(proc.pid)
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have disappeared while we were checking it
                    continue
        
        except Exception as e:
            print(f"⚠️ Warning: Could not enumerate Rerun processes: {e}")
        
        return list(set(rerun_processes))  # Remove duplicates

    def _terminate_rerun_processes(self, processes_before):
        """Terminate Rerun processes that started after the given baseline."""
        import psutil
        
        current_rerun_processes = self._get_rerun_processes()
        new_rerun_processes = [pid for pid in current_rerun_processes if pid not in processes_before]
        
        if not new_rerun_processes:
            print("ℹ️ No new Rerun processes to terminate")
            return
        
        print(f"🧹 Terminating {len(new_rerun_processes)} Rerun viewer process(es)")
        
        terminated_count = 0
        for pid in new_rerun_processes:
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                print(f"   🗑️ Terminating Rerun process: PID {pid} ({proc_name})")
                
                # Try graceful termination first (same pattern as Brush cleanup)
                proc.terminate()  # SIGTERM
                
                try:
                    proc.wait(timeout=5)  # Wait up to 5 seconds for graceful shutdown
                    terminated_count += 1
                    print(f"   ✅ Process {pid} terminated gracefully")
                except psutil.TimeoutExpired:
                    print(f"   🔪 Force killing stubborn process: PID {pid}")
                    proc.kill()  # SIGKILL
                    terminated_count += 1
                    
            except psutil.NoSuchProcess:
                print(f"   ℹ️ Process {pid} already terminated")
                terminated_count += 1
            except psutil.AccessDenied:
                print(f"   ⚠️ Access denied to terminate process {pid}")
            except Exception as e:
                print(f"   ❌ Error terminating process {pid}: {e}")
        
        if terminated_count > 0:
            print(f"✅ Cleaned up {terminated_count} Rerun process(es)")

    # --- Utility and File Dialog Callbacks ---

    def _reset_all_previews_and_caches(self):
        """
        NEW: A master reset function that clears all visual and data caches.
        """
        print("🔄 Performing full preview and cache reset.")
        # 1. Tell the VisualsManager to reset its state (pano, overlays, etc.)
        if self.visuals:
            self.visuals._reset_preview_to_initial_state()
        
        # 2. Tell the ExtractionFrameManager to clear its cache and reset its UI
        if self.extraction_manager:
            self.extraction_manager.clear_cache()
        
        # 3. Reset the content info labels in the main GUI
        self.state.content_info_var.set("No content selected")
        self.state.content_details_var.set("--")

    def _sanitize_project_name(self, raw_name):
        """Sanitize project name for file system compatibility."""
        import re
        
        # Remove illegal file system characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '', raw_name)
        
        # Replace spaces and multiple whitespace with underscores
        sanitized = re.sub(r'\s+', '_', sanitized)
        
        # Remove leading/trailing dots, underscores, spaces
        sanitized = sanitized.strip('._' + ' ')
        
        # Ensure we have something
        if not sanitized:
            sanitized = "RS_project"
        
        # Limit length to avoid filesystem issues
        if len(sanitized) > 100:
            sanitized = sanitized[:100].rstrip('_')
        
        print(f"Sanitized '{raw_name}' -> '{sanitized}'")
        return sanitized

    def save_all_settings(self, settings_to_save=None, show_success_message=False):
        """
        MODIFIED: Can now save a specific dictionary of settings, not just the current UI state.
        """
        try:
            # If a specific settings dictionary is provided, use it. Otherwise, get settings from the UI.
            settings_data = settings_to_save or self.app.get_current_settings()
            
            # The settings_manager handles the actual file writing
            settings_manager.save_settings(settings_data, _common_utils.CONFIG_FILE)
            
            if show_success_message:
                messagebox.showinfo("Success", "Settings saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def browse_file_path(self, var):
        path = filedialog.askopenfilename()
        if path: var.set(path)

    def browse_folder_path(self, var):
        path = filedialog.askdirectory()
        if path: var.set(path)

    def select_project_dir(self):
        directory = filedialog.askdirectory(title="Select Project Directory")
        if directory:
            self.state.project_dir.set(directory)
            self.check_if_ready()

    def handle_pipeline_completion(self, result=None):
        """ENHANCED: Handle pipeline completion with proper status reset."""
        def _complete_on_main_thread():
            self.state.processing = False
            self.app.run_pipeline_button.config(state='normal')
            
            # Show completion message briefly
            if result and result.get('errors'):
                error_count = len(result['errors'])
                completion_msg = f"Pipeline completed with {error_count} error(s)"
                messagebox.showwarning("Pipeline Complete with Errors", completion_msg)
            else:
                completion_msg = "Pipeline completed successfully!"
                messagebox.showinfo("Pipeline Complete", completion_msg)
            
            # After completion dialog, update status based on current queue
            self.app.root.after(1000, self.app.update_queue_status_and_progress_bars)
            
            self.check_if_ready()
        
        # Ensure UI updates happen on main thread
        self.app.root.after(0, _complete_on_main_thread)

    def on_closing(self):
        """
        ENHANCED: Clean shutdown with cache maintenance and settings save.
        """
        if self.state.processing:
            if not messagebox.askyesno("Confirm Quit", "A pipeline is currently running. Are you sure you want to quit?"):
                return

        # === ENHANCED: Add cache maintenance on close ===
        print("🧹 Performing shutdown cache maintenance...")
        try:
            self.maintenance_cleanup_cache()
            print("✅ Shutdown cache maintenance completed")
        except Exception as e:
            print(f"⚠️ Cache maintenance failed during shutdown: {e}")
            # Don't block shutdown for cache maintenance failure

        result = messagebox.askyesnocancel("Save Settings", "Save settings as the new default before quitting?")
        
        if result is None: # User clicked Cancel
            return
            
        elif result is True: # User clicked Yes
            settings_from_first_video = None
            
            # Check if the per-video cache and video queue exist and are not empty
            if hasattr(self.state, 'per_video_settings_cache') and self.state.video_queue:
                first_video_path = self.state.video_queue[0]
                # Try to get the cached settings for the first video
                settings_from_first_video = self.state.per_video_settings_cache.get(first_video_path)

            if settings_from_first_video:
                print(f"💾 Saving settings from the first video in the queue: {os.path.basename(first_video_path)}")
                self.save_all_settings(settings_to_save=settings_from_first_video)
            else:
                print("💾 No per-video settings found for the first item. Saving current UI settings as default.")
                self.save_all_settings() # Fallback to the original behavior

        # === ENHANCED: Optional deep cache cleanup ===
        # Uncomment if you want more aggressive cleanup on shutdown
        # try:
        #     print("🧹 Performing deep cache cleanup...")
        #     self.clear_preview_cache()  # More aggressive - removes ALL preview cache
        #     print("✅ Deep cache cleanup completed")
        # except Exception as e:
        #     print(f"⚠️ Deep cache cleanup failed: {e}")

        # Save current window position before closing
        try:
            geometry = self.app.root.geometry()
            # Parse geometry string like "1520x1150+100+200"
            size_pos = geometry.split('+')
            if len(size_pos) >= 3:
                window_x = int(size_pos[1])
                window_y = int(size_pos[2])
                
                # Get current window size
                size_part = size_pos[0].split('x')
                if len(size_part) == 2:
                    window_width = int(size_part[0])
                    window_height = int(size_part[1])
                    
                    # Update settings with current window position/size
                    current_settings = settings_manager.load_settings(_common_utils.CONFIG_FILE)
                    current_settings.update({
                        'window_x': window_x,
                        'window_y': window_y,
                        'window_width': window_width,
                        'window_height': window_height
                    })
                    
                    # Save window position regardless of user's choice about other settings
                    settings_manager.save_settings(current_settings, _common_utils.CONFIG_FILE)
                    print(f"💾 Saved window position: {window_width}x{window_height}+{window_x}+{window_y}")
        except Exception as e:
            print(f"⚠️ Failed to save window position: {e}")
        
        # Restore console and close the application
        self.app.restore_stdout()
        self.app.root.destroy()
