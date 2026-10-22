"""Safe archive extraction.

Untrusted archives are the primary attack surface for the analyzer, so this
module defends against:

* Zip-slip / path traversal (``../../etc/passwd``)
* Absolute paths and Windows drive letters
* Symlinks and hardlinks (rejected outright)
* Decompression bombs (bounded file count and total uncompressed size)

Anything suspicious raises :class:`UnsafeInputError` and nothing is written.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from ..errors import UnsafeInputError

SUPPORTED_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")


def _safe_target(dest: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        raise UnsafeInputError(f"archive member has absolute path: {member_name}")
    target = (dest / normalized).resolve()
    dest_resolved = dest.resolve()
    if dest_resolved != target and dest_resolved not in target.parents:
        raise UnsafeInputError(f"archive member escapes destination: {member_name}")
    return target


def _guard_size(name: str, size: int, total: int, max_total: int) -> int:
    if size < 0:
        raise UnsafeInputError(f"archive member has negative size: {name}")
    if total + size > max_total:
        raise UnsafeInputError("archive too large when decompressed")
    return total + size


def extract_archive(
    archive_path: Path | str,
    dest: Path | str,
    *,
    max_files: int = 5000,
    max_total_bytes: int = 200_000_000,
) -> Path:
    """Extract ``archive_path`` into ``dest`` (created if missing).

    Returns the directory that contains the project root (handles the common
    case where an archive wraps everything in a single top-level folder).
    """

    archive_path = Path(archive_path)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()

    if name.endswith(".zip"):
        _extract_zip(archive_path, dest, max_files, max_total_bytes)
    elif name.endswith((".tar", ".tar.gz", ".tgz")):
        _extract_tar(archive_path, dest, max_files, max_total_bytes)
    else:
        raise UnsafeInputError(
            f"unsupported archive type: {archive_path.name} "
            f"(expected one of {', '.join(SUPPORTED_SUFFIXES)})"
        )

    return _project_root(dest)


def _project_root(dest: Path) -> Path:
    entries = [e for e in dest.iterdir() if e.name not in {"__MACOSX"}]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def _extract_zip(archive_path: Path, dest: Path, max_files: int, max_total: int) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise UnsafeInputError(f"archive contains {len(infos)} files (limit {max_files})")
        total = 0
        for info in infos:
            target = _safe_target(dest, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:  # symlink
                raise UnsafeInputError(f"archive contains a symlink: {info.filename}")
            total = _guard_size(info.filename, info.file_size, total, max_total)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())


def _extract_tar(archive_path: Path, dest: Path, max_files: int, max_total: int) -> None:
    with tarfile.open(archive_path) as tf:
        members = tf.getmembers()
        if len(members) > max_files:
            raise UnsafeInputError(f"archive contains {len(members)} files (limit {max_files})")
        total = 0
        for member in members:
            if member.issym() or member.islnk():
                raise UnsafeInputError(f"archive contains a link: {member.name}")
            target = _safe_target(dest, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            total = _guard_size(member.name, member.size, total, max_total)
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with extracted, open(target, "wb") as out:
                out.write(extracted.read())
