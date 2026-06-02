# FIXED video_extraction.py - Better timestamp calculation with proper buffer
import os
import subprocess
import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image

def find_ffprobe_executable(ffmpeg_path="ffmpeg"):
    """Find ffprobe executable."""
    if ffmpeg_path and ffmpeg_path != "ffmpeg":
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ffmpeg_name = os.path.basename(ffmpeg_path)
        
        if 'ffmpeg' in ffmpeg_name.lower():
            ffprobe_name = ffmpeg_name.lower().replace('ffmpeg', 'ffprobe')
            ffprobe_path = os.path.join(ffmpeg_dir, ffprobe_name)
            if os.path.exists(ffprobe_path):
                return ffprobe_path
        
        for probe_name in ['ffprobe.exe', 'ffprobe']:
            ffprobe_path = os.path.join(ffmpeg_dir, probe_name)
            if os.path.exists(ffprobe_path):
                return ffprobe_path
    
    ffprobe_path = shutil.which('ffprobe')
    if ffprobe_path:
        return ffprobe_path
    
    return None

def get_video_info(video_path, ffmpeg_path="ffmpeg"):
    """Get video info using ffprobe only."""
    try:
        ffprobe_path = find_ffprobe_executable(ffmpeg_path)
        if not ffprobe_path:
            print("Warning: ffprobe executable not found.")
            return {}

        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json", 
            "-show_format",
            "-show_streams",
            str(video_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        data = json.loads(result.stdout)
        info = {}

        video_stream = next((stream for stream in data.get('streams', []) 
                           if stream.get('codec_type') == 'video'), None)

        if not video_stream:
            return {}

        if 'format' in data and 'duration' in data['format']:
            info['duration'] = float(data['format']['duration'])

        if 'width' in video_stream and 'height' in video_stream:
            info['width'] = int(video_stream['width'])
            info['height'] = int(video_stream['height'])

        if 'avg_frame_rate' in video_stream:
            fps_str = video_stream['avg_frame_rate']
            if fps_str and fps_str != '0/0':
                try:
                    num, den = map(int, fps_str.split('/'))
                    if den != 0:
                        info['fps'] = num / den
                except (ValueError, ZeroDivisionError):
                    pass

        return info

    except Exception as e:
        print(f"Warning: Failed to get video info: {e}")
        return {}

def extract_single_frame_gpu(video_path, timestamp, output_path, ffmpeg_path='ffmpeg', use_gpu=True):
    """
    Extract single frame with optional GPU acceleration.
    Returns True if successful, False otherwise.
    """
    try:
        if use_gpu:
            # GPU-accelerated command
            cmd = [
                ffmpeg_path,
                "-c:v", "hevc_cuvid",                   # Hardware decoder
                "-ss", f"{timestamp:.3f}",             # Seek to exact timestamp
                "-i", video_path,                      # Input video
                "-frames:v", "1",                      # Extract exactly 1 frame
                "-q:v", "2",                           # High quality
                "-y",                                  # Overwrite existing
                output_path
            ]
        else:
            # CPU fallback command
            cmd = [
                ffmpeg_path,
                "-ss", f"{timestamp:.3f}",             # Seek to exact timestamp
                "-i", video_path,                      # Input video
                "-frames:v", "1",                      # Extract exactly 1 frame
                "-q:v", "2",                           # High quality
                "-y",                                  # Overwrite existing
                output_path
            ]
        
        # Execute with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            return True
        else:
            if use_gpu and "No HEVC hardware capable devices found" in result.stderr:
                print("⚠️ GPU acceleration not available, falling back to CPU")
                return extract_single_frame_gpu(video_path, timestamp, output_path, ffmpeg_path, use_gpu=False)
            else:
                print(f"FFmpeg extraction failed: {result.stderr}")
                return False
                
    except subprocess.TimeoutExpired:
        print(f"⏰ FFmpeg extraction timeout at {timestamp:.3f}s")
        return False
    except Exception as e:
        print(f"❌ Error extracting frame at {timestamp:.3f}s: {e}")
        return False

def extract_frames_for_video(video_path, output_folder, extraction_method='interval', 
                           interval_value=1.0, interval_unit='seconds', frame_count=30,
                           progress_callback=None, ffmpeg_path='ffmpeg', frame_format='jpg', 
                           cancel_event=None, use_gpu=True):
    """
    ENHANCED: Frame extraction with GPU acceleration and FIXED timestamp calculation.
    """
    try:
        if not os.path.exists(video_path):
            print(f"Error: Video file not found: {video_path}")
            return False

        if cancel_event and cancel_event.is_set():
            print("🛑 Frame extraction cancelled before starting")
            return False
        
        os.makedirs(output_folder, exist_ok=True)
        
        # Get video info
        video_info = get_video_info(video_path, ffmpeg_path)
        duration = video_info.get('duration')
        fps = video_info.get('fps', 30)
        
        if not duration or duration <= 0:
            print(f"Error: Could not determine video duration")
            return False
        
        print(f"📹 Video: {duration:.1f}s, {fps:.1f} FPS")
        
        # FIXED: Calculate timestamps with proper buffer
        timestamps = calculate_extraction_timestamps(duration, fps, extraction_method, 
                                                   interval_value, interval_unit, frame_count)
        
        if not timestamps:
            print("Error: No valid timestamps calculated")
            return False
        
        print(f"🚀 GPU-accelerated extraction: {len(timestamps)} frames")
        print(f"🎯 Timestamps: {[f'{t:.1f}s' for t in timestamps[:3]]}...{[f'{t:.1f}s' for t in timestamps[-3:]]}")
        
        # Extract frames with GPU acceleration
        extracted_count = 0
        total_frames = len(timestamps)
        gpu_failed = False
        
        for i, timestamp in enumerate(timestamps):
            if cancel_event and cancel_event.is_set():
                print(f"🛑 Frame extraction cancelled at frame {i+1}/{total_frames}")
                break

            output_file = os.path.join(output_folder, f"frame_{i+1:06d}.{frame_format}")
            
            # Try GPU first, fallback to CPU if needed
            current_use_gpu = use_gpu and not gpu_failed
            success = extract_single_frame_gpu(video_path, timestamp, output_file, ffmpeg_path, current_use_gpu)
            
            if not success and use_gpu and not gpu_failed:
                # GPU might have failed, try CPU for this frame
                print("⚠️ GPU extraction failed, trying CPU fallback")
                success = extract_single_frame_gpu(video_path, timestamp, output_file, ffmpeg_path, False)
                if not success:
                    gpu_failed = True  # Disable GPU for remaining frames
            
            if success:
                extracted_count += 1
                if progress_callback:
                    progress_callback(extracted_count, total_frames, timestamp)
                
                accel_type = "GPU" if current_use_gpu else "CPU"
                print(f"✓ Frame {extracted_count}/{total_frames} at {timestamp:.1f}s ({accel_type})")
            else:
                print(f"✗ Failed to extract frame at {timestamp:.1f}s")
        
        print(f"✅ Extracted {extracted_count}/{total_frames} frames successfully")
        
        if progress_callback and not (cancel_event and cancel_event.is_set()):
            progress_callback(extracted_count, extracted_count, duration)
        
        return extracted_count > 0
        
    except Exception as e:
        print(f"❌ Frame extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_video_duration(video_path, ffmpeg_path="ffmpeg"):
    """Get video duration."""
    video_info = get_video_info(video_path, ffmpeg_path)
    return video_info.get('duration')

def calculate_extraction_timestamps(video_duration, video_fps, extraction_method, interval_value, interval_unit, frame_count):
    """
    FIXED: Calculate extraction timestamps with proper buffer to avoid end-of-video issues.
    Used by both preview system and pipeline extraction.
    """
    try:
        # CRITICAL FIX: Use a buffer to prevent extraction at/after video end
        buffer_time = 0.2  # 200ms buffer from end
        safe_duration = max(0, video_duration - buffer_time)
        
        if extraction_method == "count":
            if frame_count <= 0:
                return []
                
            if frame_count == 1:
                return [video_duration / 2]  # Middle of video
            else:
                # FIXED: Evenly spaced frames within safe duration
                timestamps = []
                for i in range(frame_count):
                    timestamp = i * safe_duration / (frame_count - 1)
                    timestamps.append(timestamp)
                return timestamps
                
        else:  # interval method
            if interval_value <= 0:
                return []
                
            timestamps = []
            if interval_unit == "seconds":
                current_time = 0
                while current_time < safe_duration:
                    timestamps.append(current_time)
                    current_time += interval_value
                # Add final frame if we have room
                if timestamps and timestamps[-1] < safe_duration - interval_value:
                    timestamps.append(min(timestamps[-1] + interval_value, safe_duration))
                    
            else:  # frames
                frame_interval = int(interval_value)
                total_frames = int(video_duration * video_fps)
                
                for frame_num in range(0, total_frames, frame_interval):
                    timestamp = frame_num / video_fps
                    if timestamp < safe_duration:
                        timestamps.append(timestamp)
            
            return timestamps
            
    except Exception as e:
        print(f"Error calculating extraction timestamps: {e}")
        return []