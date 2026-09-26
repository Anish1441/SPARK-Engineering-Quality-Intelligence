"""Time-safe feature engineering for anomaly detection and drift prediction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from sih26170.config import Settings, settings

MODULE_A_24H_FEATURES = [
    "ir_0h_uA",
    "ir_24h_uA",
    "change_0_24_uA",
    "slope_0_24_uA_per_h",
    "relative_change_0_24",
    "distance_to_limit_at_24h_uA",
    "robust_z_0h",
    "robust_z_24h",
    "robust_z_slope_0_24",
    "historical_robust_z_0h",
    "historical_robust_z_24h",
    "lot_shift_score_at_24h",
    "quality_issue_count_through_24h",
    "missing_count_through_24h",
    "condition_mismatch_count_through_24h",
]

MODULE_B_24H_STRICT_FEATURES = [
    "ir_0h_uA",
    "ir_24h_uA",
    "change_0_24_uA",
    "slope_0_24_uA_per_h",
    "relative_change_0_24",
]

MODULE_B_24H_EXTENDED_FEATURES = MODULE_B_24H_STRICT_FEATURES + [
    "lot_median_0h_uA",
    "lot_mad_0h_uA",
    "robust_z_0h",
    "lot_median_24h_uA",
    "lot_mad_24h_uA",
    "robust_z_24h",
    "historical_robust_z_0h",
    "historical_robust_z_24h",
    "lot_shift_score_at_24h",
]

MODULE_B_96H_UPDATE_FEATURES = MODULE_B_24H_EXTENDED_FEATURES + [
    "ir_96h_uA",
    "change_0_96_uA",
    "slope_0_96_uA_per_h",
    "slope_24_96_uA_per_h",
    "acceleration_indicator_at_96h",
    "lot_median_96h_uA",
    "lot_mad_96h_uA",
    "robust_z_96h",
    "historical_robust_z_96h",
    "lot_shift_score_at_96h",
]

MODULE_A_FINAL_FEATURES = [
    *(f"ir_{time_h}h_uA" for time_h in settings.expected_timepoints_h),
    "slope_0_24_uA_per_h",
    "slope_0_96_uA_per_h",
    "slope_0_168_uA_per_h",
    "updated_slope_96_168_uA_per_h",
    "acceleration_indicator_at_96h",
    *(f"robust_z_{time_h}h" for time_h in settings.expected_timepoints_h),
    "robust_z_slope_0_24",
]

MODULE_B_TARGET = "ir_168h_uA"


@dataclass(frozen=True)
class FeatureBuildReport:
    """Headline counts from one feature-engineering run."""

    components: int
    train_components: int
    validation_components: int
    test_components: int
    module_a_24h_usable: int
    module_b_24h_usable: int
    module_b_96h_usable: int
    target_168h_available: int


def robust_mad(values: pd.Series) -> float:
    """Median absolute deviation, ignoring missing values."""

    usable = values.dropna()
    if usable.empty:
        return np.nan
    median = usable.median()
    return float((usable - median).abs().median())


def pivot_usable_measurements(
    clean: pd.DataFrame,
    config: Settings = settings,
) -> pd.DataFrame:
    """Convert long data into one usable leakage column per checkpoint."""

    work = clean.copy()
    work["ml_value_uA"] = work["leakage_current_uA"].where(
        work["usable_for_ml"].astype(bool), np.nan
    )
    pivot = work.pivot(
        index="component_id",
        columns="measurement_time_h",
        values="ml_value_uA",
    )
    pivot = pivot.reindex(columns=list(config.expected_timepoints_h))
    pivot.columns = [f"ir_{int(time_h)}h_uA" for time_h in pivot.columns]
    return pivot.reset_index()


def _identity_table(clean: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "component_id",
        "lot_id",
        "burnin_batch_id",
        "dataset_split",
        "part_number",
        "qualification_level",
        "parameter_name",
        "datasheet_upper_limit_uA",
        "stress_temperature_c",
        "stress_reverse_bias_v",
    ]
    return (
        clean.sort_values(["component_id", "measurement_time_h"])
        .groupby("component_id", as_index=False)
        .first()[columns]
    )


def add_quality_features(wide: pd.DataFrame, clean: pd.DataFrame) -> pd.DataFrame:
    """Add final and cutoff-specific quality counts without future leakage."""

    result = wide.copy()
    final = clean.groupby("component_id").agg(
        quality_issue_count=("quality_status", lambda values: int((values != "PASS").sum())),
        missing_timepoint_count=("missing_value_flag", "sum"),
        condition_mismatch_count=("condition_mismatch_flag", "sum"),
        usable_timepoint_count=("usable_for_ml", "sum"),
    )
    result = result.merge(final.reset_index(), on="component_id", how="left")

    for cutoff in (24, 96):
        available = clean.loc[clean["measurement_time_h"] <= cutoff]
        counts = available.groupby("component_id").agg(
            **{
                f"quality_issue_count_through_{cutoff}h": (
                    "quality_status",
                    lambda values: int((values != "PASS").sum()),
                ),
                f"missing_count_through_{cutoff}h": ("missing_value_flag", "sum"),
                f"condition_mismatch_count_through_{cutoff}h": (
                    "condition_mismatch_flag",
                    "sum",
                ),
                f"usable_count_through_{cutoff}h": ("usable_for_ml", "sum"),
            }
        )
        result = result.merge(counts.reset_index(), on="component_id", how="left")
    return result


def add_temporal_features(
    wide: pd.DataFrame,
    config: Settings = settings,
) -> pd.DataFrame:
    """Calculate changes, slopes and time-specific availability flags."""

    result = wide.copy()
    result["change_0_24_uA"] = result["ir_24h_uA"] - result["ir_0h_uA"]
    result["slope_0_24_uA_per_h"] = result["change_0_24_uA"] / 24.0
    denominator = result["ir_0h_uA"].abs().clip(lower=1e-6)
    result["relative_change_0_24"] = result["change_0_24_uA"] / denominator

    result["change_0_96_uA"] = result["ir_96h_uA"] - result["ir_0h_uA"]
    result["slope_0_96_uA_per_h"] = result["change_0_96_uA"] / 96.0
    result["slope_24_96_uA_per_h"] = (
        result["ir_96h_uA"] - result["ir_24h_uA"]
    ) / 72.0
    result["acceleration_indicator_at_96h"] = (
        result["slope_24_96_uA_per_h"] - result["slope_0_24_uA_per_h"]
    )

    result["change_0_168_uA"] = result["ir_168h_uA"] - result["ir_0h_uA"]
    result["slope_0_168_uA_per_h"] = result["change_0_168_uA"] / 168.0
    result["updated_slope_96_168_uA_per_h"] = (
        result["ir_168h_uA"] - result["ir_96h_uA"]
    ) / 72.0

    for time_h in config.expected_timepoints_h:
        result[f"distance_to_limit_at_{time_h}h_uA"] = (
            config.datasheet_upper_limit_uA - result[f"ir_{time_h}h_uA"]
        )
    result["max_observed_uA"] = result[
        [f"ir_{time_h}h_uA" for time_h in config.expected_timepoints_h]
    ].max(axis=1)
    result["static_limit_pass_at_0h"] = result["ir_0h_uA"].le(
        config.datasheet_upper_limit_uA
    ).where(result["ir_0h_uA"].notna())
    result["usable_for_module_a_at_24h"] = result[MODULE_A_24H_FEATURES[:2]].notna().all(axis=1)
    result["usable_for_module_b_at_24h"] = result[MODULE_B_24H_STRICT_FEATURES[:2]].notna().all(axis=1)
    result["usable_for_module_b_at_96h"] = result[["ir_0h_uA", "ir_24h_uA", "ir_96h_uA"]].notna().all(axis=1)
    result["target_168h_available"] = result[MODULE_B_TARGET].notna()
    return result


def add_lot_relative_features(
    wide: pd.DataFrame,
    config: Settings = settings,
) -> pd.DataFrame:
    """Compare each component with robust statistics from its current lot."""

    result = wide.copy()
    for time_h in config.expected_timepoints_h:
        value_column = f"ir_{time_h}h_uA"
        median_column = f"lot_median_{time_h}h_uA"
        mad_column = f"lot_mad_{time_h}h_uA"
        result[median_column] = result.groupby("lot_id")[value_column].transform("median")
        result[mad_column] = result.groupby("lot_id")[value_column].transform(robust_mad)
        result[f"robust_z_{time_h}h"] = (
            0.6745
            * (result[value_column] - result[median_column])
            / result[mad_column].replace(0.0, np.nan)
        )

    result["lot_median_slope_0_24"] = result.groupby("lot_id")[
        "slope_0_24_uA_per_h"
    ].transform("median")
    result["lot_mad_slope_0_24"] = result.groupby("lot_id")[
        "slope_0_24_uA_per_h"
    ].transform(robust_mad)
    result["robust_z_slope_0_24"] = (
        0.6745
        * (result["slope_0_24_uA_per_h"] - result["lot_median_slope_0_24"])
        / result["lot_mad_slope_0_24"].replace(0.0, np.nan)
    )
    return result


def add_historical_training_baselines(
    wide: pd.DataFrame,
    config: Settings = settings,
) -> pd.DataFrame:
    """Add historical baselines fitted strictly from training lots."""

    result = wide.copy()
    train = result.loc[result["dataset_split"] == "train"]
    if train.empty:
        raise ValueError("Training lots are required to calculate historical baselines.")

    for time_h in config.expected_timepoints_h:
        value_column = f"ir_{time_h}h_uA"
        median = float(train[value_column].median())
        mad = robust_mad(train[value_column])
        if not np.isfinite(mad) or mad == 0:
            raise ValueError(f"Historical MAD is invalid for {value_column}.")
        result[f"historical_train_median_{time_h}h_uA"] = median
        result[f"historical_train_mad_{time_h}h_uA"] = mad
        result[f"historical_robust_z_{time_h}h"] = (
            0.6745 * (result[value_column] - median) / mad
        )
        result[f"lot_shift_score_at_{time_h}h"] = (
            0.6745 * (result[f"lot_median_{time_h}h_uA"] - median).abs() / mad
        )
    return result


def validate_time_safe_feature_lists() -> None:
    """Fail fast if an early model feature accidentally references future data."""

    feature_sets = {
        "MODULE_A_24H_FEATURES": (MODULE_A_24H_FEATURES, 24),
        "MODULE_B_24H_STRICT_FEATURES": (MODULE_B_24H_STRICT_FEATURES, 24),
        "MODULE_B_24H_EXTENDED_FEATURES": (MODULE_B_24H_EXTENDED_FEATURES, 24),
        "MODULE_B_96H_UPDATE_FEATURES": (MODULE_B_96H_UPDATE_FEATURES, 96),
    }
    for name, (columns, cutoff) in feature_sets.items():
        if MODULE_B_TARGET in columns:
            raise ValueError(f"{name} contains the Module B target.")
        for column in columns:
            referenced_times = [int(value) for value in re.findall(r"(\d+)h", column)]
            future_times = [value for value in referenced_times if value > cutoff]
            if future_times:
                raise ValueError(f"{name} contains future feature {column}.")


def build_feature_table(
    clean: pd.DataFrame,
    config: Settings = settings,
) -> tuple[pd.DataFrame, FeatureBuildReport]:
    """Build the shared component-level feature store for Modules A and B."""

    validate_time_safe_feature_lists()
    identity = _identity_table(clean)
    pivot = pivot_usable_measurements(clean, config)
    wide = identity.merge(pivot, on="component_id", how="left")
    wide = add_quality_features(wide, clean)
    wide = add_temporal_features(wide, config)
    wide = add_lot_relative_features(wide, config)
    wide = add_historical_training_baselines(wide, config)

    numeric_columns = wide.select_dtypes(include=["number"]).columns
    wide[numeric_columns] = wide[numeric_columns].round(6)

    split_counts = wide["dataset_split"].value_counts().to_dict()
    report = FeatureBuildReport(
        components=len(wide),
        train_components=int(split_counts.get("train", 0)),
        validation_components=int(split_counts.get("validation", 0)),
        test_components=int(split_counts.get("test", 0)),
        module_a_24h_usable=int(wide["usable_for_module_a_at_24h"].sum()),
        module_b_24h_usable=int(wide["usable_for_module_b_at_24h"].sum()),
        module_b_96h_usable=int(wide["usable_for_module_b_at_96h"].sum()),
        target_168h_available=int(wide["target_168h_available"].sum()),
    )
    return wide, report


def build_feature_manifest() -> dict[str, object]:
    """Document exactly which columns each model may access."""

    validate_time_safe_feature_lists()
    return {
        "module_a_24h_features": MODULE_A_24H_FEATURES,
        "module_a_final_features": MODULE_A_FINAL_FEATURES,
        "module_b_24h_strict_features": MODULE_B_24H_STRICT_FEATURES,
        "module_b_24h_extended_features": MODULE_B_24H_EXTENDED_FEATURES,
        "module_b_96h_update_features": MODULE_B_96H_UPDATE_FEATURES,
        "module_b_target": MODULE_B_TARGET,
        "split_policy": "Manufacturing-lot grouped: L01-L08 train, L09-L10 validation, L11-L12 test",
        "hidden_ground_truth_in_feature_table": False,
    }


def save_feature_outputs(
    features: pd.DataFrame,
    *,
    table_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Atomically save the feature store and its leakage-control manifest."""

    table_target = Path(table_path) if table_path is not None else settings.feature_table_path
    manifest_target = (
        Path(manifest_path) if manifest_path is not None else settings.feature_manifest_path
    )
    table_target = table_target.expanduser().resolve()
    manifest_target = manifest_target.expanduser().resolve()
    existing = [path for path in (table_target, manifest_target) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Feature output already exists: {existing[0]}. Use overwrite=True to replace it."
        )

    table_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    table_temporary = table_target.with_suffix(table_target.suffix + ".tmp")
    manifest_temporary = manifest_target.with_suffix(manifest_target.suffix + ".tmp")
    features.to_csv(table_temporary, index=False)
    manifest_temporary.write_text(
        json.dumps(build_feature_manifest(), indent=2), encoding="utf-8"
    )
    table_temporary.replace(table_target)
    manifest_temporary.replace(manifest_target)
    return table_target, manifest_target

