from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _state(observed: float, expected: float, *, warn_gap: float = 3.0, alert_gap: float = 7.0) -> str:
    gap = observed - expected
    if gap < -alert_gap:
        return "UNDER_COVERAGE"
    if gap < -warn_gap:
        return "WATCH"
    if gap > alert_gap:
        return "OVER_COVERAGE"
    return "CALIBRATED"


def calibration_monitor(module_b: pd.DataFrame | None) -> dict[str, Any]:
    """Backtest Module-B interval coverage on rows with evaluation truth.

    This monitor never changes production thresholds automatically. It produces
    a recalibration-review signal only.
    """
    if module_b is None or module_b.empty:
        return {"available": False, "status": "UNAVAILABLE", "metrics": []}

    frame = module_b.copy()
    actual_col = "actual_ir_168h_uA"
    lower_col = "prediction_lower_05_uA"
    upper_col = "prediction_upper_95_uA"
    conf_col = "conformal_safety_upper_uA"
    required = [actual_col, lower_col, upper_col]
    if any(c not in frame.columns for c in required):
        return {"available": False, "status": "UNAVAILABLE", "metrics": []}

    actual = pd.to_numeric(frame[actual_col], errors="coerce")
    lower = pd.to_numeric(frame[lower_col], errors="coerce")
    upper = pd.to_numeric(frame[upper_col], errors="coerce")
    valid = actual.notna() & lower.notna() & upper.notna()
    n = int(valid.sum())
    if n < 20:
        return {
            "available": True,
            "status": "INSUFFICIENT_EVALUATION_DATA",
            "evaluation_components": n,
            "metrics": [],
            "auto_recalibration": False,
        }

    interval_covered = ((actual[valid] >= lower[valid]) & (actual[valid] <= upper[valid])).mean() * 100.0
    interval_coverage = round(float(interval_covered), 2)
    metrics: list[dict[str, Any]] = [{
        "metric": "central_90_interval_coverage",
        "expected_pct": 90.0,
        "observed_pct": interval_coverage,
        "gap_percentage_points": round(interval_coverage - 90.0, 2),
        "state": _state(interval_coverage, 90.0),
        "n": n,
    }]

    if conf_col in frame.columns:
        conf = pd.to_numeric(frame[conf_col], errors="coerce")
        v = actual.notna() & conf.notna()
        if int(v.sum()) >= 20:
            one_sided = round(float((actual[v] <= conf[v]).mean() * 100.0), 2)
            metrics.append({
                "metric": "one_sided_safety_upper_coverage",
                "expected_pct": 99.5,
                "observed_pct": one_sided,
                "gap_percentage_points": round(one_sided - 99.5, 2),
                "state": _state(one_sided, 99.5, warn_gap=1.5, alert_gap=4.0),
                "n": int(v.sum()),
            })

    states = {m["state"] for m in metrics}
    if "UNDER_COVERAGE" in states:
        status = "RECALIBRATION_REVIEW"
    elif "WATCH" in states:
        status = "WATCH"
    else:
        status = "CALIBRATED"

    return {
        "available": True,
        "status": status,
        "mode": "SPARK CALIBRATION MONITOR",
        "evaluation_components": n,
        "metrics": metrics,
        "recalibration_review_required": status == "RECALIBRATION_REVIEW",
        "auto_recalibration": False,
        "semantics": (
            "Observed interval coverage is backtested using evaluation-only 168h truth. "
            "The monitor can request review but never changes production calibration automatically."
        ),
    }
