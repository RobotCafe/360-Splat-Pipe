# 360° SplatPipe

**360° SplatPipe Version 1.0 - 2025**  
by Nicolas de Cosson - RobotCafe - GiantEye.ca

Shoutouts:
- **Laskos Virtuals** - https://laskos.fi/rd
- **Ronskiuk** - https://www.youtube.com/@ronskiuk  
- **Olli Huttunen** - https://www.youtube.com/@OlliHuttunen78
- **PostShot** - https://www.jawset.com/
- **Brush** - https://github.com/ArthurBrussee/brush

---

A complete pipeline for converting 360° videos and equirectangular images into 3D Gaussian Splats for neural rendering and immersive experiences.

## 🚀 What's New

- **📦 Packaged App Distribution**: Lightweight installer with automatic dependency management
- **🔧 First-Run Setup Wizard**: Guided dependency installation with CPU/GPU options
- **⚡ Smart Dependency Loading**: Heavy libraries downloaded only when needed
- **VGGT AI Alignment**: Skip RealityScan with neural network-powered camera alignment
- **Anchor+Rig Expansion**: Automatic multi-view reconstruction with 144+ camera positions
- **Sparse Point Cloud Filtering**: Reduce dense point clouds with configurable density targets
- **Visual Debug System**: Colored axis indicators for camera orientation verification
- **Live Preview System**: Real-time visualization of extracted 360° views with interactive selection
- **Batch Processing**: Process multiple videos/folders with dual progress tracking
- **Skip RealityScan Mode**: Streamlined workflow using Postshot's internal alignment
- **Intelligent Caching**: Smart preview and thumbnail caching for improved performance
- **Enhanced Console**: Colored emoji-based logging with real-time feedback
- **XMP Export**: Generate RealityScan-compatible rig files for advanced workflows

## 📋 Quick Start

### 1. **Prerequisites & Installation**

**📦 Packaged App Installation:**
- Download and run the SplatPipe installer (.exe)
- **First Launch**: Setup wizard automatically handles dependency installation
- Choose installation type:
  - **Full Installation**: GPU acceleration + all features (requires CUDA 12.x)
  - **Quick Start**: CPU mode, lightweight setup
  - **Skip**: Use existing Python dependencies

**🛠️ Manual Installation (Development):**
- **FIRST** Install [CUDA Toolkit 12.x](https://developer.nvidia.com/cuda-12-8-0-download-archive) for GPU acceleration
- Run `install_requirements.bat --full` for complete installation
- Run `install_requirements.bat --core` for lightweight CPU-only setup
- To diagnose issues, run `check_cupy.bat` and verify CUDA paths

**⚠️ VGGT Installation & Model Setup Required**
- VGGT is a separate Meta research tool that must be installed following their instructions
- **Model Selection**: VGGT offers two pretrained models:
  - **Commercial Model**: Licensed for commercial/production use
  - **Non-Commercial Model**: Research and educational use only
- **Model Setup**: After choosing and downloading your model:
  1. Create a `models/` folder in your SplatPipe installation directory
  2. Place the downloaded VGGT model file in the `models/` folder
  3. Configure both VGGT installation path AND model path in Configuration tab
- **Sky Segmentation Model**: Automatically downloaded on first use
  - Downloads `skyseg.onnx` from Hugging Face to the same `models/` folder
  - Only downloads once, then uses cached version for all subsequent runs
  - No manual setup required - handled automatically when sky filtering is enabled
- GPU acceleration strongly recommended for VGGT processing
- Ensure both VGGT installation and model configuration are complete before using Skip RealityScan + VGGT mode

**Required External Tools:**
- **FFmpeg** (included in project)
- **RealityScan** - [Download](https://www.realityscan.com/en-US/download)
- **VGGT** - AI-powered camera alignment - [Download and Installation Instructions](https://github.com/facebookresearch/vggt)
- **Postshot** - [Download](https://www.jawset.com/)
- **Brush** - [Download](https://github.com/ArthurBrussee/brush)

### 2. **Configure Paths**
- Open the **Configuration** tab in the application
- Set paths to all external tools and folders:
  - **VGGT Installation Path**: Path to VGGT executable
  - **VGGT Model Path**: Path to downloaded VGGT model file (in models/ folder)
  - **RealityScan Settings Folder**: RealityScan configuration directory
  - **Other tool paths**: Postshot, Brush, FFmpeg locations
- **Important**: Both VGGT installation AND model paths must be configured
- **Save Configuration** to persist all settings

**Example VGGT Configuration:**
```
VGGT Installation: C:\VGGT\vggt.exe
VGGT Model Path: C:\SplatPipe\models\vggt_commercial_model.pth
```

**SplatPipe Folder Structure (after VGGT setup):**
```
SplatPipe/
├── App/
├── models/                         # Create this folder
│   ├── vggt_commercial_model.pth   # Commercial model (if chosen)
│   ├── vggt_noncommercial_model.pth # Non-commercial model (if chosen)
│   └── skyseg.onnx                 # Sky segmentation (auto-downloaded)
├── install_requirements.bat
└── main_app.py
```

### 3. **Basic Workflow**

#### Standard Workflow with RealityScan:
1. Add 360° videos (.mp4, .mov, .avi) OR equirectangular image folders
2. Configure frame extraction (interval or count method)
3. Set 360° view parameters (pitch angles, yaw steps, FOV)
4. Select Alignment Options
5. Select training options (Postshot and/or Brush)
6. Set output project directory
7. **Run Full Pipeline**

#### AI-Powered Workflow (Skip RealityScan + VGGT):
1. Add content and configure extraction as above
2. Choose **Skip RealityScan + VGGT** in Alignment tab
3. Configure VGGT options:
   - Enable sparse filtering for large point clouds
   - Set target point density (e.g., 2M points)
   - Enable visual debugging if needed
4. Select **Postshot** and/or **Brush Training**
5. **Run Full Pipeline** - VGGT handles alignment with neural networks

#### Postshot-Only Workflow (Skip RealityScan):
1. Add content and configure extraction as above
2. Choose **Skip RealityScan** in Alignment tab  
3. Select **Postshot Training** (Brush disabled in this mode)
4. **Run Full Pipeline** - Postshot handles alignment internally

## 📁 Input Requirements

- **Videos**: 2:1 aspect ratio in formats supported by FFmpeg (MP4, MOV, AVI)
- **Images**: 2:1 aspect ratio equirectangular format (JPG, PNG)
- **Resolution**: Higher resolution = better quality but longer processing time
- **Format**: Must be true equirectangular projection (not fisheye or other formats)

## 📂 Output Structure

```
ProjectName/
├── 01_frames/              # Extracted frames (from videos or images)
├── 02_views/               # Extracted 360° views
│   ├── frame_name/         # Individual frame directories
│   │   ├── *_view_*.jpg    # Extracted camera views
│   │   ├── *.xmp           # RealityScan rig files (if XMP export enabled)
│   ├── registration.csv    # Camera poses (RealityScan output)
│   └── pointcloud.ply      # Initial 3D points (RealityScan output)
├── 03_alignment/           # RealityScan project files
│   ├── RS.rcproj           # RealityScan project
│   └── COLMAP_for_Brush/   # Brush-compatible alignment data
├── 04_training/            # Neural training outputs
│   ├── postshot_input/     # VGGT-generated Postshot training data
│   │   ├── cameras.txt     # COLMAP camera parameters
│   │   ├── images.txt      # COLMAP image poses  
│   │   ├── points3D.txt    # COLMAP 3D points
│   │   ├── sparse_filtered.ply # Filtered point cloud (if enabled)
│   │   └── debug_scene.glb # Visual debugging (if enabled)
│   ├── brush_input/        # VGGT-generated Brush training data
│   │   └── [same structure as postshot_input]
│   ├── *_postshot.psht     # Postshot Gaussian Splat files
│   ├── *_postshot.ply      # Postshot point clouds (if enabled)
│   └── *_brush_*.ply       # Brush training outputs
└── *_pipeline_log.json     # Detailed processing log
```

## 🔧 Key Features Explained

### Frame Extraction Methods
- **Interval Method**: Extract every N seconds or N frames
- **Count Method**: Extract fixed number evenly spaced across video duration
- **GPU Acceleration**: Uses CUDA-accelerated OpenCV when available

### 360° View Generation  
- **Pitch Angles**: Vertical camera positions (e.g., "-50, -7" = down 50°, down 7°)
- **Yaw Steps**: Number of horizontal positions around each pitch (typically 6)
- **Live Preview**: Real-time visualization with interactive camera selection
- **Smart Caching**: Caches generated views for instant parameter adjustments

### Alignment Options
- **Standard Mode**: RealityScan performs Structure-from-Motion alignment
  - Most accurate alignment for complex scenes
  - Full manual control over camera poses
  - Exports data compatible with all training methods
- **Skip RealityScan + VGGT Mode**: AI-powered neural network alignment
  - Uses VGGT (View Geometry and Ground Truth) for automatic pose estimation
  - Anchor+rig expansion: Creates 144+ camera positions from 24 base anchors
  - Sparse point cloud filtering with voxel-based downsampling
  - Visual debugging with colored axis indicators for camera orientation
  - Chunked processing for memory optimization with large point clouds
  - Y-up, Z-forward coordinate system (OpenCV convention)
  - Works with both Postshot and Brush training
- **Skip RealityScan Mode**: Postshot handles alignment internally (faster, simpler)
- **XMP Export**: Generate RealityScan-compatible camera rig metadata

### Neural Training
- **Postshot (Jawset)**: Industry-standard Gaussian Splatting with multiple profiles
  - Splat3: Fast training, good for previews
  - Splat MCMC: Highest quality, adaptive management
  - Splat ADC: Experimental advanced features
- **Brush**: Alternative WebGPU-based training with cross-platform support

### Batch Processing
- **Multiple Inputs**: Process videos and image folders in sequence
- **Dual Progress**: Track individual item progress and overall batch progress
- **Error Recovery**: Continue processing if individual items fail
- **Detailed Logging**: Complete processing logs for each item

## 🧠 VGGT AI Alignment System

VGGT (View Geometry and Ground Truth) is an integrated neural network system that revolutionizes camera alignment by eliminating the need for external Structure-from-Motion software.

### Key Capabilities
- **Neural Pose Estimation**: AI-powered camera pose prediction from 360° views
- **Anchor+Rig Expansion**: Automatically creates 144+ camera positions from 24 strategic anchors
- **Coordinate System Management**: Handles Y-up, Z-forward coordinate system with proper conversions
- **Memory Optimization**: Chunked processing for handling millions of 3D points efficiently
- **Quality Control**: Sparse point cloud filtering to maintain manageable dataset sizes
- **Automatic Model Management**: Downloads and caches sky segmentation model on first use

### Technical Features
- **Vectorized Projection**: CUDA-accelerated point projection for 6.4M+ points across 144 cameras
- **Voxel-Based Filtering**: Smart downsampling that preserves geometric features while reducing density
- **Visual Debugging**: Color-coded axis indicators (Red=X, Green=Y, Blue=Z) for orientation verification
- **Robust Processing**: Handles complex multi-view reconstruction with automatic error recovery

### Performance Benefits
- **Reduces External Dependencies**: Eliminates RealityScan requirement (but requires VGGT installation)
- **Faster Processing**: Direct neural estimation vs. iterative Structure-from-Motion
- **Consistent Results**: Reproducible poses across different input scenarios
- **Scalable Architecture**: Handles both simple and complex 360° reconstructions

### Use Cases
- **Content Creation**: Rapid 360° video to Gaussian Splat conversion
- **Research Applications**: Consistent camera pose datasets for neural rendering experiments
- **Production Workflows**: Streamlined pipeline for VR/AR content development
- **Educational Projects**: Streamlined alignment process with VGGT neural network

## 🛠️ System Requirements

- **OS**: Windows 10 - Not tested in Windows 11
- **RAM**: 8GB minimum, 16GB+ recommended for large projects
- **Storage**: SSD recommended, 2-10GB per project depending on complexity
- **GPU**: - CUDA Toolkit 12.x (required for GPU acceleration)
-          - RTX 20/30/40 series or GTX 16 series GPU (recommended)
-          - Fallback to CPU if no compatible GPU
- **CPU**: Modern multi-core processor for video decoding

## 🔧 Troubleshooting

### GPU Acceleration Issues

When CuPy/CUDA issues occur, it's usually due to **PATH conflicts** between multiple CUDA versions:

**The Problem:**
- Multiple CUDA versions in your PATH environment variable create DLL conflicts
- CuPy (built for CUDA 12.x) finds older CUDA libraries (11.8, etc.) first
- Results in "specified module could not be found" errors

**The Solution:**
1. **Edit Environment Variables** (Windows Key → "environment variables")
2. **Clean Your PATH**: Remove ALL old CUDA paths (keep only one CUDA 12.x version)
   - Remove paths like: `C:\...\CUDA\v11.8\bin`
   - Keep only: `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin`
3. **Remove CUDA_PATH**: Delete any `CUDA_PATH` variables pointing to old versions
4. **Restart Computer** (required for PATH changes to take effect)
5. **Test**: Run `check_cupy.bat` to verify GPU acceleration

### VGGT Alignment Issues

- **VGGT Model Configuration Errors**:
  - Verify both VGGT installation path AND model path are set in Configuration tab
  - Ensure model file exists in the specified path (models/ folder)
  - Check that you've downloaded the correct model type (commercial vs non-commercial)
  - Confirm model file isn't corrupted (re-download if necessary)

- **Sky Segmentation Model Issues**:
  - Sky model (`skyseg.onnx`) downloads automatically on first use when sky filtering is enabled
  - If download fails, check internet connection and retry
  - Model downloads from Hugging Face and caches to `models/skyseg.onnx`
  - If corrupted, delete `models/skyseg.onnx` to force re-download on next run

- **Memory Issues with Large Point Clouds**: 
  - Enable sparse filtering to reduce point density
  - Set target points to 2M or lower for large scenes
  - Ensure sufficient RAM (16GB+ recommended)
  - Monitor console for "chunked processing" messages

- **Camera Orientation Problems**:
  - Enable visual debugging to see colored axis indicators
  - Verify that Y-axis (green) points up and Z-axis (blue) points forward
  - Check for coordinate system conversion issues in console output
  - Use debug GLB files to visualize camera positions

- **VGGT Processing Hanging**:
  - Reduce point cloud density with sparse filtering
  - Monitor memory usage during vectorized projection
  - Check for CUDA memory allocation errors in console
  - Try processing with smaller anchor sets for testing

### Other Common Issues

- **Frame Extraction Slow**: Ensure FFmpeg path is configured, try lower resolution
- **Live Preview Not Working**: Verify 2:1 aspect ratio, check py360convert installation  
- **Training Failures**: Check tool paths, ensure sufficient disk space
- **Console Issues**: Toggle console visibility, clear if cluttered

See **Help → Troubleshooting** in the application for comprehensive troubleshooting.

## 📚 Documentation

Complete documentation is available in the application:
- **Help → Quick Start Guide**: Basic workflow and setup
- **Help → Parameter Guide**: Detailed explanation of all settings
- **Help → Troubleshooting**: Solutions for common issues

## 🎯 Performance Tips

- **Use SSD storage** for faster I/O operations
- **Close GPU-intensive applications** during processing
- **Test with lower resolution** inputs before processing large projects
- **Use packaged installer** for easiest setup with automatic dependency management
- **Choose Full Installation** for GPU acceleration (requires CUDA 12.x)
- **Use VGGT mode** for fastest alignment without external dependencies
- **Enable sparse filtering** to prevent memory issues with large point clouds
- **Monitor console output** for real-time feedback and issue diagnosis
- **Use visual debugging sparingly** as GLB generation adds processing time
- **Start with 2M point targets** for sparse filtering, adjust based on scene complexity

## 📄 License & Credits

This software integrates multiple third-party tools and libraries. Please respect the individual licenses of:
- RealityScan (Epic Games)
- Postshot (Jawset)  
- Brush (Open Source)
- FFmpeg (LGPL/GPL)
- All Python dependencies

Provided as-is for educational and research purposes.