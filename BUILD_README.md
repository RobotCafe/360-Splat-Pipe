# 360° SplatPipe - Build Instructions

## Quick Build

1. **Run the build script:**
   ```
   build_app.bat
   ```

2. **Test the built app:**
   ```
   dist\SplatPipe\SplatPipe.exe
   ```

## What the Build Includes

### ✅ **Lightweight Core (~150-250MB)**
- Python runtime and core dependencies only
- FFmpeg binaries (for video processing)
- Theme assets and GUI resources  
- Dependency installer scripts
- Empty models folder structure

### ⬇️ **Downloaded on First Run**
Heavy dependencies installed via setup wizard:
- OpenCV (image/video processing)
- SciPy, Matplotlib (scientific computing)  
- CuPy (GPU acceleration, requires CUDA)
- PyColmap, Trimesh (VGGT dependencies)
- ONNXRuntime (AI model runtime)

## First Run Experience

1. User runs `SplatPipe.exe`
2. **Setup Wizard** appears if dependencies missing
3. User chooses installation type:
   - **Full Installation** (GPU + all features)
   - **Quick Start** (CPU mode, lightweight)
   - **Skip** (use existing dependencies)
4. Dependencies download and install automatically
5. App restarts with full functionality

## Distribution

### **Option 1: Simple Folder**
- Zip the entire `dist\SplatPipe\` folder
- Users extract and run `SplatPipe.exe`

### **Option 2: Installer (Recommended)**
Create a proper installer using NSIS or similar:
- Include entire `dist\SplatPipe\` folder
- Create Start Menu shortcuts
- Add to Add/Remove Programs
- Handle uninstallation properly

## File Structure After Build

```
dist/SplatPipe/
├── SplatPipe.exe              # Main executable
├── _internal/                 # PyInstaller internals
├── App/                       # Python source modules
├── FFmpeg and RS Settings/    # Video processing tools
├── models/                    # Empty, ready for user models
├── install_requirements.bat   # Dependency installer
├── requirements.txt           # Full dependency list
├── requirements-core.txt      # Core dependencies
└── README.md                  # User documentation
```

## Log Files Location

- **Development**: `project_root/logs/`
- **Packaged App**: `%APPDATA%\SplatPipe\logs\`
  - Example: `C:\Users\Username\AppData\Roaming\SplatPipe\logs\`

## Troubleshooting Build Issues

### **Import Errors**
- Check `hiddenimports` in `SplatPipe.spec`
- Add missing modules to hidden imports list

### **Missing Files**
- Add to `datas` list in `SplatPipe.spec`  
- Use format: `('source/path', 'dest/path')`

### **Large Build Size**
- Check `excludes` list in spec file
- Ensure heavy dependencies are excluded
- Review what's being bundled in `datas`

### **Runtime Errors**
- Test with `console=True` in spec for debugging
- Check paths are correct for packaged environment
- Verify `sys.frozen` detection works

## Testing Checklist

- [ ] App starts without errors
- [ ] First-run wizard appears correctly  
- [ ] Dependency installation works
- [ ] Core functionality works in CPU mode
- [ ] GPU acceleration works (if CUDA available)
- [ ] Log files save to correct location
- [ ] Help menu functions work
- [ ] External tool integration works
- [ ] App survives restart after dependency install

## Performance

**Expected sizes:**
- Built app folder: ~150-250MB
- With full dependencies: ~800MB-1.2GB
- First download for users: Fast (~150MB)
- Heavy deps download: 500-800MB (one-time)