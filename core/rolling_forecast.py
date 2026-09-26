from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _value_at(rows: pd.DataFrame, hour: int) -> float | None:
    if not {"measurement_time_h", "leakage_current_uA"}.issubset(rows.columns):
        return None
    mask = pd.to_numeric(rows["measurement_time_h"], errors="coerce") == hour
    vals = pd.to_numeric(rows.loc[mask, "leakage_current_uA"], errors="coerce")
    vals = vals[np.isfinite(vals)]
    return float(vals.iloc[-1]) if not vals.empty else None


def rolling_forecast_update(
    df: pd.DataFrame,
    raw_index: int,
    module_b_24h: dict[str, Any],
) -> dict[str, Any]:
    """Create a transparent 96h evidence update around the trained 24h forecast.

    No 96h ML model is fabricated. If 96h evidence exists, SPARK computes a
    deterministic linear trajectory projection from 24h->96h to 168h and keeps
    it explicitly labelled as an engineering update, separate from Module-B ML.
    """
    if raw_index < 0 or raw_index >= len(df):
        raise IndexError("Record index is out of range.")
    if "component_id" not in df.columns:
        return {"available": False, "status": "UNAVAILABLE", "reason": "component_id is missing."}

    component_id = df.iloc[raw_index].get("component_id")
    rows = df[df["component_id"].astype(str) == str(component_id)]
    ir24 = _value_at(rows, 24)
    ir96 = _value_at(rows, 96)
    ir168 = _value_at(rows, 168)
    f24 = _finite(module_b_24h.get("prediction_168h_uA"))

    upper_limit = None
    if "datasheet_upper_limit_uA" in rows.columns:
        vals = pd.to_numeric(rows["datasheet_upper_limit_uA"], errors="coerce")
        vals = vals[np.isfinite(vals)]
        if not vals.empty:
            upper_limit = float(vals.iloc[-1])

    result: dict[str, Any] = {
        "available": f24 is not None,
        "component_id": component_id,
        "status": "WAITING_FOR_96H" if ir96 is None else "UPDATED_AT_96H",
        "module_b_24h_forecast_168h_uA": f24,
        "observed_ir_24h_uA": ir24,
        "observed_ir_96h_uA": ir96,
        "actual_ir_168h_uA": ir168,
        "engineering_limit_uA": upper_limit,
        "update_method": "96H_LINEAR_ENGINEERING_TRAJECTORY",
        "is_trained_96h_ml_model": False,
        "message": (
            "The 24h value is the original trained Module-B forecast. The 96h update, when present, "
            "is a transparent engineering trajectory projection and is not represented as a trained ML model."
        ),
    }

    if f24 is None:
        result.update({"status": "MODULE_B_24H_UNAVAILABLE", "trajectory": "INDETERMINATE"})
        return result
    if ir24 is None or ir96 is None:
        result.update({"trajectory": "WAITING", "forecast_shift_uA": None, "updated_168h_uA": None})
        return result

    slope = (ir96 - ir24) / 72.0
    updated = ir96 + slope * 72.0
    shift = updated - f24
    tolerance = max(1.0, (upper_limit * 0.05) if upper_limit else abs(f24) * 0.10)
    if shift > tolerance:
        trajectory = "DETERIORATING"
    elif shift < -tolerance:
        trajectory = "IMPROVING"
    else:
        trajectory = "STABLE"

    result.update({
        "updated_168h_uA": round(float(updated), 6),
        "forecast_shift_uA": round(float(shift), 6),
        "observed_slope_24_96_uA_per_h": round(float(slope), 8),
        "trajectory": trajectory,
        "stability_tolerance_uA": round(float(tolerance), 6),
    })
    if ir168 is not None:
        result["module_b_24h_absolute_error_uA"] = round(abs(ir168 - f24), 6)
        result["engineering_96h_update_absolute_error_uA"] = round(abs(ir168 - updated), 6)
        result["evaluation_only_actual_168h"] = True
    return result
