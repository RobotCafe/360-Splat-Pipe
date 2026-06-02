import cv2
import subprocess
import os
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Union, Generator
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import time

class VideoFrameExtractor:
    """
    Fast and robust video frame extractor with GPU acceleration fallback.
    Tries OpenCV with CUDA first, falls back to FFmpeg if unavailable.
    """
    
    def __init__(self, prefer_gpu: bool = True, log_level: str = "INFO"):
        self.logger = self._setup_logger(log_level)
        self.cuda_available = False
        self.backend = None
        
        if prefer_gpu:
            self.cuda_available = self._check_cuda_support()
            
        self.backend = "cuda" if self.cuda_available else "cpu"
        self.logger.info(f"Initialized with backend: {self.backend}")
    
    def _setup_logger(self, level: str) -> logging.Logger:
        """Setup logging for the extractor."""
        logger = logging.getLogger("VideoFrameExtractor")
        logger.setLevel(getattr(logging, level.upper()))
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _check_cuda_support(self) -> bool:
        """Check if OpenCV was built with CUDA support."""
        try:
            # Check if OpenCV has CUDA support
            if not hasattr(cv2, 'cuda') or cv2.cuda.getCudaEnabledDeviceCount() == 0:
                self.logger.info("CUDA not available in OpenCV or no CUDA devices found")
                return False
            
            # Test CUDA functionality with a simple operation
            test_mat = cv2.cuda_GpuMat()
            test_mat.upload(np.zeros((100, 100), dtype=np.uint8))
            test_mat.download()
            
            self.logger.info(f"CUDA support confirmed. Devices: {cv2.cuda.getCudaEnabledDeviceCount()}")
            return True
            
        except Exception as e:
            self.logger.info(f"CUDA support check failed: {e}")
            return False
    
    def _check_ffmpeg_available(self) -> bool:
        """Check if FFmpeg is available in the system."""
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def get_video_info(self, video_path: str) -> dict:
        """Get video information including fps, frame count, duration, etc."""
        video_path = str(Path(video_path).resolve())
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")
        
        try:
            info = {
                'fps': cap.get(cv2.CAP_PROP_FPS),
                'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                'duration': cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS),
                'fourcc': int(cap.get(cv2.CAP_PROP_FOURCC))
            }
            return info
        finally:
            cap.release()
    
    def extract_frames_opencv(self, 
                            video_path: str,
                            output_dir: str,
                            start_time: float = 0,
                            end_time: Optional[float] = None,
                            fps_target: Optional[float] = None,
                            max_frames: Optional[int] = None,
                            frame_format: str = "jpg",
                            quality: int = 95) -> List[str]:
        """Extract frames using OpenCV (with CUDA if available)."""
        
        video_path = str(Path(video_path).resolve())
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Open video capture
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        try:
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Calculate frame extraction parameters
            start_frame = int(start_time * video_fps)
            end_frame = int(end_time * video_fps) if end_time else total_frames
            
            # Set frame extraction interval
            if fps_target:
                frame_interval = max(1, int(video_fps / fps_target))
            else:
                frame_interval = 1
            
            # Set starting position
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            extracted_files = []
            frame_count = 0
            current_frame = start_frame
            
            # Setup CUDA GPU mat if available
            if self.cuda_available:
                gpu_frame = cv2.cuda_GpuMat()
            
            while current_frame < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if current_frame % frame_interval == 0:
                    # Process frame (GPU acceleration if available)
                    if self.cuda_available:
                        try:
                            gpu_frame.upload(frame)
                            # Could add GPU-based image processing here if needed
                            processed_frame = gpu_frame.download()
                        except Exception as e:
                            self.logger.warning(f"GPU processing failed, using CPU: {e}")
                            processed_frame = frame
                    else:
                        processed_frame = frame
                    
                    # Save frame
                    timestamp = current_frame / video_fps
                    filename = f"frame_{frame_count:06d}_{timestamp:.3f}s.{frame_format}"
                    filepath = output_dir / filename
                    
                    # Set compression parameters
                    if frame_format.lower() == 'jpg':
                        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
                    elif frame_format.lower() == 'png':
                        params = [cv2.IMWRITE_PNG_COMPRESSION, 9 - (quality // 11)]
                    else:
                        params = []
                    
                    cv2.imwrite(str(filepath), processed_frame, params)
                    extracted_files.append(str(filepath))
                    frame_count += 1
                    
                    if max_frames and frame_count >= max_frames:
                        break
                
                # Skip frames for faster processing
                for _ in range(frame_interval - 1):
                    ret = cap.grab()
                    if not ret:
                        break
                    current_frame += 1
                
                current_frame += 1
            
            self.logger.info(f"Extracted {len(extracted_files)} frames using OpenCV ({self.backend})")
            return extracted_files
            
        finally:
            cap.release()
    
    def extract_frames_ffmpeg(self,
                            video_path: str,
                            output_dir: str,
                            start_time: float = 0,
                            end_time: Optional[float] = None,
                            fps_target: Optional[float] = None,
                            max_frames: Optional[int] = None,
                            frame_format: str = "jpg",
                            quality: int = 95) -> List[str]:
        """Extract frames using FFmpeg as fallback."""
        
        if not self._check_ffmpeg_available():
            raise RuntimeError("FFmpeg is not available on this system")
        
        video_path = str(Path(video_path).resolve())
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build FFmpeg command
        cmd = ['ffmpeg', '-y']  # -y to overwrite existing files
        
        # Input options
        if start_time > 0:
            cmd.extend(['-ss', str(start_time)])
        
        cmd.extend(['-i', video_path])
        
        # Duration limit
        if end_time:
            duration = end_time - start_time
            cmd.extend(['-t', str(duration)])
        
        # Frame rate
        if fps_target:
            cmd.extend(['-vf', f'fps={fps_target}'])
        
        # Max frames
        if max_frames:
            cmd.extend(['-frames:v', str(max_frames)])
        
        # Quality settings
        if frame_format.lower() == 'jpg':
            cmd.extend(['-q:v', str(31 - (quality * 30 // 100))])
        
        # Output pattern
        output_pattern = str(output_dir / f"frame_%06d.{frame_format}")
        cmd.append(output_pattern)
        
        # Execute FFmpeg
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg failed: {result.stderr}")
            
            # Get list of created files
            extracted_files = list(output_dir.glob(f"frame_*.{frame_format}"))
            extracted_files.sort()
            
            self.logger.info(f"Extracted {len(extracted_files)} frames using FFmpeg")
            return [str(f) for f in extracted_files]
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg operation timed out")
    
    def extract_frames(self,
                      video_path: str,
                      output_dir: str,
                      start_time: float = 0,
                      end_time: Optional[float] = None,
                      fps_target: Optional[float] = None,
                      max_frames: Optional[int] = None,
                      frame_format: str = "jpg",
                      quality: int = 95,
                      force_ffmpeg: bool = False) -> List[str]:
        """
        Main method to extract frames with automatic fallback.
        
        Args:
            video_path: Path to input video file
            output_dir: Directory to save extracted frames
            start_time: Start time in seconds (default: 0)
            end_time: End time in seconds (default: entire video)
            fps_target: Target FPS for extraction (default: original FPS)
            max_frames: Maximum number of frames to extract
            frame_format: Output format ('jpg', 'png', etc.)
            quality: Quality setting (1-100, higher = better quality)
            force_ffmpeg: Force use of FFmpeg instead of OpenCV
            
        Returns:
            List of paths to extracted frame files
        """
        
        start_extraction = time.time()
        
        try:
            if force_ffmpeg:
                self.logger.info("Forcing FFmpeg usage")
                return self.extract_frames_ffmpeg(
                    video_path, output_dir, start_time, end_time,
                    fps_target, max_frames, frame_format, quality
                )
            
            # Try OpenCV first
            try:
                return self.extract_frames_opencv(
                    video_path, output_dir, start_time, end_time,
                    fps_target, max_frames, frame_format, quality
                )
            except Exception as e:
                self.logger.warning(f"OpenCV extraction failed: {e}")
                self.logger.info("Falling back to FFmpeg")
                
                return self.extract_frames_ffmpeg(
                    video_path, output_dir, start_time, end_time,
                    fps_target, max_frames, frame_format, quality
                )
                
        finally:
            elapsed = time.time() - start_extraction
            self.logger.info(f"Frame extraction completed in {elapsed:.2f} seconds")


def extract_video_frames(video_path: str,
                        output_dir: str,
                        **kwargs) -> List[str]:
    """
    Convenience function for quick frame extraction.
    
    This is the main function you'd typically import and use in your pipeline.
    """
    extractor = VideoFrameExtractor()
    return extractor.extract_frames(video_path, output_dir, **kwargs)


# Example usage and testing
if __name__ == "__main__":
    # Example usage
    extractor = VideoFrameExtractor()
    
    # Get video info
    try:
        info = extractor.get_video_info("sample_video.mp4")
        print(f"Video info: {info}")
    except Exception as e:
        print(f"Could not get video info: {e}")
    
    # Extract frames
    try:
        frames = extractor.extract_frames(
            video_path="sample_video.mp4",
            output_dir="extracted_frames",
            start_time=10,      # Start at 10 seconds
            end_time=20,        # End at 20 seconds
            fps_target=2,       # Extract 2 frames per second
            max_frames=50,      # Maximum 50 frames
            frame_format="jpg",
            quality=90
        )
        print(f"Extracted {len(frames)} frames")
        
    except Exception as e:
        print(f"Extraction failed: {e}")