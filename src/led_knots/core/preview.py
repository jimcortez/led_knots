"""
Render GLB meshes to preview images using trimesh, pyrender, and Pillow.
"""

import logging
import math
from pathlib import Path
from typing import Any, List, Union

import numpy as np
import trimesh
from PIL import Image
import pyrender

logger = logging.getLogger(__name__)


def _scene_bbox_center_and_scale(trimesh_scene: trimesh.Scene) -> tuple:
    """Return (center, scale) for the scene using scene bounds (includes graph transforms)."""
    try:
        bounds = trimesh_scene.bounds
        if bounds is not None:
            center = np.array(
                (bounds[0] + bounds[1]) * 0.5,
                dtype=np.float64,
            )
            extents = bounds[1] - bounds[0]
            scale = float(np.max(extents)) or 1.0
            return center, scale
    except Exception:
        pass
    if not trimesh_scene.geometry:
        return np.zeros(3), 1.0
    all_bounds = []
    for geom in trimesh_scene.geometry.values():
        if hasattr(geom, 'bounds') and geom.bounds is not None:
            all_bounds.append(geom.bounds)
    if not all_bounds:
        return np.zeros(3), 1.0
    bounds = np.vstack(all_bounds)
    low = bounds.min(axis=0)
    high = bounds.max(axis=0)
    center = (low + high) * 0.5
    extents = high - low
    scale = float(np.max(extents)) or 1.0
    return center, scale


def _camera_pose_from_view(
    scene_center: np.ndarray,
    distance: float,
    elevation_deg: float,
    azimuth_deg: float,
    roll_deg: float = 0.0,
    *,
    world_up_axis: str = "y",
) -> np.ndarray:
    """Build a 4x4 camera pose: camera at distance from scene_center with given angles (degrees)."""
    el = math.radians(elevation_deg)
    az = math.radians(azimuth_deg)
    roll = math.radians(roll_deg)
    # Camera position on sphere around scene_center
    r = max(distance, 1e-6)
    if world_up_axis == "y":
        # Y-up (glTF): azimuth in XZ, elevation from XZ toward +Y
        x = r * math.cos(el) * math.cos(az)
        y = r * math.sin(el)
        z = r * math.cos(el) * math.sin(az)
    else:
        x = r * math.cos(el) * math.cos(az)
        y = r * math.cos(el) * math.sin(az)
        z = r * math.sin(el)
    cam_pos = scene_center + np.array([x, y, z], dtype=np.float64)
    # Look at scene center: forward = center - cam_pos, normalized
    forward = scene_center - cam_pos
    forward = forward / (np.linalg.norm(forward) + 1e-12)
    # glTF/pyrender use Y-up by default; use that so view matches exported scene
    if world_up_axis == "y":
        world_up = np.array([0, 1, 0], dtype=np.float64)
    else:
        world_up = np.array([0, 0, 1], dtype=np.float64)
    right = np.cross(forward, world_up)
    right_norm = np.linalg.norm(right)
    if right_norm > 1e-8:
        right = right / right_norm
    else:
        right = np.array([1, 0, 0], dtype=np.float64)
    up = np.cross(right, forward)
    up = up / (np.linalg.norm(up) + 1e-12)
    # Apply roll: rotate up and right around forward
    if abs(roll) > 1e-8:
        c, s = math.cos(roll), math.sin(roll)
        up = c * up + s * right
        right = np.cross(forward, up)
        right = right / (np.linalg.norm(right) + 1e-12)
    # 4x4 pose: columns are right, -up, -forward, position (pyrender convention: +X right, +Y up, -Z forward)
    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = up
    pose[:3, 2] = -forward
    pose[:3, 3] = cam_pos
    return pose.astype(np.float32)


def _trimesh_scene_to_pyrender_meshes_with_poses(
    trimesh_scene: Union[trimesh.Scene, trimesh.Trimesh],
    color_rgb: tuple,
    opacity: float,
) -> List[tuple]:
    """
    Convert trimesh Scene (or single Trimesh) to list of (pyrender.Mesh, pose_4x4).
    Merges scene to one mesh in world space (transforms applied) so pyrender gets a single mesh at identity.
    """
    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[*color_rgb, opacity],
        metallicFactor=0.2,
        roughnessFactor=0.8,
    )
    result = []
    if isinstance(trimesh_scene, trimesh.Trimesh):
        try:
            pr_mesh = pyrender.Mesh.from_trimesh(trimesh_scene, material=material)
            result.append((pr_mesh, np.eye(4, dtype=np.float32)))
        except Exception as e:
            logger.warning("Skipping geometry: %s", e)
        return result

    # Scene: merge all geometry with transforms applied (scene.dump()), then one mesh at identity
    try:
        merged = trimesh.util.concatenate(trimesh_scene)
    except Exception as e:
        logger.warning("Scene concatenate failed: %s", e)
        merged = None
    if merged is not None and hasattr(merged, "vertices") and len(merged.vertices) > 0:
        try:
            pr_mesh = pyrender.Mesh.from_trimesh(merged, material=material)
            result.append((pr_mesh, np.eye(4, dtype=np.float32)))
        except Exception as e:
            logger.warning("Pyrender from merged mesh failed: %s", e)
    if not result:
        # Fallback: add each geometry at identity
        for geom in trimesh_scene.geometry.values():
            if not isinstance(geom, trimesh.Trimesh):
                continue
            try:
                pr_mesh = pyrender.Mesh.from_trimesh(geom, material=material)
                result.append((pr_mesh, np.eye(4, dtype=np.float32)))
            except Exception as e:
                logger.warning("Skipping geometry in GLB: %s", e)
    return result


def render_glb_to_image(
    glb_path: Path,
    image_path: Path,
    preview_config: Any,
) -> None:
    """
    Render a GLB file to an image using trimesh, pyrender, and Pillow.

    Camera and image size come from preview_config.
    """
    image_path = Path(image_path)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    glb_path = Path(glb_path)
    if not glb_path.exists():
        raise FileNotFoundError(f"GLB file not found: {glb_path}")

    # Load with trimesh (GLB is typically a Scene)
    scene_tm = trimesh.load(str(glb_path), force="scene")
    if isinstance(scene_tm, trimesh.Trimesh):
        scene_tm = trimesh.Scene(geometry={"mesh": scene_tm})

    center, scale = _scene_bbox_center_and_scale(scene_tm)
    distance = 1.8 * scale

    # Slightly darken base color so model doesn’t blow out to white on light background
    r, g, b = preview_config._color_rgb
    scale = 0.82
    color_rgb = (float(r) * scale, float(g) * scale, float(b) * scale)
    opacity = max(0.0, min(1.0, preview_config.opacity))

    mesh_poses = _trimesh_scene_to_pyrender_meshes_with_poses(scene_tm, color_rgb, opacity)
    if not mesh_poses:
        raise ValueError(f"No meshes found in GLB: {glb_path}")

    # Keep ambient moderate so the model doesn’t blow out to white
    bg_r, bg_g, bg_b = preview_config._background_rgb
    scene = pyrender.Scene(
        ambient_light=[0.35, 0.35, 0.35],
        bg_color=[float(bg_r), float(bg_g), float(bg_b), 1.0],
    )
    for pr_mesh, pose in mesh_poses:
        scene.add(pr_mesh, pose=pose)

    # Camera
    width = max(1, preview_config.image_width)
    height = max(1, preview_config.image_height)
    aspect = width / height
    camera = pyrender.PerspectiveCamera(yfov=math.pi / 4.0, aspectRatio=aspect)
    cam_pose = _camera_pose_from_view(
        center,
        distance,
        elevation_deg=preview_config.elevation,
        azimuth_deg=preview_config.azimuth,
        roll_deg=preview_config.roll,
        world_up_axis="y",
    )
    scene.add(camera, pose=cam_pose)

    # Light (directional from front/side); same Y-up as camera
    light_az = math.radians(preview_config.light_azimuth)
    light_el = math.radians(preview_config.light_elevation)
    d = 2.0 * distance
    light_pos = center + np.array([
        d * math.cos(light_el) * math.cos(light_az),
        d * math.cos(light_el) * math.sin(light_az),
        d * math.sin(light_el),
    ], dtype=np.float32)
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=1.2)
    # Light pose: at light_pos, direction toward center
    light_forward = center - light_pos
    light_forward = light_forward / (np.linalg.norm(light_forward) + 1e-12)
    world_up = np.array([0, 1, 0], dtype=np.float32)
    light_right = np.cross(light_forward, world_up)
    light_right = light_right / (np.linalg.norm(light_right) + 1e-12)
    light_up = np.cross(light_right, light_forward)
    light_pose = np.eye(4, dtype=np.float32)
    light_pose[:3, 0] = light_right
    light_pose[:3, 1] = light_up
    light_pose[:3, 2] = -light_forward
    light_pose[:3, 3] = light_pos
    scene.add(light, pose=light_pose)

    # Offscreen render
    renderer = pyrender.OffscreenRenderer(width, height)
    try:
        color_buf, _ = renderer.render(scene)
    finally:
        renderer.delete()

    # Pyrender may return RGB or RGBA, and either uint8 (0-255) or float (0-1)
    # Use configured background for transparent areas
    bg_r, bg_g, bg_b = preview_config._background_rgb
    rgb = color_buf[:, :, :3]
    if color_buf.dtype == np.uint8:
        if color_buf.shape[2] >= 4:
            alpha = color_buf[:, :, 3:4].astype(np.float32) / 255.0
            bg_uint8 = np.array([int(bg_r * 255), int(bg_g * 255), int(bg_b * 255)], dtype=np.uint8)
            bg_frame = np.ones_like(rgb, dtype=np.uint8) * bg_uint8
            out_uint8 = (alpha * rgb + (1 - alpha) * bg_frame).clip(0, 255).astype(np.uint8)
        else:
            out_uint8 = rgb
    else:
        if color_buf.shape[2] >= 4:
            alpha = color_buf[:, :, 3:4]
            bg_frame = np.ones_like(rgb) * np.array([bg_r, bg_g, bg_b])
            out = (alpha * rgb + (1 - alpha) * bg_frame).clip(0, 1)
        else:
            out = rgb.clip(0, 1)
        out_uint8 = (out * 255).astype(np.uint8)
    img = Image.fromarray(out_uint8)
    ext = image_path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        img.save(str(image_path), "JPEG", quality=95)
    else:
        img.save(str(image_path), "PNG")
    logger.info("Preview image saved to %s", image_path)


def render_annotated_mesh_to_image(
    mesh: trimesh.Trimesh,
    image_path: Path,
    preview_config: Any,
    *,
    face_colors: np.ndarray,
) -> None:
    """
    Render a trimesh with per-face colors to an image.

    Used by the SLA print-optimization stage to produce annotated diagnostic
    images (e.g. overhangs in red). ``face_colors`` is a ``(F, 4)`` uint8
    RGBA array, one row per face. Lighting/camera/background come from
    ``preview_config`` (same fields as ``render_glb_to_image``).
    """
    if face_colors.shape != (len(mesh.faces), 4):
        raise ValueError(
            f"face_colors shape {face_colors.shape} does not match mesh "
            f"face count ({len(mesh.faces)}, 4)"
        )
    image_path = Path(image_path)
    image_path.parent.mkdir(parents=True, exist_ok=True)

    annotated = mesh.copy()
    annotated.visual.face_colors = face_colors

    # pyrender.Mesh.from_trimesh respects vertex colors when no material
    # is supplied — pass smooth=False so per-face colors don't blend at
    # shared vertices.
    pr_mesh = pyrender.Mesh.from_trimesh(annotated, smooth=False)

    bg_r, bg_g, bg_b = preview_config._background_rgb
    scene = pyrender.Scene(
        ambient_light=[0.45, 0.45, 0.45],
        bg_color=[float(bg_r), float(bg_g), float(bg_b), 1.0],
    )
    scene.add(pr_mesh, pose=np.eye(4, dtype=np.float32))

    bounds = annotated.bounds
    center = np.array((bounds[0] + bounds[1]) * 0.5, dtype=np.float64)
    extents = bounds[1] - bounds[0]
    scale = float(np.max(extents)) or 1.0
    distance = 1.8 * scale

    width = max(1, preview_config.image_width)
    height = max(1, preview_config.image_height)
    aspect = width / height
    camera = pyrender.PerspectiveCamera(yfov=math.pi / 4.0, aspectRatio=aspect)
    # The annotated mesh is in the source CAD frame (Z-up, mm). Match that.
    cam_pose = _camera_pose_from_view(
        center,
        distance,
        elevation_deg=preview_config.elevation,
        azimuth_deg=preview_config.azimuth,
        roll_deg=preview_config.roll,
        world_up_axis="z",
    )
    scene.add(camera, pose=cam_pose)

    light_az = math.radians(preview_config.light_azimuth)
    light_el = math.radians(preview_config.light_elevation)
    d = 2.0 * distance
    light_pos = center + np.array([
        d * math.cos(light_el) * math.cos(light_az),
        d * math.cos(light_el) * math.sin(light_az),
        d * math.sin(light_el),
    ], dtype=np.float32)
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=1.5)
    light_forward = center - light_pos
    light_forward = light_forward / (np.linalg.norm(light_forward) + 1e-12)
    world_up = np.array([0, 0, 1], dtype=np.float32)
    light_right = np.cross(light_forward, world_up)
    rn = np.linalg.norm(light_right)
    if rn > 1e-8:
        light_right = light_right / rn
    else:
        light_right = np.array([1, 0, 0], dtype=np.float32)
    light_up = np.cross(light_right, light_forward)
    light_pose = np.eye(4, dtype=np.float32)
    light_pose[:3, 0] = light_right
    light_pose[:3, 1] = light_up
    light_pose[:3, 2] = -light_forward
    light_pose[:3, 3] = light_pos
    scene.add(light, pose=light_pose)

    renderer = pyrender.OffscreenRenderer(width, height)
    try:
        color_buf, _ = renderer.render(scene)
    finally:
        renderer.delete()

    rgb = color_buf[:, :, :3]
    if color_buf.dtype == np.uint8:
        if color_buf.shape[2] >= 4:
            alpha = color_buf[:, :, 3:4].astype(np.float32) / 255.0
            bg_uint8 = np.array([int(bg_r * 255), int(bg_g * 255), int(bg_b * 255)], dtype=np.uint8)
            bg_frame = np.ones_like(rgb, dtype=np.uint8) * bg_uint8
            out_uint8 = (alpha * rgb + (1 - alpha) * bg_frame).clip(0, 255).astype(np.uint8)
        else:
            out_uint8 = rgb
    else:
        if color_buf.shape[2] >= 4:
            alpha = color_buf[:, :, 3:4]
            bg_frame = np.ones_like(rgb) * np.array([bg_r, bg_g, bg_b])
            out = (alpha * rgb + (1 - alpha) * bg_frame).clip(0, 1)
        else:
            out = rgb.clip(0, 1)
        out_uint8 = (out * 255).astype(np.uint8)
    Image.fromarray(out_uint8).save(str(image_path), "PNG")
    logger.info("Annotated preview image saved to %s", image_path)


def render_stl_to_image(
    stl_path: Path,
    image_path: Path,
    preview_config: Any,
) -> None:
    """
    Legacy entry point: render an STL file to an image.

    Deprecated. Prefer rendering from cached GLB via render_glb_to_image.
    This is kept for backward compatibility when only STL is available (e.g. export to STL + preview).
    """
    # Convert STL to in-memory mesh and render via same pipeline by exporting to GLB would require
    # cadquery/export. Simpler: keep a minimal matplotlib-based STL path for that edge case, or
    # require GLB for preview. User asked to "replace" preview with GLB-based; so we only support
    # render_glb_to_image. If caller passes STL we could try loading STL with trimesh and then
    # use pyrender the same way (trimesh.load can load STL). So we can support both: if path ends
    # with .glb/.gltf use render_glb_to_image logic; if .stl use trimesh.load('.stl') which
    # returns a single Trimesh, then same pyrender path.
    stl_path = Path(stl_path)
    if not stl_path.exists():
        raise FileNotFoundError(f"STL file not found: {stl_path}")
    # Load STL as trimesh and run through same rendering pipeline (single mesh)
    scene_tm = trimesh.load(str(stl_path))
    if isinstance(scene_tm, trimesh.Scene):
        pass
    else:
        scene_tm = trimesh.Scene(geometry={"mesh": scene_tm})
    # We need to write a temp GLB and call render_glb_to_image, or duplicate the render code.
    # Cleanest: factor out "render trimesh scene to image" and call it from both. Refactor.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=True) as f:
        scene_tm.export(f.name)
        render_glb_to_image(Path(f.name), image_path, preview_config)
