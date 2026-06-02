# COMPLETE PIPELINE LOGGING SYSTEM

import time
import json
import os
from datetime import datetime
from pathlib import Path

class PipelineLogger:
    """Comprehensive logging system for the 360° pipeline."""
    
    def __init__(self, project_name, project_dir):
        self.project_name = project_name
        self.project_dir = project_dir
        # DISABLED: Don't create pipeline_log.json in project directory
        self.log_file = None  # os.path.join(project_dir, f"{project_name}_pipeline_log.json")
        self.performance_log = os.path.join(project_dir, f"{project_name}_performance.txt")
        
        self.session_data = {
            'project_name': project_name,
            'start_time': datetime.now().isoformat(),
            'pipeline_version': '1.0',
            'stages': {},
            'settings': {},
            'system_info': self._get_system_info(),
            'performance_summary': {}
        }
        
        self.current_stage = None
        self.stage_start_time = None
        
        print(f"📝 Pipeline logging initialized for: {project_name}")
        print(f"📄 Logs will be saved to: {self.log_file}")
    
    def _get_system_info(self):
        """Collect system information for debugging."""
        try:
            import platform
            import psutil
            
            # Get GPU info if available
            gpu_info = "Unknown"
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_info = f"{gpus[0].name} ({gpus[0].memoryTotal}MB VRAM)"
            except:
                try:
                    # Try alternative method
                    import subprocess
                    result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        gpu_info = result.stdout.strip()
                except:
                    pass
            
            return {
                'os': platform.system(),
                'os_version': platform.version(),
                'cpu': platform.processor(),
                'cpu_cores': psutil.cpu_count(),
                'ram_gb': round(psutil.virtual_memory().total / (1024**3), 1),
                'gpu': gpu_info,
                'python_version': platform.python_version()
            }
        except Exception as e:
            return {'error': f"Could not collect system info: {e}"}
    
    def log_settings(self, settings):
        """Log pipeline settings."""
        self.session_data['settings'] = {
            'extraction_method': settings.get('extraction_method'),
            'interval_value': settings.get('interval_value'),
            'interval_unit': settings.get('interval_unit'),
            'frame_count': settings.get('frame_count'),
            'pitch_angles': settings.get('pitch_angles_str'),
            'yaw_steps': settings.get('yaw_steps'),
            'fov': settings.get('fov'),
            'postshot_profile': settings.get('postshot_profile'),
            'postshot_max_size': settings.get('postshot_max_size'),
            'postshot_steps': settings.get('postshot_steps'),
            'postshot_max_splats': settings.get('postshot_max_splats'),
            'run_postshot': settings.get('run_postshot'),
            'run_brush': settings.get('run_brush')
        }
    
    def start_stage(self, stage_name, details=""):
        """Start timing a pipeline stage."""
        self.current_stage = stage_name
        self.stage_start_time = time.time()
        
        stage_data = {
            'start_time': datetime.now().isoformat(),
            'details': details,
            'substeps': [],
            'output_lines': []
        }
        
        self.session_data['stages'][stage_name] = stage_data
        print(f"⏱️  Started: {stage_name}")
        if details:
            print(f"   Details: {details}")
    
    def log_substep(self, substep_name, duration=None, details=""):
        """Log a substep within the current stage."""
        if not self.current_stage:
            return
        
        substep_data = {
            'name': substep_name,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        
        if duration is not None:
            substep_data['duration_seconds'] = round(duration, 2)
        
        self.session_data['stages'][self.current_stage]['substeps'].append(substep_data)
        
        duration_str = f" ({duration:.1f}s)" if duration else ""
        print(f"   📌 {substep_name}{duration_str}")
        if details:
            print(f"      {details}")
    
    def log_output_line(self, line, source="pipeline"):
        """Log important output lines."""
        if not self.current_stage:
            return
        
        output_data = {
            'timestamp': datetime.now().isoformat(),
            'source': source,
            'line': line
        }
        
        self.session_data['stages'][self.current_stage]['output_lines'].append(output_data)
    
    def end_stage(self, success=True, error_message=""):
        """End timing the current stage."""
        if not self.current_stage or not self.stage_start_time:
            return
        
        duration = time.time() - self.stage_start_time
        stage_data = self.session_data['stages'][self.current_stage]
        
        stage_data.update({
            'end_time': datetime.now().isoformat(),
            'duration_seconds': round(duration, 2),
            'success': success,
            'error_message': error_message
        })
        
        status = "✅ Completed" if success else "❌ Failed"
        print(f"⏱️  {status}: {self.current_stage} ({duration:.1f}s)")
        if error_message:
            print(f"   Error: {error_message}")
        
        self.current_stage = None
        self.stage_start_time = None
    
    def finalize(self):
        """Finalize the log and save to files."""
        self.session_data['end_time'] = datetime.now().isoformat()
        
        # Calculate total duration
        start_time = datetime.fromisoformat(self.session_data['start_time'])
        end_time = datetime.fromisoformat(self.session_data['end_time'])
        total_duration = (end_time - start_time).total_seconds()
        
        self.session_data['total_duration_seconds'] = round(total_duration, 2)
        
        # Generate performance summary
        self._generate_performance_summary()
        
        # DISABLED: Don't save pipeline_log.json
        # try:
        #     with open(self.log_file, 'w') as f:
        #         json.dump(self.session_data, f, indent=2, default=str)
        #     print(f"📄 Detailed log saved: {self.log_file}")
        # except Exception as e:
        #     print(f"❌ Failed to save JSON log: {e}")
        print(f"📄 JSON logging disabled (pipeline_log.json not created)")
        
        # Save human-readable performance summary
        try:
            self._save_performance_summary()
            print(f"📊 Performance summary saved: {self.performance_log}")
        except Exception as e:
            print(f"❌ Failed to save performance summary: {e}")
    
    def _generate_performance_summary(self):
        """Generate human-readable performance summary."""
        summary = {
            'total_time': self.session_data.get('total_duration_seconds', 0),
            'stage_times': {},
            'bottlenecks': [],
            'recommendations': []
        }
        
        # Analyze stage times
        for stage_name, stage_data in self.session_data['stages'].items():
            duration = stage_data.get('duration_seconds', 0)
            summary['stage_times'][stage_name] = duration
            
            # Identify bottlenecks (stages taking >30% of total time)
            if duration > summary['total_time'] * 0.3:
                summary['bottlenecks'].append({
                    'stage': stage_name,
                    'duration': duration,
                    'percentage': round((duration / summary['total_time']) * 100, 1)
                })
        
        # Generate recommendations
        if summary['bottlenecks']:
            for bottleneck in summary['bottlenecks']:
                if 'Postshot' in bottleneck['stage']:
                    summary['recommendations'].append(
                        f"Postshot training took {bottleneck['duration']:.1f}s ({bottleneck['percentage']:.1f}%). "
                        f"Consider reducing max-image-size or train-steps-limit for faster results."
                    )
                elif 'Frame Extraction' in bottleneck['stage']:
                    summary['recommendations'].append(
                        f"Frame extraction took {bottleneck['duration']:.1f}s. "
                        f"Consider using fewer frames or lower resolution."
                    )
        
        self.session_data['performance_summary'] = summary
    
    def _save_performance_summary(self):
        """Save human-readable performance summary."""
        with open(self.performance_log, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write(f"360° SPLATPIPE PERFORMANCE REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Project: {self.project_name}\n")
            f.write(f"Date: {self.session_data['start_time'][:19]}\n")
            f.write(f"Total Time: {self.session_data['total_duration_seconds']:.1f} seconds\n")
            f.write("\n")
            
            # System Information
            f.write("SYSTEM INFORMATION:\n")
            f.write("-" * 30 + "\n")
            system_info = self.session_data.get('system_info', {})
            for key, value in system_info.items():
                f.write(f"{key.upper()}: {value}\n")
            f.write("\n")
            
            # Settings Used
            f.write("SETTINGS USED:\n")
            f.write("-" * 30 + "\n")
            settings = self.session_data.get('settings', {})
            for key, value in settings.items():
                f.write(f"{key}: {value}\n")
            f.write("\n")
            
            # Stage Performance
            f.write("STAGE PERFORMANCE:\n")
            f.write("-" * 30 + "\n")
            total_time = self.session_data.get('total_duration_seconds', 1)
            
            for stage_name, stage_data in self.session_data['stages'].items():
                duration = stage_data.get('duration_seconds', 0)
                percentage = (duration / total_time) * 100
                status = "✅" if stage_data.get('success', True) else "❌"
                
                f.write(f"{status} {stage_name}:\n")
                f.write(f"   Duration: {duration:.1f}s ({percentage:.1f}% of total)\n")
                
                if stage_data.get('error_message'):
                    f.write(f"   Error: {stage_data['error_message']}\n")
                
                # Show substeps if any
                substeps = stage_data.get('substeps', [])
                if substeps:
                    f.write(f"   Substeps:\n")
                    for substep in substeps:
                        substep_duration = substep.get('duration_seconds', 0)
                        f.write(f"     • {substep['name']}: {substep_duration:.1f}s\n")
                
                f.write("\n")
            
            # Performance Summary
            summary = self.session_data.get('performance_summary', {})
            if summary.get('bottlenecks'):
                f.write("PERFORMANCE BOTTLENECKS:\n")
                f.write("-" * 30 + "\n")
                for bottleneck in summary['bottlenecks']:
                    f.write(f"⚠️  {bottleneck['stage']}: {bottleneck['duration']:.1f}s ({bottleneck['percentage']:.1f}%)\n")
                f.write("\n")
            
            if summary.get('recommendations'):
                f.write("RECOMMENDATIONS:\n")
                f.write("-" * 30 + "\n")
                for i, rec in enumerate(summary['recommendations'], 1):
                    f.write(f"{i}. {rec}\n")
                f.write("\n")
            
            f.write("=" * 60 + "\n")