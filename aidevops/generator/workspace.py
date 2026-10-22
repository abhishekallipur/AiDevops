"""Isolated workspace handling for generated artifacts.

Generated files always live under ``<generated_dir>/<job_id>/`` and are written
with a path guard so a malicious plan cannot escape the workspace. Source
repositories are never modified.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import UnsafeInputError


def job_workspace(generated_dir: Path, job_id: str) -> Path:
    workspace = (Path(generated_dir) / job_id).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _safe_join(workspace: Path, rel_path: str) -> Path:
    rel = rel_path.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts or Path(rel).is_absolute():
        raise UnsafeInputError(f"artifact path escapes workspace: {rel_path}")
    target = (workspace / rel).resolve()
    if workspace != target and workspace not in target.parents:
        raise UnsafeInputError(f"artifact path escapes workspace: {rel_path}")
    return target


def write_artifact(workspace: Path, rel_path: str, content: str) -> Path:
    target = _safe_join(workspace, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def render_preview(artifacts, *, max_chars: int = 4000) -> str:
    """Human-readable preview of generated files, shown before acceptance."""

    blocks = []
    for art in artifacts:
        body = art.content
        if len(body) > max_chars:
            body = body[:max_chars] + "\n… (truncated)"
        blocks.append(f"### {art.path} ({art.kind})\n```\n{body}\n```")
    return "\n\n".join(blocks)
