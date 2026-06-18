"""
Configuration management for LED knots.

Reads configuration from config.yaml, optionally overrides with config.local.yaml,
and merges the config file passed to render-knot / render-part on top of both.
Provides an object-oriented interface to configuration values.
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from .utils import parse_render_args
from led_knots.optimize.settings import PrintOptimizationSettings
from .cache_utils import render_bundle_stem

logger = logging.getLogger(__name__)


def _resolve_config_path(project_root: Path, path_str: str) -> Path:
    """Resolve a config file path: absolute as-is, relative against project root."""
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
    'braided_rope_tube',
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


class FingerSensorHolderSettings:
    """Settings for the finger pulse-sensor holder accessory part."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        defaults = {
            "holder_width": 30.00,
            "holder_length": 67.00,
            "base_thickness": 4.48,
            "wall_thickness": 2.29,
            "wall_full_height": 20.70,
            "rear_wall_low_height": 8.45,
            "rear_transition_length": 23.57,
            "front_transition_length": 4.90,
            "hinge_axis_from_rear": 22.70,
            "hinge_axis_height_above_base": 14.40,
            "hinge_rod_diameter": 3.17,
            "hinge_outer_diameter": 5.02,
            "pedestal_front_offset": 9.50,
            "pedestal_width": 17.00,
            "pedestal_front_height": 10.00,
            "sensor_pcb_diameter": 15.80,
            "sensor_max_thickness": 3.60,
            "sensor_pocket_diameter": 16.20,
            "sensor_pocket_depth": 3.70,
            "sensor_exposed_opening_diameter": 15.00,
            "cable_channel_width": 4.50,
            "cable_channel_depth": 2.50,
            "general_fillet_radius": 1.00,
            "front_transition_radius": 2.00,
            "rear_transition_radius": 2.50,
            "pedestal_length": 32.00,
            "pedestal_rear_height_above_base": 6.00,
            "finger_trough_width": 15.00,
            "finger_trough_depth": 3.50,
            "finger_trough_length": 28.00,
            "finger_stop_radius": 8.00,
            "finger_trough_front_blend_length": 5.00,
            "sensor_center_y": 33.50,
            "sensor_face_raise_mm": 0.25,
            "hinge_rod_clearance_mm": 0.15,
            "retention_plate_clearance_mm": 0.25,
            "retention_plate_thickness_mm": 1.50,
            "retention_tab_count": 3,
            "retention_tab_width_mm": 2.00,
            "retention_tab_depth_mm": 0.80,
            "cable_exit_y": 62.00,
            "strain_relief_pocket_diameter": 6.00,
            "strain_relief_pocket_depth": 1.50,
        }
        for key, default in defaults.items():
            if key == "retention_tab_count":
                setattr(self, key, int(data.get(key, default)))
            else:
                setattr(self, key, float(data.get(key, default)))


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
    """Remote cadquery-web-viewer connection options from ``server.viewer`` in YAML."""

    def __init__(self, data: Dict[str, Any]):
        d = data or {}
        rem = d.get('remote') or {}
        self.host = str(d.get('host', rem.get('host', 'localhost')))
        self.port = int(d.get('port', rem.get('port', 32323)))
        ut = d.get('upload_timeout', rem.get('upload_timeout'))
        self.upload_timeout = float(ut) if ut is not None else 300.0
        pt = d.get('post_timeout', rem.get('post_timeout'))
        self.post_timeout = float(pt) if pt is not None else 60.0
        self.tessellation_tolerance = float(d.get('tessellation_tolerance', 0.05))
        self.tessellation_angular_tolerance = float(
            d.get('tessellation_angular_tolerance', 0.1)
        )

    def remote_options(self) -> Dict[str, Any]:
        return {
            'host': self.host,
            'port': self.port,
            'upload_timeout': self.upload_timeout,
            'post_timeout': self.post_timeout,
        }


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


DEFAULT_FILENAME_TEMPLATES: Dict[str, str] = {
    "stl": "{name}.stl",
    "step": "{name}.step",
    "3mf": "{name}.3mf",
    "glb": "{name}.glb",
    "gltf": "{name}.gltf",
    "obj": "{name}.obj",
    "preview": "{name}.png",
    "config": "{name}.yaml",
    "stats": "{name}.csv",
}

VALID_EXPORT_FORMATS = frozenset(DEFAULT_FILENAME_TEMPLATES.keys())

_RESERVED_EXPORT_KEYS = frozenset({"format", "enabled", "filename"})


def resolve_filename_template(
    template: str,
    *,
    bundle_stem: str,
    run_name: str,
) -> str:
    return (
        template.replace("{name}", bundle_stem)
        .replace("{run_name}", run_name)
    )


def _parse_color(spec: Any) -> tuple:
    import matplotlib.colors as mcolors
    if isinstance(spec, (list, tuple)) and len(spec) >= 3:
        return (float(spec[0]), float(spec[1]), float(spec[2]))
    s = str(spec).strip()
    rgb = mcolors.to_rgb(s)
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]))


def _merge_exports_by_filename(
    base: List[Dict[str, Any]],
    override: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not override:
        return list(base)
    indexed: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in base:
        job = dict(entry)
        fmt = str(job.get("format", ""))
        key = str(job.get("filename") or DEFAULT_FILENAME_TEMPLATES.get(fmt, "{name}.dat"))
        indexed[key] = job
        order.append(key)
    for entry in override:
        job = dict(entry)
        fmt = str(job.get("format", ""))
        key = str(job.get("filename") or DEFAULT_FILENAME_TEMPLATES.get(fmt, "{name}.dat"))
        if key in indexed:
            indexed[key] = Config._merge_dicts(indexed[key], job)
        else:
            indexed[key] = job
            order.append(key)
    return [indexed[k] for k in order]


class RenderingExportJob:
    """One entry in rendering.exports."""

    def __init__(self, data: Dict[str, Any], project_root: Path):
        self.format = str(data.get("format", "")).strip().lower()
        if self.format not in VALID_EXPORT_FORMATS:
            raise ValueError(
                f"rendering.exports format must be one of {sorted(VALID_EXPORT_FORMATS)!r} "
                f"(got {self.format!r})"
            )
        self.enabled = bool(data.get("enabled", True))
        self.filename_template = str(
            data.get("filename") or DEFAULT_FILENAME_TEMPLATES[self.format]
        )
        self.match_key = self.filename_template
        self.settings = {
            k: v for k, v in data.items() if k not in _RESERVED_EXPORT_KEYS
        }
        self._project_root = project_root
        self._init_format_attrs(data)

    def _init_format_attrs(self, data: Dict[str, Any]) -> None:
        if self.format == "stl":
            self.stl_ascii = bool(data.get("stl_ascii", True))
        elif self.format == "preview":
            stl_cache = str(data.get("stl_cache", "cache/preview"))
            self.preview_cache_dir = self._project_root / stl_cache
            self.mesh_tolerance = float(data.get("mesh_tolerance", 0.0005))
            self.mesh_angular_tolerance = float(data.get("mesh_angular_tolerance", 0.04))
            self.image_width = int(data.get("image_width", 800))
            self.image_height = int(data.get("image_height", 600))
            self.dpi = int(data.get("dpi", 100))
            self.elevation = float(data.get("elevation", 30))
            self.azimuth = float(data.get("azimuth", 45))
            self.roll = float(data.get("roll", 0))
            self.light_azimuth = float(data.get("light_azimuth", 225))
            self.light_elevation = float(data.get("light_elevation", 45))
            self.opacity = max(0.0, min(1.0, float(data.get("opacity", 1.0))))
            self._color_rgb = _parse_color(data.get("color", "#b3b3b3"))
            self._background_rgb = _parse_color(data.get("background", "#ffffff"))
        elif self.format == "obj":
            self.unit_scale_mm_to_m = bool(data.get("unit_scale_mm_to_m", True))
            tfc = data.get("target_face_count")
            self.target_face_count = int(tfc) if tfc is not None else None
            self.watertight_required = bool(data.get("watertight_required", False))


class RenderingSettings:
    """Render bundle output directory, shared tolerances, and export jobs."""

    def __init__(
        self,
        data: Dict[str, Any],
        project_root: Path,
        *,
        model_name: Optional[str],
        cli_name: Optional[str],
        disabled_formats: Optional[set] = None,
    ):
        self.output_dir = str(data.get("output_dir", "renders"))
        yaml_name = data.get("name")
        self._yaml_name = yaml_name
        self._model_name = model_name
        self._cli_name = cli_name
        self.tolerance = float(data.get("tolerance", 0.0001))
        self.angular_tolerance = float(data.get("angular_tolerance", 0.05))
        self._disabled_formats = {f.strip().lower() for f in (disabled_formats or set()) if f.strip()}
        raw_exports = data.get("exports")
        if raw_exports is None:
            raw_exports = _default_exports_list()
        self.exports: List[RenderingExportJob] = [
            RenderingExportJob(entry, project_root)
            for entry in raw_exports
        ]
        for job in self.exports:
            if job.format == "preview":
                job.preview_cache_dir.mkdir(parents=True, exist_ok=True)

    def resolve_run_name(self) -> str:
        if self._cli_name:
            return self._cli_name
        if self._yaml_name not in (None, ""):
            return str(self._yaml_name)
        if self._model_name:
            return self._model_name
        return "knot"

    def enabled_jobs(self) -> List[RenderingExportJob]:
        jobs = []
        for job in self.exports:
            if not job.enabled:
                continue
            if job.format in self._disabled_formats:
                continue
            jobs.append(job)
        return jobs

    def preview_jobs(self) -> List[RenderingExportJob]:
        return [j for j in self.exports if j.format == "preview" and j.enabled and j.format not in self._disabled_formats]

    def job_by_filename_template(self, key: str) -> Optional[RenderingExportJob]:
        for job in self.exports:
            if job.match_key == key:
                return job
        return None

    def first_preview_job(self) -> Optional[RenderingExportJob]:
        previews = self.preview_jobs()
        return previews[0] if previews else None


def _default_exports_list() -> List[Dict[str, Any]]:
    return [
        {"format": "stl", "enabled": True, "filename": "{name}.stl", "stl_ascii": True},
        {
            "format": "preview",
            "enabled": True,
            "filename": "{name}.png",
            "stl_cache": "cache/preview",
            "mesh_tolerance": 0.0005,
            "mesh_angular_tolerance": 0.04,
            "image_width": 800,
            "image_height": 600,
            "dpi": 100,
            "elevation": 30,
            "azimuth": 45,
            "roll": 0,
            "light_azimuth": 225,
            "light_elevation": 45,
            "color": "#b3b3b3",
            "opacity": 1.0,
            "background": "#1a1a2e",
        },
        {"format": "glb", "enabled": True, "filename": "{name}.glb"},
        {"format": "config", "enabled": True, "filename": "{name}.yaml"},
        {"format": "stats", "enabled": True, "filename": "{name}.csv"},
        {"format": "step", "enabled": False, "filename": "{name}.step"},
        {"format": "gltf", "enabled": False, "filename": "{name}.gltf"},
        {"format": "3mf", "enabled": False, "filename": "{name}.3mf"},
        {
            "format": "obj",
            "enabled": False,
            "filename": "{name}.obj",
            "unit_scale_mm_to_m": True,
            "target_face_count": None,
            "watertight_required": False,
        },
    ]


class Config:
    """Main configuration object."""
    
    def __init__(
        self,
        *,
        args=None,
        description: Optional[str] = None,
    ):
        # Find the project root (where config.yaml is located)
        # This file is in src/led_knots/core/, so we go up 3 levels
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent

        base_config_path = project_root / 'config.yaml'
        local_config_path = project_root / 'config.local.yaml'
        self.config_base_path = base_config_path
        self.config_local_path = local_config_path

        # Load base configuration
        with open(base_config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}

        # Load local overrides if they exist
        if local_config_path.exists():
            with open(local_config_path, 'r') as f:
                local_data = yaml.safe_load(f) or {}
                config_data = self._merge_dicts(config_data, local_data)

        if args is None:
            args = parse_render_args(description=description or "Render a model from a config file")

        self.config_path: Optional[Path] = None
        user_config = getattr(args, "config", None)
        if user_config:
            resolved_path = _resolve_config_path(project_root, user_config)
            if not resolved_path.exists():
                raise FileNotFoundError(f"Config file not found: {resolved_path}")
            with open(resolved_path, 'r') as f:
                overlay_data = yaml.safe_load(f) or {}
            config_data = self._merge_dicts(config_data, overlay_data)
            self.config_path = resolved_path

        disabled_formats = set()
        if getattr(args, "disable_export", None):
            disabled_formats = {
                f.strip().lower()
                for f in str(args.disable_export).split(",")
                if f.strip()
            }
        if getattr(args, "renders_dir", None):
            rendering_block = dict(config_data.get("rendering") or {})
            rendering_block["output_dir"] = args.renders_dir
            config_data["rendering"] = rendering_block
        if getattr(args, "name", None):
            rendering_block = dict(config_data.get("rendering") or {})
            rendering_block["name"] = args.name
            config_data["rendering"] = rendering_block
        
        self._config_data = config_data
        knot_type = config_data.get("knot_type")
        part_type = config_data.get("part_type")
        self.knot_type = str(knot_type).strip() if knot_type not in (None, "") else None
        self.part_type = str(part_type).strip() if part_type not in (None, "") else None
        model_name = self.knot_type or self.part_type
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
        self.finger_sensor_holder = FingerSensorHolderSettings(
            config_data.get("finger_sensor_holder", {})
        )
        self.print_optimization = PrintOptimizationSettings(
            config_data.get("print_optimization", {})
        )
        
        # Server settings (viewer + optional CADQUERY_WEB_VIEWER_* styling)
        server_data = config_data.get('server', {})
        self.server_settings = ServerSettings(server_data, project_root)

        rendering_data = config_data.get("rendering") or {}
        if not rendering_data.get("exports"):
            rendering_data = {**rendering_data, "exports": _default_exports_list()}
        self.rendering = RenderingSettings(
            rendering_data,
            project_root,
            model_name=model_name,
            cli_name=getattr(args, "name", None),
            disabled_formats=disabled_formats,
        )
        self.run_name = self.rendering.resolve_run_name()
        self.name = self.run_name
        self.render_bundle_stem = render_bundle_stem(self.run_name)
        self.render_bundle_dir = Path.cwd() / self.rendering.output_dir / self.render_bundle_stem
        self.render_stats = None

        self._init_viewer_from_args(args)

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
        """Set viewer_enabled and viewer_remote_options from ``--server``."""
        self.viewer_enabled = bool(getattr(args, 'server', False))
        if self.viewer_enabled:
            self.viewer_remote_options = self.server_settings.viewer.remote_options()
        else:
            self.viewer_remote_options = None

    def apply_viewer_from_yaml(self) -> None:
        """Enable remote cadquery-web-viewer upload from ``server.viewer`` (upload-knot)."""
        self.viewer_enabled = True
        self.viewer_remote_options = self.server_settings.viewer.remote_options()

    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge override dict into base dict."""
        result = base.copy()
        for key, value in override.items():
            if key == "rendering" and isinstance(value, dict):
                base_rendering = result.get("rendering", {})
                if not isinstance(base_rendering, dict):
                    base_rendering = {}
                merged = dict(base_rendering)
                for rk, rv in value.items():
                    if rk == "exports" and isinstance(rv, list):
                        base_exports = base_rendering.get("exports") or []
                        merged["exports"] = _merge_exports_by_filename(base_exports, rv)
                    elif isinstance(rv, dict) and isinstance(merged.get(rk), dict):
                        merged[rk] = Config._merge_dicts(merged[rk], rv)
                    else:
                        merged[rk] = rv
                result["rendering"] = merged
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result


# Global configuration instance
_config_instance: Config = None


def load_config(
    *,
    args=None,
    description: Optional[str] = None,
    set_env_vars: bool = True,
) -> Config:
    """
    Load configuration from defaults, optional local overrides, and a user config file.

    Args:
        args: Pre-parsed CLI namespace from ``parse_render_args``. When omitted, parses ``sys.argv``.
        description: Parser description when ``args`` is not provided.
        set_env_vars: If True (default), set CADQUERY_WEB_VIEWER_* environment variables from
                      server config before ``cadquery_web_viewer`` is imported.

    Returns:
        Config instance with merged YAML and CLI overrides applied.
    """
    config = Config(args=args, description=description)
    if set_env_vars:
        config.server_settings.apply_to_env()
    return config


def get_config(
    description: Optional[str] = None,
    name: Optional[str] = None,
    set_env_vars: bool = True,
) -> Config:
    """Deprecated: use ``load_config`` instead."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config(description=description, set_env_vars=set_env_vars)
    elif set_env_vars:
        _config_instance.server_settings.apply_to_env()
    return _config_instance
