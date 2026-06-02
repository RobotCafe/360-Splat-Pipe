# app_visuals.py

import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk
import numpy as np
import threading
import traceback
import os
from typing import Tuple, Optional, List
import time


try:
    from py360convert import e2p
except ImportError:
    print("WARNING: py360convert is not installed. Live preview features will fail.")


class VisualsManager:
    """
    Manages all visual components of the Pipeline GUI, including the main
    panorama canvas, overlay drawing, thumbnail generation, and live preview updates.
    """
    def __init__(self, app, state, callbacks):
        """
        Initializes the VisualsManager.

        Args:
            app: The main PipelineGUI instance (for accessing widgets).
            state: The shared AppState instance.
            callbacks: The CallbacksManager instance.
        """
        # === Core References ===
        self.app = app
        self.state = state
        self.callbacks = callbacks

        # === Display State ===
        self.current_display_tk = None
        self.current_preview_source_np = None
        self.base_display_img = None
        self.canvas_image_id = None
        self.preview_img = None

        # === Overlay Management ===
        self.overlay_items = []
        self.selected_item = None

        # === Thumbnail System ===
        self.thumbnail_generation_id = 0
        self._processed_thumbnails = {}
        self.thumbnails_complete = False
        self.expected_thumbnail_count = 0
        self.received_thumbnail_count = 0
        self.thumbnails_frozen = False

        # === Preview State ===
        self._last_preview_size = None

        # === Timers ===
        self.parameter_update_timer = None
        self._preview_update_timer = None
        
        # === Constants ===
        self.parameter_update_delay = 1000

        # REMOVE UNUSED:
        # self._last_reported_progress = {}      # ❌ UNUSED
        # self._expected_overlay_count = {}      # ❌ UNUSED
        # self._auto_selected_generations = set() # ❌ UNUSED


        print("✅ VisualsManager initialized (extraction-focused edition)")   




    def _reset_preview_to_initial_state(self):
        """Resets the view to the initial blank state with text."""
        self._reset_all_views_and_cancel_jobs()
        self.app.source_canvas.config(width=800, height=400)
        self.app.source_canvas.create_text(
            400, 200,
            text="Load a video or image folder to begin preview\n\n\n\nHelp Menu in top-left corner for more info",
            font=("Arial", 14, "bold"),
            fill="gray50",
            justify="center"  # Center-align the text
        )

    # -- Caching systems --

    def _generate_settings_hash(self):
        """Generate a hash of current view extraction settings."""
        settings_str = f"{self.app.pitch_angles_str_var.get()}|{self.app.yaw_steps_var.get()}|{self.app.fov_var.get()}"
        return hash(settings_str)
    
    def _get_content_key(self, content_path):
        """Generate enhanced content key including file modification time."""
        settings_hash = self._generate_settings_hash()
        
        # Include file modification time to detect changes
        try:
            if os.path.isfile(content_path):
                # For video files, use the video file mtime
                mtime = os.path.getmtime(content_path)
            else:
                # For folders, use the newest file mtime
                files = [os.path.join(content_path, f) for f in os.listdir(content_path)
                        if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                if files:
                    mtime = max(os.path.getmtime(f) for f in files)
                else:
                    mtime = os.path.getmtime(content_path)
            
            mtime_str = str(int(mtime))
        except Exception:
            mtime_str = "unknown"
        
        return f"{content_path}#{settings_hash}#{mtime_str}"
    
    def load_view(self, content_path, content_pil_image):
        """
        NEW: The primary, intelligent entry point for loading any new content.
        It handles saving the previous view to the cache and restoring the new
        view from cache if it exists.
        """
        # 1. Generate the unique key for the new content based on its path and settings
        content_key = self._get_content_key(content_path)
        
        # === CRITICAL: Always cleanup first, regardless of cache state ===
        print(f"🧹 Pre-load cleanup for: {os.path.basename(content_path)}")
        self._cleanup_existing_overlays()

        # If this exact view is already displayed, do nothing.
        if content_key == self.state.current_content_key and self.overlay_items:
            print(f"✅ Content already loaded with current settings.")
            return

        # 2. Before switching, save the current view (if any) to the cache.
        if self.state.current_content_key and self.overlay_items:
            self._cache_current_content()

        self.state.current_content_key = content_key
        
        # 3. Try to restore the new view from the cache.
        # We need to display the base image first before restoring overlays on top of it.
        self._initiate_new_preview_from_pil(content_pil_image)
        
        if self._validate_cache_integrity(content_key) and self._restore_from_cache(content_key):
            print(f"✅ Restored complete thumbnail/overlay set from cache.")
            return

        # 4. CACHE MISS: If not found in cache, generate a fresh view.
        print(f"ⓘ No valid thumbnail cache found for {os.path.basename(content_path)}. Generating fresh.")
        self.update_visual_overlays()

    def _validate_cache_integrity(self, content_key):
        """Validate that cached content is still valid."""
        if content_key not in self.state.content_cache:
            return False
        
        cached_data = self.state.content_cache[content_key]
        
        # Check if cache is too old (optional: expire after 24 hours)
        cache_age = time.time() - cached_data.get('cached_at', 0)
        if cache_age > 86400:  # 24 hours
            print(f"Cache expired for: {content_key}")
            del self.state.content_cache[content_key]
            return False
        
        # Validate that we have the expected data structure
        required_keys = ['overlay_items', 'thumbnail_canvases_data', 'cached_at']
        if not all(key in cached_data for key in required_keys):
            print(f"Invalid cache structure for: {content_key}")
            del self.state.content_cache[content_key]
            return False
        
        return True

    def _cache_current_content(self):
        """Cache the current rendered content with full thumbnail data."""
        if not self.state.current_content_key or not self.overlay_items:
            return
            
        print(f"💾 SAVING to cache: {len(self.overlay_items)} items")
        
        # Store complete thumbnail data for restoration
        cached_data = {
            'overlay_items': [],
            'thumbnail_canvases_data': {},
            'base_image_size': self.base_display_img.size if self.base_display_img else None,
            'cached_at': time.time()
        }
        
        # Cache overlay items with proper image data handling
        for item in self.overlay_items:
            try:
                # FIXED: Check for PIL image in the correct location
                if 'image' in item and item['image'] is not None:
                    pil_image = item['image']
                    # Store as bytes and size info
                    image_bytes = pil_image.tobytes()
                    image_size = pil_image.size
                    image_mode = pil_image.mode
                    
                    cached_item = {
                        'pitch': item['pitch'],
                        'yaw': item['yaw'], 
                        'index': item['index'],
                        'full_color': item['full_color'],
                        'shaded_color': item['shaded_color'],
                        'image_bytes': image_bytes,
                        'image_size': image_size,
                        'image_mode': image_mode
                    }
                    cached_data['overlay_items'].append(cached_item)
                    
                else:
                    print(f"⚠️ No image data found for item {item.get('index', 'unknown')}")
                    continue
                    
            except Exception as e:
                print(f"❌ Failed to cache item {item.get('index', 'unknown')}: {e}")
                continue
        
        # Cache canvas structure (which pitch angles exist)
        for pitch, canvas in self.app.thumbnail_canvases.items():
            cached_data['thumbnail_canvases_data'][pitch] = {
                'pitch': pitch,
                'exists': True
            }
        
        self.state.content_cache[self.state.current_content_key] = cached_data
        
        print(f"✅ CACHED: {len(cached_data['overlay_items'])} items with image data")
        
        # Debug: Show what was cached
        # for i, item in enumerate(cached_data['overlay_items'][:3]):  # Show first 3 items
        #     print(f"   [{i}] Pitch:{item['pitch']}, Yaw:{item['yaw']}, ImageSize:{item.get('image_size', 'Missing')}")
        
        # Limit cache size to prevent memory issues
        if len(self.state.content_cache) > self.state.cache_max_size:
            oldest_key = min(self.state.content_cache.keys(), 
                        key=lambda k: self.state.content_cache[k]['cached_at'])
            del self.state.content_cache[oldest_key]
            print(f"Removed oldest cache entry: {oldest_key}")

    def _restore_from_cache(self, content_key):
        """Fully restore content from cache."""
        if content_key not in self.state.content_cache:
            print(f"🚫 No cache entry for: {content_key}")
            return False
            
        print(f"🔄 Restoring thumbnails from cache for: {content_key}")
        cached_data = self.state.content_cache[content_key]
        
        # Validate cache structure
        if 'overlay_items' not in cached_data or not cached_data['overlay_items']:
            print(f"⚠️ CACHE_CORRUPT: No overlay items in cache")
            return False
        
        try:
            # Clear existing overlays
            for item in self.overlay_items:
                if (self.app.source_canvas.winfo_exists() and 
                    item.get('rect_id') and 
                    item['rect_id'] in self.app.source_canvas.find_all()):
                    self.app.source_canvas.delete(item['rect_id'])
            self.overlay_items.clear()
            
            # Clear existing galleries
            for widget in self.app.galleries_frame.winfo_children():
                widget.destroy()
            self.app.thumbnail_canvases.clear()
            
            # Recreate galleries from cached data
            for pitch_data in cached_data['thumbnail_canvases_data'].values():
                pitch = pitch_data['pitch']
                self._create_gallery_for_pitch(pitch)
            
            # Restore overlay items with proper image reconstruction
            img_w, img_h = self.base_display_img.size
            fov = float(self.app.fov_var.get())
            
            restored_count = 0
            for cached_item in cached_data['overlay_items']:
                try:
                    # Proper image reconstruction from cached bytes
                    if all(key in cached_item for key in ['image_bytes', 'image_size', 'image_mode']):
                        
                        # Reconstruct PIL image from bytes
                        thumb_img = Image.frombytes(
                            cached_item['image_mode'], 
                            cached_item['image_size'], 
                            cached_item['image_bytes']
                        )
                        thumb_tk = ImageTk.PhotoImage(thumb_img)
                    else:
                        print(f"⚠️ CACHE_CORRUPT: Missing image data for item {cached_item.get('index', 'unknown')}")
                        continue
                    
                    # Recreate overlay rectangle (no panning shift initially)
                    x1, y1, x2, y2 = self._calculate_overlay_coordinates(
                        cached_item['yaw'], cached_item['pitch'], img_w, img_h, fov
                    )
                    rect_id = self.app.source_canvas.create_rectangle(
                        x1, y1, x2, y2, 
                        outline=cached_item['shaded_color'], 
                        width=3
                    )
                    
                    # Add thumbnail to gallery
                    pitch = cached_item['pitch']
                    thumb_canvas = self.app.thumbnail_canvases.get(pitch)
                    if thumb_canvas:
                        thumb_size, thumb_padding, border_width = 100, 10, 2
                        i = cached_item['index']
                        thumb_x = (i * (thumb_size + thumb_padding)) + thumb_padding
                        thumb_y = thumb_padding
                        
                        border_id = thumb_canvas.create_rectangle(
                            thumb_x, thumb_y, thumb_x + thumb_size, thumb_y + thumb_size,
                            fill=cached_item['shaded_color'], 
                            outline=cached_item['shaded_color'], 
                            width=border_width
                        )
                        thumbnail_id = thumb_canvas.create_image(
                            thumb_x + border_width, thumb_y + border_width,
                            anchor='nw', image=thumb_tk
                        )
                        
                        # Update canvas scroll region
                        self._update_thumbnail_scroll_region(thumb_canvas)
                    else:
                        print(f"⚠️ No canvas for pitch {pitch}")
                        continue
                    
                    # Recreate overlay item with proper structure
                    overlay_item = {
                        'pitch': cached_item['pitch'],
                        'yaw': cached_item['yaw'],
                        'index': cached_item['index'],
                        'rect_id': rect_id,
                        'thumbnail_tk': thumb_tk,
                        'thumbnail_id': thumbnail_id,
                        'border_id': border_id,
                        'thumbnail_canvas': thumb_canvas,
                        'full_color': cached_item['full_color'],
                        'shaded_color': cached_item['shaded_color'],
                        'image': thumb_img  # Store PIL image for future caching
                    }
                    self.overlay_items.append(overlay_item)
                    restored_count += 1
                    
                except Exception as e:
                    print(f"❌ Failed to restore item {cached_item.get('index', 'unknown')}: {e}")
                    continue
            
            if restored_count == 0:
                print(f"❌ No items successfully restored from cache")
                return False
            
            # Set completion flags
            self.thumbnails_complete = True
            self.received_thumbnail_count = len(self.overlay_items)
            self.expected_thumbnail_count = len(self.overlay_items)
            
            # FIXED: Auto-select first item AND update panorama display
            if self.overlay_items:
                self.overlay_items.sort(key=lambda x: (-x['pitch'], x['index']))
                self._select_overlay(self.overlay_items[0])  # This will handle panorama rolling
            
            # Restore overlay appearance no longer used
            # self._update_overlay_appearance()
            
            print(f"✅ Successfully restored {restored_count}/{len(cached_data['overlay_items'])} thumbnails from cache")
            return True
            
        except Exception as e:
            print(f"❌ Cache restoration failed: {e}")
            # Clear the bad cache entry
            if content_key in self.state.content_cache:
                del self.state.content_cache[content_key]
            return False

    def _create_gallery_for_pitch(self, pitch):
        """Helper to create a gallery frame for a specific pitch."""
        gallery_frame = ttk.Labelframe(
            self.app.galleries_frame, 
            text=f"Pitch: {pitch}°", 
            padding=5
        )
        gallery_frame.pack(fill="x", expand=True, pady=5)
        
        thumb_canvas = tk.Canvas(gallery_frame, bg="#333333", height=120)
        thumb_canvas.pack(fill="x", expand=True)
        
        # Setup horizontal scrollbar
        x_scrollbar = ttk.Scrollbar(gallery_frame, orient="horizontal", command=thumb_canvas.xview)
        x_scrollbar.pack(fill="x")
        thumb_canvas.configure(xscrollcommand=x_scrollbar.set)
        
        # Enable mouse wheel scrolling
        def on_canvas_scroll(event, canvas=thumb_canvas):
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        
        thumb_canvas.bind("<MouseWheel>", on_canvas_scroll)
        thumb_canvas.bind("<Button-4>", lambda e, c=thumb_canvas: c.xview_scroll(-1, "units"))
        thumb_canvas.bind("<Button-5>", lambda e, c=thumb_canvas: c.xview_scroll(1, "units"))
        thumb_canvas.bind("<Button-1>", self._on_thumbnail_click)
        
        self.app.thumbnail_canvases[pitch] = thumb_canvas

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
            
            print(f"🔗 Integrated extraction frame with panorama display")
            
        except Exception as e:
            print(f"❌ PIL integration error: {e}")

    def _thumbnail_generator_worker(self, pitch_values, num_yaw_steps, fov, source_np, generation_id):
        """Worker thread to generate thumbnails."""
        try:
            if generation_id != self.thumbnail_generation_id: return

            thumb_size = 100
            for pitch in pitch_values:
                for i in range(num_yaw_steps):
                    if generation_id != self.thumbnail_generation_id: return
                    
                    yaw_angle = i * (360.0 / num_yaw_steps)
                    thumb_np = e2p(source_np, fov_deg=fov, u_deg=yaw_angle, v_deg=pitch, out_hw=(thumb_size, thumb_size), mode='bilinear')
                    
                    if generation_id == self.thumbnail_generation_id:
                        self.state.thumbnail_queue.put({
                            'generation_id': generation_id, 'pitch': pitch, 'yaw': yaw_angle, 'index': i,
                            'image': Image.fromarray(thumb_np)
                        })
        except Exception as e:
            if generation_id == self.thumbnail_generation_id:
                self.state.thumbnail_queue.put({'error': str(e)})

    def process_thumbnail_item(self, item_data):
        """Processes a single thumbnail item from the queue and adds it to the UI."""
        if item_data.get('generation_id') != self.thumbnail_generation_id:
            return

        if 'error' in item_data:
            messagebox.showerror("Thumbnail Error", f"Failed to generate thumbnail:\n{item_data['error']}")
            return

        pitch = item_data['pitch']
        thumb_canvas = self.app.thumbnail_canvases.get(pitch)
        if not thumb_canvas or not thumb_canvas.winfo_exists():
            return

        thumb_id = (pitch, item_data['yaw'], item_data['index'])
        if thumb_id in self._processed_thumbnails.get(self.thumbnail_generation_id, set()):
            return
        self._processed_thumbnails.setdefault(self.thumbnail_generation_id, set()).add(thumb_id)

        thumb_size, thumb_padding, border_width = 100, 10, 2
        i = item_data['index']
        thumb_x = (i * (thumb_size + thumb_padding)) + thumb_padding
        thumb_y = thumb_padding

        # FIXED: Store the PIL image for caching
        pil_image = item_data['image']  # This is the PIL image from the queue
        thumb_tk = ImageTk.PhotoImage(pil_image)
        
        full_color = self.app.OVERLAY_COLORS[i % len(self.app.OVERLAY_COLORS)]
        shaded_color = self._adjust_color_intensity(full_color, 0.7)

        border_id = thumb_canvas.create_rectangle(thumb_x, thumb_y, thumb_x + thumb_size, thumb_y + thumb_size, 
                                                fill=shaded_color, outline=shaded_color, width=border_width)
        thumbnail_id = thumb_canvas.create_image(thumb_x + border_width, thumb_y + border_width, anchor='nw', image=thumb_tk)

        img_w, img_h = self.base_display_img.size
        fov = float(self.app.fov_var.get())
        x1, y1, x2, y2 = self._calculate_overlay_coordinates(item_data['yaw'], pitch, img_w, img_h, fov)
        rect_id = self.app.source_canvas.create_rectangle(x1, y1, x2, y2, outline=shaded_color, width=3)
        
        # Include the PIL image in overlay data for caching
        overlay_data = {
            **item_data, 
            'rect_id': rect_id, 
            'thumbnail_tk': thumb_tk, 
            'thumbnail_id': thumbnail_id, 
            'border_id': border_id, 
            'thumbnail_canvas': thumb_canvas, 
            'full_color': full_color, 
            'shaded_color': shaded_color,
            'image': pil_image,  #  Store PIL image for caching
            'wrapped_rect_id': None 
        }
        self.overlay_items.append(overlay_data)
        
        # Update scroll region after adding thumbnail
        self._update_thumbnail_scroll_region(thumb_canvas)
        
        # Check completion
        self.received_thumbnail_count += 1
        if self.received_thumbnail_count >= self.expected_thumbnail_count:
            self.thumbnails_complete = True
            print(f"✅ All {self.expected_thumbnail_count} thumbnails complete - triggering auto-select")
            self.app.root.after(150, self._safe_auto_select)

    def _update_thumbnail_scroll_region(self, thumb_canvas):
        """Update scroll region for a specific thumbnail canvas."""
        if thumb_canvas and thumb_canvas.winfo_exists():
            # Get the bounding box of all items
            bbox = thumb_canvas.bbox("all")
            if bbox:
                # Add some padding
                thumb_padding = 10
                scroll_width = bbox[2] + thumb_padding
                thumb_canvas.configure(scrollregion=(0, 0, scroll_width, 0))
    
    def _safe_auto_select(self):
        """Prevents the regeneration feedback loop by only running once."""
        if not self.thumbnails_complete or not self.overlay_items:
            return
        
        # If an item is already selected, do not run again. This breaks the loop.  but this does not seem to work!
        if self.selected_item:
            return
            
        print("Executing auto-select...")
        self.overlay_items.sort(key=lambda x: (-x['pitch'], x['index']))
        self._select_overlay(self.overlay_items[0])

        if self.state.current_content_key and self.overlay_items:
            self._cache_current_content()

    def _calculate_overlay_coordinates(self, yaw, pitch, img_w, img_h, fov, shift_degrees=0):
        """
        ENHANCED: Calculate overlay coordinates with proper centering logic.
        """
        # Standard coordinate calculation
        # The shift_degrees parameter represents the panorama roll amount
        
        display_yaw = (yaw + shift_degrees + 360) % 360
        center_x = (display_yaw / 360.0) * img_w
        center_y = ((90 - pitch) / 180.0) * img_h
        box_w = (fov / 360.0) * img_w
        box_h = (fov / 180.0) * img_h
        return center_x - box_w / 2, center_y - box_h / 2, center_x + box_w / 2, center_y + box_h / 2

    def _select_overlay(self, item_to_select):
        """
        Handles overlay selection, panorama rolling, and crucially, sets the
        visibility ('state') of all overlay parts before calling the appearance function.
        """
        if not self.base_display_img: 
            return
        
        # --- 1. Update Thumbnail Highlighting and Selection State ---
        if self.selected_item:
            prev_canvas = self.selected_item['thumbnail_canvas']
            if prev_canvas.winfo_exists():
                prev_canvas.itemconfig(self.selected_item['border_id'], 
                                    outline=self.selected_item['shaded_color'], 
                                    fill=self.selected_item['shaded_color'])
        new_canvas = item_to_select['thumbnail_canvas']
        if new_canvas.winfo_exists():
            new_canvas.itemconfig(item_to_select['border_id'], 
                                outline=item_to_select['full_color'], 
                                fill=item_to_select['full_color'])
        self.selected_item = item_to_select
        
        # --- 2. Roll the Panorama Image ---
        selected_yaw = item_to_select['yaw']
        shift_degrees = 180.0 - selected_yaw
        img_w, img_h = self.base_display_img.size
        shift_pixels = int((shift_degrees / 360.0) * img_w) % img_w
        base_np = np.array(self.base_display_img)
        rolled_np = np.roll(base_np, shift=shift_pixels, axis=1)
        rolled_img = Image.fromarray(rolled_np)
        self.current_display_tk = ImageTk.PhotoImage(rolled_img)
        if (self.canvas_image_id and 
            self.canvas_image_id in self.app.source_canvas.find_all()):
            self.app.source_canvas.itemconfig(self.canvas_image_id, image=self.current_display_tk)

        # --- 3. Update All Overlay POSITIONS and VISIBILITY ---
        try:
            fov = float(self.app.fov_var.get())
        except (ValueError, TypeError):
            fov = 90
        
        for item in self.overlay_items:
            x1, y1, x2, y2 = self._calculate_overlay_coordinates(
                item['yaw'], item['pitch'], img_w, img_h, fov, shift_degrees
            )

            main_rect_state = 'normal'
            wrapped_rect_state = 'hidden'

            if x1 < 0:
                self.app.source_canvas.coords(item['rect_id'], 0, y1, x2, y2)
                wrapped_x1, wrapped_x2 = x1 + img_w, img_w
                if not item.get('wrapped_rect_id'):
                    item['wrapped_rect_id'] = self.app.source_canvas.create_rectangle(
                        wrapped_x1, y1, wrapped_x2, y2, state='hidden'
                    )
                else:
                    self.app.source_canvas.coords(item['wrapped_rect_id'], wrapped_x1, y1, wrapped_x2, y2)
                wrapped_rect_state = 'normal'

            elif x2 > img_w:
                self.app.source_canvas.coords(item['rect_id'], x1, y1, img_w, y2)
                wrapped_x1, wrapped_x2 = 0, x2 - img_w
                if not item.get('wrapped_rect_id'):
                    item['wrapped_rect_id'] = self.app.source_canvas.create_rectangle(
                        wrapped_x1, y1, wrapped_x2, y2, state='hidden'
                    )
                else:
                    self.app.source_canvas.coords(item['wrapped_rect_id'], wrapped_x1, y1, wrapped_x2, y2)
                wrapped_rect_state = 'normal'

            else:
                self.app.source_canvas.coords(item['rect_id'], x1, y1, x2, y2)
            
            self.app.source_canvas.itemconfig(item['rect_id'], state=main_rect_state)
            if item.get('wrapped_rect_id') and self.app.source_canvas.winfo_exists():
                self.app.source_canvas.itemconfig(item['wrapped_rect_id'], state=wrapped_rect_state)
                
        # --- 4. Final Updates ---
        self._update_overlay_appearance()
        self.update_live_preview(item_to_select['pitch'], item_to_select['yaw'])

    def _cleanup_existing_overlays(self):
        """FIXED: Complete cleanup of all overlay elements including wrapped rectangles."""
        print(f"🧹 Cleaning up {len(self.overlay_items)} overlay items...")
        
        for item in self.overlay_items:
            if not self.app.source_canvas.winfo_exists():
                continue
                
            # Delete main rectangle
            if item.get('rect_id') and item['rect_id'] in self.app.source_canvas.find_all():
                try:
                    self.app.source_canvas.delete(item['rect_id'])
                    print(f"   🗑️ Deleted main rect: {item['rect_id']}")
                except tk.TclError:
                    pass  # Already deleted
            
            # === CRITICAL: Delete wrapped rectangle ===
            if item.get('wrapped_rect_id') and item['wrapped_rect_id'] in self.app.source_canvas.find_all():
                try:
                    self.app.source_canvas.delete(item['wrapped_rect_id'])
                    print(f"   🗑️ Deleted wrapped rect: {item['wrapped_rect_id']}")
                except tk.TclError:
                    pass  # Already deleted
        
        # Clear the list
        self.overlay_items.clear()
        self.selected_item = None
        
        # === NUCLEAR OPTION: Clear ALL canvas items (if overlay cleanup fails) ===
        try:
            # Get all canvas items
            all_items = self.app.source_canvas.find_all()
            
            # Keep only the main panorama image (canvas_image_id)
            for item_id in all_items:
                if item_id != self.canvas_image_id:
                    self.app.source_canvas.delete(item_id)
                    print(f"   🧹 Force deleted canvas item: {item_id}")
        except Exception as e:
            print(f"   ⚠️ Canvas cleanup warning: {e}")
        
        print(f"✅ Overlay cleanup completed")

    # def _execute_overlay_update(self, reason="parameters"):
    #     """Execute overlay update with proper cleanup based on reason."""
    #     print(f"🔄 Executing overlay update - reason: {reason}")
        
    #     # Always unfreeze thumbnails first
    #     self.thumbnails_frozen = False
        
    #     # Clean up existing overlays BEFORE regeneration (this fixes the race condition)
    #     self._cleanup_existing_overlays()
        
    #     # Now trigger regeneration
    #     self.update_visual_overlays()

    def update_live_preview(self, pitch, yaw, size=None):
        """SIMPLIFIED: Live preview without complex debouncing."""
        if self.current_preview_source_np is None:
            return

        try:
            # Simple size determination
            if size is not None:
                render_size = min(size, 500)
            elif self._last_preview_size is not None:
                render_size = min(self._last_preview_size, 500)
            else:
                render_size = 256  # Default size

            if render_size < 50:
                return

            # Get FOV from UI
            try:
                fov = float(self.app.fov_var.get())
            except (ValueError, TypeError):
                fov = 90  # Default FOV

            # Generate preview using py360convert
            preview_np = e2p(
                self.current_preview_source_np, 
                fov_deg=fov, 
                u_deg=yaw, 
                v_deg=pitch, 
                out_hw=(render_size, render_size), 
                mode='bilinear'
            )
            
            # Convert to ImageTk and display
            self.preview_img = ImageTk.PhotoImage(Image.fromarray(preview_np))
            self.app.preview_label.config(image=self.preview_img)
            
        except Exception as e:
            print(f"Preview update error: {e}")
            self.app.preview_label.config(image='')

    def _establish_preview_size_if_needed(self):
        """SIMPLIFIED: Basic size establishment."""
        if self._last_preview_size is None:
            try:
                available_w = self.app.preview_frame.winfo_width()
                available_h = self.app.preview_frame.winfo_height()
                
                if available_w > 100 and available_h > 100:
                    calculated_size = max(50, min(available_w - 20, available_h - 30, 500))
                else:
                    calculated_size = 256
                    
                self._last_preview_size = calculated_size
                
            except Exception:
                self._last_preview_size = 256

    def on_preview_resize(self, event):
        """SIMPLIFIED: Immediate resize without complex logic."""
        if not self.selected_item or event.widget != self.app.preview_frame:
            return

        # Calculate new size
        new_size = min(event.width - 20, event.height - 30, 500)
        final_size = max(50, new_size)
        
        # Only update if significantly different
        if abs(final_size - (self._last_preview_size or 0)) > 10:
            self._last_preview_size = final_size
            self.update_live_preview(
                self.selected_item['pitch'],
                self.selected_item['yaw'], 
                final_size
            )

    def _do_preview_update_immediate(self, pitch, yaw, size=None):
        """Immediate preview update without any delays."""
        try:
            # Determine render size with 500px maximum
            if size is not None:
                render_size = min(size, 500)
            elif self._last_preview_size is not None:
                render_size = min(self._last_preview_size, 500)
            else:
                self._establish_preview_size_if_needed()
                render_size = min(self._last_preview_size or 256, 500)

            if render_size < 50:
                return

            # Skip if we're already rendering this exact configuration
            current_config = (pitch, yaw, render_size)
            if hasattr(self, '_last_render_config') and self._last_render_config == current_config:
                return
            
            self._last_render_config = current_config

            fov = float(self.app.fov_var.get())
            preview_np = e2p(
                self.current_preview_source_np, 
                fov_deg=fov, 
                u_deg=yaw, 
                v_deg=pitch, 
                out_hw=(render_size, render_size), 
                mode='bilinear'
            )
            self.preview_img = ImageTk.PhotoImage(Image.fromarray(preview_np))
            self.app.preview_label.config(image=self.preview_img)
        
        except (ValueError, TypeError) as e:
            print(f"Preview update error: {e}")
            self.app.preview_label.config(image='')

    def _reset_all_views_and_cancel_jobs(self):
        """ENHANCED: More thorough cleanup including canvas state reset."""
        print("🔄 Resetting all views and cancelling jobs...")
        
        # Cancel thumbnail generation
        self.thumbnail_generation_id += 1
        
        # Cleanup image resources
        self._cleanup_image_resources()
        
        # Reset render state
        self._reset_render_state()

        # === ENHANCED: Complete overlay cleanup ===
        self._cleanup_existing_overlays()

        # Reset core image state
        self.base_display_img = None
        self.current_preview_source_np = None

        # === NUCLEAR CANVAS CLEANUP ===
        if self.app.source_canvas.winfo_exists():
            # Store the current image before clearing
            stored_image = self.canvas_image_id
            
            # Clear ALL canvas items
            self.app.source_canvas.delete("all")
            print("🧹 Nuclear canvas cleanup - deleted ALL items")
            
            # Reset canvas image ID since we deleted everything
            self.canvas_image_id = None

        # Clear thumbnail galleries
        for widget in self.app.galleries_frame.winfo_children(): 
            widget.destroy()
        self.app.thumbnail_canvases.clear()
        
        # Clear preview
        if self.preview_img: 
            self.app.preview_label.config(image='')
            self.preview_img = None

    def _cleanup_image_resources(self):
        """Explicitly deletes ImageTk objects to prevent memory leaks."""
        self.current_display_tk = None
        self.preview_img = None
        for item in self.overlay_items:
            item['thumbnail_tk'] = None
        import gc
        gc.collect()

    def _get_color_rgb(self, color_name):
        """Converts a tkinter color name to an (R, G, B) tuple."""
        r, g, b = self.app.root.winfo_rgb(color_name)
        return r // 256, g // 256, b // 256

    def _adjust_color_intensity(self, color_name, factor):
        """Creates a darker shade of a color."""
        r, g, b = self._get_color_rgb(color_name)
        return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"

# In app_visuals.py, replace this entire function

    def _update_overlay_appearance(self, *args):
        """
        Final, corrected version. Handles appearance for all overlay states
        without making boxes permanently disappear at zero opacity.
        """
        if not self.overlay_items:
            return
        
        opacity_value = self.app.overlay_opacity_var.get()

        for item in self.overlay_items:
            rect_id = item.get('rect_id')
            wrapped_rect_id = item.get('wrapped_rect_id')
            
            if not (self.app.source_canvas.winfo_exists() and rect_id and rect_id in self.app.source_canvas.find_all()):
                continue

            is_selected = (self.selected_item and item == self.selected_item)
            
            appearance_config = {}
            if is_selected:
                # --- Style for the currently selected item ---
                # This is unaffected by the opacity slider.
                appearance_config = {
                    'outline': item['full_color'],
                    'fill': item['full_color'],
                    'stipple': 'gray25',
                    'width': 4,
                }
            else:
                # --- Style for all unselected items (based on opacity) ---
                outline_color_val = ""
                width_val = 0

                if opacity_value >= 0.5:
                    strength = (opacity_value - 0.5) * 2.0
                    outline_color_val = self._blend_color_to_white(item['full_color'], strength)
                    width_val = 2
                else:
                    visibility = opacity_value * 2.0
                    # Set a small threshold to become truly invisible
                    if visibility < 0.05:
                        width_val = 0
                        # Make the outline empty so it doesn't render 1 pixel wide
                        outline_color_val = ""
                    else:
                        intensity = int(255 * visibility)
                        outline_color_val = f"#{intensity:02x}{intensity:02x}{intensity:02x}"
                        width_val = max(1, int(2 * visibility))

                appearance_config = {
                    'outline': outline_color_val,
                    'fill': "",
                    'stipple': "",
                    'width': width_val,
                }

            # Apply the appearance config to all parts of the overlay.
            # This version no longer touches the 'state' property, fixing the bug.
            self.app.source_canvas.itemconfig(rect_id, **appearance_config)
            if wrapped_rect_id and wrapped_rect_id in self.app.source_canvas.find_all():
                self.app.source_canvas.itemconfig(wrapped_rect_id, **appearance_config)

    def _blend_color_to_white(self, color_name, strength):
        """Blends a color towards white."""
        r, g, b = self._get_color_rgb(color_name)
        return f"#{int(r*strength+255*(1-strength)):02x}{int(g*strength+255*(1-strength)):02x}{int(b*strength+255*(1-strength)):02x}"
 
    def _reset_render_state(self):
        """Reset render state when switching content."""
        if hasattr(self, '_last_render_config'):
            delattr(self, '_last_render_config')
        self._last_preview_size = None

    def _get_params_for_preview(self) -> Tuple[Optional[List[float]], Optional[int], Optional[float]]:
        """
        Get and validate preview parameters from UI controls.
        
        Returns:
            Tuple of (pitch_angles, yaw_steps, fov) where:
            - pitch_angles: List of pitch angles in degrees, or None if invalid
            - yaw_steps: Number of yaw steps, or None if invalid  
            - fov: Field of view in degrees, or None if invalid
            
            Returns (None, None, None) if any parameter is invalid.
        """
        try:
            # Get raw values and strip whitespace
            yaw_steps_str = self.app.yaw_steps_var.get().strip()
            pitch_angles_str = self.app.pitch_angles_str_var.get().strip()
            fov_str = self.app.fov_var.get().strip()
            
            # Check for empty or whitespace-only strings
            if not yaw_steps_str or yaw_steps_str.isspace():
                return None, None, None
            if not pitch_angles_str or pitch_angles_str.isspace():
                return None, None, None
            if not fov_str or fov_str.isspace():
                return None, None, None
            
            # Check for incomplete typing
            if yaw_steps_str in ['-', '+', '.']:
                return None, None, None
            if fov_str in ['-', '+', '.']:
                return None, None, None
            
            # Parse yaw steps
            try:
                yaw_steps = int(yaw_steps_str)
            except ValueError:
                if yaw_steps_str not in ['', '-', '+']:
                    print(f"Invalid yaw steps: '{yaw_steps_str}' is not a valid integer")
                return None, None, None
            
            # ENHANCED: Parse pitch angles with robust comma handling
            try:
                pitch_angles = []
                # Split by comma and clean each part
                angle_parts = pitch_angles_str.split(',')
                
                for angle_str in angle_parts:
                    angle_str = angle_str.strip()  # Remove whitespace
                    
                    # Skip empty parts (handles trailing commas)
                    if not angle_str:
                        continue
                        
                    # Skip incomplete entries
                    if angle_str in ['-', '+', '.']:
                        continue
                    
                    try:
                        angle = float(angle_str)
                        pitch_angles.append(angle)
                    except ValueError:
                        print(f"Invalid pitch angle: '{angle_str}' is not a valid number")
                        continue  # Skip invalid angles rather than failing entirely
                
                # Must have at least one valid angle
                if not pitch_angles:
                    print("No valid pitch angles found")
                    return None, None, None
                    
            except Exception as e:
                print(f"Error parsing pitch angles: {e}")
                return None, None, None
            
            # Parse FOV
            try:
                fov = float(fov_str)
            except ValueError:
                if fov_str not in ['', '-', '+', '.']:
                    print(f"Invalid FOV: '{fov_str}' is not a valid number")
                return None, None, None
            
            # Validation with range checking
            if not (1 <= yaw_steps <= 100):
                print(f"Yaw steps out of range: {yaw_steps} (must be 1-100)")
                return None, None, None
            
            if not (30 <= fov <= 160):
                print(f"FOV out of range: {fov} (must be 30-160)")
                return None, None, None
            
            # Validate pitch angles are reasonable
            for angle in pitch_angles:
                if not (-90 <= angle <= 90):
                    print(f"Pitch angle out of range: {angle} (must be -90 to 90)")
                    return None, None, None
                
            #print(f"✅ Valid parameters: pitch_angles={pitch_angles}, yaw_steps={yaw_steps}, fov={fov}")
            return pitch_angles, yaw_steps, fov
            
        except Exception as e:
            print(f"Unexpected parameter parsing error: {e}")
            return None, None, None

    def update_visual_overlays(self, *args):
        """
        Update overlays with extraction frame awareness.
        """
        if getattr(self, 'thumbnails_frozen', False):
            print("❄️ Thumbnails frozen during extraction frame navigation")
            return
        
        self.thumbnail_generation_id += 1
        self.thumbnails_complete = False
        self.received_thumbnail_count = 0
        
        if not self.base_display_img or self.current_preview_source_np is None: 
            return

        print(f"Updating visual overlays - gen_id: {self.thumbnail_generation_id}")

        # --- FIX: Use the new robust cleanup function ---
        self._cleanup_existing_overlays()
        
        # Clear galleries
        for widget in self.app.galleries_frame.winfo_children():
            widget.destroy()
        self.app.thumbnail_canvases.clear()

        # === VERIFY: Check canvas state after cleanup ===
        remaining_items = self.app.source_canvas.find_all()
        overlay_items = [item for item in remaining_items if item != self.canvas_image_id]
        
        if overlay_items:
            print(f"⚠️ WARNING: {len(overlay_items)} overlay items still on canvas after cleanup!")
            # Force delete any remaining overlay items
            for item_id in overlay_items:
                try:
                    self.app.source_canvas.delete(item_id)
                    print(f"   🧹 Force deleted remaining item: {item_id}")
                except tk.TclError:
                    pass

        pitch_values, num_yaw_steps, fov = self._get_params_for_preview()
        if pitch_values is None: 
            return
        
        self.expected_thumbnail_count = len(pitch_values) * num_yaw_steps
        print(f"Expecting {self.expected_thumbnail_count} thumbnails for generation {self.thumbnail_generation_id}")

        # Sort pitch values for consistent ordering
        pitch_values.sort(reverse=True)
        print(f"Generating overlays: pitches={pitch_values}, yaw_steps={num_yaw_steps}, fov={fov}")
        
        # Create placeholder galleries
        self.app.thumbnail_canvases = {}
        for pitch in pitch_values:
            gallery_frame = ttk.Labelframe(
                self.app.galleries_frame, 
                text=f"Pitch: {pitch}°", 
                padding=5
            )
            gallery_frame.pack(fill="x", expand=True, pady=5)
            
            thumb_canvas = tk.Canvas(gallery_frame, bg="#333333", height=120)
            thumb_canvas.pack(fill="x", expand=True)
            
            x_scrollbar = ttk.Scrollbar(gallery_frame, orient="horizontal", command=thumb_canvas.xview)
            x_scrollbar.pack(fill="x")
            thumb_canvas.configure(xscrollcommand=x_scrollbar.set)
            
            def on_canvas_scroll(event, canvas=thumb_canvas):
                canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            
            thumb_canvas.bind("<MouseWheel>", on_canvas_scroll)
            thumb_canvas.bind("<Button-4>", lambda e, c=thumb_canvas: c.xview_scroll(-1, "units"))
            thumb_canvas.bind("<Button-5>", lambda e, c=thumb_canvas: c.xview_scroll(1, "units"))
            
            thumb_canvas.bind("<Button-1>", self._on_thumbnail_click)
            self.app.thumbnail_canvases[pitch] = thumb_canvas
        
        threading.Thread(
            target=self._thumbnail_generator_worker, 
            args=(pitch_values, num_yaw_steps, fov, self.current_preview_source_np, self.thumbnail_generation_id), 
            daemon=True
        ).start()

    def _restore_overlay_appearance(self, opacity_value):
        """Restore overlay appearance after regeneration."""
        if self.overlay_items and self.thumbnails_complete:
            print(f"Restoring overlay appearance with opacity: {opacity_value}")
            self.app.overlay_opacity_var.set(opacity_value)
            self._update_overlay_appearance()

    def _on_thumbnail_click(self, event):
        """Handle thumbnail clicks."""
        if not self.overlay_items: return
        clicked_canvas = event.widget
        item_id = clicked_canvas.find_closest(clicked_canvas.canvasx(event.x), clicked_canvas.canvasy(event.y))[0]
        for item in self.overlay_items:
            if item['thumbnail_canvas'] == clicked_canvas and (item['thumbnail_id'] == item_id or item['border_id'] == item_id):
                self._select_overlay(item)
                break

    # def _debounced_parameter_update(self, *args, reason="parameters"):
    #     """
    #     ENHANCED: Centralized debouncing for all overlay updates.
        
    #     Args:
    #         reason: "parameters" (settings changed) or "frame_navigation" (frame changed)
    #     """
    #     # Handle frame navigation differently
    #     if reason == "frame_navigation":
    #         # Freeze thumbnails during active navigation
    #         self.thumbnails_frozen = True
    #         print(f"❄️ Thumbnails frozen for frame navigation")
            
    #         # Cancel existing timer
    #         if self.parameter_update_timer:
    #             self.app.root.after_cancel(self.parameter_update_timer)
            
    #         # Shorter delay for frame navigation (500ms)
    #         self.parameter_update_timer = self.app.root.after(
    #             500, 
    #             lambda: self._execute_overlay_update(reason="frame_navigation")
    #         )
    #     else:
    #         # Parameter changes - existing logic
    #         self._parameter_change_pending = True
            
    #         if self.parameter_update_timer:
    #             self.app.root.after_cancel(self.parameter_update_timer)
            
    #         # Normal delay for parameter changes (1000ms)
    #         self.parameter_update_timer = self.app.root.after(
    #             self.parameter_update_delay, 
    #             lambda: self._execute_overlay_update(reason="parameters")
    #         )

    def _cleanup_existing_overlays(self):
        """Clean up all existing overlay elements to prevent race conditions."""
        for item in self.overlay_items:
            if (self.app.source_canvas.winfo_exists() and 
                item.get('rect_id') and 
                item['rect_id'] in self.app.source_canvas.find_all()):
                self.app.source_canvas.delete(item['rect_id'])
            
            # CRITICAL: Also clean up wrapped rectangles
            if (item.get('wrapped_rect_id') and 
                self.app.source_canvas.winfo_exists() and
                item['wrapped_rect_id'] in self.app.source_canvas.find_all()):
                self.app.source_canvas.delete(item['wrapped_rect_id'])
        
        self.overlay_items.clear()
        self.selected_item = None
        print(f"🧹 Cleaned up all overlay items")