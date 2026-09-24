from __future__ import annotations

import datetime as dt
import math
import os
import uuid
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


# ============================================================
# APPLICATION PATHS
# ============================================================

BASE = os.path.dirname(os.path.abspath(__file__))

DATA = os.path.join(BASE, "data")

PIPELINE = os.environ.get(
    "SPARK_PIPELINE_ROOT",
    r"C:\Users\anish\OneDrive\Desktop\SPARK_PHASE1",
)


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


# ============================================================
# MANAGERS
# ============================================================

dm = DatasetManager(DATA)

qa = QAManager(
    os.path.join(DATA, "qa")
)

ml = PipelineAdapter(PIPELINE)


# ============================================================
# JSON SERIALIZATION
# ============================================================
#
# Pandas / NumPy frequently return values such as:
#
#   numpy.int64
#   numpy.float64
#   numpy.bool_
#   numpy.ndarray
#   pandas.Timestamp
#   pandas.NA
#
# Flask's JSON encoder does not serialize all of these
# automatically.
#
# This function recursively converts them into standard
# JSON-compatible Python values.
# ============================================================


def _json_safe(value: Any) -> Any:
    """
    Recursively convert NumPy/Pandas/Python objects into
    values that can safely be serialized as JSON.

    Supported:
        - NumPy integer
        - NumPy floating point
        - NumPy boolean
        - NumPy arrays
        - Pandas Timestamp
        - Pandas Timedelta
        - Pandas NA / NaN
        - Python datetime/date/time
        - UUID
        - pathlib.Path
        - dict
        - list
        - tuple
        - set
    """

    # --------------------------------------------------------
    # None / standard JSON values
    # --------------------------------------------------------

    if value is None:
        return None

    if isinstance(value, (str, bool, int)):
        return value

    # --------------------------------------------------------
    # Python floating point
    # --------------------------------------------------------

    if isinstance(value, float):
        if not math.isfinite(value):
            return None

        return value

    # --------------------------------------------------------
    # NumPy scalar values
    # --------------------------------------------------------

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        numeric_value = float(value)

        if not math.isfinite(numeric_value):
            return None

        return numeric_value

    if isinstance(value, np.bool_):
        return bool(value)

    # --------------------------------------------------------
    # NumPy arrays
    # --------------------------------------------------------

    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]

    # --------------------------------------------------------
    # Pandas missing values
    # --------------------------------------------------------

    if value is pd.NA:
        return None

    # --------------------------------------------------------
    # Pandas Timestamp
    # --------------------------------------------------------

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None

        return value.isoformat()

    # --------------------------------------------------------
    # Pandas Timedelta
    # --------------------------------------------------------

    if isinstance(value, pd.Timedelta):
        return value.total_seconds()

    # --------------------------------------------------------
    # Python date / datetime / time
    # --------------------------------------------------------

    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()

    # --------------------------------------------------------
    # Python timedelta
    # --------------------------------------------------------

    if isinstance(value, dt.timedelta):
        return value.total_seconds()

    # --------------------------------------------------------
    # UUID
    # --------------------------------------------------------

    if isinstance(value, uuid.UUID):
        return str(value)

    # --------------------------------------------------------
    # pathlib.Path
    # --------------------------------------------------------

    if isinstance(value, Path):
        return str(value)

    # --------------------------------------------------------
    # Dictionary
    # --------------------------------------------------------

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    # --------------------------------------------------------
    # List / tuple / set / frozenset
    # --------------------------------------------------------

    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _json_safe(item)
            for item in value
        ]

    # --------------------------------------------------------
    # Generic Pandas / NumPy scalar fallback
    # --------------------------------------------------------

    if hasattr(value, "item"):
        try:
            converted = value.item()

            if converted is not value:
                return _json_safe(converted)

        except Exception:
            pass

    # --------------------------------------------------------
    # Generic iterable fallback
    # --------------------------------------------------------

    if hasattr(value, "tolist"):
        try:
            converted = value.tolist()

            if converted is not value:
                return _json_safe(converted)

        except Exception:
            pass

    # --------------------------------------------------------
    # Final fallback
    # --------------------------------------------------------
    #
    # Do not crash the API because an unusual value was returned.
    # Converting unknown objects to string is safer than returning
    # a serialization exception.
    #
    # --------------------------------------------------------

    return str(value)


def safe_jsonify(data: Any = None, status_code: int | None = None, **kwargs):
    """
    Centralized JSON response helper.

    Every response passes through _json_safe() before Flask
    serializes it.
    """

    cleaned = _json_safe(data)

    if kwargs:
        cleaned_kwargs = _json_safe(kwargs)

        if isinstance(cleaned, dict):
            cleaned.update(cleaned_kwargs)
        else:
            cleaned = cleaned_kwargs

    if status_code is None:
        return jsonify(cleaned)

    return jsonify(cleaned), status_code


# ============================================================
# HEALTH
# ============================================================


@app.get("/api/health")
def health():
    return safe_jsonify(
        {
            "status": "ok",
            "service": "SPARK Engineering Quality Intelligence",
            "version": "6.0.0",
        }
    )


# ============================================================
# HOME
# ============================================================


@app.get("/")
def index():
    return render_template("index.html")


# ============================================================
# DATASET LIST
# ============================================================


@app.get("/api/datasets")
def list_datasets():
    try:
        datasets = dm.list()

        return safe_jsonify(
            {
                "datasets": datasets
            }
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )


# ============================================================
# DATASET UPLOAD
# ============================================================


@app.post("/api/datasets/upload")
def upload():
    file = request.files.get("file")

    if not file or not file.filename:
        return safe_jsonify(
            {
                "detail": "Select a CSV or Excel dataset."
            },
            400,
        )

    try:
        result = dm.save_upload(file)

        return safe_jsonify(
            result,
            201,
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            400,
        )


# ============================================================
# DATASET ACTIVATE
# ============================================================


@app.post("/api/datasets/<dataset_id>/activate")
def activate(dataset_id):
    try:
        result = dm.activate(dataset_id)

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )


# ============================================================
# DATASET DELETE
# ============================================================


@app.delete("/api/datasets/<dataset_id>")
def remove(dataset_id):
    try:
        result = dm.remove(dataset_id)

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )


# ============================================================
# DATASET ANALYSIS
# ============================================================


@app.get("/api/datasets/<dataset_id>/analysis")
def analysis(dataset_id):
    try:
        _, df = dm.get(dataset_id)

        result = analyze_dataset(df)

        # Important:
        # analyze_dataset() may contain NumPy/Pandas values such as
        # numpy.int64, numpy.float64, numpy.bool_, etc.
        #
        # safe_jsonify() recursively converts all of them.
        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )


# ============================================================
# SIGNAL CONTROL
# ============================================================


@app.get("/api/datasets/<dataset_id>/signals/<path:column>/control")
def control(dataset_id, column):
    try:
        _, df = dm.get(dataset_id)

        result = signal_control(df, column)

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )

    except KeyError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            400,
        )


# ============================================================
# RECORD ASSESSMENT
# ============================================================


@app.get("/api/datasets/<dataset_id>/records/<int:index>/assessment")
def assessment(dataset_id, index):
    try:
        _, df = dm.get(dataset_id)

        result = record_assessment(
            df,
            index,
        )

        model_result = ml.assess(
            df,
            index,
        )

        result["model"] = model_result

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )

    except IndexError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            400,
        )

    except KeyError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            400,
        )


# ============================================================
# DATASET COMPARISON
# ============================================================


@app.get("/api/datasets/<dataset_id>/comparison")
def comparison(dataset_id):
    try:
        _, df = dm.get(dataset_id)

        result = dataset_comparison(df)

        return safe_jsonify(result)

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )


# ============================================================
# QA LIST
# ============================================================


@app.get("/api/qa/<dataset_id>")
def qa_list(dataset_id):
    try:
        items = qa.list(dataset_id)

        return safe_jsonify(
            {
                "items": items
            }
        )

    except Exception as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            500,
        )


# ============================================================
# QA SAVE
# ============================================================


@app.post("/api/qa/<dataset_id>")
def qa_save(dataset_id):
    try:
        dm.get(dataset_id)

        payload = request.get_json(
            silent=True
        ) or {}

        result = qa.save(
            dataset_id,
            payload,
        )

        return safe_jsonify(
            result,
            201,
        )

    except DatasetError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            404,
        )

    except ValueError as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            400,
        )


# ============================================================
# PIPELINE STATUS
# ============================================================


@app.get("/api/pipeline/status")
def pipeline_status():
    try:
        result = ml.status()

        return safe_jsonify(result)

    except Exception as exc:
        return safe_jsonify(
            {
                "detail": str(exc)
            },
            500,
        )


# ============================================================
# APPLICATION ERROR HANDLER
# ============================================================
#
# This prevents unexpected backend exceptions from returning
# an HTML Flask error page to the frontend.
#
# The actual exception is still printed to the console for
# debugging.
# ============================================================


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


# ============================================================
# APPLICATION START
# ============================================================


if __name__ == "__main__":
    app.run(
        host=os.environ.get(
            "SPARK_HOST",
            "127.0.0.1",
        ),
        port=int(
            os.environ.get(
                "SPARK_PORT",
                "5000",
            )
        ),
        debug=False,
    )