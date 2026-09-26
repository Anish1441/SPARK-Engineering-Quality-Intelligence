from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


SUPPORTED = "SUPPORTED"
CAUTION = "SUPPORTED_WITH_CAUTION"
OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
MODEL_NOT_APPLICABLE = "MODEL_NOT_APPLICABLE"


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _checkpoint_value(rows: pd.DataFrame, hour: int) -> float | None:
    matches = rows[pd.to_numeric(rows["measurement_time_h"], errors="coerce") == hour]
    if matches.empty:
        return None
    values = pd.to_numeric(matches["leakage_current_uA"], errors="coerce")
    values = values[np.isfinite(values)]
    if values.empty:
        return None
    return float(values.iloc[-1])


def _reference_stats(reference_df: pd.DataFrame | None, hour: int) -> tuple[float, float] | None:
    if reference_df is None or reference_df.empty:
        return None
    if not {"measurement_time_h", "leakage_current_uA"}.issubset(reference_df.columns):
        return None
    rows = reference_df[
        pd.to_numeric(reference_df["measurement_time_h"], errors="coerce") == hour
    ]
    values = pd.to_numeric(rows["leakage_current_uA"], errors="coerce")
    values = values[np.isfinite(values)]
    if len(values) < 20:
        return None
    median = float(values.median())
    mad = float((values - median).abs().median())
    return median, max(mad, 1e-9)


def assess_model_applicability(
    df: pd.DataFrame,
    raw_index: int,
    *,
    reference_df: pd.DataFrame | None = None,
    required_columns: list[str] | None = None,
    required_checkpoints: tuple[int, ...] = (0, 24),
) -> dict[str, Any]:
    """Fail-closed contract + robust population applicability gate.

    OOD is deliberately a robust statistical screen, not a learned OOD model.
    It only uses information available through the requested checkpoints.
    """
    required_columns = required_columns or [
        "component_id",
        "measurement_time_h",
        "leakage_current_uA",
    ]
    missing_columns = [c for c in required_columns if c not in df.columns]
    if missing_columns:
        return {
            "available": True,
            "status": SCHEMA_INCOMPATIBLE,
            "applicable": False,
            "reason": "Required model-contract column(s) are missing: " + ", ".join(missing_columns),
            "missing_columns": missing_columns,
            "required_checkpoints_h": list(required_checkpoints),
        }

    if raw_index < 0 or raw_index >= len(df):
        raise IndexError("Record index is out of range.")

    component_id = df.iloc[raw_index].get("component_id")
    rows = df[df["component_id"].astype(str) == str(component_id)].copy()
    checkpoint_values = {
        int(hour): _checkpoint_value(rows, int(hour)) for hour in required_checkpoints
    }
    missing_checkpoints = [hour for hour, value in checkpoint_values.items() if value is None]
    if missing_checkpoints:
        return {
            "available": True,
            "component_id": component_id,
            "status": INSUFFICIENT_EVIDENCE,
            "applicable": False,
            "reason": "Required checkpoint evidence is unavailable: " + ", ".join(f"{h}h" for h in missing_checkpoints),
            "required_checkpoints_h": list(required_checkpoints),
            "checkpoint_values_uA": checkpoint_values,
            "population_similarity": "NOT_EVALUATED",
        }

    robust_distances: dict[str, float] = {}
    for hour, value in checkpoint_values.items():
        stats = _reference_stats(reference_df, hour)
        if stats is None or value is None:
            continue
        median, mad = stats
        # 1.4826*MAD approximates sigma under normality, while remaining robust.
        robust_z = abs(value - median) / (1.4826 * mad)
        robust_distances[f"{hour}h"] = round(float(robust_z), 4)

    max_distance = max(robust_distances.values(), default=None)
    if max_distance is None:
        status = CAUTION
        applicable = True
        similarity = "REFERENCE_UNAVAILABLE"
        reason = (
            "Schema and checkpoints satisfy the model contract, but a training-reference "
            "population was unavailable for OOD screening."
        )
    elif max_distance >= 6.0:
        status = OUT_OF_DOMAIN
        applicable = False
        similarity = "OUT_OF_DOMAIN"
        reason = (
            f"Early evidence is {max_distance:.2f} robust-sigma from the training reference; "
            "prediction should abstain pending engineering review."
        )
    elif max_distance >= 4.0:
        status = CAUTION
        applicable = True
        similarity = "DISTANT"
        reason = (
            f"Early evidence is {max_distance:.2f} robust-sigma from the training reference; "
            "prediction is allowed with caution."
        )
    else:
        status = SUPPORTED
        applicable = True
        similarity = "IN_DOMAIN"
        reason = "Schema, checkpoints, and robust population similarity support model use."

    return {
        "available": True,
        "component_id": component_id,
        "status": status,
        "applicable": applicable,
        "reason": reason,
        "required_checkpoints_h": list(required_checkpoints),
        "checkpoint_values_uA": checkpoint_values,
        "population_similarity": similarity,
        "robust_distance_by_checkpoint": robust_distances,
        "max_robust_distance": max_distance,
        "thresholds": {"caution": 4.0, "abstain": 6.0},
        "method": "ROBUST_MAD_REFERENCE_SCREEN",
        "uses_future_measurements": False,
    }


def applicability_summary(
    df: pd.DataFrame,
    *,
    reference_df: pd.DataFrame | None = None,
    max_components: int = 500,
) -> dict[str, Any]:
    """Summarize applicability on a deterministic component sample."""
    if "component_id" not in df.columns:
        return {
            "available": False,
            "status": SCHEMA_INCOMPATIBLE,
            "evaluated_components": 0,
            "counts": {SCHEMA_INCOMPATIBLE: 1},
        }
    components = df["component_id"].dropna().astype(str).drop_duplicates().tolist()
    selected = components[:max_components]
    counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    for component_id in selected:
        matches = df.index[df["component_id"].astype(str) == component_id]
        if len(matches) == 0:
            continue
        result = assess_model_applicability(
            df,
            int(matches[0]),
            reference_df=reference_df,
        )
        status = str(result.get("status") or MODEL_NOT_APPLICABLE)
        counts[status] = counts.get(status, 0) + 1
        if status != SUPPORTED and len(examples) < 10:
            examples.append(
                {
                    "component_id": component_id,
                    "status": status,
                    "reason": result.get("reason"),
                    "max_robust_distance": result.get("max_robust_distance"),
                }
            )
    blocked = sum(counts.get(x, 0) for x in (OUT_OF_DOMAIN, SCHEMA_INCOMPATIBLE, INSUFFICIENT_EVIDENCE, MODEL_NOT_APPLICABLE))
    caution = counts.get(CAUTION, 0)
    overall = "BLOCKED_PRESENT" if blocked else "CAUTION" if caution else "SUPPORTED"
    return {
        "available": True,
        "status": overall,
        "evaluated_components": len(selected),
        "total_components": len(components),
        "sample_limited": len(components) > len(selected),
        "counts": counts,
        "examples": examples,
    }
