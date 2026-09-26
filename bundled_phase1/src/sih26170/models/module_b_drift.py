"""Module B: 168-hour leakage prediction from 0-hour and 24-hour data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import RegressorMixin
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sih26170.features import (
    MODULE_B_24H_EXTENDED_FEATURES,
    MODULE_B_24H_STRICT_FEATURES,
    MODULE_B_TARGET,
)


@dataclass
class ModuleBModelBundle:
    """Selected point model, challengers and uncertainty models."""

    point_models: dict[str, RegressorMixin]
    selected_model_name: str
    validation_mae: dict[str, float]
    quantile_models: dict[str, RegressorMixin]
    point_feature_sets: dict[str, list[str]]
    ensemble_members: list[str]
    quantile_feature_columns: list[str]
    safety_residual_quantile: float
    safety_margin_uA: float
    random_state: int


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing Module B columns: {missing}")


def _training_mask(features: pd.DataFrame) -> pd.Series:
    return (
        features["dataset_split"].eq("train")
        & features["usable_for_module_b_at_24h"].astype(bool)
        & features[MODULE_B_TARGET].notna()
    )


def _validation_mask(features: pd.DataFrame) -> pd.Series:
    return (
        features["dataset_split"].eq("validation")
        & features["usable_for_module_b_at_24h"].astype(bool)
        & features[MODULE_B_TARGET].notna()
    )


def _make_point_models(random_state: int) -> dict[str, RegressorMixin]:
    return {
        "huber": Pipeline(
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
        "hist_gradient_boosting": Pipeline(
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
        "extra_trees": Pipeline(
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


def linear_extrapolation(features: pd.DataFrame) -> pd.Series:
    """Transparent benchmark assuming the first-day slope stays constant."""

    return features["ir_0h_uA"] + 7.0 * (
        features["ir_24h_uA"] - features["ir_0h_uA"]
    )


def _estimate_safety_margin(
    features: pd.DataFrame,
    train_mask: pd.Series,
    random_state: int,
    quantile: float,
) -> float:
    """Estimate a one-sided safety margin from lot-grouped OOF residuals."""

    train = features.loc[train_mask].reset_index(drop=True)
    lot_count = int(train["lot_id"].nunique())
    if lot_count < 2:
        raise ValueError("At least two training lots are required for calibration.")

    splitter = GroupKFold(n_splits=min(4, lot_count))
    out_of_fold = np.full(len(train), np.nan, dtype=float)
    for fit_indices, predict_indices in splitter.split(
        train,
        groups=train["lot_id"],
    ):
        fold_models = _make_point_models(random_state)
        fold_models["huber"].fit(
            train.loc[fit_indices, MODULE_B_24H_STRICT_FEATURES],
            train.loc[fit_indices, MODULE_B_TARGET],
        )
        fold_models["hist_gradient_boosting"].fit(
            train.loc[fit_indices, MODULE_B_24H_EXTENDED_FEATURES],
            train.loc[fit_indices, MODULE_B_TARGET],
        )
        linear_prediction = linear_extrapolation(
            train.loc[predict_indices]
        ).to_numpy()
        huber_prediction = fold_models["huber"].predict(
            train.loc[predict_indices, MODULE_B_24H_STRICT_FEATURES]
        )
        boosting_prediction = fold_models["hist_gradient_boosting"].predict(
            train.loc[predict_indices, MODULE_B_24H_EXTENDED_FEATURES]
        )
        out_of_fold[predict_indices] = np.median(
            np.column_stack(
                [
                    linear_prediction,
                    huber_prediction,
                    boosting_prediction,
                ]
            ),
            axis=1,
        )

    residuals = train[MODULE_B_TARGET].to_numpy() - out_of_fold
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size == 0:
        raise ValueError("No finite residuals were available for calibration.")
    return float(max(0.0, np.quantile(residuals, quantile, method="higher")))


def fit_module_b(
    features: pd.DataFrame,
    *,
    random_state: int = 42,
    safety_residual_quantile: float = 0.995,
) -> ModuleBModelBundle:
    """Fit candidates on training lots and choose one using validation MAE."""

    required = list(
        dict.fromkeys(
            MODULE_B_24H_EXTENDED_FEATURES
            + [
                MODULE_B_TARGET,
                "dataset_split",
                "lot_id",
                "usable_for_module_b_at_24h",
            ]
        )
    )
    _require_columns(features, required)

    train_mask = _training_mask(features)
    validation_mask = _validation_mask(features)
    if not train_mask.any():
        raise ValueError("No usable training rows are available for Module B.")
    if not validation_mask.any():
        raise ValueError("No usable validation rows are available for Module B.")

    point_feature_sets = {
        "huber": list(MODULE_B_24H_STRICT_FEATURES),
        "hist_gradient_boosting": list(MODULE_B_24H_EXTENDED_FEATURES),
        "extra_trees": list(MODULE_B_24H_EXTENDED_FEATURES),
    }
    models = _make_point_models(random_state)
    validation_mae: dict[str, float] = {}

    validation_target = features.loc[validation_mask, MODULE_B_TARGET]
    linear_predictions = linear_extrapolation(features.loc[validation_mask])
    validation_mae["linear_extrapolation"] = float(
        mean_absolute_error(validation_target, linear_predictions)
    )

    for name, model in models.items():
        columns = point_feature_sets[name]
        model.fit(
            features.loc[train_mask, columns],
            features.loc[train_mask, MODULE_B_TARGET],
        )
        prediction = model.predict(features.loc[validation_mask, columns])
        validation_mae[name] = float(
            mean_absolute_error(validation_target, prediction)
        )

    ensemble_members = [
        "linear_extrapolation",
        "huber",
        "hist_gradient_boosting",
    ]
    ensemble_predictions = np.median(
        np.column_stack(
            [
                linear_predictions.to_numpy(),
                models["huber"].predict(
                    features.loc[
                        validation_mask,
                        point_feature_sets["huber"],
                    ]
                ),
                models["hist_gradient_boosting"].predict(
                    features.loc[
                        validation_mask,
                        point_feature_sets["hist_gradient_boosting"],
                    ]
                ),
            ]
        ),
        axis=1,
    )
    validation_mae["median_ensemble"] = float(
        mean_absolute_error(validation_target, ensemble_predictions)
    )
    selected_name = min(validation_mae, key=validation_mae.get)
    safety_margin_uA = _estimate_safety_margin(
        features,
        train_mask,
        random_state,
        safety_residual_quantile,
    )

    quantile_models: dict[str, RegressorMixin] = {}
    for name, quantile in {"q05": 0.05, "q50": 0.50, "q95": 0.95}.items():
        model = _make_quantile_model(quantile, random_state)
        model.fit(
            features.loc[train_mask, MODULE_B_24H_EXTENDED_FEATURES],
            features.loc[train_mask, MODULE_B_TARGET],
        )
        quantile_models[name] = model

    return ModuleBModelBundle(
        point_models=models,
        selected_model_name=selected_name,
        validation_mae=validation_mae,
        quantile_models=quantile_models,
        point_feature_sets=point_feature_sets,
        ensemble_members=ensemble_members,
        quantile_feature_columns=list(MODULE_B_24H_EXTENDED_FEATURES),
        safety_residual_quantile=safety_residual_quantile,
        safety_margin_uA=safety_margin_uA,
        random_state=random_state,
    )


def predict_module_b(
    features: pd.DataFrame,
    bundle: ModuleBModelBundle,
) -> pd.DataFrame:
    """Predict 168-hour leakage and a model-based uncertainty interval."""

    required = list(
        dict.fromkeys(
            bundle.quantile_feature_columns
            + [
                "component_id",
                "lot_id",
                "burnin_batch_id",
                "dataset_split",
                "ir_24h_uA",
                MODULE_B_TARGET,
                "usable_for_module_b_at_24h",
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
            MODULE_B_TARGET,
        ]
    ].copy()
    result = result.rename(columns={MODULE_B_TARGET: "actual_ir_168h_uA"})
    usable = features["usable_for_module_b_at_24h"].astype(bool)
    result["module_b_prediction_available"] = usable
    result["linear_prediction_168h_uA"] = np.nan
    result.loc[usable, "linear_prediction_168h_uA"] = linear_extrapolation(
        features.loc[usable]
    )

    for name, model in bundle.point_models.items():
        output_column = f"{name}_prediction_168h_uA"
        result[output_column] = np.nan
        columns = bundle.point_feature_sets[name]
        result.loc[usable, output_column] = model.predict(
            features.loc[usable, columns]
        )

    result["median_ensemble_prediction_168h_uA"] = result[
        [
            "linear_prediction_168h_uA",
            "huber_prediction_168h_uA",
            "hist_gradient_boosting_prediction_168h_uA",
        ]
    ].median(axis=1, skipna=False)
    prediction_columns = {
        "linear_extrapolation": "linear_prediction_168h_uA",
        "median_ensemble": "median_ensemble_prediction_168h_uA",
        **{
            name: f"{name}_prediction_168h_uA"
            for name in bundle.point_models
        },
    }
    selected_column = prediction_columns.get(bundle.selected_model_name)
    if selected_column is None:
        raise ValueError(
            f"Unknown selected Module B model: {bundle.selected_model_name}"
        )
    result["selected_model"] = bundle.selected_model_name
    result["predicted_ir_168h_uA"] = result[selected_column]

    quantile_predictions: dict[str, np.ndarray] = {}
    for name, model in bundle.quantile_models.items():
        quantile_predictions[name] = model.predict(
            features.loc[usable, bundle.quantile_feature_columns]
        )
    result["prediction_lower_05_uA"] = np.nan
    result["prediction_median_50_uA"] = np.nan
    result["prediction_upper_95_uA"] = np.nan
    if usable.any():
        ordered_quantiles = np.sort(
            np.column_stack(
                [
                    quantile_predictions["q05"],
                    quantile_predictions["q50"],
                    quantile_predictions["q95"],
                ]
            ),
            axis=1,
        )
        result.loc[usable, "prediction_lower_05_uA"] = ordered_quantiles[:, 0]
        result.loc[usable, "prediction_median_50_uA"] = ordered_quantiles[:, 1]
        result.loc[usable, "prediction_upper_95_uA"] = ordered_quantiles[:, 2]
    result["prediction_interval_width_uA"] = (
        result["prediction_upper_95_uA"]
        - result["prediction_lower_05_uA"]
    )
    result["predicted_slope_24_168_uA_per_h"] = (
        result["predicted_ir_168h_uA"] - result["ir_24h_uA"]
    ) / 144.0
    result["safety_margin_uA"] = bundle.safety_margin_uA
    result["conformal_safety_upper_uA"] = np.maximum(
        result["prediction_upper_95_uA"],
        result["predicted_ir_168h_uA"] + bundle.safety_margin_uA,
    )
    result["absolute_prediction_error_uA"] = (
        result["actual_ir_168h_uA"] - result["predicted_ir_168h_uA"]
    ).abs()
    return result


def module_b_metadata(bundle: ModuleBModelBundle) -> dict[str, Any]:
    """Return serialisable information for audit and deployment."""

    return {
        "module": "B",
        "target": MODULE_B_TARGET,
        "prediction_time_h": 24,
        "forecast_time_h": 168,
        "selected_model": bundle.selected_model_name,
        "validation_mae": bundle.validation_mae,
        "point_feature_sets": bundle.point_feature_sets,
        "ensemble_members": bundle.ensemble_members,
        "quantile_feature_columns": bundle.quantile_feature_columns,
        "quantiles": [0.05, 0.50, 0.95],
        "safety_residual_quantile": bundle.safety_residual_quantile,
        "safety_margin_uA": bundle.safety_margin_uA,
        "safety_calibration": "lot-grouped out-of-fold one-sided residual",
        "uses_96h_or_168h_as_input": False,
        "uses_hidden_truth_labels": False,
        "random_state": bundle.random_state,
    }
