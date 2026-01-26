"""
Configuration management for LED knots.

Reads configuration from config.yaml and optionally overrides with config.local.yaml.
Provides an object-oriented interface to configuration values.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from .utils import parse_args


class OutputBounds:
    """Output bounds configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.width = float(data.get('width', 100.0))
        self.length = float(data.get('length', 100.0))
        self.height = float(data.get('height', 100.0))


class TubeSettings:
    """Tube settings configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.outer_diameter = float(data.get('outer_diameter', 30.0))
        self.wall_thickness = float(data.get('wall_thickness', 1.0))
        self.oval_wall_thickness = float(data.get('oval_wall_thickness', 2.0))
        self.connector_width = float(data.get('connector_width', 1.0))
        self.double_sided_led = bool(data.get('double_sided_led', True))
        self.led_tolerance_width = float(data.get('led_tolerance_width', 1.0))
        self.led_tolerance_height = float(data.get('led_tolerance_height', 1.0))
    
    @property
    def outer_radius(self) -> float:
        """Calculate outer radius from outer diameter."""
        return self.outer_diameter / 2.0
    
    def to_led_circle_face_kwargs(self, **kwargs) -> Dict[str, Any]:
        """
        Return a dictionary of parameters suitable for create_led_circle_face.
        
        This includes all tube_settings parameters that are used by create_led_circle_face.
        Additional named parameters can be provided to override or extend the default values.
        
        Can be used with **kwargs unpacking: 
            create_led_circle_face(**config.tube_settings.to_led_circle_face_kwargs())
        
        Or with overrides:
            create_led_circle_face(**config.tube_settings.to_led_circle_face_kwargs(orient_to_path=path, rotation_z=90))
        
        Args:
            **kwargs: Additional parameters to merge with the default values. 
                     These will override any default values with the same key.
        
        Returns:
            Dict with keys: outer_radius, wall_thickness, oval_wall_thickness, connector_width,
            plus any additional keys provided in kwargs.
        """
        base_kwargs = {
            'outer_radius': self.outer_radius,
            'wall_thickness': self.wall_thickness,
            'oval_wall_thickness': self.oval_wall_thickness,
            'connector_width': self.connector_width,
        }
        # Merge additional kwargs, allowing them to override defaults
        base_kwargs.update(kwargs)
        return base_kwargs


class ExportSettings:
    """Export settings configuration."""
    
    def __init__(self, data: Dict[str, Any], filepath: Optional[str] = None):
        self.filepath = filepath  # From command line argument
        self.tolerance = float(data.get('tolerance', 0.00005))
        self.angular_tolerance = float(data.get('angular_tolerance', 0.05))


class Config:
    """Main configuration object."""
    
    def __init__(self, description: Optional[str] = None, name: Optional[str] = None):
        # Find the project root (where config.yaml is located)
        # This file is in src/led_knots/core/, so we go up 3 levels
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        
        config_path = project_root / 'config.yaml'
        local_config_path = project_root / 'config.local.yaml'
        
        # Load base configuration
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
        
        # Load local overrides if they exist
        if local_config_path.exists():
            with open(local_config_path, 'r') as f:
                local_data = yaml.safe_load(f) or {}
                # Merge local overrides into base config
                config_data = self._merge_dicts(config_data, local_data)
        
        # Initialize configuration sections
        self.output_bounds = OutputBounds(config_data.get('output_bounds', {}))
        self.tube_settings = TubeSettings(config_data.get('tube_settings', {}))
        
        # Parse command line arguments
        args = parse_args(description=description or "Create and render a knot model")
        
        # Initialize export settings with command line filepath
        self.export = ExportSettings(config_data.get('export', {}), filepath=args.export)
        
        # Store other command line arguments as properties
        self.server = args.server
        self.name = name  # Name of the part (used for export/display)
    
    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge override dict into base dict."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result


# Global configuration instance
_config_instance: Config = None


def get_config(description: Optional[str] = None, name: Optional[str] = None) -> Config:
    """
    Get the global configuration instance.
    
    Args:
        description: Optional description for the argument parser. 
                     If provided, will be used when parsing command line arguments.
        name: Optional name of the part (used for export/display).
    
    Returns:
        Config: The global configuration instance with parsed command line arguments.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(description=description, name=name)
    return _config_instance
