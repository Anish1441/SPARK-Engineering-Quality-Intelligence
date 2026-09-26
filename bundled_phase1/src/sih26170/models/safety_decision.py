"""Combined fail-safe decisions for Module A and both Module B checkpoints."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SafetyDecisionConfig:
    """Documented prototype limits; guardband is validation-tunable."""

    datasheet_limit_uA: float = 175.0
    guardband_uA: float = 15.0
    group_shift_threshold: float = 2.5

    @property
    def guardband_limit_uA(self) -> float:
        return self.datasheet_limit_uA - self.guardband_uA


def _require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {missing}")


def _validate_unique(frame: pd.DataFrame, name: str) -> None:
    if frame["component_id"].duplicated().any():
        raise ValueError(f"{name} contains duplicate component_id values.")


def build_safety_decisions(
    module_a: pd.DataFrame,
    prediction_24h: pd.DataFrame,
    prediction_96h: pd.DataFrame,
    *,
    config: SafetyDecisionConfig | None = None,
) -> pd.DataFrame:
    """Build provisional 24-hour and updated 96-hour screening decisions."""

    config = config or SafetyDecisionConfig()
    _require_columns(
        module_a,
        {
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "dataset_split",
            "ir_0h_uA",
            "ir_24h_uA",
            "batch_slope_shift_score",
            "static_limit_failed_at_24h",
            "module_a_action",
            "module_a_primary_reason",
        },
        "Module A report",
    )
    prediction_columns = {
        "component_id",
        "module_b_prediction_available",
        "predicted_ir_168h_uA",
        "prediction_upper_95_uA",
        "conformal_safety_upper_uA",
        "prediction_interval_width_uA",
    }
    _require_columns(
        prediction_24h,
        prediction_columns | {"predicted_slope_24_168_uA_per_h"},
        "24-hour predictions",
    )
    _require_columns(
        prediction_96h,
        prediction_columns
        | {
            "ir_96h_uA",
            "predicted_slope_96_168_uA_per_h",
            "robust_z_96h",
            "historical_robust_z_96h",
            "acceleration_indicator_at_96h",
        },
        "96-hour predictions",
    )
    for frame, name in [
        (module_a, "Module A report"),
        (prediction_24h, "24-hour predictions"),
        (prediction_96h, "96-hour predictions"),
    ]:
        _validate_unique(frame, name)

    a_columns = [
        "component_id",
        "lot_id",
        "burnin_batch_id",
        "dataset_split",
        "ir_0h_uA",
        "ir_24h_uA",
        "batch_slope_shift_score",
        "static_limit_failed_at_24h",
        "module_a_action",
        "module_a_primary_reason",
    ]
    p24_columns = [
        "component_id",
        "module_b_prediction_available",
        "predicted_ir_168h_uA",
        "prediction_upper_95_uA",
        "conformal_safety_upper_uA",
        "prediction_interval_width_uA",
        "predicted_slope_24_168_uA_per_h",
    ]
    p96_columns = [
        "component_id",
        "ir_96h_uA",
        "robust_z_96h",
        "historical_robust_z_96h",
        "acceleration_indicator_at_96h",
        "module_b_prediction_available",
        "predicted_ir_168h_uA",
        "prediction_upper_95_uA",
        "conformal_safety_upper_uA",
        "prediction_interval_width_uA",
        "predicted_slope_96_168_uA_per_h",
    ]
    result = module_a[a_columns].merge(
        prediction_24h[p24_columns].rename(
            columns={
                column: f"{column}_at_24h"
                for column in p24_columns
                if column != "component_id"
            }
        ),
        on="component_id",
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        prediction_96h[p96_columns].rename(
            columns={
                column: f"{column}_at_96h"
                for column in p96_columns
                if column != "component_id"
            }
        ),
        on="component_id",
        how="left",
        validate="one_to_one",
    )

    result["datasheet_limit_uA"] = config.datasheet_limit_uA
    result["guardband_limit_uA"] = config.guardband_limit_uA
    result["allowable_slope_24_168_uA_per_h"] = (
        config.guardband_limit_uA - result["ir_24h_uA"]
    ) / 144.0
    result["allowable_slope_96_168_uA_per_h"] = (
        config.guardband_limit_uA - result["ir_96h_uA_at_96h"]
    ) / 72.0

    available_24 = result[
        "module_b_prediction_available_at_24h"
    ].fillna(False).astype(bool)
    available_96 = result[
        "module_b_prediction_available_at_96h"
    ].fillna(False).astype(bool)
    static_failure_24 = result["static_limit_failed_at_24h"].fillna(False)
    group_shift = result["batch_slope_shift_score"].ge(
        config.group_shift_threshold
    )
    forecast_risk_24 = (
        result["predicted_ir_168h_uA_at_24h"].ge(
            config.guardband_limit_uA
        )
        | result["prediction_upper_95_uA_at_24h"].ge(
            config.guardband_limit_uA
        )
        | result["conformal_safety_upper_uA_at_24h"].ge(
            config.datasheet_limit_uA
        )
        | result["predicted_slope_24_168_uA_per_h_at_24h"].gt(
            result["allowable_slope_24_168_uA_per_h"]
        )
    )

    action_24_conditions = [
        static_failure_24,
        result["module_a_action"].eq("RETEST") | ~available_24,
        group_shift,
        result["module_a_action"].eq("HOLD_FOR_REVIEW") | forecast_risk_24,
        result["module_a_action"].eq("WATCH"),
    ]
    result["decision_at_24h"] = np.select(
        action_24_conditions,
        [
            "REJECT_EARLY",
            "RETEST",
            "QUARANTINE_LOT_BATCH",
            "HOLD_FOR_REVIEW",
            "WATCH_TO_96H",
        ],
        default="CONTINUE_TO_96H",
    )
    result["decision_reason_at_24h"] = np.select(
        action_24_conditions,
        [
            "Measured leakage exceeded the datasheet limit by 24 hours.",
            "Early measurements are missing or unusable; retest is required.",
            "The burn-in batch has an abnormal collective drift slope.",
            "Anomaly or conservative 168-hour forecast requires QA review.",
            "Moderate early anomaly requires mandatory 96-hour monitoring.",
        ],
        default="No early risk; continue burn-in and re-screen at 96 hours.",
    )

    static_failure_96 = result["ir_96h_uA_at_96h"].gt(
        config.datasheet_limit_uA
    )
    point_failure_96 = result["predicted_ir_168h_uA_at_96h"].ge(
        config.datasheet_limit_uA
    )
    forecast_risk_96 = (
        result["prediction_upper_95_uA_at_96h"].ge(
            config.guardband_limit_uA
        )
        | result["conformal_safety_upper_uA_at_96h"].ge(
            config.datasheet_limit_uA
        )
        | result["predicted_slope_96_168_uA_per_h_at_96h"].gt(
            result["allowable_slope_96_168_uA_per_h"]
        )
    )
    trajectory_risk_96 = (
        result["robust_z_96h_at_96h"].clip(lower=0).ge(2.5)
        | result["historical_robust_z_96h_at_96h"].clip(lower=0).ge(2.5)
    )
    prior_safety_intervention = result["decision_at_24h"].isin(
        {"HOLD_FOR_REVIEW", "WATCH_TO_96H", "RETEST"}
    )

    action_96_conditions = [
        result["decision_at_24h"].eq("REJECT_EARLY"),
        result["decision_at_24h"].eq("QUARANTINE_LOT_BATCH"),
        static_failure_96 | point_failure_96,
        ~available_96,
        forecast_risk_96 | trajectory_risk_96 | prior_safety_intervention,
    ]
    result["decision_at_96h"] = np.select(
        action_96_conditions,
        [
            "REJECT_EARLY",
            "QUARANTINE_LOT_BATCH",
            "REJECT_EARLY",
            "RETEST",
            "HOLD_FOR_REVIEW",
        ],
        default="CONTINUE_TO_168H",
    )
    result["decision_reason_at_96h"] = np.select(
        action_96_conditions,
        [
            "The component already failed the 24-hour static gate.",
            "The affected burn-in batch remains quarantined.",
            "Measured or predicted leakage exceeds the datasheet limit.",
            "The 96-hour measurement is unavailable; retest is required.",
            "Updated forecast, trajectory anomaly or earlier risk requires hold.",
        ],
        default="Updated forecast is safe; continue burn-in to 168 hours.",
    )
    result["final_release_permitted_at_96h"] = False
    result["mandatory_next_checkpoint_h"] = np.where(
        result["decision_at_96h"].eq("CONTINUE_TO_168H"),
        168,
        np.nan,
    )
    return result
