"""Module A: explainable 24-hour dynamic anomaly detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from sih26170.config import Settings, settings
from sih26170.features import MODULE_A_24H_FEATURES, robust_mad


@dataclass(frozen=True)
class ModuleAConfig:
    """Conservative defaults that are tuned only on validation lots."""

    robust_z_watch_threshold: float = 2.5
    robust_z_hold_threshold: float = 3.5
    group_shift_watch_threshold: float = 2.5
    group_shift_hold_threshold: float = 3.5
    isolation_contamination: float = 0.03
    random_state: int = 42


@dataclass
class ModuleAModel:
    """Fitted unsupervised model and training-only historical baselines."""

    pipeline: Pipeline
    feature_columns: list[str]
    historical_slope_median: float
    historical_slope_mad: float
    config: ModuleAConfig


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing Module A columns: {missing}")


def _positive_max(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Return the largest positive deviation across the requested signals."""

    return frame[columns].clip(lower=0).max(axis=1, skipna=True).fillna(0.0)


def fit_module_a(
    features: pd.DataFrame,
    *,
    config: ModuleAConfig | None = None,
) -> ModuleAModel:
    """
    Fit Module A using training lots and information available through 24 hours.

    Truth labels and the 96-hour/168-hour measurements are never used.
    """

    config = config or ModuleAConfig()
    required = MODULE_A_24H_FEATURES + [
        "dataset_split",
        "usable_for_module_a_at_24h",
        "slope_0_24_uA_per_h",
    ]
    _require_columns(features, required)

    train = features.loc[
        (features["dataset_split"] == "train")
        & features["usable_for_module_a_at_24h"].astype(bool)
    ].copy()
    if train.empty:
        raise ValueError("No usable training components available for Module A.")

    training_slopes = train["slope_0_24_uA_per_h"].dropna()
    slope_median = float(training_slopes.median())
    slope_mad = robust_mad(training_slopes)
    if not np.isfinite(slope_mad) or slope_mad <= 0:
        raise ValueError("Training slope MAD is invalid for Module A.")

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "isolation_forest",
                IsolationForest(
                    n_estimators=300,
                    contamination=config.isolation_contamination,
                    random_state=config.random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(train[MODULE_A_24H_FEATURES])

    return ModuleAModel(
        pipeline=pipeline,
        feature_columns=list(MODULE_A_24H_FEATURES),
        historical_slope_median=slope_median,
        historical_slope_mad=float(slope_mad),
        config=config,
    )


def score_module_a(
    features: pd.DataFrame,
    model: ModuleAModel,
    *,
    domain: Settings = settings,
) -> pd.DataFrame:
    """Generate anomaly signals, preliminary actions and QA-ready reasons."""

    required = model.feature_columns + [
        "component_id",
        "lot_id",
        "burnin_batch_id",
        "dataset_split",
        "ir_0h_uA",
        "ir_24h_uA",
        "slope_0_24_uA_per_h",
        "robust_z_0h",
        "robust_z_24h",
        "robust_z_slope_0_24",
        "historical_robust_z_0h",
        "historical_robust_z_24h",
        "lot_shift_score_at_24h",
        "usable_for_module_a_at_24h",
    ]
    _require_columns(features, required)
    result = features.copy()

    usable = result["usable_for_module_a_at_24h"].astype(bool)
    result["isolation_forest_raw_score"] = np.nan
    result["isolation_forest_is_outlier"] = False
    if usable.any():
        usable_features = result.loc[usable, model.feature_columns]
        result.loc[usable, "isolation_forest_raw_score"] = (
            -model.pipeline.decision_function(usable_features)
        )
        result.loc[usable, "isolation_forest_is_outlier"] = (
            model.pipeline.predict(usable_features) == -1
        )

    result["within_lot_risk_score"] = _positive_max(
        result,
        ["robust_z_0h", "robust_z_24h", "robust_z_slope_0_24"],
    )
    result["historical_risk_score"] = _positive_max(
        result,
        ["historical_robust_z_0h", "historical_robust_z_24h"],
    )
    result["lot_shift_risk_score"] = result[
        "lot_shift_score_at_24h"
    ].fillna(0.0)

    result["batch_median_slope_0_24"] = result.groupby("burnin_batch_id")[
        "slope_0_24_uA_per_h"
    ].transform("median")
    positive_batch_shift = (
        result["batch_median_slope_0_24"] - model.historical_slope_median
    ).clip(lower=0.0)
    result["batch_slope_shift_score"] = (
        0.6745 * positive_batch_shift / model.historical_slope_mad
    ).fillna(0.0)

    result["static_limit_failed_at_24h"] = (
        result["ir_0h_uA"].gt(domain.datasheet_upper_limit_uA)
        | result["ir_24h_uA"].gt(domain.datasheet_upper_limit_uA)
    )

    result["module_a_action"] = "ACCEPT"
    result.loc[~usable, "module_a_action"] = "RETEST"
    result.loc[
        usable & result["static_limit_failed_at_24h"],
        "module_a_action",
    ] = "REJECT"

    hold_mask = (
        usable
        & ~result["static_limit_failed_at_24h"]
        & (
            result["within_lot_risk_score"].ge(
                model.config.robust_z_hold_threshold
            )
            | result["historical_risk_score"].ge(
                model.config.robust_z_hold_threshold
            )
            | result["batch_slope_shift_score"].ge(
                model.config.group_shift_hold_threshold
            )
            | result["isolation_forest_is_outlier"]
        )
    )
    result.loc[hold_mask, "module_a_action"] = "HOLD_FOR_REVIEW"

    watch_mask = (
        usable
        & ~result["static_limit_failed_at_24h"]
        & ~hold_mask
        & (
            result["within_lot_risk_score"].ge(
                model.config.robust_z_watch_threshold
            )
            | result["historical_risk_score"].ge(
                model.config.robust_z_watch_threshold
            )
            | result["lot_shift_risk_score"].ge(
                model.config.group_shift_watch_threshold
            )
            | result["batch_slope_shift_score"].ge(
                model.config.group_shift_watch_threshold
            )
        )
    )
    result.loc[watch_mask, "module_a_action"] = "WATCH"

    result["module_a_primary_reason"] = np.select(
        [
            ~usable,
            result["static_limit_failed_at_24h"],
            result["batch_slope_shift_score"].ge(
                model.config.group_shift_watch_threshold
            ),
            result["within_lot_risk_score"].ge(
                model.config.robust_z_hold_threshold
            ),
            result["historical_risk_score"].ge(
                model.config.robust_z_hold_threshold
            ),
            result["isolation_forest_is_outlier"],
            result["lot_shift_risk_score"].ge(
                model.config.group_shift_watch_threshold
            ),
        ],
        [
            "Missing or unusable 0h/24h measurement; retest required.",
            "Leakage current exceeded the 175 uA datasheet maximum.",
            "Burn-in batch has an abnormal early leakage-drift slope.",
            "Component is an extreme outlier within its own lot.",
            "Component is far above the historical healthy-lot baseline.",
            "Isolation Forest detected an unusual early-life pattern.",
            "The complete lot has shifted from its historical baseline.",
        ],
        default="No significant 24-hour anomaly detected.",
    )

    return result[
        [
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "dataset_split",
            "ir_0h_uA",
            "ir_24h_uA",
            "within_lot_risk_score",
            "historical_risk_score",
            "lot_shift_risk_score",
            "batch_median_slope_0_24",
            "batch_slope_shift_score",
            "isolation_forest_raw_score",
            "isolation_forest_is_outlier",
            "static_limit_failed_at_24h",
            "module_a_action",
            "module_a_primary_reason",
        ]
    ].copy()


def model_metadata(model: ModuleAModel) -> dict[str, Any]:
    """Return serialisable information for model governance and auditing."""

    return {
        "module": "A",
        "algorithm": (
            "Lot MAD + historical baseline + batch slope + Isolation Forest"
        ),
        "feature_columns": model.feature_columns,
        "historical_slope_median": model.historical_slope_median,
        "historical_slope_mad": model.historical_slope_mad,
        "configuration": asdict(model.config),
        "time_cutoff_h": 24,
        "uses_ground_truth_labels": False,
    }
