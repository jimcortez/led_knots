---
name: Knot Preview
description: >
  Run knot scripts with uv run --no-cache to generate static PNG previews via
  their CLI into the exports/ folder using unique filenames, then load those
  previews into context to visually verify knot geometry (knot type, crossings,
  strand thickness). Use when you need to preview or validate a specific knot
  (e.g., trefoil, rope, braided tube) as a static image.
---

# Knot Preview Skill

Use this skill to generate and verify static image previews for individual knots.
Each knot script is treated as a CLI that knows how to render a PNG when given
an output path.

The core workflow:

- Choose a knot script.
- Generate a unique PNG filename under `exports/`.
- Run `uv run --no-cache python <knot_script>.py --preview exports/<unique_id>.png`.
- Load that exact PNG into context and visually verify the knot.

## Quickstart

Follow this sequence whenever you need a preview for a single knot.

1. **Identify the knot script**
   - Determine the Python script that defines the knot you want to preview,
     for example:
     - `knots/trefoil.py`
     - `knots/braided_tube.py`
   - Ensure the script supports a `--preview <png_path>` CLI option that
     generates a PNG at the given path.

2. **Generate a unique preview filename in `exports/`**
   - Construct a filename based on:
     - The knot name (e.g., `trefoil`).
     - A timestamp (e.g., ISO8601 or compact yyyymmddThhmmssZ).
     - A short random or hash-like suffix.
   - Example pattern:
     - `exports/trefoil_20260313T184530Z_ab12cd.png`
   - Use this **same** string everywhere in the remaining steps.

3. **Run the CLI preview command with uv (no cache)**
   - From the repository root (or the appropriate working directory), run:

     ```bash
     uv run --no-cache python <path/to/knot_script>.py --preview exports/<unique_id>.png
     ```

   - Replace `<path/to/knot_script>.py` and `<unique_id>` with the actual
     script path and the unique filename chosen in step 2.

4. **Confirm the PNG exists**
   - After the command completes, verify that:
     - `exports/<unique_id>.png` exists.
     - The file is readable and is a valid PNG image.

5. **Load the preview into context**
   - Attach `exports/<unique_id>.png` to the current session as the preview
     for this knot.
   - Use this image for all subsequent visual reasoning and user-facing
     explanations.

## Detailed Workflow

### Step 1 – Resolve the knot script and CLI

- Determine the exact path to the knot script:
  - Examples: `knots/trefoil.py`, `knots/rope_core.py`, `knots/complex_braid.py`.
- Identify any additional CLI arguments the script expects beyond `--preview`,
  such as:
  - Parameter overrides (e.g., `--pitch 40`, `--segments 300`).
  - Different preset names (e.g., `--variant tight`).
- Treat the script as a black box:
  - The only strict requirement is that when invoked with
    `--preview <png_path>`, it writes a PNG file to `<png_path>`.

### Step 2 – Build a unique preview path under `exports/`

- Use a naming function that combines:
  - The knot identifier (e.g., `trefoil`, `tube_rope`).
  - A timestamp (e.g., `20260313T184530Z`).
  - A short random string or hash to guarantee uniqueness.
- Example:
  - `exports/tube_rope_20260313T184530Z_f93a2c.png`
- Always:
  - Ensure the `exports/` directory exists (or is created by the environment).
  - Use the full path `exports/<knot_name>_<timestamp>_<suffix>.png` exactly
    in both the command and later when loading the image.

### Step 3 – Run the preview command with uv (no cache)

- Construct the command line:

  ```bash
  uv run --no-cache python <path/to/knot_script>.py --preview exports/<unique_id>.png [other args...]
  ```

- Notes:
  - Always include `--no-cache` to avoid stale environments or cached state.
  - Keep the `--preview exports/<unique_id>.png` arguments adjacent and
    consistent with the unique filename chosen earlier.
  - Include any additional CLI flags required by the knot script after
    the `--preview` arguments.
- Execute the command using the environment’s shell/command tool and allow it
  to run to completion.

### Step 4 – Validate the generated PNG

- After the process exits:
  - Check that `exports/<unique_id>.png` now exists on disk.
  - If possible, confirm that it is a valid PNG (e.g., non-zero size and
    correct file signature).
- If the file is missing or invalid:
  - Inspect the CLI output for errors.
  - Fix any issues in the knot script or arguments.
  - Regenerate a fresh unique filename and rerun the command.

### Step 5 – Attach the preview to context

- Once the PNG is verified:
  - Load `exports/<unique_id>.png` into the current session as an image
    artifact.
  - Refer to this artifact by its filename and knot name when reasoning
    about the geometry or explaining the result.
- Avoid reusing old previews:
  - Always rely on the latest `exports/<unique_id>.png` produced in the
    current run.
  - Do not infer correctness from older PNGs with different unique IDs.

### Step 6 – Visual verification checklist

When examining the preview image, apply the following checks:

- **Topology**
  - Does the knot match the intended type (e.g., trefoil, figure-eight,
    braided tube)?
  - Are the crossings and overall structure consistent with the design goal?

- **Crossing pattern and density**
  - Are crossings evenly distributed where expected?
  - Does the visual density (tight vs. loose) match the specified parameters?

- **Strand and tube quality**
  - Is strand thickness appropriate relative to the core and overall size?
  - Are there any obvious gaps, overlaps, or self-intersections that look
    unintentional?

- **Rendering artifacts**
  - Are there jagged edges or faceting that suggest insufficient resolution?
  - Is any part of the knot clipped or missing from the frame?

If any of these checks fail:

- Adjust the knot’s parameters or implementation (e.g., pitch, number of
  segments, sampling density, strand radius).
- Repeat Steps 2–5 to generate a **new** preview with a fresh unique filename
  under `exports/`.

## Usage Notes and Extensibility

- This skill is optimized for **single-knot previews**.
  - For batches or parameter sweeps, repeat the same process for each knot,
    producing a set of unique PNGs in `exports/`.
- Keep the CLI contract stable:
  - All knots that participate in this workflow should honor the
    `--preview <png_path>` convention.
  - This allows the skill to stay generic and reusable across knots.