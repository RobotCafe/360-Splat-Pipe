
# FIXED app_help_docs.py - Debug menu with corrected method signatures

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import threading
import sys
import datetime
from pathlib import Path
import re


class AppHelpDocs:
    """
    Manages and displays help documentation for the application.
    """
    def __init__(self, app):
        self.app = app
        self.root = app.root

    def create_help_menu(self):
        """Create help menu with documentation and FIXED debug menu."""
        # Simple approach - always create a new menubar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        help_menu.add_command(label="Quick Start Guide", command=self.show_quick_start)
        help_menu.add_command(label="Parameter Guide", command=self.show_parameter_guide)
        help_menu.add_command(label="Troubleshooting", command=self.show_troubleshooting)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)

        # === FIXED DEBUG MENU ===
        debug_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Debug", menu=debug_menu)

        # Basic System Info
        debug_menu.add_command(label="🎬 Extraction Frame Info", 
                              command=self._debug_extraction_info_safe)
        debug_menu.add_command(label="🧪 Test GPU Acceleration", 
                              command=self._test_gpu_acceleration_safe)
        debug_menu.add_separator()
        
        # === FIXED: Settings & Trace Debugging ===
        settings_submenu = tk.Menu(debug_menu, tearoff=0)
        debug_menu.add_cascade(label="Settings & Traces", menu=settings_submenu)
        
        settings_submenu.add_command(label="🔍 Test Frame Estimation Update", 
                                   command=self._test_frame_estimation_trace_fixed)
        settings_submenu.add_command(label="📊 Show Trace Status", 
                                   command=self._debug_trace_status_fixed)
        settings_submenu.add_command(label="⚙️ Manual Settings Change Test", 
                                   command=self._test_manual_settings_change_fixed)
        settings_submenu.add_command(label="🔄 Force Frame Estimation Update", 
                                   command=self._force_frame_estimation_update_fixed)
        settings_submenu.add_separator()
        settings_submenu.add_command(label="📋 Per-Video Settings Cache", 
                                   command=self._debug_per_video_settings_fixed)
        settings_submenu.add_command(label="🧹 Clear Per-Video Settings Cache", 
                                   command=self._clear_per_video_settings_cache_fixed)
        
        # === FIXED: Cache & Performance Diagnostics ===
        cache_submenu = tk.Menu(debug_menu, tearoff=0)
        debug_menu.add_cascade(label="Cache & Performance", menu=cache_submenu)
        
        cache_submenu.add_command(label="💾 Cache Performance Analysis", 
                                command=self._safe_method_call("debug_cache_performance"))
        cache_submenu.add_command(label="⏱️ Cache Operation Benchmark", 
                                command=self._safe_method_call("benchmark_cache_operations"))
        cache_submenu.add_command(label="🗂️ Multi-Queue State Debug", 
                                command=self._safe_method_call("debug_multi_queue_state"))
        cache_submenu.add_separator()
        cache_submenu.add_command(label="🧹 Clear Preview Cache", 
                                command=self._safe_method_call("clear_preview_cache"))
        cache_submenu.add_command(label="🔧 Cache Maintenance", 
                                command=self._safe_method_call("maintenance_cleanup_cache"))
        
        # Integration Testing
        test_submenu = tk.Menu(debug_menu, tearoff=0)
        debug_menu.add_cascade(label="Integration Testing", menu=test_submenu)
        
        test_submenu.add_command(label="🔄 Test Queue Switching", 
                                command=self._safe_method_call("test_queue_switching_scenarios"))
        test_submenu.add_command(label="🎯 Display State Debug", 
                                command=self._safe_method_call("debug_display_state"))
        
        # System Diagnostics
        debug_menu.add_separator()
        debug_menu.add_command(label="📋 Display Debug State", 
                              command=self._safe_method_call("debug_display_state_with_cache"))
        debug_menu.add_separator()
        debug_menu.add_command(label="💾 Save Debug Log", 
                              command=self._save_debug_log_safe)
        
        # === ADD LOGGING TOOLS TO DEBUG MENU ===
        logging_submenu = tk.Menu(debug_menu, tearoff=0)
        debug_menu.add_cascade(label="Logging Tools", menu=logging_submenu)
        
        logging_submenu.add_command(label="📝 Open Current Log File", 
                                   command=self._open_current_log_file)
        logging_submenu.add_command(label="📂 Open Logs Folder", 
                                   command=self._open_logs_folder)
        logging_submenu.add_command(label="🗂️ Show Log File Info", 
                                   command=self._show_log_file_info)
        logging_submenu.add_command(label="🧹 Clean Old Log Files", 
                                   command=self._clean_old_log_files)
        logging_submenu.add_separator()
        logging_submenu.add_command(label="📊 Generate Log Summary", 
                                   command=self._generate_log_summary)


    # --- Per Session CONSOLE Log File

    def _open_current_log_file(self):
        """Open the current session log file."""
        try:
            if hasattr(self.app, 'log_filename') and self.app.log_filename:
                import subprocess
                import platform
                
                log_path = str(self.app.log_filename)
                
                if platform.system() == "Windows":
                    subprocess.run(['notepad', log_path])
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(['open', log_path])
                else:  # Linux
                    subprocess.run(['xdg-open', log_path])
                    
                print(f"📝 Opened log file: {log_path}")
            else:
                messagebox.showwarning("No Log", "No active log file found.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Could not open log file: {e}")

    def _open_logs_folder(self):
        """Open the logs folder in file explorer."""
        try:
            from _common_utils import get_user_logs_directory
            logs_dir = get_user_logs_directory()
            if logs_dir.exists():
                import subprocess
                import platform
                
                if platform.system() == "Windows":
                    subprocess.run(['explorer', str(logs_dir)])
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(['open', str(logs_dir)])
                else:  # Linux
                    subprocess.run(['xdg-open', str(logs_dir)])
                    
                print(f"📂 Opened logs folder: {logs_dir}")
            else:
                messagebox.showwarning("No Logs", "Logs folder does not exist yet.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Could not open logs folder: {e}")

    def _show_log_file_info(self):
        """Show information about the current log file."""
        try:
            if not hasattr(self.app, 'log_filename') or not self.app.log_filename:
                messagebox.showinfo("Log Info", "No active log file.")
                return
                
            log_path = self.app.log_filename
            
            if log_path.exists():
                file_size = log_path.stat().st_size
                modified_time = datetime.datetime.fromtimestamp(log_path.stat().st_mtime)
                
                with open(log_path, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for _ in f)
                
                info_text = f"""CURRENT LOG FILE INFO:

File: {log_path.name}
Path: {log_path}
Size: {file_size:,} bytes ({file_size/1024:.1f} KB)
Lines: {line_count:,}
Modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}

Log files are automatically created for each session and
contain timestamped entries of all console output.
Perfect for debugging batch processing issues!"""
                
                messagebox.showinfo("Log File Info", info_text)
            else:
                messagebox.showwarning("Log Info", "Log file does not exist.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Could not get log info: {e}")

    def _clean_old_log_files(self):
        """Clean up old log files (keep last 10)."""
        try:
            from _common_utils import get_user_logs_directory
            logs_dir = get_user_logs_directory()
            if not logs_dir.exists():
                messagebox.showinfo("Clean Logs", "No logs folder found.")
                return
            
            log_files = list(logs_dir.glob("splatpipe_session_*.log"))
            log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            if len(log_files) <= 10:
                messagebox.showinfo("Clean Logs", f"Only {len(log_files)} log files found. No cleanup needed.")
                return
            
            files_to_delete = log_files[10:]  # Keep newest 10
            
            if messagebox.askyesno("Clean Logs", 
                                  f"Delete {len(files_to_delete)} old log files?\n"
                                  f"(Keeping newest 10 files)"):
                
                deleted_count = 0
                for log_file in files_to_delete:
                    try:
                        log_file.unlink()
                        deleted_count += 1
                    except Exception as e:
                        print(f"Could not delete {log_file}: {e}")
                
                messagebox.showinfo("Clean Logs", f"Deleted {deleted_count} old log files.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Could not clean log files: {e}")

    def _generate_log_summary(self):
        """Generate a comprehensive summary of the current log file."""
        try:
            if not hasattr(self.app, 'log_filename') or not self.app.log_filename:
                messagebox.showinfo("Log Summary", "No active log file to summarize.")
                return
                
            log_path = self.app.log_filename
            
            if not log_path.exists():
                messagebox.showwarning("Log Summary", "Log file does not exist.")
                return
            
            # Analyze log file
            summary_data = self._analyze_log_file(log_path)
            
            # Create summary window
            self._show_log_summary_window(summary_data, log_path)
                
        except Exception as e:
            messagebox.showerror("Error", f"Could not generate log summary: {e}")

    def _analyze_log_file(self, log_path):
        """Analyze log file and extract key statistics."""
        summary = {
            'session_start': None,
            'session_duration': None,
            'total_lines': 0,
            'batch_sessions': 0,
            'items_processed': 0,
            'items_completed': 0,
            'errors': [],
            'warnings': [],
            'performance_stats': {},
            'processing_times': []
        }
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                summary['total_lines'] = len(lines)
                
                session_start_time = None
                latest_time = None
                current_item_start = None
                
                for line in lines:
                    # Extract timestamp if present
                    timestamp_match = re.search(r'\[(\d{2}:\d{2}:\d{2}\.\d{3})\]', line)
                    if timestamp_match:
                        time_str = timestamp_match.group(1)
                        try:
                            time_obj = datetime.datetime.strptime(time_str, '%H:%M:%S.%f')
                            if session_start_time is None:
                                session_start_time = time_obj
                            latest_time = time_obj
                        except:
                            pass
                    
                    # Look for session start
                    if 'Session started:' in line:
                        match = re.search(r'Session started: (.+)', line)
                        if match:
                            summary['session_start'] = match.group(1)
                    
                    # Count batch processing sessions
                    if '🚀 BATCH PROCESSING SESSION STARTED' in line:
                        summary['batch_sessions'] += 1
                    
                    # Count items processed
                    if '📦 PROCESSING ITEM' in line:
                        summary['items_processed'] += 1
                        if current_item_start and timestamp_match:
                            # Previous item timing
                            pass
                        current_item_start = timestamp_match.group(1) if timestamp_match else None
                    
                    # Count items completed
                    if '🎉 COMPLETED ITEM' in line:
                        summary['items_completed'] += 1
                        if current_item_start and timestamp_match:
                            # Calculate processing time
                            try:
                                start_time = datetime.datetime.strptime(current_item_start, '%H:%M:%S.%f')
                                end_time = datetime.datetime.strptime(timestamp_match.group(1), '%H:%M:%S.%f')
                                duration = (end_time - start_time).total_seconds()
                                summary['processing_times'].append(duration)
                            except:
                                pass
                    
                    # Look for errors
                    if any(error_word in line.lower() for error_word in ['error', 'exception', 'failed', 'traceback']):
                        summary['errors'].append(line.strip())
                    
                    # Look for warnings
                    if any(warning_word in line for warning_word in ['⚠️', 'Warning:', 'warning']):
                        summary['warnings'].append(line.strip())
                
                # Calculate session duration
                if session_start_time and latest_time:
                    duration = latest_time - session_start_time
                    hours, remainder = divmod(duration.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    summary['session_duration'] = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
                
                # Calculate performance stats
                if summary['processing_times']:
                    times = summary['processing_times']
                    summary['performance_stats'] = {
                        'avg_time': sum(times) / len(times),
                        'min_time': min(times),
                        'max_time': max(times),
                        'total_processing_time': sum(times)
                    }
        
        except Exception as e:
            summary['analysis_error'] = str(e)
        
        return summary

    def _show_log_summary_window(self, summary_data, log_path):
        """Display log summary in a dedicated window."""
        # Create summary window
        summary_window = tk.Toplevel(self.app.root)
        summary_window.title("📊 Log File Summary")
        summary_window.geometry("700x600")
        summary_window.resizable(True, True)
        
        # Create scrollable text widget
        frame = tk.Frame(summary_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text_widget = tk.Text(frame, wrap=tk.WORD, font=('Consolas', 10))
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Generate summary text
        summary_text = self._format_log_summary(summary_data, log_path)
        
        # Insert summary text
        text_widget.insert(tk.END, summary_text)
        text_widget.config(state=tk.DISABLED)
        
        # Add close button
        close_button = tk.Button(summary_window, text="Close", command=summary_window.destroy)
        close_button.pack(pady=5)

    def _format_log_summary(self, summary, log_path):
        """Format the summary data into readable text."""
        text = f"""
{'='*80}
📊 SPLATPIPE SESSION LOG SUMMARY
{'='*80}

📁 LOG FILE: {log_path.name}
📅 SESSION START: {summary.get('session_start', 'Unknown')}
⏱️  SESSION DURATION: {summary.get('session_duration', 'Unknown')}
📄 TOTAL LOG LINES: {summary['total_lines']:,}

{'='*80}
📦 PROCESSING STATISTICS
{'='*80}

🚀 Batch Processing Sessions: {summary['batch_sessions']}
📦 Items Started: {summary['items_processed']}
✅ Items Completed: {summary['items_completed']}
📊 Success Rate: {(summary['items_completed']/max(summary['items_processed'], 1)*100):.1f}%

"""
        
        # Performance statistics
        if summary['performance_stats']:
            perf = summary['performance_stats']
            text += f"""{'='*80}
⚡ PERFORMANCE STATISTICS
{'='*80}

📈 Average Processing Time: {perf['avg_time']:.1f} seconds
⚡ Fastest Item: {perf['min_time']:.1f} seconds
🐌 Slowest Item: {perf['max_time']:.1f} seconds
🕐 Total Processing Time: {perf['total_processing_time']:.1f} seconds

"""
        
        # Errors section
        if summary['errors']:
            text += f"""{'='*80}
❌ ERRORS DETECTED ({len(summary['errors'])})
{'='*80}

"""
            for i, error in enumerate(summary['errors'][:10], 1):  # Show first 10 errors
                text += f"{i}. {error}\n"
            
            if len(summary['errors']) > 10:
                text += f"\n... and {len(summary['errors']) - 10} more errors\n"
            text += "\n"
        
        # Warnings section
        if summary['warnings']:
            text += f"""{'='*80}
⚠️ WARNINGS DETECTED ({len(summary['warnings'])})
{'='*80}

"""
            for i, warning in enumerate(summary['warnings'][:5], 1):  # Show first 5 warnings
                text += f"{i}. {warning}\n"
            
            if len(summary['warnings']) > 5:
                text += f"\n... and {len(summary['warnings']) - 5} more warnings\n"
            text += "\n"
        
        # Processing timeline (if we have timing data)
        if summary['processing_times']:
            text += f"""{'='*80}
📊 PROCESSING TIMELINE
{'='*80}

Individual Item Processing Times:
"""
            for i, time_val in enumerate(summary['processing_times'], 1):
                text += f"Item {i}: {time_val:.1f}s\n"
            text += "\n"
        
        text += f"""{'='*80}
💡 SUMMARY INSIGHTS
{'='*80}

"""
        
        # Add insights based on the data
        insights = []
        
        if summary['items_completed'] == summary['items_processed'] and summary['items_processed'] > 0:
            insights.append("✅ All items completed successfully - no failures detected!")
        
        if summary['errors']:
            insights.append(f"⚠️ {len(summary['errors'])} errors detected - check log for details")
        
        if summary['performance_stats']:
            avg_time = summary['performance_stats']['avg_time']
            if avg_time < 30:
                insights.append("⚡ Fast processing times - system running efficiently")
            elif avg_time > 120:
                insights.append("🐌 Slow processing detected - consider optimizing settings")
        
        if summary['batch_sessions'] > 1:
            insights.append(f"📦 Multiple batch sessions ({summary['batch_sessions']}) in this log")
        
        if not insights:
            insights.append("📈 Normal processing session with standard performance")
        
        for insight in insights:
            text += f"{insight}\n"
        
        text += f"\n{'='*80}\n"
        
        return text


    # === FIXED METHODS WITH PROPER ERROR HANDLING ===

    def _safe_method_call(self, method_name):
        """Create a safe wrapper for calling callback methods."""
        def wrapper():
            try:
                if not hasattr(self.app, 'callbacks'):
                    messagebox.showwarning("Debug", "Callbacks manager not available")
                    return
                
                if not hasattr(self.app.callbacks, method_name):
                    messagebox.showwarning("Debug", f"Method '{method_name}' not found in callbacks")
                    return
                
                print(f"\n🔍 Running: {method_name}")
                method = getattr(self.app.callbacks, method_name)
                method()
                
            except Exception as e:
                print(f"❌ Debug method {method_name} failed: {e}")
                import traceback
                traceback.print_exc()
                messagebox.showerror("Debug Error", f"Method failed: {method_name}\n\nError: {e}")
        
        return wrapper

    def _test_frame_estimation_trace_fixed(self):
        """FIXED: Test frame estimation with current architecture."""
        try:
            if not hasattr(self.app, 'callbacks'):
                messagebox.showwarning("Debug", "No callbacks manager available")
                return
                
            print("\n🔍 TESTING FRAME ESTIMATION TRACE:")
            print("="*50)
            
            callbacks = self.app.callbacks
            
            # Check current state
            loading_flag = getattr(callbacks, '_settings_loading_in_progress', 'Not set')
            update_flag = getattr(callbacks, '_trace_update_in_progress', 'Not set')
            timer_active = getattr(callbacks, '_frame_estimate_timer', None) is not None
            
            print(f"Settings loading in progress: {loading_flag}")
            print(f"Trace update in progress: {update_flag}")
            print(f"Frame estimate timer active: {timer_active}")
            
            # Get current settings safely
            try:
                method = self.app.extraction_method_var.get()
                if method == "count":
                    value = self.app.frame_count_var.get()
                    print(f"Current settings: {method} method, {value} frames")
                else:
                    interval_val = self.app.interval_value_var.get()
                    interval_unit = self.app.interval_unit_var.get()
                    print(f"Current settings: {method} method, {interval_val} {interval_unit}")
            except Exception as e:
                print(f"Error reading current settings: {e}")
            
            # Test the trace - use the CURRENT method signature
            print("\n🚀 Manually triggering on_extraction_settings_change...")
            if hasattr(callbacks, 'on_extraction_settings_change'):
                callbacks.on_extraction_settings_change()
                print("✅ Manual trace trigger completed")
            else:
                print("❌ Method on_extraction_settings_change not found")
            
            print("="*50)
            messagebox.showinfo("Trace Test", "Frame estimation trace test completed.\nCheck console for detailed output.")
            
        except Exception as e:
            messagebox.showerror("Debug Error", f"Frame estimation trace test failed: {e}")

    def _debug_trace_status_fixed(self):
        """FIXED: Show trace status with current architecture."""
        try:
            info_text = "TRACE STATUS DEBUG:\n" + "="*40 + "\n"
            
            # Check trace lists in GUI
            if hasattr(self.app, 'save_traces'):
                info_text += f"Save traces: {len(self.app.save_traces)} active\n"
                for i, (var, trace_id) in enumerate(self.app.save_traces[:3]):
                    var_name = getattr(var, '_name', 'Unknown')
                    info_text += f"  [{i}] {var_name}: {trace_id}\n"
            else:
                info_text += "Save traces: NOT INITIALIZED\n"
                
            if hasattr(self.app, 'estimation_traces'):
                info_text += f"Estimation traces: {len(self.app.estimation_traces)} active\n"
            else:
                info_text += "Estimation traces: NOT INITIALIZED\n"
                
            if hasattr(self.app, 'visual_update_traces'):
                info_text += f"Visual update traces: {len(self.app.visual_update_traces)} active\n"
            else:
                info_text += "Visual update traces: NOT INITIALIZED\n"
            
            # Check callbacks state
            if hasattr(self.app, 'callbacks'):
                callbacks = self.app.callbacks
                info_text += f"\nCallbacks state:\n"
                info_text += f"- Loading in progress: {getattr(callbacks, '_settings_loading_in_progress', 'Not set')}\n"
                info_text += f"- Update in progress: {getattr(callbacks, '_trace_update_in_progress', 'Not set')}\n"
                info_text += f"- Timer active: {getattr(callbacks, '_frame_estimate_timer', None) is not None}\n"
            else:
                info_text += "\nCallbacks: NOT AVAILABLE\n"
            
            # Check extraction manager
            if hasattr(self.app, 'extraction_manager') and self.app.extraction_manager:
                info_text += f"\nExtraction Manager: AVAILABLE\n"
                info_text += f"- Current video: {getattr(self.app.extraction_manager, 'current_video_path', 'None')}\n"
            else:
                info_text += f"\nExtraction Manager: NOT AVAILABLE\n"
            
            messagebox.showinfo("Trace Status", info_text)
            
        except Exception as e:
            messagebox.showerror("Debug Error", f"Trace status debug failed: {e}")

    def _test_manual_settings_change_fixed(self):
        """FIXED: Manual settings change test."""
        try:
            current_method = self.app.extraction_method_var.get()
            
            if current_method == "count":
                current_count = self.app.frame_count_var.get()
                new_count = current_count + 1
                
                print(f"\n🔧 MANUAL SETTINGS TEST:")
                print(f"Changing frame count: {current_count} → {new_count}")
                
                self.app.frame_count_var.set(new_count)
                
                messagebox.showinfo("Settings Test", 
                                   f"Changed frame count from {current_count} to {new_count}.\n"
                                   f"Check if frame estimation updated immediately.")
            else:
                current_interval = self.app.interval_value_var.get()
                new_interval = current_interval + 0.5
                
                print(f"\n🔧 MANUAL SETTINGS TEST:")
                print(f"Changing interval: {current_interval} → {new_interval}")
                
                self.app.interval_value_var.set(new_interval)
                
                messagebox.showinfo("Settings Test", 
                                   f"Changed interval from {current_interval} to {new_interval}.\n"
                                   f"Check if frame estimation updated immediately.")
                
        except Exception as e:
            messagebox.showerror("Debug Error", f"Manual settings test failed: {e}")

    def _force_frame_estimation_update_fixed(self):
        """FIXED: Force frame estimation update."""
        try:
            if hasattr(self.app, 'callbacks') and hasattr(self.app.callbacks, '_update_frame_estimate'):
                print("🔄 Forcing immediate frame estimation update...")
                self.app.callbacks._update_frame_estimate()
                messagebox.showinfo("Force Update", "Frame estimation update forced.\nCheck if display updated.")
            else:
                messagebox.showwarning("Debug", "Frame estimation update method not available")
                
        except Exception as e:
            messagebox.showerror("Debug Error", f"Force update failed: {e}")

    def _debug_per_video_settings_fixed(self):
        """FIXED: Show per-video settings cache."""
        try:
            if not hasattr(self.app, 'state') or not hasattr(self.app.state, 'per_video_settings_cache'):
                messagebox.showinfo("Per-Video Settings", "Per-video settings cache not available.")
                return
                
            cache = self.app.state.per_video_settings_cache
            
            if not cache:
                messagebox.showinfo("Per-Video Settings", "No per-video settings cached.")
                return
            
            info_text = f"PER-VIDEO SETTINGS CACHE ({len(cache)} videos):\n" + "="*50 + "\n"
            
            for i, (video_path, settings) in enumerate(cache.items()):
                video_name = os.path.basename(video_path)
                info_text += f"\n[{i+1}] {video_name}:\n"
                
                # Show key settings
                method = settings.get('extraction_method', 'unknown')
                if method == 'count':
                    count = settings.get('frame_count', 'unknown')
                    info_text += f"  Method: {method}, Frames: {count}\n"
                else:
                    interval = settings.get('interval_value', 'unknown')
                    unit = settings.get('interval_unit', 'unknown')
                    info_text += f"  Method: {method}, Interval: {interval} {unit}\n"
                
                # Show view settings
                pitch = settings.get('pitch_angles_str', 'unknown')
                yaw = settings.get('yaw_steps', 'unknown')
                fov = settings.get('fov', 'unknown')
                info_text += f"  Views: Pitch={pitch}, Yaw={yaw}, FOV={fov}\n"
            
            messagebox.showinfo("Per-Video Settings Cache", info_text)
            
        except Exception as e:
            messagebox.showerror("Debug Error", f"Per-video settings debug failed: {e}")

    def _clear_per_video_settings_cache_fixed(self):
        """FIXED: Clear per-video settings cache."""
        try:
            if not hasattr(self.app, 'state') or not hasattr(self.app.state, 'per_video_settings_cache'):
                messagebox.showinfo("Clear Cache", "Per-video settings cache not available.")
                return
                
            cache_size = len(self.app.state.per_video_settings_cache)
            
            if cache_size == 0:
                messagebox.showinfo("Clear Cache", "Per-video settings cache is already empty.")
                return
            
            if messagebox.askyesno("Clear Cache", 
                                  f"Clear per-video settings cache?\n"
                                  f"This will remove cached settings for {cache_size} video(s)."):
                
                self.app.state.per_video_settings_cache.clear()
                messagebox.showinfo("Cache Cleared", 
                                   f"Cleared per-video settings for {cache_size} video(s).")
                print(f"🧹 Cleared per-video settings cache ({cache_size} entries)")
            
        except Exception as e:
            messagebox.showerror("Debug Error", f"Clear cache failed: {e}")

    def _debug_extraction_info_safe(self):
        """FIXED: Debug extraction frame system safely."""
        try:
            if not hasattr(self.app, 'extraction_manager') or not self.app.extraction_manager:
                messagebox.showwarning("Debug", "Extraction manager not available")
                return
                
            manager = self.app.extraction_manager
            
            # Safely get current video path
            current_video = getattr(manager, 'current_video_path', 'None')
            video_name = os.path.basename(current_video) if current_video else 'None'
            
            # Get cache entry safely
            cache_entry = None
            if hasattr(manager, '_get_current_cache_entry'):
                try:
                    cache_entry = manager._get_current_cache_entry()
                except:
                    pass
            
            debug_text = f"""
EXTRACTION FRAME SYSTEM DEBUG:

Video: {video_name}
Video Path: {current_video}

Cache Status:
• Cache Entry Exists: {cache_entry is not None}
• Cache Valid: {cache_entry.get('cache_valid', False) if cache_entry else False}
• Total Frames: {cache_entry.get('total_frames', 0) if cache_entry else 0}
• Current Index: {cache_entry.get('current_index', 0) if cache_entry else 0}

Extraction State:
• In Progress: {getattr(manager, 'extraction_in_progress', False)}
• Video Duration: {getattr(manager, 'video_duration', 0):.1f}s
• Video FPS: {getattr(manager, 'video_fps', 0):.1f}

UI State:
• Navigator Exists: {getattr(manager, 'frame_navigator', None) is not None}
• Info Label Exists: {getattr(manager, 'frame_info_label', None) is not None}
            """
            
            messagebox.showinfo("Extraction Frame Debug", debug_text.strip())
            
        except Exception as e:
            messagebox.showerror("Debug Error", f"Extraction debug failed: {e}")

    def _test_gpu_acceleration_safe(self):
        """FIXED: Test GPU acceleration safely."""
        try:
            if not hasattr(self.app, 'extraction_manager') or not self.app.extraction_manager:
                messagebox.showwarning("GPU Test", "Extraction manager not available")
                return
                
            manager = self.app.extraction_manager
            
            if not getattr(manager, 'current_video_path', None):
                messagebox.showwarning("GPU Test", "Load a video first to test GPU acceleration")
                return
            
            import time
            video_path = manager.current_video_path
            test_timestamp = getattr(manager, 'video_duration', 10) / 2
            
            # Test single frame extraction
            print("🧪 Testing GPU acceleration...")
            start_time = time.time()
            
            # Use the actual extraction method
            if hasattr(manager, '_extract_single_frame'):
                frame = manager._extract_single_frame(video_path, test_timestamp)
            else:
                messagebox.showwarning("GPU Test", "Frame extraction method not available")
                return
            
            extraction_time = (time.time() - start_time) * 1000
            
            if frame:
                result_text = f"""
GPU Acceleration Test Results:

✅ Extraction successful!
Time: {extraction_time:.1f}ms
Frame size: {frame.size if hasattr(frame, 'size') else 'Unknown'}

Performance Rating:
{('🚀 EXCELLENT' if extraction_time < 200 else 
  '✅ GOOD' if extraction_time < 500 else 
  '⚠️ SLOW')} ({extraction_time:.1f}ms)

For 200 frames: ~{(extraction_time * 200 / 1000):.1f}s total
                """
                messagebox.showinfo("GPU Test Results", result_text.strip())
            else:
                messagebox.showerror("GPU Test Failed", 
                                   f"GPU extraction failed after {extraction_time:.1f}ms")
        
        except Exception as e:
            messagebox.showerror("GPU Test Error", f"GPU test failed: {e}")

    def _save_debug_log_safe(self):
        """FIXED: Save debug log safely."""
        try:
            if hasattr(self.app, 'callbacks') and hasattr(self.app.callbacks, 'save_debug_log'):
                self.app.callbacks.save_debug_log()
                messagebox.showinfo("Debug Log", "Debug log saved to debug_trace.txt")
            else:
                # Fallback - create a basic debug log
                import datetime
                log_content = f"""
360° SplatPipe Debug Log
Generated: {datetime.datetime.now()}

Application State:
- GUI Available: {hasattr(self.app, 'root')}
- Callbacks Available: {hasattr(self.app, 'callbacks')}
- State Available: {hasattr(self.app, 'state')}
- Visuals Available: {hasattr(self.app, 'visuals')}
- Extraction Manager: {hasattr(self.app, 'extraction_manager')}

Video Queue: {len(getattr(self.app.state, 'video_queue', [])) if hasattr(self.app, 'state') else 'Unknown'}
Folder Queue: {len(getattr(self.app.state, 'image_folder_queue', [])) if hasattr(self.app, 'state') else 'Unknown'}
                """
                
                with open("debug_log.txt", "w") as f:
                    f.write(log_content.strip())
                
                messagebox.showinfo("Debug Log", "Basic debug log saved to debug_log.txt")
                
        except Exception as e:
            messagebox.showerror("Debug Error", f"Error saving debug log: {e}")

    # === HELP CONTENT METHODS (UNCHANGED) ===
    
    def show_quick_start(self):
        """Show quick start guide."""
        help_text = """
    360° SplatPipe - Quick Start Guide

    1. SETUP:
    • Install CUDA Toolkit 12.x for GPU acceleration (recommended)
    • Run install_requirements.bat to install Python dependencies
    • Download and install required tools:
      - FFmpeg (included in project)
      - RealityScan (for camera alignment)
      - Postshot (for neural training)
      - Brush (alternative neural training)
    • Configure tool paths in the Configuration tab
    • Save your configuration

    2. BASIC WORKFLOW:
    • Add 360° videos (.mp4, .mov, .avi) OR equirectangular image folders to input queues
    • Adjust frame extraction settings:
      - Interval Method: Extract every N seconds/frames
      - Count Method: Extract fixed number of evenly-spaced frames
    • Configure 360° view extraction:
      - Pitch Angles: Vertical camera angles (e.g., "-50, -7")
      - Yaw Steps: Number of horizontal rotations (typically 6)
      - Field of View: Camera lens angle (70-120°, default 90°)
    • Choose alignment method:
      - Standard: Use RealityScan for camera alignment + training
      - Skip RealityScan: Let Postshot handle alignment internally
    • Select training options (Postshot and/or Brush)
    • Set output project directory
    • Run Full Pipeline

    3. NEW FEATURES:
    • Live Preview: Real-time view of extracted 360° perspectives
    • Batch Processing: Process multiple videos/folders in sequence
    • Per-Video Staging: Session-based cache for both UI settings AND extracted frames. 
    • Configure each video for batch processing and with persistent settings.
    • VGGT AI Alignment: Skip RealityScan with neural network camera alignment
      - Automatic anchor+rig expansion for multi-view reconstruction
      - Sparse point cloud filtering with configurable density targets
      - Visual debugging with colored axis indicators
    • Dual Progress Bars: Track current item and overall batch progress
    • Intelligent Caching: Speeds up preview generation and parameter changes
    • Console Output: Monitor detailed progress with emoji indicators
    • XMP Export: Generate RealityScan rig files for manual import

    4. TIPS:
    • Input must be 2:1 aspect ratio equirectangular format
    • Use Skip RealityScan + VGGT mode for AI-powered alignment and training
    • Enable sparse filtering to reduce VGGT point clouds to manageable sizes
    • Use visual debugging to verify camera orientations in complex scenes
    • Higher resolution inputs = better quality but longer processing
    • Monitor console for detailed progress and troubleshooting

    5. COMPREHENSIVE CONSOLE-TO-FILE LOGGING TOOLS
    • Perfect for batch processing where logs fly by too quickly to read

        FEATURES:
        • ALL console output saved to timestamped log files
        • Thread-safe logging with timestamps down to milliseconds
        • Batch processing session markers
        • Item-level progress tracking
        • Debug menu tools for log management
        • Automatic old log cleanup

        LOG FILE LOCATION:
        • logs/splatpipe_session_YYYYMMDD_HHMMSS.log
        • Example: logs/splatpipe_session_20241208_143052.log

        PERFECT FOR BATCH PROCESSING:
        • Track which items succeeded/failed
        • Debug extraction issues across multiple videos
        • Performance analysis across batch
        • Error patterns and timing issues
        • Complete audit trail of all operations

    For detailed parameter explanations, see Parameter Guide.
        """
        self._show_help_window("Quick Start Guide", help_text)

    def show_parameter_guide(self):
        """Show detailed parameter explanations."""
        help_text = """
    360° SplatPipe - Parameter Guide

    FRAME EXTRACTION:
    • Interval Method: Extract frames at regular time/frame intervals
      - Seconds: Extract every N seconds (e.g., 1.0 = every second)
      - Frames: Extract every N frames (e.g., 30 = every 30th frame)
    • Count Method: Extract fixed number of evenly-spaced frames
      - Total Frames: Exact number of frames to extract from entire video
      - Automatically calculates optimal spacing across video duration
    • Frame Format: Choose between JPEG (fast) or PNG (high quality)

    360° VIEW EXTRACTION:
    • Pitch Angles: Vertical camera angles, comma-separated (e.g., "-50, -7")
      - Negative = looking down, Positive = looking up
      - Typical range: -60° to +30°
      - More angles = better coverage but longer processing
    • Yaw Steps: Number of horizontal rotations around each pitch
      - Distributes cameras evenly around 360° horizon
      - Recommended: 6 steps (60° between cameras)
      - More steps = denser coverage but exponentially longer processing
    • Field of View: Camera lens angle in degrees
      - Typical range: 70-120°, Default: 90°
      - Wider FOV = more context per view but potential distortion
      - Narrower FOV = more detailed views but requires more cameras

    OVERLAY APPEARANCE:
    • Opacity Slider: Controls visibility of camera position overlays
      - 0% = Invisible overlays
      - 50% = White overlays  
      - 100% = Full-color overlays
      - Selected camera always shows full color with stipple pattern

    ALIGNMENT OPTIONS:
    • Standard Mode: Use RealityScan for camera pose alignment
      - Most accurate alignment for complex scenes
      - Exports data for both Postshot and Brush training
      - Requires RealityScan installation and setup
    • Skip RealityScan + VGGT Mode: AI-powered camera alignment
      - Uses VGGT (View Geometry and Ground Truth) neural network
      - Estimates camera poses and generates 3D point clouds automatically
      - Works with both Postshot and Brush training
      - Supports anchor+rig expansion for multi-view reconstruction
      - Includes sparse point cloud filtering options:
        * Enable Sparse Filter: Reduces dense point clouds to manageable size
        * Target Points: Specify final point cloud density (e.g., 2M points)
        * Uses voxel-based downsampling with smart clustering
      - Visual debugging with colored axis indicators for camera orientation
      - No external alignment software required

    TRAINING METHODS:
    • Postshot Training (Jawset): https://www.jawset.com/
      - Splat3: Fast training, good for testing and previews
      - Splat MCMC: Best quality, adaptive splat management, longer training
      - Splat ADC: Advanced density control, experimental features
      - Max Image Size: Resize images for training (0 = original resolution)
      - Train Steps: More steps = better quality but longer time (default: 30k)
      - Max Splats: Maximum 3D Gaussian points (MCMC profile only)
      - Export PLY: Save point cloud for external visualization
    
    • Brush Training (Alternative): https://github.com/ArthurBrussee/brush
      - WebGPU-based renderer, cross-platform compatibility
      - Generally faster rendering than traditional Gaussian Splatting
      - Total Steps: Training iterations (default: 30k)
      - Export Interval: Save intermediate results every N steps
      - Viewer Mode: Show real-time training progress (resource intensive)
      - Rerun Logging: Enable detailed training visualization

    EXPORT OPTIONS:
    • XMP Rig Files: Generate camera rig metadata for RealityScan
      - Creates .xmp files alongside extracted views

    HARDWARE RECOMMENDATIONS:
    • GPU: NVIDIA RTX 3060 or better for optimal performance
    • RAM: 16GB+ recommended for large projects
    • Storage: SSD recommended, 2-10GB per project
    • CPU: Modern multi-core processor for video decoding
        """
        self._show_help_window("Parameter Guide", help_text)

    def show_troubleshooting(self):
        """Show troubleshooting guide."""
        help_text = """
    360° SplatPipe - Troubleshooting

    COMMON ISSUES:

    1. GPU Acceleration Not Working:
    ---- Read the README ----
    • Install CUDA Toolkit 12.x (not 11.x)
    • Run check_cupy.bat to verify CuPy installation
    • Clear PATH environment variable of old CUDA versions
    • Restart computer after CUDA installation
    • Check console for "GPU acceleration enabled" message

    2. Frame Extraction Slow/Failing:
    • Ensure FFmpeg path is configured correctly
    • Try using lower resolution videos for testing
    • Check video format is supported (MP4, MOV, AVI)
    • For interval method, try smaller interval values
    • Monitor console for specific FFmpeg error messages

    3. Live Preview Not Working:
    • Verify input images are exactly 2:1 aspect ratio
    • Check that py360convert library is installed
    • Ensure image files are not corrupted
    • Use standard image formats (JPG, PNG)

    4. RealityScan Integration Issues:
    • Verify RealityScan executable path is correct
    • Check RealityScan settings folder path
    • Run RealityScan manually to test installation

    5. Training Failures:
    • Check training tool executable paths (Postshot/Brush)
    • Ensure sufficient disk space (2-10GB per project)
    • Monitor console for specific training error messages
    • Try reducing max image size or train steps
    • For Brush: disable viewer mode if system resources are limited

    6. Batch Processing Issues:
    • Ensure all input files are valid and accessible
    • Check project directory has write permissions
    • One failed item won't stop the entire batch
    • Use console output to identify problematic files
    • Clear queues and restart if UI becomes unresponsive

    7. Console Output Problems:
    • Toggle console visibility with the Console button
    • Clear console if it becomes cluttered
    • Console shows colored output with emoji indicators
    • Use console output for detailed error diagnosis

    GETTING HELP:
    • Check Configuration tab for missing tool paths
    • Ensure all external dependencies are properly installed
    • Monitor console output for detailed error information
    • Verify input files meet format requirements (2:1 aspect ratio)
    • Try processing a simple test case before complex projects

    PERFORMANCE OPTIMIZATION:
    • Use SSD storage for faster file I/O
    • Close other GPU-intensive applications during processing
    • Reduce image resolution for faster testing
    • Use Skip RealityScan mode for simpler workflows
        """
        self._show_help_window("Troubleshooting", help_text)

    def show_about(self):
        """Show about dialog."""
        about_text = """
    360° SplatPipe
    Version 1.0 - 2025 Edition
    by Nicolas de Cosson - RobotCafe - GiantEye.ca
    
    Major shoutouts:
    • Laskos Virtuals - https://laskos.fi/rd
    • Ronskiuk - https://www.youtube.com/@ronskiuk
    • Olli Huttunen - https://www.youtube.com/@OlliHuttunen78

    DESCRIPTION:
    A complete pipeline for processing 360° content into 3D Gaussian Splats for 
    neural rendering and immersive experiences. Combines traditional computer vision 
    with cutting-edge neural radiance field techniques.

    KEY FEATURES:
    • Frame extraction from 360° videos with GPU acceleration
    • Multi-angle view generation with real-time preview
    • Per-Video Settings: In-memory caching for individual video configurations in a batch.
    • Camera pose alignment via RealityScan or VGGT neural network
    • Neural training with Postshot and Brush integration
    • Batch processing with dual progress tracking
    • "Smart" Extraction: Incrementally adds/removes frames from the cache when settings are changed.
    • VGGT Mode: AI-powered camera alignment with anchor+rig expansion
    • Coordinate system debugging with visual axis indicators
    • Sparse point cloud filtering with voxel-based downsampling
    • Intelligent caching for improved performance
    • Live console output with colored logging
    • XMP export for advanced RealityScan workflows

    SUPPORTED WORKFLOWS:
    • Standard: Video → Frames → Views → RealityScan → Training
    • Skip RealityScan + VGGT: Video → Frames → Views → VGGT Alignment → Training
      * AI-powered camera pose estimation with anchor+rig expansion
      * Automatic sparse point cloud generation and filtering
    • Image Mode: Equirectangular Images → Views → Training
    • Batch Mode: Multiple inputs processed sequentially with per-video settings

    CORE DEPENDENCIES:
    • Python 3.8+ with tkinter GUI framework
    • NumPy, Pillow, OpenCV for image processing
    • CuPy (optional) for GPU-accelerated view extraction  
    • py360convert for equirectangular projections
    • FFmpeg for video frame extraction
    • Matplotlib, SciPy for mathematical operations

    EXTERNAL TOOLS:
    • RealityScan: Camera pose alignment and registration
    • Postshot: High-quality Gaussian Splatting training
    • Brush: Alternative WebGPU-based neural training
    • CUDA Toolkit 12.x: GPU acceleration support

    OUTPUT FORMATS:
    • PSHT files: Postshot native format for real-time playback
    • PLY files: Point cloud format for external viewers
    • Training data: Raw Gaussian parameters for research
    • XMP files: RealityScan-compatible camera metadata

    SYSTEM REQUIREMENTS:
    • OS: Windows 10 - Has not been tested on Windows 11
    • RAM: 8GB minimum, 16GB+ recommended  
    • GPU: NVIDIA RTX series recommended 
    • Storage: 2-10GB per project depending on complexity
    • Network: Not required (fully offline processing)

    This software is provided as-is
        """
        self._show_help_window("About 360° SplatPipe", about_text)

    def _show_help_window(self, title, content):
        """Show help content in a scrollable window."""
        help_window = tk.Toplevel(self.root)
        help_window.title(title)
        help_window.geometry("900x600")
        
        # Create scrolled text widget
        text_widget = scrolledtext.ScrolledText(
            help_window, 
            wrap=tk.WORD, 
            font=("Arial", 10),
            padx=10,
            pady=10
        )
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Insert content
        text_widget.insert(tk.END, content)
        text_widget.config(state=tk.DISABLED)  # Make read-only
        
        # Close button
        ttk.Button(help_window, text="Close", command=help_window.destroy).pack(pady=10)