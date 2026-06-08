#!/usr/bin/env python3
"""
Generate preview images for all knot types.

Runs render-knot for each knot type (writes a render bundle under renders/) and
copies the preview PNG into assets/. Use for README or GitHub project visuals.

Usage:
    uv run python scripts/generate_previews.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from led_knots.knots.registry import list_knot_types

GIF_FRAME_DURATION_MS = 2000
LABEL_FONT_SIZE = 24
LABEL_PADDING = 12
LABEL_TEXT_COLOR = (255, 255, 255)


def _knot_display_name(name: str) -> str:
    return name.replace("_", " ").title()


def _get_label_font(size: int = LABEL_FONT_SIZE) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def add_label_to_preview(image: Image.Image, knot_name: str) -> None:
    draw = ImageDraw.Draw(image)
    font = _get_label_font()
    label = _knot_display_name(knot_name)
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
    except AttributeError:
        bbox = (0, 0, *draw.textsize(label, font=font))  # type: ignore[attr-defined]
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x, y = LABEL_PADDING, image.height - LABEL_PADDING - th
    margin = 6
    rect = [x - margin, y - margin, x + tw + margin, y + th + margin]
    rect_fill = (0, 0, 0, 200) if image.mode == "RGBA" else (0, 0, 0)
    draw.rectangle(rect, fill=rect_fill)
    draw.text((x, y), label, fill=LABEL_TEXT_COLOR, font=font)


def _latest_preview_png(renders_dir: Path) -> Path | None:
    bundles = sorted(
        (p for p in renders_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for bundle in bundles:
        pngs = sorted(bundle.glob("*.png"))
        if pngs:
            return pngs[0]
    return None


def _write_knot_config(path: Path, knot_type: str) -> None:
    path.write_text(
        f"knot_type: {knot_type}\n"
        f"rendering:\n"
        f"  name: {knot_type}\n",
        encoding="utf-8",
    )


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    assets_dir = project_root / "assets"
    renders_dir = project_root / "renders"
    assets_dir.mkdir(exist_ok=True)

    knots = list_knot_types()
    failed = []

    with tempfile.TemporaryDirectory(prefix="knot_previews_") as tmp:
        tmp_dir = Path(tmp)
        for name in knots:
            out_path = assets_dir / f"{name}.png"
            config_path = tmp_dir / f"{name}.yaml"
            _write_knot_config(config_path, name)
            cmd = [
                sys.executable,
                "-m",
                "led_knots.cli",
                str(config_path),
            ]
            print(f"Generating {name} -> {out_path.relative_to(project_root)} ...")
            try:
                subprocess.run(
                    cmd,
                    cwd=project_root,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                preview_src = _latest_preview_png(renders_dir)
                if preview_src is None or not preview_src.exists():
                    print("  FAILED: no preview PNG in render bundle")
                    failed.append(name)
                    continue
                shutil.copy2(preview_src, out_path)
                print(f"  -> {out_path.name} (from {preview_src.parent.name}/)")
                with Image.open(out_path) as img:
                    img.load()
                    labeled = img.copy()
                add_label_to_preview(labeled, name)
                labeled.save(out_path)
            except subprocess.CalledProcessError as e:
                print(f"  FAILED: {e.stderr or e}")
                failed.append(name)
            except subprocess.TimeoutExpired:
                print("  TIMEOUT")
                failed.append(name)

    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        return 1

    frames = []
    for name in knots:
        png_path = assets_dir / f"{name}.png"
        if png_path.exists():
            frames.append(Image.open(png_path).convert("RGB"))
    if frames:
        gif_path = assets_dir / "previews.gif"
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=GIF_FRAME_DURATION_MS,
            loop=0,
        )
        print(
            f"\nCombined GIF: {gif_path.relative_to(project_root)} "
            f"({len(frames)} frames, {GIF_FRAME_DURATION_MS} ms each, loop)"
        )

    print(f"\nDone. Previews in {assets_dir.relative_to(project_root)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
