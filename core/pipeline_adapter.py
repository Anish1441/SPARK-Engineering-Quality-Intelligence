from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


class PipelineContractError(RuntimeError):
    """Raised when the original SPARK ML pipeline is unavailable."""


class PipelineAdapter:
    """
    Adapter for the original SPARK Module-B ML pipeline.

    Flow:

        clean measurements
            ↓
        original build_feature_table()
            ↓
        original module_b_24h.joblib
            ↓
        original predict_module_b()
            ↓
        real Module-B prediction

    No synthetic or fabricated prediction is generated.
    """

    REQUIRED_INPUT_COLUMNS = {
        "component_id",
        "measurement_time_h",
        "leakage_current_uA",
        "usable_for_ml",
    }

    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()

        self._feature_builder = None
        self._predict_function = None
        self._bundle = None
        self._metadata = {}
        self._load_error = None

        self._load_pipeline()

    def _load_pipeline(self) -> None:
        try:
            if not self.root.exists():
                raise PipelineContractError(
                    f"Original SPARK pipeline root does not exist: {self.root}"
                )

            src = self.root / "src"

            if not src.exists():
                raise PipelineContractError(
                    f"Original SPARK pipeline src directory not found: {src}"
                )

            src_path = str(src)

            if src_path not in sys.path:
                sys.path.insert(0, src_path)

            features_module = importlib.import_module(
                "sih26170.features"
            )

            model_module = importlib.import_module(
                "sih26170.models.module_b_drift"
            )

            feature_builder = getattr(
                features_module,
                "build_feature_table",
                None,
            )

            predict_function = getattr(
                model_module,
                "predict_module_b",
                None,
            )

            if not callable(feature_builder):
                raise PipelineContractError(
                    "Original build_feature_table() was not found."
                )

            if not callable(predict_function):
                raise PipelineContractError(
                    "Original predict_module_b() was not found."
                )

            model_path = self._model_path()

            if not model_path.exists():
                raise PipelineContractError(
                    f"Module-B model artifact not found: {model_path}"
                )

            artifact = joblib.load(model_path)

            if not isinstance(artifact, dict):
                raise PipelineContractError(
                    "Module-B model artifact is not a dictionary."
                )

            if "bundle" not in artifact:
                raise PipelineContractError(
                    "Module-B model artifact does not contain 'bundle'."
                )

            bundle = artifact["bundle"]

            if bundle is None:
                raise PipelineContractError(
                    "Module-B model bundle is empty."
                )

            self._feature_builder = feature_builder
            self._predict_function = predict_function
            self._bundle = bundle
            self._metadata = artifact.get("metadata", {})

        except Exception as exc:
            self._load_error = str(exc)

    def _model_path(self) -> Path:
        configured = os.environ.get(
            "SPARK_MODULE_B_MODEL",
            "",
        ).strip()

        if configured:
            return Path(configured).expanduser().resolve()

        return (
            self.root
            / "artifacts"
            / "models"
            / "module_b_24h.joblib"
        )

    @staticmethod
    def _native(value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, (str, bool, int)):
            return value

        if isinstance(value, float):
            return value if np.isfinite(value) else None

        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            value = float(value)
            return value if np.isfinite(value) else None

        if isinstance(value, np.bool_):
            return bool(value)

        if isinstance(value, np.ndarray):
            return [
                PipelineAdapter._native(v)
                for v in value.tolist()
            ]

        if isinstance(value, pd.Timestamp):
            return (
                value.isoformat()
                if not pd.isna(value)
                else None
            )

        if isinstance(value, dict):
            return {
                str(k): PipelineAdapter._native(v)
                for k, v in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                PipelineAdapter._native(v)
                for v in value
            ]

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        return str(value)

    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = sorted(
            self.REQUIRED_INPUT_COLUMNS - set(df.columns)
        )

        if missing:
            raise PipelineContractError(
                "Dataset is not compatible with the original "
                "SPARK clean-measurement format. Missing columns: "
                + ", ".join(missing)
            )

        if df.empty:
            raise PipelineContractError(
                "Dataset contains no records."
            )

    def status(self) -> dict[str, Any]:
        model_path = self._model_path()

        loaded = (
            self._load_error is None
            and self._feature_builder is not None
            and self._predict_function is not None
            and self._bundle is not None
        )

        if self._load_error:
            message = self._load_error
        elif loaded:
            message = (
                "Original SPARK Module-B ML pipeline loaded successfully."
            )
        else:
            message = (
                "Original SPARK Module-B ML pipeline is not loaded."
            )

        selected_model = None

        if self._bundle is not None:
            selected_model = getattr(
                self._bundle,
                "selected_model_name",
                None,
            )

        return {
            "configured_root": str(self.root),
            "pipeline_accessible": self.root.exists(),
            "feature_engineering_loaded": (
                self._feature_builder is not None
            ),
            "inference_function_loaded": (
                self._predict_function is not None
            ),
            "model_path": str(model_path),
            "model_exists": model_path.exists(),
            "model_bundle_loaded": self._bundle is not None,
            "prediction_available": loaded,
            "selected_model": selected_model,
            "mode": "ORIGINAL SPARK ML PIPELINE",
            "message": message,
        }

    def assess(
        self,
        df: pd.DataFrame,
        index: int,
    ) -> dict[str, Any]:

        if index < 0 or index >= len(df):
            raise IndexError(
                "Record index is out of range."
            )

        if self._load_error:
            return {
                "available": False,
                "mode": "ORIGINAL SPARK ML PIPELINE",
                "prediction": None,
                "confidence": None,
                "score": None,
                "message": (
                    "Original ML pipeline could not be loaded: "
                    + self._load_error
                ),
            }

        if self._bundle is None:
            return {
                "available": False,
                "mode": "ORIGINAL SPARK ML PIPELINE",
                "prediction": None,
                "confidence": None,
                "score": None,
                "message": (
                    "Original SPARK Module-B model bundle is unavailable."
                ),
            }

        try:
            self._validate_input(df)

            # Use the ORIGINAL feature engineering.
            features, build_report = self._feature_builder(df)

            if not isinstance(features, pd.DataFrame):
                raise PipelineContractError(
                    "Original build_feature_table() did not return a DataFrame."
                )

            if features.empty:
                raise PipelineContractError(
                    "Original feature engineering returned no rows."
                )

            # Use the ORIGINAL Module-B inference function.
            predictions = self._predict_function(
                features,
                self._bundle,
            )

            if not isinstance(predictions, pd.DataFrame):
                raise PipelineContractError(
                    "Original predict_module_b() did not return a DataFrame."
                )

            if predictions.empty:
                raise PipelineContractError(
                    "Original Module-B inference returned no rows."
                )

            component_id = df.iloc[index]["component_id"]

            matches = predictions[
                predictions["component_id"].astype(str)
                == str(component_id)
            ]

            if matches.empty:
                return {
                    "available": False,
                    "mode": "ORIGINAL SPARK ML PIPELINE",
                    "prediction": None,
                    "confidence": None,
                    "score": None,
                    "component_id": self._native(component_id),
                    "message": (
                        "The selected component is not present in "
                        "the Module-B prediction output."
                    ),
                }

            row = matches.iloc[0]

            available = bool(
                row.get(
                    "module_b_prediction_available",
                    False,
                )
            )

            if not available:
                return {
                    "available": False,
                    "mode": "ORIGINAL SPARK ML PIPELINE",
                    "prediction": None,
                    "confidence": None,
                    "score": None,
                    "component_id": self._native(component_id),
                    "message": (
                        "Module-B inference is unavailable because "
                        "the original pipeline marked this component "
                        "unusable at 24h."
                    ),
                }

            result = {
                "available": True,
                "mode": "ORIGINAL SPARK ML PIPELINE",
                "model": self._native(
                    row.get("selected_model")
                ),
                "prediction": self._native(
                    row.get("predicted_ir_168h_uA")
                ),
                "prediction_168h_uA": self._native(
                    row.get("predicted_ir_168h_uA")
                ),
                "prediction_lower_05_uA": self._native(
                    row.get("prediction_lower_05_uA")
                ),
                "prediction_median_50_uA": self._native(
                    row.get("prediction_median_50_uA")
                ),
                "prediction_upper_95_uA": self._native(
                    row.get("prediction_upper_95_uA")
                ),
                "prediction_interval_width_uA": self._native(
                    row.get("prediction_interval_width_uA")
                ),
                "predicted_slope_24_168_uA_per_h": self._native(
                    row.get("predicted_slope_24_168_uA_per_h")
                ),
                "safety_margin_uA": self._native(
                    row.get("safety_margin_uA")
                ),
                "conformal_safety_upper_uA": self._native(
                    row.get("conformal_safety_upper_uA")
                ),
                "actual_ir_168h_uA": self._native(
                    row.get("actual_ir_168h_uA")
                ),
                "absolute_prediction_error_uA": self._native(
                    row.get("absolute_prediction_error_uA")
                ),
                "component_id": self._native(
                    component_id
                ),
                "confidence": None,
                "score": None,
                "message": (
                    "Prediction generated by the original "
                    "SPARK Module-B trained pipeline."
                ),
            }

            if hasattr(build_report, "__dict__"):
                result["feature_build"] = self._native(
                    vars(build_report)
                )

            if isinstance(self._metadata, dict):
                result["model_metadata"] = self._native(
                    self._metadata
                )

            return result

        except Exception as exc:
            return {
                "available": False,
                "mode": "ORIGINAL SPARK ML PIPELINE",
                "prediction": None,
                "confidence": None,
                "score": None,
                "message": (
                    "Original SPARK ML inference failed safely: "
                    + str(exc)
                ),
            }