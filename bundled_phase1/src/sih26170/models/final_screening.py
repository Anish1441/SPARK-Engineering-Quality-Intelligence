"""Final 168-hour screening and inspector-facing release decisions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FinalScreeningConfig:
    datasheet_limit_uA: float = 175.0
    anomaly_watch_threshold: float = 2.5
    anomaly_hold_threshold: float = 3.5
    group_shift_threshold: float = 2.5


def _require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {missing}")


def _robust_mad(values: pd.Series) -> float:
    usable = values.dropna()
    if usable.empty:
        return np.nan
    median = usable.median()
    return float((usable - median).abs().median())


def _boolean_series(values: pd.Series, name: str) -> pd.Series:
    """Read booleans safely from either memory or a CSV round trip."""

    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    normalized = values.astype("string").str.strip().str.lower()
    invalid = normalized.notna() & ~normalized.isin({"true", "false"})
    if invalid.any():
        raise ValueError(f"{name} contains invalid Boolean values.")
    return normalized.eq("true").fillna(False)


def build_final_screening(
    decisions: pd.DataFrame,
    features: pd.DataFrame,
    *,
    config: FinalScreeningConfig | None = None,
) -> pd.DataFrame:
    """Resolve final release decisions without accessing truth labels."""

    config = config or FinalScreeningConfig()
    _require_columns(
        decisions,
        {
            "component_id",
            "dataset_split",
            "decision_at_24h",
            "decision_at_96h",
        },
        "Combined decisions",
    )
    _require_columns(
        features,
        {
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "dataset_split",
            "ir_168h_uA",
            "target_168h_available",
            "robust_z_168h",
            "historical_robust_z_168h",
            "updated_slope_96_168_uA_per_h",
        },
        "Feature table",
    )
    if decisions["component_id"].duplicated().any():
        raise ValueError("Combined decisions contain duplicate component IDs.")
    if features["component_id"].duplicated().any():
        raise ValueError("Feature table contains duplicate component IDs.")

    feature_columns = [
        "component_id",
        "lot_id",
        "burnin_batch_id",
        "dataset_split",
        "ir_168h_uA",
        "target_168h_available",
        "robust_z_168h",
        "historical_robust_z_168h",
        "updated_slope_96_168_uA_per_h",
    ]
    result = decisions.merge(
        features[feature_columns],
        on=["component_id", "dataset_split"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_feature"),
    )

    result["lot_median_final_slope"] = result.groupby("lot_id")[
        "updated_slope_96_168_uA_per_h"
    ].transform("median")
    result["lot_mad_final_slope"] = result.groupby("lot_id")[
        "updated_slope_96_168_uA_per_h"
    ].transform(_robust_mad)
    result["robust_z_final_slope"] = (
        0.6745
        * (
            result["updated_slope_96_168_uA_per_h"]
            - result["lot_median_final_slope"]
        )
        / result["lot_mad_final_slope"].replace(0.0, np.nan)
    )

    train_slopes = result.loc[
        result["dataset_split"].eq("train"),
        "updated_slope_96_168_uA_per_h",
    ].dropna()
    historical_slope_median = float(train_slopes.median())
    historical_slope_mad = _robust_mad(train_slopes)
    if not np.isfinite(historical_slope_mad) or historical_slope_mad <= 0:
        raise ValueError("Historical final-slope MAD is invalid.")

    result["batch_median_final_slope"] = result.groupby("burnin_batch_id")[
        "updated_slope_96_168_uA_per_h"
    ].transform("median")
    result["batch_final_shift_score"] = (
        0.6745
        * (
            result["batch_median_final_slope"] - historical_slope_median
        ).clip(lower=0.0)
        / historical_slope_mad
    ).fillna(0.0)
    result["final_component_anomaly_score"] = result[
        [
            "robust_z_168h",
            "historical_robust_z_168h",
            "robust_z_final_slope",
        ]
    ].clip(lower=0.0).max(axis=1, skipna=True).fillna(0.0)

    measurement_available = (
        _boolean_series(
            result["target_168h_available"],
            "target_168h_available",
        )
        & result["ir_168h_uA"].notna()
    )
    static_failure = result["ir_168h_uA"].gt(config.datasheet_limit_uA)
    prior_reject = result["decision_at_96h"].eq("REJECT_EARLY")
    prior_quarantine = result["decision_at_96h"].eq(
        "QUARANTINE_LOT_BATCH"
    )
    prior_hold = result["decision_at_96h"].isin(
        {"HOLD_FOR_REVIEW", "RETEST"}
    )
    group_shift = result["batch_final_shift_score"].ge(
        config.group_shift_threshold
    )
    high_anomaly = result["final_component_anomaly_score"].ge(
        config.anomaly_hold_threshold
    )
    moderate_anomaly = result["final_component_anomaly_score"].ge(
        config.anomaly_watch_threshold
    )

    conditions = [
        prior_reject,
        prior_quarantine,
        ~measurement_available,
        static_failure,
        group_shift,
        high_anomaly | moderate_anomaly | prior_hold,
    ]
    result["final_decision"] = np.select(
        conditions,
        [
            "REJECT_FINAL",
            "QUARANTINE_LOT_BATCH",
            "RETEST",
            "REJECT_FINAL",
            "QUARANTINE_LOT_BATCH",
            "HOLD_FOR_REVIEW",
        ],
        default="ACCEPT_FINAL",
    )
    result["final_decision_reason"] = np.select(
        conditions,
        [
            "Component was rejected at an earlier checkpoint.",
            "Burn-in batch remains quarantined for collective drift.",
            "The 168-hour measurement is missing or unusable.",
            "Measured 168-hour leakage exceeds the datasheet limit.",
            "The burn-in batch has an abnormal final drift shift.",
            "Final anomaly or earlier hold requires inspector review.",
        ],
        default="All checkpoints passed; final release is permitted.",
    )
    result["release_permitted"] = result["final_decision"].eq("ACCEPT_FINAL")
    result["qa_inspector_summary"] = result.apply(
        lambda row: (
            f"{row['component_id']}: {row['final_decision']}. "
            f"IR@168h={row['ir_168h_uA']:.3f} uA; "
            f"limit={config.datasheet_limit_uA:.1f} uA; "
            f"anomaly_score={row['final_component_anomaly_score']:.3f}. "
            f"{row['final_decision_reason']}"
        ),
        axis=1,
    )
    return result
