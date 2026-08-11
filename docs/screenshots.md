# Screenshots

Preview images for each knot type. Generate any preview with a config that sets
`knot_type`:

```bash
render-knot knot_configs/<name>.yaml
```

Or regenerate all previews (and the combined GIF) with:

```bash
uv run python scripts/generate_previews.py
```

## Table of contents

- [Rod](#rod)
- [Ring](#ring)
- [Helix](#helix)
- [Quarter turn](#quarter-turn)
- [Jog bend](#jog-bend)
- [Figure 8](#figure-8)

---

## Rod

Straight vertical pipe.

![Rod](../assets/rod.png)

```bash
render-knot knot_configs/rod.yaml
```

---

## Ring

Simple circular ring.

![Ring](../assets/ring.png)

```bash
render-knot knot_configs/ring.yaml
```

---

## Helix

Helical spiral path.

![Helix](../assets/helix.png)

```bash
render-knot knot_configs/helix.yaml
```

---

## Quarter turn

90-degree turn path.

![Quarter turn](../assets/quarter_turn.png)

```bash
render-knot knot_configs/quarter_turn.yaml
```

---

## Jog bend

2D jog bend path.

![Jog bend](../assets/jog_bend.png)

```bash
render-knot knot_configs/jog_bend.yaml
```

---

## Figure 8

The figure-eight knot (4_1), slot 4 of the 15.

![Figure 8](../assets/k4_1.png)

```bash
render-knot knot_configs/k4_1-figure-eight.yaml
```

The gallery above predates the full 15-knot set and covers only the starter
shapes. Rerun `scripts/generate_previews.py` to refresh `assets/` for every
knot type, or see [knotbook.ipynb](../knotbook.ipynb) for path previews of all
15 slots.
