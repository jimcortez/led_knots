#!/usr/bin/env python3
"""
Generate preview images for all knot types.

Runs each knot module with --preview and saves PNGs into the project's assets/
directory. Use for README or GitHub project visuals.

Usage:
    uv run python scripts/generate_previews.py
    # or from project root:
    python scripts/generate_previews.py
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Knot module names (must be runnable as python -m led_knots.knots.<name>)
KNOTS = [
    "rod",
    "twisted_rod",
    "quarter_turn",
    "ring",
    "jog_bend",
    "jog_bend_3d",
    "helix",
    "figure_8",
    # "sine_wave",
    "trefoil",
    "k4_1",
    "stevedore",
]

# Duration per frame in the combined GIF (milliseconds)
GIF_FRAME_DURATION_MS = 2000  # 2 seconds

# Text overlay for knot name
LABEL_FONT_SIZE = 24
LABEL_PADDING = 12
LABEL_TEXT_COLOR = (255, 255, 255)


def _knot_display_name(name: str) -> str:
    """Convert knot module name to display label (e.g. 'quarter_turn' -> 'Quarter turn')."""
    return name.replace("_", " ").title()


def _get_label_font(size: int = LABEL_FONT_SIZE) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font for the label; prefer system font, fall back to default."""
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
    """Draw the knot type name as a text overlay (bottom-left). Modifies image in place."""
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


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    assets_dir = project_root / "assets"
    assets_dir.mkdir(exist_ok=True)

    python = sys.executable
    failed = []

    for name in KNOTS:
        out_path = assets_dir / f"{name}.png"
        cmd = [
            python,
            "-m",
            f"led_knots.knots.{name}",
            "--preview",
            str(out_path),
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
            if not out_path.exists():
                print(f"  FAILED: no output file (preview may have been skipped)")
                failed.append(name)
            else:
                print(f"  -> {out_path.name}")
                with Image.open(out_path) as img:
                    img.load()
                    labeled = img.copy()
                add_label_to_preview(labeled, name)
                labeled.save(out_path)
        except subprocess.CalledProcessError as e:
            print(f"  FAILED: {e.stderr or e}")
            failed.append(name)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT")
            failed.append(name)

    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        return 1

    # Combine all knot previews into a single looping GIF (KNOTS order)
    frames = []
    for name in KNOTS:
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
        print(f"\nCombined GIF: {gif_path.relative_to(project_root)} ({len(frames)} frames, {GIF_FRAME_DURATION_MS} ms each, loop)")

    print(f"\nDone. Previews in {assets_dir.relative_to(project_root)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
