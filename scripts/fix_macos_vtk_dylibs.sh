#!/usr/bin/env bash
# Remove stray libvtkRenderingUI.dylib (PyPI vtk wheel) that duplicates
# cadquery-vtk's libvtkRenderingUI-9.3.dylib and triggers objc duplicate-class warnings on macOS.
set -euo pipefail
cd "$(dirname "$0")/.."
DYLIBS="$(uv run python -c "from pathlib import Path; import vtkmodules; print(Path(vtkmodules.__file__).parent / '.dylibs')")"
STRAY="${DYLIBS}/libvtkRenderingUI.dylib"
if [[ -f "$STRAY" ]]; then
  echo "Removing stray duplicate: $STRAY"
  rm -f "$STRAY"
else
  echo "No stray libvtkRenderingUI.dylib (only cadquery-vtk libs expected)."
fi
uv pip install --reinstall cadquery-vtk
echo "libvtkRenderingUI* in vtkmodules:"
ls -la "${DYLIBS}"/libvtkRenderingUI* 2>/dev/null || true
uv run python -c "import cadquery as cq; print('cadquery', cq.__version__)" 2>&1
