"""Runtime configuration, read from environment variables (and a local .env).

No secret values are ever logged or persisted by this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is optional at runtime, required by the documented setup.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - import guard only
    load_dotenv = None  # type: ignore[assignment]

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent


def _env_str(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve(path_value: str) -> Path:
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    return candidate


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of configuration.

    Instantiate via :func:`load_settings`. Tests build their own instance so
    they never depend on the developer's real environment.
    """

    data_dir: Path
    generated_dir: Path
    db_path: Path

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1

    analyzer_max_files: int = 2000
    analyzer_max_file_bytes: int = 200_000
    analyzer_max_depth: int = 8
    allow_local_paths: bool = True
    max_upload_bytes: int = 50_000_000
    max_extract_files: int = 5000

    exec_timeout_seconds: int = 120
    exec_max_output_bytes: int = 100_000
    exec_backend: str = "auto"  # auto | container | disabled
    container_image: str = "python:3.12-slim"

    cors_origins: tuple[str, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------ helpers
    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def llm_mode(self) -> str:
        """'live' when a provider key is present, otherwise 'mock'."""
        return "live" if self.llm_configured else "mock"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings(*, load_dotenv_file: bool = True) -> Settings:
    """Build a :class:`Settings` from the environment.

    Reads ``.env`` from the repository root first (if python-dotenv is
    installed) so local development works without exporting variables.
    """

    if load_dotenv_file and load_dotenv is not None:
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

    data_dir = _resolve(_env_str("AIDEVOPS_DATA_DIR", "data") or "data")
    generated_dir = _resolve(
        _env_str("AIDEVOPS_GENERATED_DIR", str(data_dir / "generated")) or ""
    )
    db_path = _resolve(
        _env_str("AIDEVOPS_DB_PATH", str(data_dir / "aidevops.db")) or ""
    )

    cors_raw = _env_str("AIDEVOPS_CORS_ORIGINS", "") or ""
    cors_origins = tuple(x.strip() for x in cors_raw.split(",") if x.strip())

    settings = Settings(
        data_dir=data_dir,
        generated_dir=generated_dir,
        db_path=db_path,
        openai_api_key=_env_str("OPENAI_API_KEY"),
        openai_base_url=_env_str("OPENAI_BASE_URL"),
        openai_model=_env_str("OPENAI_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
        llm_timeout_seconds=_env_float("AIDEVOPS_LLM_TIMEOUT_SECONDS", 30.0),
        llm_max_retries=_env_int("AIDEVOPS_LLM_MAX_RETRIES", 1),
        analyzer_max_files=_env_int("AIDEVOPS_ANALYZER_MAX_FILES", 2000),
        analyzer_max_file_bytes=_env_int("AIDEVOPS_ANALYZER_MAX_FILE_BYTES", 200_000),
        analyzer_max_depth=_env_int("AIDEVOPS_ANALYZER_MAX_DEPTH", 8),
        allow_local_paths=_env_bool("AIDEVOPS_ALLOW_LOCAL_PATHS", True),
        max_upload_bytes=_env_int("AIDEVOPS_MAX_UPLOAD_BYTES", 50_000_000),
        max_extract_files=_env_int("AIDEVOPS_MAX_EXTRACT_FILES", 5000),
        exec_timeout_seconds=_env_int("AIDEVOPS_EXEC_TIMEOUT_SECONDS", 120),
        exec_max_output_bytes=_env_int("AIDEVOPS_EXEC_MAX_OUTPUT_BYTES", 100_000),
        exec_backend=_env_str("AIDEVOPS_EXEC_BACKEND", "auto") or "auto",
        container_image=_env_str("AIDEVOPS_CONTAINER_IMAGE", "python:3.12-slim")
        or "python:3.12-slim",
        cors_origins=cors_origins,
    )
    settings.ensure_dirs()
    return settings
