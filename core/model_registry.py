from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd


BASE_REQUIRED_COLUMNS = [
    "component_id",
    "measurement_time_h",
    "leakage_current_uA",
]


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_fingerprint(df: pd.DataFrame) -> str:
    """Stable fingerprint of column names + pandas dtypes, not row contents."""
    contract = "\n".join(
        f"{column}:{df[column].dtype}"
        for column in sorted(df.columns)
    )
    return hashlib.sha256(contract.encode("utf-8")).hexdigest()


def dataset_schema_contract(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "schema_id": "SCHEMA-BURNIN-AUTO-v1",
        "fingerprint": schema_fingerprint(df),
        "columns": [
            {"name": column, "dtype": str(df[column].dtype)}
            for column in sorted(df.columns)
        ],
        "required_base_columns": list(BASE_REQUIRED_COLUMNS),
        "base_contract_satisfied": all(
            column in df.columns for column in BASE_REQUIRED_COLUMNS
        ),
    }


def _module_entry(
    *,
    module: str,
    model_id: str,
    artifact: Path,
    metadata: dict[str, Any] | None,
    required_checkpoints: list[int],
    target: str | None,
    prediction_cutoff_h: int,
    status: str = "PRODUCTION",
) -> dict[str, Any]:
    metadata = metadata or {}
    feature_columns = metadata.get("feature_columns")
    if not feature_columns:
        point_sets = metadata.get("point_feature_sets") or {}
        merged: list[str] = []
        for columns in point_sets.values():
            for name in columns or []:
                if name not in merged:
                    merged.append(name)
        feature_columns = merged

    return {
        "module": module,
        "model_id": model_id,
        "status": status,
        "artifact": str(artifact),
        "artifact_exists": artifact.exists(),
        "artifact_sha256": _sha256_file(artifact),
        "prediction_cutoff_h": prediction_cutoff_h,
        "required_checkpoints_h": required_checkpoints,
        "target": target,
        "feature_set": feature_columns or [],
        "metadata": metadata,
    }


def build_model_registry(
    pipeline_root: Path,
    pipeline_status: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Create a read-only registry view of the currently deployed SPARK models."""
    module_a_status = pipeline_status.get("module_a") or {}
    module_b_status = pipeline_status.get("module_b") or {}

    module_a_path = pipeline_root / "artifacts" / "models" / "module_a_24h.joblib"
    module_b_path = pipeline_root / "artifacts" / "models" / "module_b_24h.joblib"
    module_b_96_path = pipeline_root / "artifacts" / "models" / "module_b_96h.joblib"

    models = [
        _module_entry(
            module="A",
            model_id="MODULE-A-24H-v1",
            artifact=module_a_path,
            metadata=module_a_status.get("metadata") or {},
            required_checkpoints=[0, 24],
            target="early_dynamic_anomaly",
            prediction_cutoff_h=24,
            status="PRODUCTION" if module_a_status.get("available") else "UNAVAILABLE",
        ),
        _module_entry(
            module="B",
            model_id="MODULE-B-24H-v1",
            artifact=module_b_path,
            metadata=module_b_status.get("metadata") or {},
            required_checkpoints=[0, 24],
            target="ir_168h_uA",
            prediction_cutoff_h=24,
            status="PRODUCTION" if module_b_status.get("available") else "UNAVAILABLE",
        ),
    ]

    # Phase 8 does not invent a 96h ML model. If a future Phase-1 artifact is
    # present, surface it as a discovered candidate for controlled integration.
    if module_b_96_path.exists():
        models.append(
            _module_entry(
                module="B96",
                model_id="MODULE-B-96H-DISCOVERED",
                artifact=module_b_96_path,
                metadata={},
                required_checkpoints=[0, 24, 96],
                target="ir_168h_uA",
                prediction_cutoff_h=96,
                status="DISCOVERED_NOT_ACTIVATED",
            )
        )

    return {
        "registry_version": 1,
        "schema": dataset_schema_contract(df),
        "models": models,
        "production_models": [
            model["model_id"] for model in models if model["status"] == "PRODUCTION"
        ],
        "discovered_96h_model": module_b_96_path.exists(),
        "policy": (
            "Registry is read-only in Phase 8. New artifacts are never promoted "
            "to production automatically."
        ),
    }
