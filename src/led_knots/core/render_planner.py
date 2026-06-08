"""Dependency-aware planning for render bundle export jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import (
    DEFAULT_FILENAME_TEMPLATES,
    RenderingExportJob,
    RenderingSettings,
    resolve_filename_template,
)

# Execution phases (lower runs first). Config array order is ignored.
_FORMAT_PHASE: Dict[str, int] = {
    "step": 10,
    "stl": 20,
    "3mf": 30,
    "glb": 40,
    "gltf": 50,
    "obj": 60,
    "preview": 70,
    "config": 80,
    "stats": 90,
}

# Formats that require another format's on-disk output if not already planned.
_DEPENDENCY_DEFAULTS: Dict[str, str] = {
    "preview": "glb",
    "obj": "glb",
    "gltf": "glb",
    "3mf": "stl",
}


class DuplicateExportFilenameError(ValueError):
    """Raised when two export jobs resolve to the same output path."""


@dataclass(frozen=True)
class ExportJob:
    format: str
    enabled: bool
    filename_template: str
    resolved_path: Path
    settings: Dict[str, Any]
    dependency_of: Optional[str] = None
    match_key: str = ""

    @property
    def is_dependency_only(self) -> bool:
        return not self.enabled and self.dependency_of is not None


@dataclass(frozen=True)
class RenderPlan:
    bundle_dir: Path
    bundle_stem: str
    run_name: str
    jobs: Tuple[ExportJob, ...]
    execution_order: Tuple[ExportJob, ...]
    want_viewer: bool

    @property
    def has_side_effects(self) -> bool:
        return bool(self.jobs) or self.want_viewer

    @property
    def needs_stl_tessellation(self) -> bool:
        return any(j.format in ("stl", "3mf") for j in self.jobs)

    @property
    def needs_glb_bytes(self) -> bool:
        return any(j.format in ("glb", "gltf", "obj", "preview") for j in self.jobs) or self.want_viewer

    @property
    def needs_step_export(self) -> bool:
        return any(j.format == "step" for j in self.jobs)


def _job_from_rendering_job(
    job: RenderingExportJob,
    *,
    bundle_dir: Path,
    bundle_stem: str,
    run_name: str,
    dependency_of: Optional[str] = None,
    enabled_override: Optional[bool] = None,
) -> ExportJob:
    resolved_name = resolve_filename_template(
        job.filename_template,
        bundle_stem=bundle_stem,
        run_name=run_name,
    )
    _validate_resolved_filename(resolved_name)
    return ExportJob(
        format=job.format,
        enabled=job.enabled if enabled_override is None else enabled_override,
        filename_template=job.filename_template,
        resolved_path=bundle_dir / resolved_name,
        settings=dict(job.settings),
        dependency_of=dependency_of,
        match_key=job.match_key,
    )


def _validate_resolved_filename(name: str) -> None:
    if not name or name != Path(name).name or ".." in Path(name).parts:
        raise ValueError(f"Invalid export filename after template resolution: {name!r}")


def _ensure_dependency_jobs(
    jobs: List[ExportJob],
    rendering: RenderingSettings,
    *,
    bundle_dir: Path,
    bundle_stem: str,
    run_name: str,
    project_root: Path,
) -> List[ExportJob]:
    by_path = {j.resolved_path: j for j in jobs}
    by_format_enabled = {j.format for j in jobs if j.enabled}

    def _has_format_output(fmt: str) -> bool:
        return any(j.format == fmt for j in jobs)

    added: List[ExportJob] = []
    for job in list(jobs):
        if not job.enabled:
            continue
        dep_fmt = _DEPENDENCY_DEFAULTS.get(job.format)
        if dep_fmt is None or _has_format_output(dep_fmt):
            continue
        dep_template = DEFAULT_FILENAME_TEMPLATES[dep_fmt]
        dep_job_cfg = RenderingExportJob(
            {"format": dep_fmt, "enabled": False, "filename": dep_template},
            project_root,
        )
        dep = _job_from_rendering_job(
            dep_job_cfg,
            bundle_dir=bundle_dir,
            bundle_stem=bundle_stem,
            run_name=run_name,
            dependency_of=job.filename_template,
            enabled_override=False,
        )
        if dep.resolved_path in by_path:
            continue
        added.append(dep)
        by_path[dep.resolved_path] = dep
        by_format_enabled.add(dep_fmt)
        _has_format_output(dep_fmt)  # noqa: B018 — side effect via loop

    return jobs + added


def _detect_duplicates(jobs: Sequence[ExportJob]) -> None:
    seen: Dict[Path, ExportJob] = {}
    for job in jobs:
        if job.resolved_path in seen:
            other = seen[job.resolved_path]
            raise DuplicateExportFilenameError(
                f"Duplicate export filename {job.resolved_path.name!r}: "
                f"{other.format} ({other.filename_template}) and "
                f"{job.format} ({job.filename_template})"
            )
        seen[job.resolved_path] = job


def _sort_jobs(jobs: Sequence[ExportJob]) -> Tuple[ExportJob, ...]:
    return tuple(
        sorted(
            jobs,
            key=lambda j: (_FORMAT_PHASE.get(j.format, 100), j.filename_template),
        )
    )


class RenderPlanner:
    @classmethod
    def from_config(cls, config: Any) -> RenderPlan:
        rendering: RenderingSettings = config.rendering
        bundle_stem = config.render_bundle_stem
        bundle_dir = config.render_bundle_dir
        run_name = config.run_name

        enabled = rendering.enabled_jobs()
        jobs: List[ExportJob] = [
            _job_from_rendering_job(
                j,
                bundle_dir=bundle_dir,
                bundle_stem=bundle_stem,
                run_name=run_name,
            )
            for j in enabled
        ]
        base_path = getattr(config, "config_base_path", None)
        project_root = Path(base_path).parent if base_path is not None else bundle_dir.parent
        jobs = _ensure_dependency_jobs(
            jobs,
            rendering,
            bundle_dir=bundle_dir,
            bundle_stem=bundle_stem,
            run_name=run_name,
            project_root=project_root,
        )
        _detect_duplicates(jobs)
        execution_order = _sort_jobs(jobs)
        return RenderPlan(
            bundle_dir=bundle_dir,
            bundle_stem=bundle_stem,
            run_name=run_name,
            jobs=tuple(jobs),
            execution_order=execution_order,
            want_viewer=bool(getattr(config, "viewer_enabled", False)),
        )
