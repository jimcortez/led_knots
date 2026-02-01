"""
Configuration management for LED knots.

Reads configuration from config.yaml and optionally overrides with config.local.yaml.
Provides an object-oriented interface to configuration values.
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from .utils import parse_args

logger = logging.getLogger(__name__)


class OutputBounds:
    """Output bounds configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.width = float(data.get('width', 100.0))
        self.length = float(data.get('length', 100.0))
        self.height = float(data.get('height', 100.0))


class LedStripSettings:
    """LED strip settings configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.width = float(data.get('width', 10.0))
        self.height = float(data.get('height', 1.8))
        self.led_count = int(data.get('led_count', 300))
        # Note: min_90_degtree_twist distance is not yet implemented


class TubeSettings:
    """Tube settings configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.auto_diameter = bool(data.get('auto_diameter', False))
        # outer_diameter may be None if auto_diameter is True
        outer_diameter_value = data.get('outer_diameter')
        if outer_diameter_value is not None:
            self.outer_diameter = float(outer_diameter_value)
        else:
            self.outer_diameter = None
        self.wall_thickness = float(data.get('wall_thickness', 1.0))
        self.oval_wall_thickness = float(data.get('oval_wall_thickness', 2.0))
        self.connector_width = float(data.get('connector_width', 1.0))
        self.double_sided_led = bool(data.get('double_sided_led', True))
        self.led_tolerance_width = float(data.get('led_tolerance_width', 1.0))
        self.led_tolerance_height = float(data.get('led_tolerance_height', 1.0))
        
        # Diffusion ridges configuration
        diffusion_ridges_data = data.get('diffusion_ridges')
        if diffusion_ridges_data is False or diffusion_ridges_data is None:
            self.diffusion_ridges = None
        elif isinstance(diffusion_ridges_data, dict):
            self.diffusion_ridges = {
                'ridge_height': float(diffusion_ridges_data.get('ridge_height', 0.5)),
                'ridge_width': float(diffusion_ridges_data.get('ridge_width', 1.0)),
                'ridge_spacing': float(diffusion_ridges_data.get('ridge_spacing', 0.0)),
            }
        else:
            # If it's True or some other truthy value, use defaults
            self.diffusion_ridges = {
                'ridge_height': 0.5,
                'ridge_width': 1.0,
                'ridge_spacing': 0.0,
            }
        
        self._led_strip_settings: Optional['LedStripSettings'] = None
    
    def set_led_strip_settings(self, led_strip_settings: 'LedStripSettings'):
        """Set the LED strip settings reference and calculate diameter if auto_diameter is enabled."""
        self._led_strip_settings = led_strip_settings
        
        # Calculate outer_diameter automatically if auto_diameter is True
        if self.auto_diameter:
            if led_strip_settings is None or led_strip_settings.led_count <= 0:
                raise ValueError("auto_diameter requires led_strip_settings with valid led_count")
            
            # Distance between LEDs in mm: 1000mm (1 meter) / led_count
            distance_between_leds = 1000.0 / led_strip_settings.led_count
            
            # Inner radius = distance between LEDs
            inner_radius = distance_between_leds
            
            # Inner diameter = 2 * inner_radius
            inner_diameter = 2.0 * inner_radius
            
            # Outer diameter = inner_diameter + 2 * wall_thickness
            self.outer_diameter = inner_diameter + 2.0 * self.wall_thickness
        else:
            # Validate that outer_diameter is set when auto_diameter is False
            if self.outer_diameter is None:
                raise ValueError("outer_diameter must be set when auto_diameter is False")
    
    @property
    def outer_radius(self) -> float:
        """Calculate outer radius from outer diameter."""
        if self.outer_diameter is None:
            raise ValueError("outer_diameter is not set. Ensure set_led_strip_settings() is called if using auto_diameter.")
        return self.outer_diameter / 2.0
    
    def to_led_circle_face_kwargs(self, **kwargs) -> Dict[str, Any]:
        """
        Return a dictionary of parameters suitable for create_led_circle_face.
        
        This includes all tube_settings parameters that are used by create_led_circle_face.
        The inner rectangle dimensions (rect_inner_x, rect_inner_y) are automatically calculated
        from LED strip settings if available.
        
        Can be used with **kwargs unpacking: 
            create_led_circle_face(**config.tube_settings.to_led_circle_face_kwargs())
        
        Or with overrides:
            create_led_circle_face(**config.tube_settings.to_led_circle_face_kwargs(orient_to_path=path, rotation_z=90))
        
        Args:
            **kwargs: Additional parameters to merge with the default values. 
                     These will override any default values with the same key.
        
        Returns:
            Dict with keys: outer_radius, wall_thickness, oval_wall_thickness, connector_width,
            diffusion_ridges (if enabled), rect_inner_x, rect_inner_y (if led_strip_settings available),
            plus any additional keys provided in kwargs.
        """
        base_kwargs = {
            'outer_radius': self.outer_radius,
            'wall_thickness': self.wall_thickness,
            'min_oval_wall_thickness': self.oval_wall_thickness,  # Use oval_wall_thickness as minimum to respect desired thickness
            'oval_wall_thickness': self.oval_wall_thickness,
            'connector_width': self.connector_width,
        }
        
        # Add diffusion_ridges if configured
        if self.diffusion_ridges is not None:
            base_kwargs['diffusion_ridges'] = self.diffusion_ridges
        
        # Calculate inner rectangle dimensions from LED strip settings if available
        if self._led_strip_settings is not None:
            # Width: use LED strip width + tolerance
            rect_inner_y = self._led_strip_settings.width + self.led_tolerance_width
            
            # Height: use LED strip height + tolerance, double if double_sided_led is true
            rect_inner_x = self._led_strip_settings.height + self.led_tolerance_height
            if self.double_sided_led:
                rect_inner_x *= 2.0
            
            base_kwargs['rect_inner_x'] = rect_inner_x
            base_kwargs['rect_inner_y'] = rect_inner_y
        
        # Merge additional kwargs, allowing them to override defaults
        base_kwargs.update(kwargs)
        return base_kwargs


class ServerSettings:
    """Server and yacv-related configuration. Optional keys map to YACV_* env vars."""

    # Attribute name -> YACV env var name
    _ENV_MAP = {
        'protocol': 'YACV_PROTOCOL',
        'texture': 'YACV_TEXTURE',
        'color_faces': 'YACV_COLOR_FACES',
        'color_edges': 'YACV_COLOR_EDGES',
        'color_vertices': 'YACV_COLOR_VERTICES',
        'graceful_secs_connect': 'YACV_GRACEFUL_SECS_CONNECT',
        'graceful_secs_work': 'YACV_GRACEFUL_SECS_WORK',
        'host': 'YACV_HOST',
        'port': 'YACV_PORT',
        'disable_server': 'YACV_DISABLE_SERVER',
    }

    def __init__(self, data: Dict[str, Any], project_root: Path):
        self.object_cache = str(data.get('object_cache', 'cache/glb_blobs'))
        self.cache_dir = project_root / self.object_cache
        # Optional yacv env overrides (snake_case in YAML)
        self.protocol = data.get('protocol')
        self.texture = data.get('texture')
        self.color_faces = data.get('color_faces')
        self.color_edges = data.get('color_edges')
        self.color_vertices = data.get('color_vertices')
        self.graceful_secs_connect = data.get('graceful_secs_connect')
        self.graceful_secs_work = data.get('graceful_secs_work')
        self.host = data.get('host')
        self.port = data.get('port')
        _disable = data.get('disable_server')
        self.disable_server = str(_disable).lower() in ('true', '1', 'yes') if _disable is not None else None

    def apply_to_env(self) -> None:
        """Set YACV_* environment variables for any non-None attributes."""
        for attr, env_name in self._ENV_MAP.items():
            val = getattr(self, attr, None)
            if val is not None:
                os.environ[env_name] = str(val)


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
        self.led_strip_settings = LedStripSettings(config_data.get('led_strip_settings', {}))
        
        # Link LED strip settings to tube settings so it can be used automatically
        self.tube_settings.set_led_strip_settings(self.led_strip_settings)
        
        # Parse command line arguments
        args = parse_args(description=description or "Create and render a knot model")
        
        # Server settings (cache dir, optional yacv env)
        server_data = config_data.get('server', {})
        self.server_settings = ServerSettings(server_data, project_root)
        self.server_settings.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Cache directory: %s", self.server_settings.cache_dir)
        
        # Initialize export settings with command line filepath
        self.export = ExportSettings(config_data.get('export', {}), filepath=args.export)
        
        # Store other command line arguments as properties
        self.server = args.server
        self.no_cache = args.no_cache
        self.only_cache = args.only_cache
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


def get_config(
    description: Optional[str] = None,
    name: Optional[str] = None,
    set_env_vars: bool = True,
) -> Config:
    """
    Get the global configuration instance.
    
    Args:
        description: Optional description for the argument parser. 
                     If provided, will be used when parsing command line arguments.
        name: Optional name of the part (used for export/display).
        set_env_vars: If True (default), set YACV_* environment variables from
                      server config so yacv_server sees them when later imported.
    
    Returns:
        Config: The global configuration instance with parsed command line arguments.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(description=description, name=name)
    if set_env_vars:
        _config_instance.server_settings.apply_to_env()
    return _config_instance
