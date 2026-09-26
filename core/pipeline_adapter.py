from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


class PipelineContractError(RuntimeError):
    """Raised when an original SPARK Phase-1 contract is unavailable."""


class PipelineAdapter:
    """Bridge Phase 7 to the original Phase-1 Module-A and Module-B pipeline.

    The adapter deliberately reuses the original feature engineering and model
    artifacts. It never fabricates a model result. Feature engineering and both
    Module-A/Module-B outputs are cached per dataset so component navigation is
    fast even for the 24,000-row long-form burn-in dataset.
    """

    REQUIRED_INPUT_COLUMNS = {
        "component_id",
        "measurement_time_h",
        "leakage_current_uA",
        "usable_for_ml",
    }

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve(strict=False)

        self._feature_builder = None
        self._feature_load_error: str | None = None

        self._module_a_score_function = None
        self._module_a_model = None
        self._module_a_metadata: dict[str, Any] = {}
        self._module_a_load_error: str | None = None

        self._module_b_predict_function = None
        self._module_b_bundle = None
        self._module_b_metadata: dict[str, Any] = {}
        self._module_b_load_error: str | None = None

        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = threading.RLock()

        self._load_pipeline()

    # ------------------------------------------------------------------
    # MODEL / SOURCE LOADING
    # ------------------------------------------------------------------

    def _load_pipeline(self) -> None:
        if not self.root.exists():
            message = f"Original SPARK pipeline root does not exist: {self.root}"
            self._feature_load_error = message
            self._module_a_load_error = message
            self._module_b_load_error = message
            return

        src = self.root / "src"
        if not src.exists():
            message = f"Original SPARK pipeline src directory not found: {src}"
            self._feature_load_error = message
            self._module_a_load_error = message
            self._module_b_load_error = message
            return

        src_path = str(src)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        try:
            features_module = importlib.import_module("sih26170.features")
            feature_builder = getattr(
                features_module,
                "build_feature_table",
                None,
            )
            if not callable(feature_builder):
                raise PipelineContractError(
                    "Original build_feature_table() was not found."
                )
            self._feature_builder = feature_builder
            self._feature_load_error = None
        except Exception as exc:
            self._feature_load_error = str(exc)

        self._load_module_a()
        self._load_module_b()

    def _load_module_a(self) -> None:
        try:
            if self._feature_builder is None:
                raise PipelineContractError(
                    "Module A requires the original SPARK feature builder."
                )

            module = importlib.import_module(
                "sih26170.models.module_a_anomaly"
            )
            score_function = getattr(module, "score_module_a", None)
            if not callable(score_function):
                raise PipelineContractError(
                    "Original score_module_a() was not found."
                )

            model_path = self._module_a_model_path()
            if not model_path.exists():
                raise PipelineContractError(
                    f"Module-A model artifact not found: {model_path}"
                )

            artifact = joblib.load(model_path)
            model, metadata = self._extract_module_a_artifact(artifact)
            if model is None:
                raise PipelineContractError(
                    "Module-A artifact does not contain a usable model."
                )

            if not metadata:
                metadata_function = getattr(module, "model_metadata", None)
                if callable(metadata_function):
                    try:
                        generated = metadata_function(model)
                        if isinstance(generated, dict):
                            metadata = generated
                    except Exception:
                        metadata = {}

            self._module_a_score_function = score_function
            self._module_a_model = model
            self._module_a_metadata = metadata
            self._module_a_load_error = None

        except Exception as exc:
            self._module_a_load_error = str(exc)

    def _load_module_b(self) -> None:
        try:
            if self._feature_builder is None:
                raise PipelineContractError(
                    "Module B requires the original SPARK feature builder."
                )

            module = importlib.import_module(
                "sih26170.models.module_b_drift"
            )
            predict_function = getattr(module, "predict_module_b", None)
            if not callable(predict_function):
                raise PipelineContractError(
                    "Original predict_module_b() was not found."
                )

            model_path = self._module_b_model_path()
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

            self._module_b_predict_function = predict_function
            self._module_b_bundle = bundle
            self._module_b_metadata = artifact.get("metadata", {}) or {}
            self._module_b_load_error = None

        except Exception as exc:
            self._module_b_load_error = str(exc)

    @staticmethod
    def _extract_module_a_artifact(
        artifact: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Support the historical Module-A artifact formats used in Phase 1."""
        if isinstance(artifact, dict):
            metadata = artifact.get("metadata", {}) or {}
            for key in (
                "model",
                "module_a_model",
                "bundle",
                "estimator",
            ):
                if key in artifact and artifact[key] is not None:
                    return artifact[key], metadata if isinstance(metadata, dict) else {}
            return None, metadata if isinstance(metadata, dict) else {}

        # Older snapshots may have stored the ModuleAModel object directly.
        return artifact, {}

    def _module_a_model_path(self) -> Path:
        configured = os.environ.get("SPARK_MODULE_A_MODEL", "").strip()
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return self.root / "artifacts" / "models" / "module_a_24h.joblib"

    def _module_b_model_path(self) -> Path:
        configured = os.environ.get("SPARK_MODULE_B_MODEL", "").strip()
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return self.root / "artifacts" / "models" / "module_b_24h.joblib"

    # Backward-compatible alias retained for older Phase-7 tests/tools.
    def _model_path(self) -> Path:
        return self._module_b_model_path()

    # ------------------------------------------------------------------
    # NORMALIZATION / VALIDATION
    # ------------------------------------------------------------------

    @staticmethod
    def _native(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            converted = float(value)
            return converted if np.isfinite(converted) else None
        if isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if np.isfinite(value) else None
        if isinstance(value, np.ndarray):
            return [PipelineAdapter._native(v) for v in value.tolist()]
        if isinstance(value, pd.Timestamp):
            return value.isoformat() if not pd.isna(value) else None
        if isinstance(value, dict):
            return {
                str(k): PipelineAdapter._native(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [PipelineAdapter._native(v) for v in value]
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return str(value)

    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = sorted(self.REQUIRED_INPUT_COLUMNS - set(df.columns))
        if missing:
            raise PipelineContractError(
                "Dataset is not compatible with the original SPARK "
                "clean-measurement format. Missing columns: "
                + ", ".join(missing)
            )
        if df.empty:
            raise PipelineContractError("Dataset contains no records.")

    # ------------------------------------------------------------------
    # UNAVAILABLE RESULTS
    # ------------------------------------------------------------------

    def _module_a_unavailable(
        self,
        message: str,
        *,
        component_id: Any = None,
    ) -> dict[str, Any]:
        return {
            "available": False,
            "mode": "ORIGINAL SPARK MODULE-A PIPELINE",
            "component_id": self._native(component_id),
            "action": None,
            "primary_reason": None,
            "ir_0h_uA": None,
            "ir_24h_uA": None,
            "within_lot_risk_score": None,
            "historical_risk_score": None,
            "lot_shift_risk_score": None,
            "batch_median_slope_0_24": None,
            "batch_slope_shift_score": None,
            "isolation_forest_raw_score": None,
            "isolation_forest_is_outlier": None,
            "static_limit_failed_at_24h": None,
            "metadata": self._native(self._module_a_metadata),
            "message": message,
        }

    def _module_b_unavailable(
        self,
        message: str,
        *,
        component_id: Any = None,
    ) -> dict[str, Any]:
        return {
            "available": False,
            "mode": "ORIGINAL SPARK MODULE-B PIPELINE",
            "model": None,
            "prediction": None,
            "prediction_168h_uA": None,
            "prediction_lower_05_uA": None,
            "prediction_median_50_uA": None,
            "prediction_upper_95_uA": None,
            "prediction_interval_width_uA": None,
            "predicted_slope_24_168_uA_per_h": None,
            "safety_margin_uA": None,
            "conformal_safety_upper_uA": None,
            "actual_ir_168h_uA": None,
            "absolute_prediction_error_uA": None,
            "component_id": self._native(component_id),
            "confidence": None,
            "score": None,
            "metadata": self._native(self._module_b_metadata),
            "message": message,
        }

    # Historical private name retained for compatibility with any local code.
    def _unavailable(self, message: str, *, component_id: Any = None) -> dict:
        return self._module_b_unavailable(
            message,
            component_id=component_id,
        )

    # ------------------------------------------------------------------
    # CACHED FEATURE / MODEL EXECUTION
    # ------------------------------------------------------------------

    def _prepare_evidence(
        self,
        df: pd.DataFrame,
        *,
        cache_key: str | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None, Any, bool]:
        if cache_key:
            with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    return (
                        cached["features"],
                        cached.get("module_a"),
                        cached.get("module_b"),
                        cached.get("build_report"),
                        True,
                    )

        if self._feature_builder is None:
            raise PipelineContractError(
                self._feature_load_error
                or "Original SPARK feature engineering is unavailable."
            )

        features, build_report = self._feature_builder(df)
        if not isinstance(features, pd.DataFrame):
            raise PipelineContractError(
                "Original build_feature_table() did not return a DataFrame."
            )
        if features.empty:
            raise PipelineContractError(
                "Original feature engineering returned no rows."
            )
        if "component_id" not in features.columns:
            raise PipelineContractError(
                "Original feature table is missing component_id."
            )

        module_a_output: pd.DataFrame | None = None
        if (
            self._module_a_load_error is None
            and self._module_a_score_function is not None
            and self._module_a_model is not None
        ):
            module_a_output = self._module_a_score_function(
                features,
                self._module_a_model,
            )
            if not isinstance(module_a_output, pd.DataFrame):
                raise PipelineContractError(
                    "Original score_module_a() did not return a DataFrame."
                )
            if "component_id" not in module_a_output.columns:
                raise PipelineContractError(
                    "Original Module-A output is missing component_id."
                )

        module_b_output: pd.DataFrame | None = None
        if (
            self._module_b_load_error is None
            and self._module_b_predict_function is not None
            and self._module_b_bundle is not None
        ):
            module_b_output = self._module_b_predict_function(
                features,
                self._module_b_bundle,
            )
            if not isinstance(module_b_output, pd.DataFrame):
                raise PipelineContractError(
                    "Original predict_module_b() did not return a DataFrame."
                )
            if "component_id" not in module_b_output.columns:
                raise PipelineContractError(
                    "Original Module-B output is missing component_id."
                )

        if cache_key:
            with self._cache_lock:
                self._cache[cache_key] = {
                    "features": features,
                    "module_a": module_a_output,
                    "module_b": module_b_output,
                    "build_report": build_report,
                }

        return (
            features,
            module_a_output,
            module_b_output,
            build_report,
            False,
        )

    # Backward-compatible helper retained for previous tests/internals.
    def _prepare_predictions(
        self,
        df: pd.DataFrame,
        *,
        cache_key: str | None,
    ) -> tuple[pd.DataFrame, Any, bool]:
        _, _, module_b_output, build_report, cache_hit = self._prepare_evidence(
            df,
            cache_key=cache_key,
        )
        if module_b_output is None:
            raise PipelineContractError(
                self._module_b_load_error
                or "Original Module-B inference is unavailable."
            )
        return module_b_output, build_report, cache_hit

    def invalidate(self, cache_key: str | None = None) -> None:
        with self._cache_lock:
            if cache_key is None:
                self._cache.clear()
            else:
                self._cache.pop(cache_key, None)

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        module_a_path = self._module_a_model_path()
        module_b_path = self._module_b_model_path()

        module_a_loaded = (
            self._feature_builder is not None
            and self._module_a_load_error is None
            and self._module_a_score_function is not None
            and self._module_a_model is not None
        )
        module_b_loaded = (
            self._feature_builder is not None
            and self._module_b_load_error is None
            and self._module_b_predict_function is not None
            and self._module_b_bundle is not None
        )

        selected_model = None
        if self._module_b_bundle is not None:
            selected_model = getattr(
                self._module_b_bundle,
                "selected_model_name",
                None,
            )

        with self._cache_lock:
            cache_entries = len(self._cache)

        module_a_status = {
            "available": module_a_loaded,
            "model_path": str(module_a_path),
            "model_exists": module_a_path.exists(),
            "score_function_loaded": self._module_a_score_function is not None,
            "model_loaded": self._module_a_model is not None,
            "metadata": self._native(self._module_a_metadata),
            "message": (
                "Original SPARK Module-A dynamic anomaly pipeline loaded successfully."
                if module_a_loaded
                else (
                    self._module_a_load_error
                    or "Original SPARK Module-A pipeline is not loaded."
                )
            ),
        }

        module_b_status = {
            "available": module_b_loaded,
            "model_path": str(module_b_path),
            "model_exists": module_b_path.exists(),
            "inference_function_loaded": self._module_b_predict_function is not None,
            "model_bundle_loaded": self._module_b_bundle is not None,
            "selected_model": selected_model,
            "metadata": self._native(self._module_b_metadata),
            "message": (
                "Original SPARK Module-B ML pipeline loaded successfully."
                if module_b_loaded
                else (
                    self._module_b_load_error
                    or "Original SPARK Module-B pipeline is not loaded."
                )
            ),
        }

        # Keep the existing top-level Module-B fields so previous UI/tools do
        # not break while exposing the richer dual-module status.
        return {
            "configured_root": str(self.root),
            "pipeline_accessible": self.root.exists(),
            "feature_engineering_loaded": self._feature_builder is not None,
            "feature_engineering_error": self._feature_load_error,
            "module_a_available": module_a_loaded,
            "module_b_available": module_b_loaded,
            "module_a": module_a_status,
            "module_b": module_b_status,
            "inference_function_loaded": self._module_b_predict_function is not None,
            "model_path": str(module_b_path),
            "model_exists": module_b_path.exists(),
            "model_bundle_loaded": self._module_b_bundle is not None,
            "prediction_available": module_b_loaded,
            "selected_model": selected_model,
            "cached_datasets": cache_entries,
            "mode": "ORIGINAL SPARK MODULE-A + MODULE-B PIPELINE",
            "message": (
                "Original SPARK Module-A and Module-B pipelines loaded successfully."
                if module_a_loaded and module_b_loaded
                else "SPARK pipeline loaded with one or more unavailable modules."
            ),
        }

    # ------------------------------------------------------------------
    # COMPONENT ASSESSMENT
    # ------------------------------------------------------------------

    def _module_a_for_component(
        self,
        output: pd.DataFrame | None,
        component_id: Any,
    ) -> dict[str, Any]:
        if self._module_a_load_error:
            return self._module_a_unavailable(
                "Original Module-A pipeline could not be loaded: "
                + self._module_a_load_error,
                component_id=component_id,
            )
        if self._module_a_model is None or self._module_a_score_function is None:
            return self._module_a_unavailable(
                "Original SPARK Module-A model is unavailable.",
                component_id=component_id,
            )
        if output is None or output.empty:
            return self._module_a_unavailable(
                "Original Module-A inference returned no rows.",
                component_id=component_id,
            )

        matches = output[
            output["component_id"].astype(str) == str(component_id)
        ]
        if matches.empty:
            return self._module_a_unavailable(
                "The selected component is not present in the Module-A output.",
                component_id=component_id,
            )

        row = matches.iloc[0]
        action = self._native(row.get("module_a_action"))
        return {
            "available": True,
            "mode": "ORIGINAL SPARK MODULE-A PIPELINE",
            "component_id": self._native(component_id),
            "action": action,
            "primary_reason": self._native(
                row.get("module_a_primary_reason")
            ),
            "ir_0h_uA": self._native(row.get("ir_0h_uA")),
            "ir_24h_uA": self._native(row.get("ir_24h_uA")),
            "within_lot_risk_score": self._native(
                row.get("within_lot_risk_score")
            ),
            "historical_risk_score": self._native(
                row.get("historical_risk_score")
            ),
            "lot_shift_risk_score": self._native(
                row.get("lot_shift_risk_score")
            ),
            "batch_median_slope_0_24": self._native(
                row.get("batch_median_slope_0_24")
            ),
            "batch_slope_shift_score": self._native(
                row.get("batch_slope_shift_score")
            ),
            "isolation_forest_raw_score": self._native(
                row.get("isolation_forest_raw_score")
            ),
            "isolation_forest_is_outlier": self._native(
                row.get("isolation_forest_is_outlier")
            ),
            "static_limit_failed_at_24h": self._native(
                row.get("static_limit_failed_at_24h")
            ),
            "metadata": self._native(self._module_a_metadata),
            "message": (
                "Dynamic anomaly evidence generated by the original SPARK "
                "Module-A 24-hour pipeline."
            ),
        }

    def _module_b_for_component(
        self,
        output: pd.DataFrame | None,
        component_id: Any,
    ) -> dict[str, Any]:
        if self._module_b_load_error:
            return self._module_b_unavailable(
                "Original Module-B pipeline could not be loaded: "
                + self._module_b_load_error,
                component_id=component_id,
            )
        if self._module_b_bundle is None or self._module_b_predict_function is None:
            return self._module_b_unavailable(
                "Original SPARK Module-B model bundle is unavailable.",
                component_id=component_id,
            )
        if output is None or output.empty:
            return self._module_b_unavailable(
                "Original Module-B inference returned no rows.",
                component_id=component_id,
            )

        matches = output[
            output["component_id"].astype(str) == str(component_id)
        ]
        if matches.empty:
            return self._module_b_unavailable(
                "The selected component is not present in the Module-B "
                "prediction output.",
                component_id=component_id,
            )

        row = matches.iloc[0]
        available = bool(row.get("module_b_prediction_available", False))
        if not available:
            return self._module_b_unavailable(
                "Module-B inference is unavailable because the original "
                "pipeline marked this component unusable at 24h.",
                component_id=component_id,
            )

        return {
            "available": True,
            "mode": "ORIGINAL SPARK MODULE-B PIPELINE",
            "model": self._native(row.get("selected_model")),
            "prediction": self._native(row.get("predicted_ir_168h_uA")),
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
            "safety_margin_uA": self._native(row.get("safety_margin_uA")),
            "conformal_safety_upper_uA": self._native(
                row.get("conformal_safety_upper_uA")
            ),
            "actual_ir_168h_uA": self._native(
                row.get("actual_ir_168h_uA")
            ),
            "absolute_prediction_error_uA": self._native(
                row.get("absolute_prediction_error_uA")
            ),
            "component_id": self._native(component_id),
            "confidence": None,
            "score": None,
            "metadata": self._native(self._module_b_metadata),
            "message": (
                "Prediction generated by the original SPARK Module-B "
                "trained pipeline."
            ),
        }

    def assess(
        self,
        df: pd.DataFrame,
        index: int,
        *,
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        if index < 0 or index >= len(df):
            raise IndexError("Record index is out of range.")

        component_id = (
            df.iloc[index].get("component_id")
            if "component_id" in df.columns
            else None
        )

        try:
            self._validate_input(df)
            (
                _features,
                module_a_output,
                module_b_output,
                build_report,
                cache_hit,
            ) = self._prepare_evidence(
                df,
                cache_key=cache_key,
            )

            component_id = df.iloc[index]["component_id"]
            module_a = self._module_a_for_component(
                module_a_output,
                component_id,
            )
            module_b = self._module_b_for_component(
                module_b_output,
                component_id,
            )

            # Preserve the old Module-B top-level contract while adding the
            # original Module-A evidence as a nested result.
            result = dict(module_b)
            result.update(
                {
                    "mode": "ORIGINAL SPARK MODULE-A + MODULE-B PIPELINE",
                    "component_id": self._native(component_id),
                    "module_a": module_a,
                    "module_b": module_b,
                    "module_a_available": module_a.get("available", False),
                    "module_b_available": module_b.get("available", False),
                    "cache_hit": cache_hit,
                }
            )

            if hasattr(build_report, "__dict__"):
                result["feature_build"] = self._native(vars(build_report))

            return result

        except Exception as exc:
            message = "Original SPARK feature/model inference failed safely: " + str(exc)
            module_a = self._module_a_unavailable(
                message,
                component_id=component_id,
            )
            module_b = self._module_b_unavailable(
                message,
                component_id=component_id,
            )
            result = dict(module_b)
            result.update(
                {
                    "mode": "ORIGINAL SPARK MODULE-A + MODULE-B PIPELINE",
                    "module_a": module_a,
                    "module_b": module_b,
                    "module_a_available": False,
                    "module_b_available": False,
                    "cache_hit": False,
                }
            )
            return result
