from __future__ import annotations

import datetime as dt
import math
import os
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

from core.dataset_manager import DatasetManager, DatasetError
from core.analysis_engine import (
    analyze_dataset,
    record_assessment,
    signal_control,
    dataset_comparison,
)
from core.qa_manager import QAManager
from core.pipeline_adapter import PipelineAdapter


# ---------------------------------------------------------------------------
# APPLICATION CONFIGURATION
# ---------------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

PIPELINE = os.environ.get(
    "SPARK_PIPELINE_ROOT",
    r"C:\Users\anish\OneDrive\Desktop\SPARK_PHASE1",
)

HOST = os.environ.get("SPARK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPARK_PORT", "5000"))


# ---------------------------------------------------------------------------
# APPLICATION INITIALIZATION
# ---------------------------------------------------------------------------

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

dm = DatasetManager(DATA)
qa = QAManager(os.path.join(DATA, "qa"))

# IMPORTANT:
# This adapter loads the ORIGINAL SPARK ML pipeline.
# No prediction is fabricated inside this application.
ml = PipelineAdapter(PIPELINE)


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
) -> str:
    """
    Generate a concise engineering evidence statement.

    The statement does not make the final QA disposition.
    It reports statistical evidence and the actual ML pipeline result.
    """

    state = statistical.get("state", "REVIEW")
    score = statistical.get("score")
    contributors = statistical.get("contributors") or []

    model_available = bool(model.get("available"))

    prediction = model.get("prediction_168h_uA")

    lower = model.get("prediction_lower_05_uA")
    upper = model.get("prediction_upper_95_uA")

    selected_model = model.get("model")

    # ---------------------------------------------------------------
    # Statistical evidence
    # ---------------------------------------------------------------

    if contributors:
        top = contributors[0]

        signal = top.get(
            "signal",
            "the leading signal",
        )

        robust_z = top.get("robust_z")

        evidence = (
            f"{signal} is the leading statistical contributor"
        )

        if isinstance(robust_z, (int, float)):
            evidence += f" at robust-z {robust_z:.2f}"

        evidence += "."

    else:
        evidence = (
            "No strong population-level numeric deviation "
            "was detected."
        )

    # ---------------------------------------------------------------
    # Statistical score
    # ---------------------------------------------------------------

    if isinstance(score, (int, float)):
        score_text = f"{score}/100"
    else:
        score_text = "not available"

    # ---------------------------------------------------------------
    # Real ML evidence
    # ---------------------------------------------------------------

    if model_available:
        model_text = (
            " The original SPARK Module-B ML pipeline "
            f"({selected_model or 'selected model'}) "
            "returned a 168h prediction"
        )

        if isinstance(prediction, (int, float)):
            model_text += f" of {prediction:.3f} uA"

        if (
            isinstance(lower, (int, float))
            and isinstance(upper, (int, float))
        ):
            model_text += (
                f" with a model interval of "
                f"{lower:.3f}–{upper:.3f} uA"
            )

        model_text += "."

    else:
        model_text = (
            " The original SPARK Module-B ML pipeline "
            "did not return an inference for this record."
        )

    return (
        f"Statistical assessment is {state} with an "
        f"analytical score of {score_text}. "
        f"{evidence}{model_text}"
    )


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
            "version": "7.0.0",
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
        return safe_jsonify(
            dm.remove(dataset_id)
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc),
            },
            404,
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
# RECORD ASSESSMENT
# ---------------------------------------------------------------------------

@app.get(
    "/api/datasets/<dataset_id>/records/<int:index>/assessment"
)
def assessment(dataset_id, index):
    """
    Return statistical + ORIGINAL SPARK ML assessment.

    ML path:

        Dataset
            ↓
        Original SPARK feature engineering
            ↓
        Original module_b_24h.joblib
            ↓
        Original predict_module_b()
            ↓
        QA Inspector
    """

    try:
        # -----------------------------------------------------------
        # Load selected dataset
        # -----------------------------------------------------------

        _, df = dm.get(dataset_id)

        # -----------------------------------------------------------
        # Existing statistical assessment
        # -----------------------------------------------------------

        statistical = record_assessment(
            df,
            index,
        )

        # -----------------------------------------------------------
        # REAL SPARK ML INFERENCE
        # -----------------------------------------------------------

        model = ml.assess(
            df,
            index,
        )

        # -----------------------------------------------------------
        # API RESPONSE
        # -----------------------------------------------------------

        result = {
            **statistical,

            # Complete raw model response.
            "model": model,

            # -------------------------------------------------------
            # ML availability
            # -------------------------------------------------------

            "ai_available": model.get(
                "available"
            ),

            # -------------------------------------------------------
            # Actual selected model
            # -------------------------------------------------------

            "ai_model": model.get(
                "model"
            ),

            # -------------------------------------------------------
            # Real 168h prediction
            # -------------------------------------------------------

            "ai_prediction_168h_uA": model.get(
                "prediction_168h_uA"
            ),

            # -------------------------------------------------------
            # Real prediction interval
            # -------------------------------------------------------

            "ai_prediction_lower_05_uA": model.get(
                "prediction_lower_05_uA"
            ),

            "ai_prediction_median_50_uA": model.get(
                "prediction_median_50_uA"
            ),

            "ai_prediction_upper_95_uA": model.get(
                "prediction_upper_95_uA"
            ),

            "ai_prediction_interval_width_uA": model.get(
                "prediction_interval_width_uA"
            ),

            # -------------------------------------------------------
            # Predicted slope
            # -------------------------------------------------------

            "ai_predicted_slope_24_168_uA_per_h": model.get(
                "predicted_slope_24_168_uA_per_h"
            ),

            # -------------------------------------------------------
            # Safety information
            # -------------------------------------------------------

            "ai_safety_margin_uA": model.get(
                "safety_margin_uA"
            ),

            "ai_conformal_safety_upper_uA": model.get(
                "conformal_safety_upper_uA"
            ),

            # -------------------------------------------------------
            # Actual 168h value
            # -------------------------------------------------------

            "ai_actual_ir_168h_uA": model.get(
                "actual_ir_168h_uA"
            ),

            # -------------------------------------------------------
            # Prediction error
            # -------------------------------------------------------

            "ai_absolute_prediction_error_uA": model.get(
                "absolute_prediction_error_uA"
            ),

            # -------------------------------------------------------
            # Human-readable engineering statement
            # -------------------------------------------------------

            "qa_comment": _qa_comment(
                statistical,
                model,
            ),

            # -------------------------------------------------------
            # Traceability
            # -------------------------------------------------------

            "assessment_source": {
                "analytical": (
                    "SPARK statistical evidence"
                ),
                "ml": (
                    "Original SPARK Module-B "
                    "trained ML pipeline"
                ),
                "feature_engineering": (
                    "Original SPARK "
                    "build_feature_table()"
                ),
                "inference": (
                    "Original SPARK "
                    "predict_module_b()"
                ),
                "model_artifact": (
                    "module_b_24h.joblib"
                ),
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