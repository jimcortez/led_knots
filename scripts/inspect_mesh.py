"""
Inspect a mesh using trimesh and report watertightness and basic diagnostics.

Usage (recommended via uv):

    uv run python scripts/inspect_mesh.py path/to/mesh.(glb|obj|stl|...)

This script is read-only: it never modifies mesh files.
"""

import argparse
import sys
from pathlib import Path

import trimesh


def _load_mesh(path: Path) -> trimesh.Trimesh:
    """
    Load a mesh file as a single Trimesh instance.

    Supports any format that trimesh.load can read. If the file contains a
    Scene, all geometries are concatenated into one mesh.
    """
    try:
        # Let trimesh auto-detect the file type based on extension / contents.
        scene_or_mesh = trimesh.load(path)
    except Exception as exc:
        print(f"ERROR: Failed to load mesh '{path}': {exc!r}", file=sys.stderr)
        sys.exit(1)

    if isinstance(scene_or_mesh, trimesh.Scene):
        if not scene_or_mesh.geometry:
            print(f"ERROR: Mesh '{path}' contains an empty Scene.", file=sys.stderr)
            sys.exit(1)
        mesh = scene_or_mesh.to_geometry()
    else:
        mesh = scene_or_mesh

    if not isinstance(mesh, trimesh.Trimesh):
        print(
            f"ERROR: Loaded object from '{path}' is not a Trimesh (got {type(mesh)!r}).",
            file=sys.stderr,
        )
        sys.exit(1)

    return mesh


def _summarize_mesh(mesh: trimesh.Trimesh, path: Path) -> None:
    """Print a human-readable summary of the mesh's topology and basic stats."""
    print(f"File: {path}")
    print(f"  Watertight: {mesh.is_watertight}")
    print(f"  Vertices:  {len(mesh.vertices)}")
    print(f"  Faces:     {len(mesh.faces)}")

    try:
        components = mesh.split(only_watertight=False)
        print(f"  Components (all): {len(components)}")
    except Exception as exc:
        print(f"  Components: <error computing components: {exc!r}>")

    print(f"  Trimesh:   {trimesh.__version__}")

    # Boundary and non-manifold edge diagnostics. trimesh APIs vary by version,
    # so we compute incidence counts from faces->unique-edges when needed.
    boundary_count = None
    nonmanifold_count = None

    # Different trimesh versions expose boundary edges as properties or attributes.
    edges_boundary = getattr(mesh, "edges_boundary", None)
    if edges_boundary is None and hasattr(mesh, "boundary_edges"):
        edges_boundary = getattr(mesh, "boundary_edges")

    if edges_boundary is not None:
        try:
            boundary_count = len(edges_boundary)
        except TypeError:
            # Some versions expose it as a property returning an ndarray directly.
            try:
                boundary_count = len(list(edges_boundary))
            except Exception:
                boundary_count = None

    # Fallback: compute boundary/non-manifold edges from edge-face incidence.
    # trimesh>=4 no longer exposes edges_face_count; build counts ourselves.
    if boundary_count is None or nonmanifold_count is None:
        try:
            import numpy as np

            # faces_unique_edges is (n_faces, 3) with indices into edges_unique
            fue = getattr(mesh, "faces_unique_edges", None)
            if fue is None:
                raise AttributeError("mesh.faces_unique_edges unavailable")
            if not isinstance(fue, np.ndarray):
                fue = np.asarray(fue)
            if fue.size == 0:
                # Empty mesh: counts are trivially zero.
                efc = np.zeros((0,), dtype=np.int64)
            else:
                num_unique_edges = len(getattr(mesh, "edges_unique"))
                efc = np.bincount(fue.reshape(-1), minlength=num_unique_edges)

            if boundary_count is None:
                boundary_count = int((efc == 1).sum())
            if nonmanifold_count is None:
                nonmanifold_count = int((efc > 2).sum())
        except Exception:
            # Leave as unavailable if we can't compute.
            pass

    edges_nonmanifold = getattr(mesh, "edges_nonmanifold", None)
    if edges_nonmanifold is not None:
        try:
            nonmanifold_count = len(edges_nonmanifold)
        except TypeError:
            try:
                nonmanifold_count = len(list(edges_nonmanifold))
            except Exception:
                # Keep any fallback-computed value.
                pass

    if boundary_count is not None:
        print(f"  Boundary edges:   {boundary_count}")
        if boundary_count > 0:
            print("    NOTE: Non-zero boundary edges indicate leaks/open surfaces.")
    else:
        print("  Boundary edges:   <unavailable on this trimesh version>")

    if nonmanifold_count is not None:
        print(f"  Non-manifold edges: {nonmanifold_count}")
        if nonmanifold_count > 0:
            print("    NOTE: Non-manifold edges may cause issues in simulation/meshing.")
    else:
        print("  Non-manifold edges: <unavailable on this trimesh version>")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a mesh with trimesh and report watertightness and mesh diagnostics."
    )
    parser.add_argument(
        "mesh_path",
        type=str,
        help="Path to the mesh file to inspect (e.g. .glb, .obj, .stl, ...)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    path = Path(args.mesh_path)

    if not path.is_file():
        print(f"ERROR: Mesh file not found: {path}", file=sys.stderr)
        sys.exit(1)

    mesh = _load_mesh(path)
    _summarize_mesh(mesh, path)


if __name__ == "__main__":
    main()

