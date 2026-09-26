from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
QA_DIR = DATA_DIR / "qa"
SAMPLE_DIR = BASE_DIR / "samples"


def _normalized(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _pipeline_candidates() -> list[Path]:
    """Return known SPARK Phase-1 locations without hardcoding a username."""
    home = Path.home()
    candidates: list[Path] = []

    configured = os.environ.get("SPARK_PIPELINE_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured))

    candidates.extend(
        [
            BASE_DIR.parent / "SPARK_PHASE1",
            home / "Desktop" / "SPARK_PHASE1",
            home / "Downloads" / "SPARK_PHASE1",
            home
            / "Downloads"
            / "SIH26170_Prototype_Phase1"
            / "sih26170_prototype",
            home / "OneDrive" / "Desktop" / "SPARK_PHASE1",
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = _normalized(candidate)
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _looks_like_pipeline_root(path: Path) -> bool:
    return (
        (path / "src" / "sih26170").exists()
        and (path / "artifacts" / "models" / "module_b_24h.joblib").exists()
        and (
            path
            / "data"
            / "processed"
            / "02_clean_measurements_long.csv"
        ).exists()
    )


def resolve_pipeline_root() -> Path:
    """
    Resolve the original SPARK Phase-1 project.

    If SPARK_PIPELINE_ROOT is explicitly set, that value always wins so a bad
    configuration is visible instead of silently falling back elsewhere.
    Otherwise common historical locations are auto-detected.
    """
    configured = os.environ.get("SPARK_PIPELINE_ROOT", "").strip()
    if configured:
        return _normalized(Path(configured))

    candidates = _pipeline_candidates()
    for candidate in candidates:
        if _looks_like_pipeline_root(candidate):
            return candidate

    # Stable fallback used only for status/error reporting when no candidate
    # exists. The application still starts and fails closed for ML inference.
    return _normalized(BASE_DIR.parent / "SPARK_PHASE1")


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    qa_dir: Path
    sample_dir: Path
    pipeline_root: Path
    host: str
    port: int


def load_settings() -> Settings:
    host = os.environ.get("SPARK_HOST", "127.0.0.1").strip() or "127.0.0.1"

    try:
        port = int(os.environ.get("SPARK_PORT", "5000"))
    except ValueError as exc:
        raise ValueError("SPARK_PORT must be an integer.") from exc

    if not (1 <= port <= 65535):
        raise ValueError("SPARK_PORT must be between 1 and 65535.")

    return Settings(
        base_dir=BASE_DIR,
        data_dir=DATA_DIR,
        qa_dir=QA_DIR,
        sample_dir=SAMPLE_DIR,
        pipeline_root=resolve_pipeline_root(),
        host=host,
        port=port,
    )
