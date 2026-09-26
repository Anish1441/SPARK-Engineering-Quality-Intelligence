from __future__ import annotations

import datetime as dt
import math
import threading
import time
import uuid
import webbrowser
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

from core.config import load_settings
from core.dataset_manager import DatasetManager, DatasetError
from core.analysis_engine import (
    analyze_dataset,
    record_assessment,
    signal_control,
    dataset_comparison,
)
from core.qa_manager import QAManager
from core.pipeline_adapter import PipelineAdapter
from core.inspection import resolve_inspection_target
from core.gates import data_confidence_gate, engineering_safety_gate
from core.risk_engine import reliability_risk_engine
from core.explainability import build_decision_explanation
from core.model_registry import build_model_registry
from core.applicability import assess_model_applicability, applicability_summary
from core.drift import drift_snapshot
from core.rolling_forecast import rolling_forecast_update
from core.lot_intelligence import build_lot_intelligence
from core.commonality import commonality_engine
from core.calibration import calibration_monitor
from core.feedback_learning import governed_feedback_learning


# ---------------------------------------------------------------------------
# APPLICATION CONFIGURATION
# ---------------------------------------------------------------------------

SETTINGS = load_settings()
HOST = SETTINGS.host
PORT = SETTINGS.port


# ---------------------------------------------------------------------------
# APPLICATION INITIALIZATION
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

dm = DatasetManager(
    SETTINGS.data_dir,
    pipeline_root=SETTINGS.pipeline_root,
    sample_root=SETTINGS.sample_dir,
)
qa = QAManager(SETTINGS.qa_dir)

# IMPORTANT:
# This adapter loads the ORIGINAL SPARK Phase-1 Module-A and Module-B
# pipelines. No anomaly or prediction result is fabricated here.
ml = PipelineAdapter(SETTINGS.pipeline_root)


# ---------------------------------------------------------------------------
# JSON SAFETY
# ---------------------------------------------------------------------------

def _json_safe(value: Any) -> Any:
    """Convert NumPy/Pandas/Python values into JSON-safe values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        converted = float(value)
        return converted if math.isfinite(converted) else None

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]

    if value is pd.NA:
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat() if not pd.isna(value) else None

    if isinstance(value, pd.Timedelta):
        return value.total_seconds()

    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()

    if isinstance(value, dt.timedelta):
        return value.total_seconds()

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(k): _json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]

    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass

    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except Exception:
            pass

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return str(value)


def safe_jsonify(
    data: Any = None,
    status_code: int | None = None,
):
    """Return a Flask JSON response with all values normalized."""

    response = jsonify(_json_safe(data))

    if status_code is not None:
        return response, status_code

    return response


# ---------------------------------------------------------------------------
# QA COMMENT
# ---------------------------------------------------------------------------

def _qa_comment(
    statistical: dict[str, Any],
    model: dict[str, Any],
    data_confidence: dict[str, Any],
    engineering_safety: dict[str, Any],
    reliability_risk: dict[str, Any],
) -> str:
    """Generate a concise, evidence-only engineering statement.

    SPARK reports three separate evidence sources here: generic statistical
    context, original Phase-1 Module-A dynamic anomaly evidence, and original
    Phase-1 Module-B drift forecasting. The final QA disposition remains a
    human decision.
    """

    state = statistical.get("state", "REVIEW")
    score = statistical.get("score")
    contributors = statistical.get("contributors") or []

    if contributors:
        top = contributors[0]
        signal = top.get("signal", "the leading signal")
        robust_z = top.get("robust_z")
        evidence = f"{signal} is the leading statistical contributor"
        if isinstance(robust_z, (int, float)):
            evidence += f" at robust-z {robust_z:.2f}"
        evidence += "."
    else:
        evidence = (
            "No strong population-level numeric deviation was detected."
        )

    score_text = (
        f"{score}/100" if isinstance(score, (int, float))
        else "not available"
    )

    data_status = data_confidence.get("status", "UNAVAILABLE")
    data_score = data_confidence.get("score_pct")
    data_text = f" Data Trust Gate is {data_status}"
    if isinstance(data_score, (int, float)):
        data_text += f" at {data_score:.1f}% evidence confidence"
    data_text += "."

    safety_status = engineering_safety.get("status", "UNAVAILABLE")
    safety_text = f" Engineering Safety Gate is {safety_status}."
    if engineering_safety.get("reason"):
        safety_text += f" {engineering_safety['reason']}"

    module_a = model.get("module_a") or {}
    if module_a.get("available"):
        action = module_a.get("action") or "REVIEW"
        reason = module_a.get("primary_reason")
        a_text = (
            f" Original SPARK Module-A returned {action}."
        )
        if reason:
            a_text += f" {reason}"
    else:
        a_text = (
            " Original SPARK Module-A did not return dynamic anomaly "
            "evidence for this component."
        )

    module_b = model.get("module_b") or model
    prediction = module_b.get("prediction_168h_uA")
    lower = module_b.get("prediction_lower_05_uA")
    upper = module_b.get("prediction_upper_95_uA")
    selected_model = module_b.get("model")

    if module_b.get("available"):
        b_text = (
            " Original SPARK Module-B "
            f"({selected_model or 'selected model'}) returned a 168h prediction"
        )
        if isinstance(prediction, (int, float)):
            b_text += f" of {prediction:.3f} uA"
        if (
            isinstance(lower, (int, float))
            and isinstance(upper, (int, float))
        ):
            b_text += f" with a model interval of {lower:.3f}–{upper:.3f} uA"
        b_text += "."
    else:
        b_text = (
            " Original SPARK Module-B did not return a drift forecast for "
            "this component."
        )

    applicability = model.get("model_applicability") or {}
    applicability_text = (
        f" Model Applicability Gate is {applicability.get('status', 'UNAVAILABLE')}."
    )
    if applicability.get("reason"):
        applicability_text += f" {applicability['reason']}"

    rolling = model.get("rolling_forecast") or {}
    rolling_text = ""
    if rolling:
        rolling_text = (
            f" Rolling 96h evidence update is {rolling.get('trajectory') or rolling.get('status') or 'UNAVAILABLE'}."
        )
        if isinstance(rolling.get("forecast_shift_uA"), (int, float)):
            rolling_text += f" Forecast shift is {rolling['forecast_shift_uA']:.3f} uA."

    risk_action = reliability_risk.get("unified_action", "HOLD")
    risk_band = reliability_risk.get("risk_band", "INDETERMINATE")
    risk_score = reliability_risk.get("reliability_risk_score")
    risk_text = f" Unified Reliability Risk Engine recommends {risk_action} ({risk_band})"
    if isinstance(risk_score, (int, float)):
        risk_text += f" with prioritisation index {risk_score:.1f}/100"
    risk_text += "."
    if reliability_risk.get("reason"):
        risk_text += f" {reliability_risk['reason']}"

    return (
        f"Statistical assessment is {state} with an analytical score of "
        f"{score_text}. {evidence}{data_text}{safety_text}{applicability_text}{a_text}{b_text}{rolling_text}{risk_text}"
    )




# ---------------------------------------------------------------------------
# PHASE 8 REFERENCE DATA / MODEL HEALTH
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _phase1_reference_df() -> pd.DataFrame | None:
    """Load the original Phase-1 clean dataset for contract/OOD reference.

    The original file remains read-only. If it is unavailable, Phase 8 fails
    closed to caution rather than fabricating a training reference.
    """
    path = (
        SETTINGS.pipeline_root
        / "data"
        / "processed"
        / "02_clean_measurements_long.csv"
    )
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    if "dataset_split" in frame.columns:
        train = frame[
            frame["dataset_split"].astype(str).str.lower().eq("train")
        ]
        if not train.empty:
            return train
    return frame


def _population_evidence(df: pd.DataFrame, cache_key: str | None = None) -> dict[str, Any]:
    try:
        return ml.evidence_tables(df, cache_key=cache_key)
    except Exception as exc:
        return {
            "features": pd.DataFrame(),
            "module_a": None,
            "module_b": None,
            "build_report": None,
            "cache_hit": False,
            "error": str(exc),
        }


def _model_health_payload(df: pd.DataFrame, *, cache_key: str | None = None) -> dict[str, Any]:
    pipeline_status = ml.status()
    reference = _phase1_reference_df()
    registry = build_model_registry(
        SETTINGS.pipeline_root,
        pipeline_status,
        df,
    )
    evidence = _population_evidence(df, cache_key=cache_key)
    return {
        "phase": 9,
        "mode": "SPARK MODEL HEALTH + CALIBRATION",
        "registry": registry,
        "applicability": applicability_summary(
            df,
            reference_df=reference,
        ),
        "drift": drift_snapshot(df),
        "calibration": calibration_monitor(evidence.get("module_b")),
        "pipeline": pipeline_status,
    }


def _lot_intelligence_payload(dataset_id: str, df: pd.DataFrame) -> dict[str, Any]:
    evidence = _population_evidence(df, cache_key=dataset_id)
    features = evidence.get("features")
    module_a = evidence.get("module_a")
    module_b = evidence.get("module_b")
    rows = qa.list(dataset_id)
    return {
        "phase": 9,
        "mode": "SPARK POPULATION INTELLIGENCE",
        "health": build_lot_intelligence(
            features,
            module_a,
            module_b,
            rows,
        ),
        "commonality": commonality_engine(
            df,
            features,
            module_a,
        ),
    }


def _apply_model_applicability(
    model: dict[str, Any],
    applicability: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed at the decision boundary when Module-B is not applicable."""
    if applicability.get("applicable") is True:
        return model

    safe = dict(model)
    raw_module_b = dict(model.get("module_b") or {})
    abstained = {
        "available": False,
        "mode": "SPARK MODULE-B APPLICABILITY GATE",
        "status": "ABSTAINED",
        "component_id": model.get("component_id"),
        "model": raw_module_b.get("model"),
        "prediction_168h_uA": None,
        "prediction_lower_05_uA": None,
        "prediction_median_50_uA": None,
        "prediction_upper_95_uA": None,
        "conformal_safety_upper_uA": None,
        "reason": applicability.get("reason"),
        "message": (
            "Module-B output is withheld from the reliability decision because "
            "the Phase-8 applicability gate did not authorize model use."
        ),
    }
    safe["module_b_diagnostic"] = raw_module_b
    safe["module_b"] = abstained
    safe["module_b_available"] = False
    safe["available"] = False
    safe["prediction"] = None
    safe["prediction_168h_uA"] = None
    safe["prediction_lower_05_uA"] = None
    safe["prediction_median_50_uA"] = None
    safe["prediction_upper_95_uA"] = None
    safe["conformal_safety_upper_uA"] = None
    safe["message"] = abstained["message"]
    return safe

# ---------------------------------------------------------------------------
# MAIN PAGE
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# HEALTH
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return safe_jsonify(
        {
            "status": "ok",
            "service": (
                "SPARK Engineering Quality Intelligence"
            ),
            "version": "9.0.0",
            "pipeline_root": str(SETTINGS.pipeline_root),
        }
    )


# ---------------------------------------------------------------------------
# DATASETS
# ---------------------------------------------------------------------------

@app.get("/api/datasets")
def list_datasets():
    try:
        return safe_jsonify(
            {
                "datasets": dm.list(),
            }
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )


@app.post("/api/datasets/upload")
def upload():
    file = request.files.get("file")

    if not file or not file.filename:
        return safe_jsonify(
            {
                "detail": (
                    "Select a CSV or Excel dataset."
                ),
            },
            400,
        )

    try:
        return safe_jsonify(
            dm.save_upload(file),
            201,
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            400,
        )


@app.post("/api/datasets/<dataset_id>/activate")
def activate(dataset_id):
    try:
        result = dm.activate(dataset_id)
        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )


@app.delete("/api/datasets/<dataset_id>")
def remove(dataset_id):
    try:
        result = dm.remove(dataset_id)
        result["qa_records_deleted"] = qa.delete_dataset(dataset_id)
        ml.invalidate(dataset_id)
        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            400,
        )


# ---------------------------------------------------------------------------
# DATASET ANALYSIS
# ---------------------------------------------------------------------------

@app.get("/api/datasets/<dataset_id>/analysis")
def analysis(dataset_id):
    try:
        _, df = dm.get(dataset_id)

        return safe_jsonify(
            analyze_dataset(df)
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )


# ---------------------------------------------------------------------------
# PHASE 8 MODEL HEALTH
# ---------------------------------------------------------------------------

@app.get("/api/datasets/<dataset_id>/model-health")
def model_health(dataset_id):
    try:
        _, df = dm.get(dataset_id)
        return safe_jsonify(_model_health_payload(df, cache_key=dataset_id))
    except DatasetError as exc:
        return safe_jsonify({"detail": str(exc)}, 404)


# ---------------------------------------------------------------------------
# PHASE 9 LOT / POPULATION INTELLIGENCE
# ---------------------------------------------------------------------------

@app.get("/api/datasets/<dataset_id>/lot-intelligence")
def lot_intelligence(dataset_id):
    try:
        _, df = dm.get(dataset_id)
        return safe_jsonify(_lot_intelligence_payload(dataset_id, df))
    except DatasetError as exc:
        return safe_jsonify({"detail": str(exc)}, 404)
    except ValueError as exc:
        return safe_jsonify({"detail": str(exc)}, 500)


# ---------------------------------------------------------------------------
# SIGNAL CONTROL
# ---------------------------------------------------------------------------

@app.get(
    "/api/datasets/<dataset_id>/signals/<path:column>/control"
)
def control(dataset_id, column):
    try:
        _, df = dm.get(dataset_id)

        return safe_jsonify(
            signal_control(
                df,
                column,
            )
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )

    except KeyError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            400,
        )


# ---------------------------------------------------------------------------
# RECORD / COMPONENT ASSESSMENT
# ---------------------------------------------------------------------------

@app.get(
    "/api/datasets/<dataset_id>/inspection/<int:index>/assessment"
)
@app.get(
    "/api/datasets/<dataset_id>/records/<int:index>/assessment"
)
def assessment(dataset_id, index):
    """
    Return statistical + ORIGINAL SPARK Module-A/Module-B assessment.

    Evidence path:

        Dataset
            ↓
        Original SPARK feature engineering
            ↓
        Module A: module_a_24h.joblib + score_module_a()
        Module B: module_b_24h.joblib + predict_module_b()
            ↓
        QA Inspector
    """

    try:
        # -----------------------------------------------------------
        # Load selected dataset
        # -----------------------------------------------------------

        _, df = dm.get(dataset_id)
        target = resolve_inspection_target(df, index)
        raw_index = target["record_index"]

        # -----------------------------------------------------------
        # Existing statistical assessment
        # -----------------------------------------------------------

        statistical = record_assessment(
            df,
            raw_index,
        )

        # -----------------------------------------------------------
        # PHASE 8 MODEL APPLICABILITY / OOD GATE
        # -----------------------------------------------------------

        model_applicability = assess_model_applicability(
            df,
            raw_index,
            reference_df=_phase1_reference_df(),
        )

        # -----------------------------------------------------------
        # REAL SPARK ML INFERENCE
        # -----------------------------------------------------------

        model = ml.assess(
            df,
            raw_index,
            cache_key=dataset_id,
        )
        model = _apply_model_applicability(
            model,
            model_applicability,
        )

        # -----------------------------------------------------------
        # SAFETY / DATA-TRUST GUARDRAILS (EARLY EVIDENCE <= 24h)
        # -----------------------------------------------------------

        data_confidence = data_confidence_gate(df, raw_index)
        engineering_safety = engineering_safety_gate(df, raw_index)

        # -----------------------------------------------------------
        # UNIFIED RELIABILITY RISK ENGINE
        # -----------------------------------------------------------

        module_a = model.get("module_a") or {}
        module_b = model.get("module_b") or model
        rolling_forecast = rolling_forecast_update(
            df,
            raw_index,
            module_b,
        )
        # Persist Phase-8 evidence through the existing model_snapshot field in
        # the governed QA ledger without changing historical schema-v7 hashes.
        model["model_applicability"] = model_applicability
        model["rolling_forecast"] = rolling_forecast
        reliability_risk = reliability_risk_engine(
            data_confidence,
            engineering_safety,
            module_a,
            module_b,
        )

        # -----------------------------------------------------------
        # DETERMINISTIC QA EXPLAINABILITY
        # -----------------------------------------------------------

        explanation = build_decision_explanation(
            data_confidence,
            engineering_safety,
            module_a,
            module_b,
            reliability_risk,
        )

        # -----------------------------------------------------------
        # API RESPONSE
        # -----------------------------------------------------------

        row = df.iloc[raw_index]

        result = {
            **statistical,
            "inspection_index": target["inspection_index"],
            "inspection_count": target["inspection_count"],
            "inspection_mode": target["inspection_mode"],

            "component_id": _json_safe(row.get("component_id")),
            "measurement_time_h": _json_safe(row.get("measurement_time_h")),
            "lot_id": _json_safe(row.get("lot_id")),
            "burnin_batch_id": _json_safe(row.get("burnin_batch_id")),

            # -------------------------------------------------------
            # Phase 8 applicability / rolling forecast
            # -------------------------------------------------------

            "model_applicability": model_applicability,
            "model_applicability_status": model_applicability.get("status"),
            "model_applicable": model_applicability.get("applicable"),
            "rolling_forecast": rolling_forecast,
            "rolling_forecast_status": rolling_forecast.get("status"),
            "rolling_forecast_trajectory": rolling_forecast.get("trajectory"),
            "rolling_forecast_updated_168h_uA": rolling_forecast.get("updated_168h_uA"),
            "rolling_forecast_shift_uA": rolling_forecast.get("forecast_shift_uA"),

            # -------------------------------------------------------
            # Data Trust / Engineering Safety guardrails
            # -------------------------------------------------------

            "data_confidence": data_confidence,
            "data_confidence_status": data_confidence.get("status"),
            "data_confidence_score_pct": data_confidence.get("score_pct"),
            "data_confidence_action": data_confidence.get("action"),
            "engineering_safety": engineering_safety,
            "engineering_safety_status": engineering_safety.get("status"),
            "engineering_safety_action": engineering_safety.get("action"),
            "engineering_safety_hard_failure": engineering_safety.get("hard_failure"),
            "engineering_safety_minimum_margin_uA": engineering_safety.get("minimum_margin_uA"),
            "engineering_safety_limit_uA": engineering_safety.get("engineering_limit_uA"),

            # -------------------------------------------------------
            # Unified Reliability Risk Engine
            # -------------------------------------------------------

            "reliability_risk": reliability_risk,
            "reliability_risk_score": reliability_risk.get("reliability_risk_score"),
            "reliability_risk_band": reliability_risk.get("risk_band"),
            "reliability_evidence_completeness_pct": reliability_risk.get("evidence_completeness_pct"),
            "reliability_unified_action": reliability_risk.get("unified_action"),
            "reliability_reason": reliability_risk.get("reason"),
            "reliability_forecast_limit_utilization_pct": reliability_risk.get("forecast_limit_utilization_pct"),

            # -------------------------------------------------------
            # Deterministic decision explanation / reason codes
            # -------------------------------------------------------

            "explanation": explanation,
            "primary_reason_code": explanation.get("primary_reason_code"),
            "primary_reason_title": explanation.get("primary_reason_title"),
            "primary_reason": explanation.get("primary_reason"),
            "reason_codes": explanation.get("reason_codes", []),
            "decision_path": explanation.get("decision_path", []),

            # Complete raw model response.
            "model": model,


            # -------------------------------------------------------
            # Original Module-A dynamic anomaly evidence
            # -------------------------------------------------------

            "module_a_available": module_a.get("available"),
            "module_a_action": module_a.get("action"),
            "module_a_primary_reason": module_a.get("primary_reason"),
            "module_a_ir_0h_uA": module_a.get("ir_0h_uA"),
            "module_a_ir_24h_uA": module_a.get("ir_24h_uA"),
            "module_a_within_lot_risk_score": module_a.get(
                "within_lot_risk_score"
            ),
            "module_a_historical_risk_score": module_a.get(
                "historical_risk_score"
            ),
            "module_a_lot_shift_risk_score": module_a.get(
                "lot_shift_risk_score"
            ),
            "module_a_batch_slope_shift_score": module_a.get(
                "batch_slope_shift_score"
            ),
            "module_a_isolation_forest_raw_score": module_a.get(
                "isolation_forest_raw_score"
            ),
            "module_a_isolation_forest_is_outlier": module_a.get(
                "isolation_forest_is_outlier"
            ),
            "module_a_static_limit_failed_at_24h": module_a.get(
                "static_limit_failed_at_24h"
            ),

            # -------------------------------------------------------
            # ML availability
            # -------------------------------------------------------

            "ai_available": module_b.get(
                "available"
            ),

            # -------------------------------------------------------
            # Actual selected model
            # -------------------------------------------------------

            "ai_model": module_b.get(
                "model"
            ),

            # -------------------------------------------------------
            # Real 168h prediction
            # -------------------------------------------------------

            "ai_prediction_168h_uA": module_b.get(
                "prediction_168h_uA"
            ),

            # -------------------------------------------------------
            # Real prediction interval
            # -------------------------------------------------------

            "ai_prediction_lower_05_uA": module_b.get(
                "prediction_lower_05_uA"
            ),

            "ai_prediction_median_50_uA": module_b.get(
                "prediction_median_50_uA"
            ),

            "ai_prediction_upper_95_uA": module_b.get(
                "prediction_upper_95_uA"
            ),

            "ai_prediction_interval_width_uA": module_b.get(
                "prediction_interval_width_uA"
            ),

            # -------------------------------------------------------
            # Predicted slope
            # -------------------------------------------------------

            "ai_predicted_slope_24_168_uA_per_h": module_b.get(
                "predicted_slope_24_168_uA_per_h"
            ),

            # -------------------------------------------------------
            # Safety information
            # -------------------------------------------------------

            "ai_safety_margin_uA": module_b.get(
                "safety_margin_uA"
            ),

            "ai_conformal_safety_upper_uA": module_b.get(
                "conformal_safety_upper_uA"
            ),

            # -------------------------------------------------------
            # Actual 168h value
            # -------------------------------------------------------

            "ai_actual_ir_168h_uA": module_b.get(
                "actual_ir_168h_uA"
            ),

            # -------------------------------------------------------
            # Prediction error
            # -------------------------------------------------------

            "ai_absolute_prediction_error_uA": module_b.get(
                "absolute_prediction_error_uA"
            ),

            # -------------------------------------------------------
            # Human-readable engineering statement
            # -------------------------------------------------------

            "qa_comment": _qa_comment(
                statistical,
                model,
                data_confidence,
                engineering_safety,
                reliability_risk,
            ),

            # -------------------------------------------------------
            # Traceability
            # -------------------------------------------------------

            "assessment_source": {
                "analytical": "SPARK statistical evidence",
                "data_confidence": "SPARK Data Trust Gate (0h/24h evidence quality)",
                "engineering_safety": "SPARK Engineering Safety Gate (documented hard limits)",
                "reliability_risk": "SPARK Unified Reliability Risk Engine (deterministic evidence fusion)",
                "explainability": "SPARK deterministic reason-code hierarchy (no LLM)",
                "model_applicability": "SPARK Phase-8 model-contract + robust OOD gate",
                "rolling_forecast": "SPARK Phase-8 96h engineering trajectory update; not a trained 96h ML model",
                "feature_engineering": (
                    "Original SPARK build_feature_table()"
                ),
                "module_a": {
                    "source": "Original SPARK Module-A dynamic anomaly pipeline",
                    "inference": "score_module_a()",
                    "model_artifact": "module_a_24h.joblib",
                },
                "module_b": {
                    "source": "Original SPARK Module-B trained ML pipeline",
                    "inference": "predict_module_b()",
                    "model_artifact": "module_b_24h.joblib",
                },
            },
        }

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )

    except (IndexError, KeyError) as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            400,
        )


# ---------------------------------------------------------------------------
# DATASET COMPARISON
# ---------------------------------------------------------------------------

@app.get("/api/datasets/<dataset_id>/comparison")
def comparison(dataset_id):
    try:
        _, df = dm.get(dataset_id)

        return safe_jsonify(
            dataset_comparison(df)
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )


# ---------------------------------------------------------------------------
# QA RECORDS
# ---------------------------------------------------------------------------

@app.get("/api/qa/<dataset_id>")
def qa_list(dataset_id):
    try:
        dm.get(dataset_id)

        return safe_jsonify(
            {
                "items": qa.list(dataset_id),
            }
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )

    except ValueError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            500,
        )


@app.get("/api/qa/<dataset_id>/integrity")
def qa_integrity(dataset_id):
    try:
        dm.get(dataset_id)
        return safe_jsonify(qa.verify(dataset_id))
    except DatasetError as exc:
        return safe_jsonify({"detail": str(exc)}, 404)
    except ValueError as exc:
        return safe_jsonify({"detail": str(exc)}, 500)


@app.get("/api/qa/<dataset_id>/feedback-summary")
def qa_feedback_summary(dataset_id):
    try:
        dm.get(dataset_id)
        return safe_jsonify(qa.feedback_summary(dataset_id))
    except DatasetError as exc:
        return safe_jsonify({"detail": str(exc)}, 404)
    except ValueError as exc:
        return safe_jsonify({"detail": str(exc)}, 500)


@app.get("/api/qa/<dataset_id>/feedback-learning")
def qa_feedback_learning(dataset_id):
    try:
        dm.get(dataset_id)
        return safe_jsonify(governed_feedback_learning(qa.list(dataset_id)))
    except DatasetError as exc:
        return safe_jsonify({"detail": str(exc)}, 404)
    except ValueError as exc:
        return safe_jsonify({"detail": str(exc)}, 500)


@app.post("/api/qa/<dataset_id>")
def qa_save(dataset_id):
    try:
        dm.get(dataset_id)

        payload = request.get_json(
            silent=True
        ) or {}

        return safe_jsonify(
            qa.save(
                dataset_id,
                payload,
            ),
            201,
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
        )

    except ValueError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            400,
        )


# ---------------------------------------------------------------------------
# ML PIPELINE STATUS
# ---------------------------------------------------------------------------

@app.get("/api/pipeline/status")
def pipeline_status():
    """
    Return the real SPARK ML pipeline status.

    This endpoint does not perform inference.
    """

    return safe_jsonify(
        ml.status()
    )


# ---------------------------------------------------------------------------
# GLOBAL ERROR HANDLER
# ---------------------------------------------------------------------------

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception(
        "Unhandled application exception: %s",
        error,
    )

    return safe_jsonify(
        {
            "detail": "Internal server error.",
            "error_type": type(error).__name__,
        },
        500,
    )


# ---------------------------------------------------------------------------
# AUTO-OPEN BROWSER
# ---------------------------------------------------------------------------

def _open_browser():
    time.sleep(1.2)

    webbrowser.open(
        f"http://{HOST}:{PORT}",
        new=2,
    )


# ---------------------------------------------------------------------------
# APPLICATION ENTRYPOINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    threading.Thread(
        target=_open_browser,
        daemon=True,
    ).start()

    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False,
    )