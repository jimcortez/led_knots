"""
Configuration management for LED knots.

Reads configuration from config.yaml, optionally overrides with config.local.yaml,
and supports a --config CLI overlay merged on top of both.
Provides an object-oriented interface to configuration values.
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from .utils import parse_args
from led_knots.optimize.settings import PrintOptimizationSettings

logger = logging.getLogger(__name__)


def _resolve_config_path(project_root: Path, path_str: str) -> Path:
    """Resolve a --config path: absolute as-is, relative against project root."""
    p = Path(path_str)
    return p if p.is_absolute() else project_root / p


# Face types allowed for top-level face_type and in face_settings keys.
VALID_FACE_TYPES = (
    'led_circle',
    'led_circle_tube',
    'solid_circle',
    'square',
    'pyramid_studded',
    'braided_rope',
)


def _deep_merge_face_settings(base: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge current over base. Nested dicts (e.g. pyramid_studded, braided_rope)
    are merged by key; keys in current override base. 'inherit_from' is not
    copied into the result.
    """
    result = dict(base)
    for key, value in current.items():
        if key == 'inherit_from':
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_face_settings(result[key], value)
        else:
            result[key] = value
    return result


def resolve_face_settings(face_settings_dict: Dict[str, Any], face_type: str, _stack: Optional[set] = None) -> Dict[str, Any]:
    """
    Resolve face settings for the given face type, applying inherit_from and deep merge.
    Returns a single dict with no inherit_from key. Detects cycles and missing parents.
    """
    if face_settings_dict is None or not face_settings_dict:
        return {}
    if _stack is None:
        _stack = set()
    if face_type in _stack:
        raise ValueError(f"face_settings inheritance cycle: {' -> '.join(_stack)} -> {face_type}")
    block = face_settings_dict.get(face_type)
    if block is None:
        return {}
    block = dict(block)  # don't mutate config
    inherit_from = block.pop('inherit_from', None)
    if inherit_from is None:
        return block
    parent = str(inherit_from).strip()
    if parent not in face_settings_dict:
        raise ValueError(f"face_settings: {face_type!r} has inherit_from: {parent!r} but that face type is not defined")
    _stack.add(face_type)
    try:
        base = resolve_face_settings(face_settings_dict, parent, _stack)
    finally:
        _stack.discard(face_type)
    return _deep_merge_face_settings(base, block)


class OutputBounds:
    """Output bounds configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.width = float(data.get('width', 100.0))
        self.length = float(data.get('length', 100.0))
        self.height = float(data.get('height', 100.0))


class PrintJointSettings:
    """Registration geometry settings for cut boundaries between printed segments."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", False))
        self.style: str = str(data.get("style", "twin_pin")).strip().lower()
        self.clearance_mm: float = float(data.get("clearance_mm", 0.2))
        self.close_loop: bool = bool(data.get("close_loop", False))

        # twin_pin defaults
        self.pin_diameter_mm: float = float(data.get("pin_diameter_mm", 3.0))
        self.pin_depth_mm: float = float(data.get("pin_depth_mm", 4.0))
        self.pin_radial_offset_mm: float = float(data.get("pin_radial_offset_mm", 17.0))
        self.pin_spacing_mm: float = float(data.get("pin_spacing_mm", 7.0))

        # Axial lap overlap at internal segment cuts (mm along path tangent).
        self.lap_overlap_mm: float = float(data.get("lap_overlap_mm", 4.0))
        self.lap_step_height_mm: float = float(data.get("lap_step_height_mm", 3.0))

        # dovetail defaults
        self.neck_width_mm: float = float(data.get("neck_width_mm", 3.0))
        self.base_width_mm: float = float(data.get("base_width_mm", 5.0))
        self.depth_mm: float = float(data.get("depth_mm", 4.0))
        self.flank_angle_deg: float = float(data.get("flank_angle_deg", 12.0))

        if self.style not in ("twin_pin", "dovetail"):
            raise ValueError(f"max_print_bounds.joint.style must be 'twin_pin' or 'dovetail' (got {self.style!r})")
        if self.clearance_mm < 0:
            raise ValueError("max_print_bounds.joint.clearance_mm must be >= 0")
        if self.lap_overlap_mm < 0:
            raise ValueError("max_print_bounds.joint.lap_overlap_mm must be >= 0")
        if self.lap_step_height_mm <= 0:
            raise ValueError("max_print_bounds.joint.lap_step_height_mm must be > 0")

        positive_fields = (
            "pin_diameter_mm",
            "pin_depth_mm",
            "pin_radial_offset_mm",
            "pin_spacing_mm",
            "neck_width_mm",
            "base_width_mm",
            "depth_mm",
            "flank_angle_deg",
        )
        for key in positive_fields:
            if getattr(self, key) <= 0:
                raise ValueError(f"max_print_bounds.joint.{key} must be > 0")
        if self.base_width_mm <= self.neck_width_mm:
            raise ValueError("max_print_bounds.joint.base_width_mm must be > neck_width_mm")


class MaxPrintBoundsSettings:
    """Optional print-volume settings for auto-segmentation into printable parts."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", False))
        self.width: float = float(data.get("width", 0.0))
        self.length: float = float(data.get("length", 0.0))
        self.height: float = float(data.get("height", 0.0))
        self.clearance_mm: float = float(data.get("clearance_mm", 0.0))
        self.max_segments: int = int(data.get("max_segments", 32))
        self.layout: str = str(data.get("layout", "path")).strip().lower()
        self.layout_gap_mm: float = float(data.get("layout_gap_mm", 12.0))
        self.path_samples: int = int(data.get("path_samples", 1001))
        self.joint = PrintJointSettings(data.get("joint", {}))

        if self.enabled:
            for key in ("width", "length", "height"):
                if getattr(self, key) <= 0:
                    raise ValueError(f"max_print_bounds.{key} must be > 0 when enabled")
            if self.clearance_mm < 0:
                raise ValueError("max_print_bounds.clearance_mm must be >= 0")
            if self.max_segments < 1:
                raise ValueError("max_print_bounds.max_segments must be >= 1")
            if self.layout not in ("path", "print_bed"):
                raise ValueError("max_print_bounds.layout must be 'path' or 'print_bed'")
            if self.layout_gap_mm < 0:
                raise ValueError("max_print_bounds.layout_gap_mm must be >= 0")
            if self.path_samples < 8:
                raise ValueError("max_print_bounds.path_samples must be >= 8")
            usable = [self.width - 2.0 * self.clearance_mm, self.length - 2.0 * self.clearance_mm, self.height - 2.0 * self.clearance_mm]
            if min(usable) <= 0:
                raise ValueError("max_print_bounds dimensions minus clearance must be positive")


class PathSettings:
    """Path/twist configuration (e.g. min distance for 90° twist)."""

    def __init__(self, data: Dict[str, Any]):
        twist_dist = data.get('min_90_degree_twist_distance') or data.get('min_90_degtree_twist_distance', 90.0)
        self.min_90_degree_twist_distance = float(twist_dist)
        if self.min_90_degree_twist_distance <= 0:
            raise ValueError(
                "min_90_degree_twist_distance must be positive (got %s)" % self.min_90_degree_twist_distance
            )


class TubeGapSettings:
    """Optional gap settings to open the tube for wire/LED insertion."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", False))
        self.gap_length_mm: float = float(data.get("gap_length_mm", 0.0))
        # In [-0.5, 0.5]; 0.0 = centered along point polyline length.
        self.center_fraction: float = float(data.get("center_fraction", 0.0))
        if self.gap_length_mm < 0:
            raise ValueError("tube_gap.gap_length_mm must be >= 0 (got %s)" % self.gap_length_mm)
        if not (-0.5 <= self.center_fraction <= 0.5):
            raise ValueError("tube_gap.center_fraction must be in [-0.5, 0.5] (got %s)" % self.center_fraction)


class ClampSettings:
    """Settings for the 2-part tube clamp used to close the gap."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", True))

        # Clearance on diameter (mm): clamp ID = tube OD + clearance_diameter_mm
        self.clearance_diameter_mm: float = float(data.get("clearance_diameter_mm", 1.0))
        self.length_mm: float = float(data.get("length_mm", 18.0))
        self.wall_thickness_mm: float = float(data.get("wall_thickness_mm", 2.5))

        # Lap joint dimensions along the seam for gluing/alignment.
        self.lap_depth_mm: float = float(data.get("lap_depth_mm", 1.0))
        # For the seam step: radial step height into the wall thickness.
        self.lap_step_height_mm: float = float(data.get("lap_step_height_mm", 1.5))
        self.lap_clearance_mm: float = float(data.get("lap_clearance_mm", 0.2))

        # Wire feed hole + ring.
        self.wire_hole_diameter_mm: float = float(data.get("wire_hole_diameter_mm", 4.0))
        self.wire_ring_height_mm: float = float(data.get("wire_ring_height_mm", 4.0))
        self.wire_ring_top_thickness_mm: float = float(data.get("wire_ring_top_thickness_mm", 1.0))
        self.wire_ring_base_thickness_mm: float = float(data.get("wire_ring_base_thickness_mm", 2.0))

        # Adhesive / joint tolerances.
        self.adhesive_gap_mm: float = float(data.get("adhesive_gap_mm", 0.10))

        # Registration: circular lip + groove along the seam.
        self.reg_lip_height_mm: float = float(data.get("reg_lip_height_mm", 0.8))
        self.reg_lip_width_mm: float = float(data.get("reg_lip_width_mm", 1.2))
        self.reg_clearance_mm: float = float(data.get("reg_clearance_mm", 0.08))

        # Adhesive relief features (escape pockets).
        self.relief_enabled: bool = bool(data.get("relief_enabled", True))
        self.relief_depth_mm: float = float(data.get("relief_depth_mm", 0.3))
        self.relief_width_mm: float = float(data.get("relief_width_mm", 0.5))

        # Alignment notch: key-and-slot to prevent halves from sliding along Z.
        self.alignment_notch_enabled: bool = bool(data.get("alignment_notch_enabled", True))
        self.alignment_notch_width_mm: float = float(data.get("alignment_notch_width_mm", 3.0))
        self.alignment_notch_depth_mm: float = float(data.get("alignment_notch_depth_mm", 0.8))
        self.alignment_notch_clearance_mm: float = float(data.get("alignment_notch_clearance_mm", 0.1))

        for k in (
            "clearance_diameter_mm",
            "length_mm",
            "wall_thickness_mm",
            "lap_depth_mm",
            "lap_step_height_mm",
            "wire_hole_diameter_mm",
            "wire_ring_height_mm",
            "wire_ring_top_thickness_mm",
            "wire_ring_base_thickness_mm",
            "reg_lip_height_mm",
            "reg_lip_width_mm",
            "relief_depth_mm",
            "relief_width_mm",
            "alignment_notch_width_mm",
            "alignment_notch_depth_mm",
        ):
            if getattr(self, k) <= 0:
                raise ValueError(f"clamp.{k} must be > 0 (got {getattr(self, k)})")

        for k in ("adhesive_gap_mm", "reg_clearance_mm", "alignment_notch_clearance_mm"):
            if getattr(self, k) < 0:
                raise ValueError(f"clamp.{k} must be >= 0 (got {getattr(self, k)})")


class TubeSettings:
    """Active face configuration built from resolved face_settings for the selected face_type."""

    def __init__(self, face_type: str, face_data: Dict[str, Any]):
        self.face_type = str(face_type)
        if self.face_type not in VALID_FACE_TYPES:
            raise ValueError(
                f"face_type must be one of {VALID_FACE_TYPES!r} (got {self.face_type!r})"
            )
        data = dict(face_data) if face_data else {}

        # Square uses outer_width; others use outer_diameter
        if self.face_type == 'square':
            ow = data.get('outer_width')
            self.outer_diameter = float(ow) if ow is not None else None  # not used for square
            self._outer_width = float(ow) if ow is not None else None
        else:
            od = data.get('outer_diameter')
            self.outer_diameter = float(od) if od is not None else None
            self._outer_width = None

        self.wall_thickness = float(data.get('wall_thickness', 1.0))
        self.oval_wall_thickness = float(data.get('oval_wall_thickness', 2.0))
        self.connector_width = float(data.get('connector_width', 1.0))
        self.rect_inner_x = float(data.get('rect_inner_x', 4.0))
        self.rect_inner_y = float(data.get('rect_inner_y', 12.0))

        itd = data.get('inner_tube_diameter')
        self.inner_tube_diameter = float(itd) if itd is not None else None
        itwt = data.get('inner_tube_wall_thickness')
        self.inner_tube_wall_thickness = float(itwt) if itwt is not None else None

        # Per-model config blocks. Each tube model pulls the dict it cares about
        # out of the resolved face_settings entry (which has already had
        # `inherit_from` applied by `resolve_face_settings`).
        pyr = data.get('pyramid_studded')
        if isinstance(pyr, dict):
            self.pyramid_studded = {str(k): v for k, v in pyr.items()}
        else:
            self.pyramid_studded = None

        br = data.get('braided_rope')
        if isinstance(br, dict):
            self.braided_rope = {str(k): v for k, v in br.items()}
        else:
            self.braided_rope = None

    @property
    def outer_radius(self) -> float:
        """Outer radius in mm. For square, outer_width/2; for circles, outer_diameter/2."""
        if self.face_type == 'square':
            if self._outer_width is None:
                raise ValueError("square face requires outer_width in face_settings")
            return self._outer_width / 2.0
        if self.outer_diameter is None:
            raise ValueError("outer_diameter must be set in face_settings for face_type %r" % self.face_type)
        return self.outer_diameter / 2.0

    def to_led_circle_face_kwargs(self, **kwargs) -> Dict[str, Any]:
        """
        Return a dictionary of parameters suitable for create_led_circle_face (or create_square_face).
        rect_inner_x, rect_inner_y and outer_radius come from resolved face_settings.
        """
        base_kwargs = {
            'outer_radius': self.outer_radius,
            'wall_thickness': self.wall_thickness,
            'min_oval_wall_thickness': self.oval_wall_thickness,
            'oval_wall_thickness': self.oval_wall_thickness,
            'connector_width': self.connector_width,
            'rect_inner_x': self.rect_inner_x,
            'rect_inner_y': self.rect_inner_y,
        }
        base_kwargs.update(kwargs)
        return base_kwargs

    def to_led_circle_tube_face_kwargs(self, **kwargs) -> Dict[str, Any]:
        """
        Return parameters for create_led_circle_tube_face.
        Requires inner_tube_diameter and inner_tube_wall_thickness in face_settings.
        """
        if self.inner_tube_diameter is None:
            raise ValueError(
                "inner_tube_diameter must be set in face_settings for face_type 'led_circle_tube'"
            )
        if self.inner_tube_wall_thickness is None:
            raise ValueError(
                "inner_tube_wall_thickness must be set in face_settings for face_type 'led_circle_tube'"
            )
        base_kwargs = {
            'outer_radius': self.outer_radius,
            'wall_thickness': self.wall_thickness,
            'inner_tube_diameter': self.inner_tube_diameter,
            'inner_tube_wall_thickness': self.inner_tube_wall_thickness,
            'connector_width': self.connector_width,
        }
        base_kwargs.update(kwargs)
        return base_kwargs


class ViewerSettings:
    """cadquery-web-viewer options from ``server.viewer`` in YAML."""

    _VALID_MODES = frozenset({'off', 'embedded', 'remote'})

    def __init__(self, data: Dict[str, Any]):
        d = data or {}
        mode = str(d.get('mode', 'remote')).strip().lower()
        if mode not in self._VALID_MODES:
            raise ValueError(
                "server.viewer.mode must be one of %r (got %r)"
                % (sorted(self._VALID_MODES), mode)
            )
        self.mode = mode
        emb = d.get('embedded') or {}
        self.embedded_host = str(emb.get('host', '127.0.0.1'))
        self.embedded_port = int(emb.get('port', 32323))
        self.embedded_open_browser = bool(emb.get('open_browser', True))
        self.embedded_wait_for_first_client = bool(emb.get('wait_for_first_client', False))
        self.embedded_block_until_disconnect = bool(emb.get('block_until_disconnect', False))
        rem = d.get('remote') or {}
        self.remote_host = str(rem.get('host', 'localhost'))
        self.remote_port = int(rem.get('port', 32323))
        ut = rem.get('upload_timeout')
        self.remote_upload_timeout = float(ut) if ut is not None else 300.0
        pt = rem.get('post_timeout')
        self.remote_post_timeout = float(pt) if pt is not None else 60.0


class ServerSettings:
    """cadquery-web-viewer styling env vars and viewer connection settings."""

    # YAML attribute -> CADQUERY_WEB_VIEWER_* (read by cadquery_web_viewer.engine)
    _ENV_MAP = {
        'protocol': 'CADQUERY_WEB_VIEWER_PROTOCOL',
        'texture': 'CADQUERY_WEB_VIEWER_TEXTURE',
        'color_faces': 'CADQUERY_WEB_VIEWER_COLOR_FACES',
        'color_edges': 'CADQUERY_WEB_VIEWER_COLOR_EDGES',
        'color_vertices': 'CADQUERY_WEB_VIEWER_COLOR_VERTICES',
    }

    def __init__(self, data: Dict[str, Any], _project_root: Path):
        self.protocol = data.get('protocol')
        self.texture = data.get('texture')
        self.color_faces = data.get('color_faces')
        self.color_edges = data.get('color_edges')
        self.color_vertices = data.get('color_vertices')
        self.viewer = ViewerSettings(data.get('viewer'))

    def apply_to_env(self) -> None:
        """Set CADQUERY_WEB_VIEWER_* environment variables for any non-None styling/protocol keys."""
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
        self.stl_ascii = bool(data.get('stl_ascii', True))  # True = ASCII (e.g. GitHub), False = binary


class PreviewSettings:
    """Preview image settings (mesh to image; fine tessellation for smooth tubes)."""

    def __init__(self, data: Dict[str, Any], project_root: Path):
        stl_cache = str(data.get('stl_cache', 'cache/preview'))
        self.preview_cache_dir = project_root / stl_cache
        # Tessellation for preview mesh (smaller = smoother)
        self.mesh_tolerance = float(data.get('mesh_tolerance', 0.0005))
        self.mesh_angular_tolerance = float(data.get('mesh_angular_tolerance', 0.04))
        self.image_width = int(data.get('image_width', 800))
        self.image_height = int(data.get('image_height', 600))
        self.dpi = int(data.get('dpi', 100))
        self.elevation = float(data.get('elevation', 30))
        self.azimuth = float(data.get('azimuth', 45))
        self.roll = float(data.get('roll', 0))
        self.light_azimuth = float(data.get('light_azimuth', 225))
        self.light_elevation = float(data.get('light_elevation', 45))
        self.opacity = float(data.get('opacity', 1.0))
        self.opacity = max(0.0, min(1.0, self.opacity))
        color_spec = data.get('color', '#b3b3b3')
        self._color_rgb = self._parse_color(color_spec)
        background_spec = data.get('background', '#ffffff')
        self._background_rgb = self._parse_color(background_spec)

    @staticmethod
    def _parse_color(spec: Any) -> tuple:
        """Parse color from hex string (e.g. '#b3b3b3') or name; return (r, g, b) in [0, 1]."""
        import matplotlib.colors as mcolors
        if isinstance(spec, (list, tuple)) and len(spec) >= 3:
            return (float(spec[0]), float(spec[1]), float(spec[2]))
        s = str(spec).strip()
        rgb = mcolors.to_rgb(s)
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]))


class MeshSettings:
    """Mesh export configuration for simulation-focused OBJ output."""

    def __init__(self, data: Dict[str, Any], filepath: Optional[str] = None):
        # Target output mesh path from the command line (--output-mesh).
        self.filepath: Optional[str] = filepath

        # Unit scaling: when true, convert from millimeters (CadQuery default)
        # to meters (used by Genesis and many physics engines).
        self.unit_scale_mm_to_m: bool = bool(data.get("unit_scale_mm_to_m", True))

        # Optional decimation target: maximum number of faces to aim for.
        # When None, no automatic decimation is performed.
        tfc = data.get("target_face_count", None)
        self.target_face_count: Optional[int] = int(tfc) if tfc is not None else None

        # Require watertight meshes for export. If true and the generated mesh
        # is not watertight, mesh export will fail with a clear error.
        self.watertight_required: bool = bool(data.get("watertight_required", True))


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

        # Parse command line arguments (overlay must merge before settings init)
        args = parse_args(description=description or "Create and render a knot model")

        self.config_overlay_path: Optional[Path] = None
        if args.config:
            overlay_path = _resolve_config_path(project_root, args.config)
            if not overlay_path.exists():
                raise FileNotFoundError(f"Config overlay not found: {overlay_path}")
            with open(overlay_path, 'r') as f:
                overlay_data = yaml.safe_load(f) or {}
            config_data = self._merge_dicts(config_data, overlay_data)
            self.config_overlay_path = overlay_path
        
        # Initialize configuration sections
        self.output_bounds = OutputBounds(config_data.get('output_bounds', {}))
        face_type = str(config_data.get('face_type', 'led_circle'))
        if face_type not in VALID_FACE_TYPES:
            raise ValueError(f"face_type must be one of {VALID_FACE_TYPES!r} (got {face_type!r})")
        face_settings_raw = config_data.get('face_settings') or {}
        face_data = resolve_face_settings(face_settings_raw, face_type)
        self.tube_settings = TubeSettings(face_type, face_data)
        self.path_settings = PathSettings(config_data.get('path', {}))
        self.max_print_bounds = MaxPrintBoundsSettings(config_data.get("max_print_bounds", {}))
        self.tube_gap = TubeGapSettings(config_data.get("tube_gap", {}))
        self.clamp = ClampSettings(config_data.get("clamp", {}))
        self.print_optimization = PrintOptimizationSettings(
            config_data.get("print_optimization", {})
        )
        
        # Server settings (viewer + optional CADQUERY_WEB_VIEWER_* styling)
        server_data = config_data.get('server', {})
        self.server_settings = ServerSettings(server_data, project_root)
        
        # Initialize export settings with command line filepath
        self.export = ExportSettings(config_data.get('export', {}), filepath=args.export)

        # Mesh export settings (simulation-focused OBJ output).
        self.mesh = MeshSettings(config_data.get("mesh", {}), filepath=getattr(args, "output_mesh", None))

        # Preview settings (STL cache dir, image size, view angles)
        preview_data = config_data.get('preview', {})
        self.preview_settings = PreviewSettings(preview_data, project_root)
        self.preview_settings.preview_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Preview cache directory: %s", self.preview_settings.preview_cache_dir)
        
        # Store other command line arguments as properties
        self.server = args.server
        self._init_viewer_from_args(args)
        self.preview_filepath = args.preview
        # Optional multi-part export (e.g., assembly vs individual parts)
        self.export_parts = getattr(args, "export_parts", None)
        self.export_parts_dir = getattr(args, "export_parts_dir", None)
        self.name = name  # Name of the part (used for export/display)

        # CLI overrides for the print-optimization stage. --auto-orient
        # implies enabling the optimizer; --optimize / --no-optimize set
        # it explicitly. None means "use config.yaml value".
        cli_optimize = getattr(args, "optimize", None)
        cli_auto_orient = bool(getattr(args, "auto_orient", False))
        cli_report_dir = getattr(args, "optimize_report_dir", None)
        if cli_optimize is True or cli_auto_orient or cli_report_dir:
            self.print_optimization.enabled = True
        elif cli_optimize is False:
            self.print_optimization.enabled = False
        if cli_auto_orient:
            self.print_optimization.orientation.auto_apply = True
        self.optimize_report_dir = cli_report_dir

    def _init_viewer_from_args(self, args) -> None:
        """
        Resolve cadquery-web-viewer usage from ``--viewer`` / ``--server`` and YAML ``server.viewer``.
        Sets: viewer_enabled, viewer_server_type, viewer_block_until_disconnect,
        viewer_server_options, viewer_remote_options.
        """
        v = getattr(args, 'viewer', None)
        vs = self.server_settings.viewer

        if v == 'off':
            self.viewer_enabled = False
        elif v in ('embedded', 'embedded-block', 'remote'):
            self.viewer_enabled = True
        elif bool(getattr(args, 'server', False)):
            self.viewer_enabled = True
        else:
            self.viewer_enabled = False

        if not self.viewer_enabled:
            self.viewer_server_type: Optional[str] = None
            self.viewer_block_until_disconnect = False
            self.viewer_server_options = None
            self.viewer_remote_options = None
            return

        if v in ('embedded', 'embedded-block'):
            yaml_mode = 'embedded'
            block = v == 'embedded-block'
        elif v == 'remote':
            yaml_mode = 'remote'
            block = False
        else:
            # ``--server`` with no ``--viewer`` (or future defaults): YAML ``server.viewer.mode``
            yaml_mode = vs.mode if vs.mode != 'off' else 'embedded'
            block = yaml_mode == 'embedded' and vs.embedded_block_until_disconnect

        if yaml_mode == 'remote':
            self.viewer_server_type = 'remote'
            self.viewer_block_until_disconnect = False
            self.viewer_server_options = None
            self.viewer_remote_options = {
                'host': vs.remote_host,
                'port': vs.remote_port,
                'upload_timeout': vs.remote_upload_timeout,
                'post_timeout': vs.remote_post_timeout,
            }
        else:
            self.viewer_server_type = 'in-process'
            self.viewer_block_until_disconnect = block
            self.viewer_server_options = {
                'host': vs.embedded_host,
                'port': vs.embedded_port,
                'open_browser': vs.embedded_open_browser,
                'wait_for_first_client': vs.embedded_wait_for_first_client,
                'wait_for_client_timeout': 120.0,
            }
            self.viewer_remote_options = None

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
        set_env_vars: If True (default), set CADQUERY_WEB_VIEWER_* environment variables from
                      server config before ``cadquery_web_viewer`` is imported.
    
    Returns:
        Config: The global configuration instance with parsed command line arguments.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(description=description, name=name)
    if set_env_vars:
        _config_instance.server_settings.apply_to_env()
    return _config_instance
