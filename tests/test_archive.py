import io
import zipfile
from pathlib import Path

import pytest

from aidevops.analyzer import extract_archive
from aidevops.errors import UnsafeInputError


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_zip_slip_is_rejected(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../../evil.txt": "pwned"}))

    with pytest.raises(UnsafeInputError):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_absolute_path_member_is_rejected(tmp_path: Path):
    archive = tmp_path / "abs.zip"
    archive.write_bytes(_zip_bytes({"/etc/evil": "x"}))
    with pytest.raises(UnsafeInputError):
        extract_archive(archive, tmp_path / "out")


def test_symlink_member_is_rejected(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)  # symlink mode
        zf.writestr(info, "/etc/passwd")
    archive = tmp_path / "link.zip"
    archive.write_bytes(buf.getvalue())

    with pytest.raises(UnsafeInputError):
        extract_archive(archive, tmp_path / "out")


def test_valid_archive_extracts_and_finds_project_root(tmp_path: Path):
    archive = tmp_path / "good.zip"
    archive.write_bytes(_zip_bytes({"myapp/requirements.txt": "fastapi\n", "myapp/app.py": "print(1)\n"}))

    root = extract_archive(archive, tmp_path / "out")
    assert root.name == "myapp"
    assert (root / "requirements.txt").exists()


def test_too_many_files_rejected(tmp_path: Path):
    archive = tmp_path / "many.zip"
    archive.write_bytes(_zip_bytes({f"f{i}.txt": "x" for i in range(10)}))
    with pytest.raises(UnsafeInputError):
        extract_archive(archive, tmp_path / "out", max_files=5)
