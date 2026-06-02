# settings_manager.py

import configparser

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / '360_SplatPipe_config.ini'

def load_settings(config_file=CONFIG_FILE):
    """Enhanced to load new extraction and appearance settings."""
    config = configparser.ConfigParser()
    config.read(config_file)
    
    # ENHANCED: Safe config file reading with fallback
    try:
        config.read(config_file)
        print(f"✅ Loaded settings from: {config_file}")
    except Exception as e:
        print(f"⚠️ Error reading config file {config_file}: {e}")
        print("   Using default settings")
        # Continue with empty config (all fallbacks will be used)
    
    settings = {}
    
    # Video Frame Extraction Settings (Enhanced)
    settings['extraction_method'] = config.get('Extraction', 'extraction_method', fallback='interval')
    settings['interval_value'] = config.getfloat('Extraction', 'interval_value', fallback=1.0)
    settings['interval_unit'] = config.get('Extraction', 'interval_unit', fallback="seconds")
    settings['frame_count'] = config.getint('Extraction', 'frame_count', fallback=30)
    settings['frame_format'] = config.get('Extraction', 'frame_format', fallback='jpg')
    
    # Cache Settings (for the new caching system)
    settings['cache_max_size'] = config.getint('Cache', 'max_size', fallback=60)
    settings['preview_cache_enabled'] = config.getboolean('Cache', 'preview_enabled', fallback=True)

    # Project Directory (critical for per-video settings)
    settings['project_dir'] = config.get('Paths', 'project_dir', fallback='')
    
    # 360 View Extraction Settings
    settings['pitch_angles_str'] = config.get('Extraction', 'pitch_angles_str', fallback="-50, -7")
    settings['yaw_steps'] = config.get('Extraction', 'yaw_steps', fallback='6')
    settings['fov'] = config.get('Extraction', 'fov', fallback='94.6')

    # Overlay Appearance Settings
    settings['overlay_opacity'] = config.getfloat('Appearance', 'overlay_opacity', fallback=0.2)
    
    # Window Position Settings
    settings['window_x'] = config.getint('Window', 'x', fallback=100)
    settings['window_y'] = config.getint('Window', 'y', fallback=100)
    settings['window_width'] = config.getint('Window', 'width', fallback=1520)
    settings['window_height'] = config.getint('Window', 'height', fallback=1150)

    # Alignment settings
    settings['run_postshot'] = config.getboolean('Alignment', 'run_postshot', fallback=True)
    settings['run_brush'] = config.getboolean('Alignment', 'run_brush', fallback=False)
    settings['run_vggt'] = config.getboolean('Alignment', 'run_vggt', fallback=False)
    settings['export_xmp'] = config.getboolean('Alignment', 'export_xmp', fallback=False)
    settings['skip_realityscan'] = config.getboolean('Alignment', 'skip_realityscan', fallback=False)

    
    # VGGT filter settings
    settings['vggt_conf_threshold'] = config.getfloat('Alignment', 'vggt_conf_threshold', fallback=50.0)
    settings['vggt_mask_sky'] = config.getboolean('Alignment', 'vggt_mask_sky', fallback=True)
    settings['vggt_mask_black_bg'] = config.getboolean('Alignment', 'vggt_mask_black_bg', fallback=False)
    settings['vggt_mask_white_bg'] = config.getboolean('Alignment', 'vggt_mask_white_bg', fallback=False)
    settings['vggt_prediction_mode'] = config.get('Alignment', 'vggt_prediction_mode', fallback='Depthmap and Camera Branch')
    settings['vggt_temporal_sequencing'] = config.getboolean('Alignment', 'vggt_temporal_sequencing', fallback=True)
    settings['sky_sensitivity_threshold'] = config.getfloat('Alignment', 'sky_sensitivity_threshold', fallback=32)
    
    # VGGT sparse point cloud filter settings
    settings['vggt_enable_sparse'] = config.getboolean('Alignment', 'vggt_enable_sparse', fallback=False)
    settings['vggt_sparse_target'] = config.getint('Alignment', 'vggt_sparse_target', fallback=150000)
    
    # VGGT anchor+rig mode settings (experimental)
    settings['vggt_use_anchor_rig'] = config.getboolean('Alignment', 'vggt_use_anchor_rig', fallback=False)
    settings['vggt_anchor_view'] = config.get('Alignment', 'vggt_anchor_view', fallback='y00')
    settings['vggt_rig_optimization_min_points'] = config.getint('Alignment', 'vggt_rig_optimization_min_points', fallback=500000)
    
    # VGGT visualization settings
    settings['vggt_show_camera'] = config.getboolean('Alignment', 'vggt_show_camera', fallback=True)

    # Postshot Settings (unchanged)
    settings['postshot_profile'] = config.get('Postshot', 'profile', fallback='Splat3')
    settings['postshot_max_size'] = config.getint('Postshot', 'max_image_size', fallback=3840)
    settings['postshot_steps'] = config.getint('Postshot', 'train_steps', fallback=30)
    settings['postshot_max_splats'] = config.getint('Postshot', 'max_splats', fallback=3000)
    settings['postshot_aa'] = config.getboolean('Postshot', 'anti_aliasing', fallback=True)
    settings['postshot_error'] = config.getboolean('Postshot', 'show_train_error', fallback=True)
    settings['postshot_context'] = config.getboolean('Postshot', 'store_context', fallback=True)
    settings['postshot_export_ply'] = config.getboolean('Postshot', 'export_ply', fallback=True)
    settings['postshot_alpha_mask'] = config.getboolean('Postshot', 'alpha_mask', fallback=False)
    settings['postshot_sky_model'] = config.getboolean('Postshot', 'sky_model', fallback=False)

    # Brush Settings (unchanged)
    settings['brush_total_steps'] = config.getint('Brush', 'total_steps', fallback=30000)
    settings['brush_max_splats'] = config.getint('Brush', 'max_splats', fallback=3000)
    settings['brush_max_resolution'] = config.getint('Brush', 'max_resolution', fallback=1920)
    settings['brush_seed'] = config.getint('Brush', 'seed', fallback=42)
    settings['brush_rerun'] = config.getboolean('Brush', 'rerun_logging', fallback=False)
    settings['brush_viewer'] = config.getboolean('Brush', 'spawn_viewer', fallback=False)
    # Brush Export Settings (referenced in GUI but not saved)
    settings['brush_export_every'] = config.getint('Brush', 'export_every', fallback=5000)
    settings['brush_export_name'] = config.get('Brush', 'export_name', fallback='{project}_brush_{iter}.ply')
    
    # Paths (unchanged)
    settings['ffmpeg_path'] = config.get('Paths', 'ffmpeg_path', fallback='C:/Users/USER/SOMEWHERE/360_GS Pipe/FFmpeg_RS_settings/ffmpeg.exe')
    settings['rs_path'] = config.get('Paths', 'rs_path', fallback='C:/Program Files/Epic Games/RealityScan_2.0/RealityScan.exe')
    settings['postshot_path'] = config.get('Paths', 'postshot_path', fallback='C:/Program Files/Jawset Postshot/bin/postshot-cli.exe')
    settings['brush_path'] = config.get('Paths', 'brush_path', fallback='C:/Users/USER/SOMEWHERE/brush_app.exe')
    settings['rs_settings_path'] = config.get('Paths', 'rs_settings_path', fallback='C:/Users/USER/SOMEWHERE/360_GS Pipe/FFmpeg_RS_settings')
    settings['vggt_path'] = config.get('Paths', 'vggt_path', fallback='C:/Users/USER/SOMEWHERE/vggt')
    
    return settings

def save_settings(settings_data, config_file=CONFIG_FILE):
    """Enhanced to save new extraction and appearance settings."""
    config = configparser.ConfigParser()
    
    config['Extraction'] = {
        'extraction_method': settings_data.get('extraction_method', 'interval'),
        'interval_value': settings_data.get('interval_value', 1.0),
        'interval_unit': settings_data.get('interval_unit', 'seconds'),
        'frame_count': settings_data.get('frame_count', 30),
        'frame_format': settings_data.get('frame_format', 'jpg'),
        'pitch_angles_str': settings_data.get('pitch_angles_str', '-50, -7'),
        'yaw_steps': settings_data.get('yaw_steps', '6'),
        'fov': settings_data.get('fov', '94.6')
    }
    
    config['Cache'] = {
        'max_size': settings_data.get('cache_max_size', 60),
        'preview_enabled': settings_data.get('preview_cache_enabled', True)
    }
    
    config['Paths'] = {
        'project_dir': settings_data.get('project_dir', '')
    }


    config['Appearance'] = {
        'overlay_opacity': settings_data.get('overlay_opacity', 0.2),
    }
    
    config['Window'] = {
        'x': settings_data.get('window_x', 100),
        'y': settings_data.get('window_y', 100),
        'width': settings_data.get('window_width', 1520),
        'height': settings_data.get('window_height', 1150)
    }

    config['Alignment'] = {
        'run_postshot': settings_data.get('run_postshot', True),
        'run_brush': settings_data.get('run_brush', False),
        'run_vggt': settings_data.get('run_vggt', False),
        'export_xmp': settings_data.get('export_xmp', False),
        'skip_realityscan': settings_data.get('skip_realityscan', False),
        'vggt_conf_threshold': settings_data.get('vggt_conf_threshold', 50.0),
        'vggt_mask_sky': settings_data.get('vggt_mask_sky', True),
        'vggt_mask_black_bg': settings_data.get('vggt_mask_black_bg', False),
        'vggt_mask_white_bg': settings_data.get('vggt_mask_white_bg', False),
        'vggt_prediction_mode': settings_data.get('vggt_prediction_mode', 'Depthmap and Camera Branch'),
        'vggt_temporal_sequencing': settings_data.get('vggt_temporal_sequencing', True),
        'vggt_enable_sparse': settings_data.get('vggt_enable_sparse', False),
        'vggt_sparse_target': settings_data.get('vggt_sparse_target', 150000),
        'vggt_use_anchor_rig': settings_data.get('vggt_use_anchor_rig', False),
        'vggt_anchor_view': settings_data.get('vggt_anchor_view', 'y00'),
        'vggt_rig_optimization_min_points': settings_data.get('vggt_rig_optimization_min_points', 500000),
        'vggt_show_camera': settings_data.get('vggt_show_camera', True),
        'sky_sensitivity_threshold': settings_data.get('sky_sensitivity_threshold', 32)
    }   
    
    config['Postshot'] = {
        'profile': settings_data.get('postshot_profile', 'Splat3'),
        'max_image_size': settings_data.get('postshot_max_size', 3840),
        'train_steps': settings_data.get('postshot_steps', 30),
        'max_splats': settings_data.get('postshot_max_splats', 3000),
        'anti_aliasing': settings_data.get('postshot_aa', True),
        'show_train_error': settings_data.get('postshot_error', True),
        'store_context': settings_data.get('postshot_context', True),
        'export_ply': settings_data.get('postshot_export_ply', True),
        'alpha_mask': settings_data.get('postshot_alpha_mask', False),
        'sky_model': settings_data.get('postshot_sky_model', False)
    }

    config['Brush'] = {
        'total_steps': settings_data.get('brush_total_steps', 30000),
        'max_splats': settings_data.get('brush_max_splats', 3000),
        'max_resolution': settings_data.get('brush_max_resolution', 1920),
        'seed': settings_data.get('brush_seed', 42),
        'rerun_logging': settings_data.get('brush_rerun', False),
        'spawn_viewer': settings_data.get('brush_viewer', False),
        'export_every': settings_data.get('brush_export_every', 5000),
        'export_name': settings_data.get('brush_export_name', '{project}_brush_{iter}.ply')
    }

    config['Paths'] = {
        'ffmpeg_path': settings_data.get('ffmpeg_path', 'C:/Users/USER/SOMEWHERE/360_GS Pipe/FFmpeg_RS_settings/ffmpeg.exe'),
        'rs_path': settings_data.get('rs_path', 'C:/Program Files/Epic Games/RealityScan_2.0/RealityScan.exe'),
        'postshot_path': settings_data.get('postshot_path', 'C:/Program Files/Jawset Postshot/bin/postshot-cli.exe'),
        'brush_path': settings_data.get('brush_path', 'C:/Users/USER/SOMEWHERE/brush_app.exe'),
        'rs_settings_path': settings_data.get('rs_settings_path', 'C:/Users/USER/SOMEWHERE/360_GS Pipe/FFmpeg_RS_settings'),
        'vggt_path': settings_data.get('vggt_path', 'C:/Users/USER/SOMEWHERE/vggt')
    }

    try:
        with open(config_file, 'w') as configfile:
            config.write(configfile)
        print(f"✅ Settings saved successfully to {config_file}")
        
        # ENHANCED: Verify ALL settings sections were saved
        verify_config = configparser.ConfigParser()
        verify_config.read(config_file)
        
        expected_sections = ['Extraction', 'Appearance', 'Alignment', 'Postshot', 'Brush', 'Paths']
        all_sections_ok = True
        
        print(f"🔍 Verifying all settings sections in saved file:")
        
        for section_name in expected_sections:
            if verify_config.has_section(section_name):
                section_items = dict(verify_config[section_name])
                print(f"✅ [{section_name}] - {len(section_items)} settings")
                
                # Show first few items in each section for verification
                for i, (key, value) in enumerate(section_items.items()):
                    if i < 3:  # Show first 3 items
                        print(f"   {key} = {value}")
                    elif i == 3:
                        print(f"   ... and {len(section_items) - 3} more settings")
                        break
            else:
                print(f"❌ [{section_name}] - MISSING!")
                all_sections_ok = False
        
        # Overall verification result
        if all_sections_ok:
            print(f"✅ ALL SETTINGS SECTIONS VERIFIED SUCCESSFULLY!")
        else:
            print(f"❌ WARNING: Some settings sections are missing!")
        
        # Optional: Show total settings count
        total_settings = sum(len(verify_config[section]) for section in verify_config.sections())
        print(f"📊 Total settings saved: {total_settings} across {len(verify_config.sections())} sections")
            
    except Exception as e:
        print(f"❌ Error saving settings: {e}")
        raise