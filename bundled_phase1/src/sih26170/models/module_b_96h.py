"""Module B update: forecast 168-hour leakage using data through 96 hours."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import RegressorMixin
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sih26170.features import MODULE_B_96H_UPDATE_FEATURES, MODULE_B_TARGET

STRICT_96H_FEATURES = [
    "ir_0h_uA",
    "ir_24h_uA",
    "ir_96h_uA",
    "change_0_24_uA",
    "change_0_96_uA",
    "slope_0_24_uA_per_h",
    "slope_0_96_uA_per_h",
    "slope_24_96_uA_per_h",
    "acceleration_indicator_at_96h",
]


@dataclass
class ModuleB96ModelBundle:
    """Fitted 96-hour point, interval and safety-calibration models."""

    point_models: dict[str, RegressorMixin]
    selected_model_name: str
    validation_mae: dict[str, float]
    quantile_models: dict[str, RegressorMixin]
    point_feature_sets: dict[str, list[str]]
    quantile_feature_columns: list[str]
    ensemble_members: list[str]
    safety_residual_quantile: float
    safety_margin_uA: float
    random_state: int


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing 96-hour Module B columns: {missing}")


def _training_mask(features: pd.DataFrame) -> pd.Series:
    return (
        features["dataset_split"].eq("train")
        & features["usable_for_module_b_at_96h"].astype(bool)
        & features[MODULE_B_TARGET].notna()
    )


def _validation_mask(features: pd.DataFrame) -> pd.Series:
    return (
        features["dataset_split"].eq("validation")
        & features["usable_for_module_b_at_96h"].astype(bool)
        & features[MODULE_B_TARGET].notna()
    )


def updated_linear_extrapolation(features: pd.DataFrame) -> pd.Series:
    """Continue the observed 24-to-96-hour slope for the final 72 hours."""

    return features["ir_96h_uA"] + (
        features["ir_96h_uA"] - features["ir_24h_uA"]
    )


def _make_point_models(random_state: int) -> dict[str, RegressorMixin]:
    return {
        "huber_96h": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "regressor",
                    HuberRegressor(
                        epsilon=1.35,
                        alpha=0.0001,
                        max_iter=2_000,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting_96h": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "regressor",
                    HistGradientBoostingRegressor(
                        loss="absolute_error",
                        learning_rate=0.05,
                        max_iter=300,
                        max_leaf_nodes=31,
                        min_samples_leaf=20,
                        l2_regularization=0.1,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "extra_trees_96h": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "regressor",
                    ExtraTreesRegressor(
                        n_estimators=400,
                        min_samples_leaf=2,
                        max_features=0.9,
                        n_jobs=-1,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def _make_quantile_model(
    quantile: float,
    random_state: int,
) -> RegressorMixin:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "regressor",
                HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=quantile,
                    learning_rate=0.05,
                    max_iter=300,
                    max_leaf_nodes=31,
                    min_samples_leaf=20,
                    l2_regularization=0.1,
                    random_state=random_state,
                ),
            ),
        ]
    )


def _ensemble_prediction(
    frame: pd.DataFrame,
    models: dict[str, RegressorMixin],
) -> np.ndarray:
    linear = updated_linear_extrapolation(frame).to_numpy()
    huber = models["huber_96h"].predict(frame[STRICT_96H_FEATURES])
    boosting = models["hist_gradient_boosting_96h"].predict(
        frame[MODULE_B_96H_UPDATE_FEATURES]
    )
    return np.median(np.column_stack([linear, huber, boosting]), axis=1)


def _estimate_safety_margin(
    features: pd.DataFrame,
    train_mask: pd.Series,
    random_state: int,
    quantile: float,
) -> float:
    """Estimate a one-sided margin using lot-grouped OOF residuals."""

    train = features.loc[train_mask].reset_index(drop=True)
    lot_count = int(train["lot_id"].nunique())
    if lot_count < 2:
        raise ValueError("At least two training lots are required for calibration.")

    out_of_fold = np.full(len(train), np.nan, dtype=float)
    splitter = GroupKFold(n_splits=min(4, lot_count))
    for fit_indices, predict_indices in splitter.split(
        train,
        groups=train["lot_id"],
    ):
        fold_models = _make_point_models(random_state)
        fold_models["huber_96h"].fit(
            train.loc[fit_indices, STRICT_96H_FEATURES],
            train.loc[fit_indices, MODULE_B_TARGET],
        )
        fold_models["hist_gradient_boosting_96h"].fit(
            train.loc[fit_indices, MODULE_B_96H_UPDATE_FEATURES],
            train.loc[fit_indices, MODULE_B_TARGET],
        )
        out_of_fold[predict_indices] = _ensemble_prediction(
            train.loc[predict_indices],
            fold_models,
        )

    residuals = train[MODULE_B_TARGET].to_numpy() - out_of_fold
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size == 0:
        raise ValueError("No finite residuals were available for calibration.")
    return float(max(0.0, np.quantile(residuals, quantile, method="higher")))


def fit_module_b_96h(
    features: pd.DataFrame,
    *,
    random_state: int = 42,
    safety_residual_quantile: float = 0.995,
) -> ModuleB96ModelBundle:
    """Train on training lots and select the point method on validation lots."""

    required = list(
        dict.fromkeys(
            MODULE_B_96H_UPDATE_FEATURES
            + STRICT_96H_FEATURES
            + [
                MODULE_B_TARGET,
                "dataset_split",
                "lot_id",
                "usable_for_module_b_at_96h",
            ]
        )
    )
    _require_columns(features, required)
    train_mask = _training_mask(features)
    validation_mask = _validation_mask(features)
    if not train_mask.any():
        raise ValueError("No usable training rows are available at 96 hours.")
    if not validation_mask.any():
        raise ValueError("No usable validation rows are available at 96 hours.")

    feature_sets = {
        "huber_96h": list(STRICT_96H_FEATURES),
        "hist_gradient_boosting_96h": list(MODULE_B_96H_UPDATE_FEATURES),
        "extra_trees_96h": list(MODULE_B_96H_UPDATE_FEATURES),
    }
    models = _make_point_models(random_state)
    validation_target = features.loc[validation_mask, MODULE_B_TARGET]
    validation_mae = {
        "updated_linear_extrapolation": float(
            mean_absolute_error(
                validation_target,
                updated_linear_extrapolation(features.loc[validation_mask]),
            )
        )
    }
    for name, model in models.items():
        columns = feature_sets[name]
        model.fit(
            features.loc[train_mask, columns],
            features.loc[train_mask, MODULE_B_TARGET],
        )
        prediction = model.predict(features.loc[validation_mask, columns])
        validation_mae[name] = float(
            mean_absolute_error(validation_target, prediction)
        )

    ensemble_prediction = _ensemble_prediction(
        features.loc[validation_mask],
        models,
    )
    validation_mae["median_ensemble_96h"] = float(
        mean_absolute_error(validation_target, ensemble_prediction)
    )
    selected_name = min(validation_mae, key=validation_mae.get)

    quantile_models: dict[str, RegressorMixin] = {}
    for name, quantile in {"q05": 0.05, "q50": 0.50, "q95": 0.95}.items():
        model = _make_quantile_model(quantile, random_state)
        model.fit(
            features.loc[train_mask, MODULE_B_96H_UPDATE_FEATURES],
            features.loc[train_mask, MODULE_B_TARGET],
        )
        quantile_models[name] = model

    safety_margin = _estimate_safety_margin(
        features,
        train_mask,
        random_state,
        safety_residual_quantile,
    )
    return ModuleB96ModelBundle(
        point_models=models,
        selected_model_name=selected_name,
        validation_mae=validation_mae,
        quantile_models=quantile_models,
        point_feature_sets=feature_sets,
        quantile_feature_columns=list(MODULE_B_96H_UPDATE_FEATURES),
        ensemble_members=[
            "updated_linear_extrapolation",
            "huber_96h",
            "hist_gradient_boosting_96h",
        ],
        safety_residual_quantile=safety_residual_quantile,
        safety_margin_uA=safety_margin,
        random_state=random_state,
    )


def predict_module_b_96h(
    features: pd.DataFrame,
    bundle: ModuleB96ModelBundle,
) -> pd.DataFrame:
    """Create updated 168-hour predictions from data through 96 hours."""

    required = list(
        dict.fromkeys(
            bundle.quantile_feature_columns
            + [
                "component_id",
                "lot_id",
                "burnin_batch_id",
                "dataset_split",
                "ir_0h_uA",
                "ir_24h_uA",
                "ir_96h_uA",
                "robust_z_96h",
                "historical_robust_z_96h",
                "acceleration_indicator_at_96h",
                MODULE_B_TARGET,
                "usable_for_module_b_at_96h",
            ]
        )
    )
    _require_columns(features, required)
    result = features[
        [
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "dataset_split",
            "ir_0h_uA",
            "ir_24h_uA",
            "ir_96h_uA",
            "robust_z_96h",
            "historical_robust_z_96h",
            "acceleration_indicator_at_96h",
            MODULE_B_TARGET,
        ]
    ].copy()
    result = result.rename(columns={MODULE_B_TARGET: "actual_ir_168h_uA"})
    usable = features["usable_for_module_b_at_96h"].astype(bool)
    result["module_b_prediction_available"] = usable

    result["updated_linear_prediction_168h_uA"] = np.nan
    result.loc[usable, "updated_linear_prediction_168h_uA"] = (
        updated_linear_extrapolation(features.loc[usable])
    )
    for name, model in bundle.point_models.items():
        output_column = f"{name}_prediction_168h_uA"
        result[output_column] = np.nan
        result.loc[usable, output_column] = model.predict(
            features.loc[usable, bundle.point_feature_sets[name]]
        )

    result["median_ensemble_96h_prediction_168h_uA"] = result[
        [
            "updated_linear_prediction_168h_uA",
            "huber_96h_prediction_168h_uA",
            "hist_gradient_boosting_96h_prediction_168h_uA",
        ]
    ].median(axis=1, skipna=False)
    prediction_columns = {
        "updated_linear_extrapolation": "updated_linear_prediction_168h_uA",
        "median_ensemble_96h": "median_ensemble_96h_prediction_168h_uA",
        **{
            name: f"{name}_prediction_168h_uA"
            for name in bundle.point_models
        },
    }
    selected_column = prediction_columns.get(bundle.selected_model_name)
    if selected_column is None:
        raise ValueError(f"Unknown 96-hour model: {bundle.selected_model_name}")
    result["selected_model"] = bundle.selected_model_name
    result["predicted_ir_168h_uA"] = result[selected_column]

    result["prediction_lower_05_uA"] = np.nan
    result["prediction_median_50_uA"] = np.nan
    result["prediction_upper_95_uA"] = np.nan
    if usable.any():
        quantile_predictions = [
            bundle.quantile_models[name].predict(
                features.loc[usable, bundle.quantile_feature_columns]
            )
            for name in ("q05", "q50", "q95")
        ]
        ordered = np.sort(np.column_stack(quantile_predictions), axis=1)
        result.loc[usable, "prediction_lower_05_uA"] = ordered[:, 0]
        result.loc[usable, "prediction_median_50_uA"] = ordered[:, 1]
        result.loc[usable, "prediction_upper_95_uA"] = ordered[:, 2]

    result["prediction_interval_width_uA"] = (
        result["prediction_upper_95_uA"]
        - result["prediction_lower_05_uA"]
    )
    result["predicted_slope_96_168_uA_per_h"] = (
        result["predicted_ir_168h_uA"] - result["ir_96h_uA"]
    ) / 72.0
    result["safety_margin_uA"] = bundle.safety_margin_uA
    result["conformal_safety_upper_uA"] = np.maximum(
        result["prediction_upper_95_uA"],
        result["predicted_ir_168h_uA"] + bundle.safety_margin_uA,
    )
    result["absolute_prediction_error_uA"] = (
        result["actual_ir_168h_uA"] - result["predicted_ir_168h_uA"]
    ).abs()
    return result


def module_b_96h_metadata(bundle: ModuleB96ModelBundle) -> dict[str, Any]:
    return {
        "module": "B_96H_UPDATE",
        "target": MODULE_B_TARGET,
        "prediction_time_h": 96,
        "forecast_time_h": 168,
        "selected_model": bundle.selected_model_name,
        "validation_mae": bundle.validation_mae,
        "point_feature_sets": bundle.point_feature_sets,
        "quantile_feature_columns": bundle.quantile_feature_columns,
        "ensemble_members": bundle.ensemble_members,
        "safety_residual_quantile": bundle.safety_residual_quantile,
        "safety_margin_uA": bundle.safety_margin_uA,
        "uses_168h_as_input": False,
        "uses_hidden_truth_labels": False,
        "random_state": bundle.random_state,
    }
