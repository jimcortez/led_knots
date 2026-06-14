# AGENTS

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: `npx openskills read <skill-name>` (run in your shell)
  - For multiple: `npx openskills read skill-one,skill-two`
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>brainstorming</name>
<description>"You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."</description>
<location>global</location>
</skill>

<skill>
<name>systematic-debugging</name>
<description>Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes</description>
<location>global</location>
</skill>

<skill>
<name>using-git-worktrees</name>
<description>Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification</description>
<location>global</location>
</skill>

<skill>
<name>using-superpowers</name>
<description>Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions</description>
<location>global</location>
</skill>

<skill>
<name>verification-before-completion</name>
<description>Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always</description>
<location>global</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>

## Patterns to avoid

Geometry and export code should use one correct method and fail loudly when it
does not work. Silent fallbacks hide bugs that need fixing and produce renders
that look successful while missing strands, studs, holes, or mesh pieces.

### Silent geometry fallbacks

Do not chain alternate CadQuery/OCC operations when the primary build step fails.
Examples we have removed or must not reintroduce:

- Loft fails → retry with `ruled=True` → fall back to spline sweep (`braided_rope.py`)
- Fillet fails → retry with a smaller radius → return unfilleted solid
- `GCPnts_UniformAbscissa` fails → sample uniform parameter `t` instead
- Mesh decimation fails → export the undecimated mesh anyway
- Preview concatenate fails → fall back to per-mesh conversion and skip bad pieces (`preview.py`)

Prefer a single path and let the underlying exception propagate (or re-raise with
a short contextual message). If two methods are genuinely equivalent, pick one;
do not try both at runtime.

**Exception:** an intentional multi-step fallback is only OK when every step must
succeed and the last step still raises if all attempts fail. Partial success
after exhausting fallbacks is not OK.

### Degraded success

Do not log a warning and continue with worse or partial geometry. A warning that
still returns a solid looks like success to callers and to render logs. Either
succeed with the intended geometry or raise.

Concrete anti-patterns from this repo:

| Pattern | Why it is bad |
|--------|----------------|
| Skip failed braid strands and build `N-1`/`N` (`if strand is not None`) | Braid looks sparse; log says “built 48/50” |
| Embed clip drops zero-volume strands and logs “removed X/Y strands” | Missing weave with no hard failure |
| Return base tube when pyramid rows do not fit the path | Studded tube renders without studs |
| Fuse leaves multiple lumps but exports anyway (`fuse_utils.py`) | STL looks like one file; geometry is disconnected |
| Skip drain-hole cuts per cavity and return the unmodified part | Resin cavities stay sealed |
| Skip GLB/pyrender mesh pieces and still write a preview PNG | Image hides missing geometry |

### Sentinel returns on failure

Do not catch exceptions and return a default that looks valid:

- `None, "failed"` from a strand builder instead of raising
- Empty or zero bounds instead of failing bbox computation
- `False` from an analyzer when the ray cast threw
- Skipping a configured step (decimation, fillet, clip) without failing the run
- `return part, []` when drilling was requested but every cut failed

If the operation is required for correctness, raise. If it is optional and
documented as best-effort (e.g. some optimize diagnostics), say so explicitly in
the API and report — do not pretend the full pipeline ran.

### Count and completeness checks

When building a fixed set of repeated features (strands, pyramids, studs, holes),
assert the final count matches the expected total. Do not infer success from
“at least one succeeded.”

```python
# Bad
if strand is not None:
    strands.append(strand)

# Good
strands.append(strand)  # builder raises on failure
if len(strands) != total_strands:
    raise RuntimeError(...)
```

### When soft-fail is acceptable

Best-effort analysis or optional diagnostics may log and continue only when the
caller clearly treats the result as partial (e.g. optimization report fields
left empty with a `note`). Do not use that pattern in:

- Tube models (`src/led_knots/core/tube_models/`)
- Path framing and sweep construction
- Boolean fuse (`fuse_utils.py`)
- Preview PNG generation (`preview.py`)
- Drain-hole drilling (`optimize/drain_holes.py`)
- Any export path that defines the printed part

When adding new geometry code, search for `logger.warning`, bare `except`,
`continue` in loops over features, and `return None` on failure — these often
mark the patterns above.
