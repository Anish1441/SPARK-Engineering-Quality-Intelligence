from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _finite_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values[np.isfinite(values)]


def _checkpoint_values(df: pd.DataFrame, hour: int) -> pd.Series:
    if not {"measurement_time_h", "leakage_current_uA"}.issubset(df.columns):
        return pd.Series(dtype=float)
    mask = pd.to_numeric(df["measurement_time_h"], errors="coerce") == hour
    return _finite_series(df.loc[mask, "leakage_current_uA"])


def _robust_shift(reference: pd.Series, current: pd.Series) -> dict[str, Any]:
    if len(reference) < 20 or len(current) < 5:
        return {"available": False, "reason": "Insufficient reference/current observations."}
    ref_median = float(reference.median())
    cur_median = float(current.median())
    ref_mad = float((reference - ref_median).abs().median())
    scale = max(1.4826 * ref_mad, 1e-9)
    shift = abs(cur_median - ref_median) / scale
    return {
        "available": True,
        "reference_median": ref_median,
        "current_median": cur_median,
        "reference_mad": ref_mad,
        "median_shift_robust_sigma": round(float(shift), 4),
        "reference_n": int(len(reference)),
        "current_n": int(len(current)),
    }


def _population_selector(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    if "dataset_split" in df.columns:
        split = df["dataset_split"].astype(str).str.lower()
        reference = df[split.eq("train")]
        current = df[~split.eq("train")]
        if not reference.empty and not current.empty:
            return reference, current, "train vs validation/test"
    if "lot_id" in df.columns:
        lots = [x for x in df["lot_id"].dropna().astype(str).unique().tolist() if x]
        if len(lots) >= 2:
            latest = lots[-1]
            return df[df["lot_id"].astype(str) != latest], df[df["lot_id"].astype(str) == latest], f"historical lots vs {latest}"
    return df.iloc[0:0], df, "reference unavailable"


def drift_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    """Compute an auditable dataset drift snapshot.

    This is recalculated on demand; it is not described as background streaming.
    """
    reference, current, comparison = _population_selector(df)
    metrics: list[dict[str, Any]] = []
    severities: list[str] = []

    for hour in (0, 24):
        metric = _robust_shift(_checkpoint_values(reference, hour), _checkpoint_values(current, hour))
        metric.update({"metric": f"leakage_{hour}h", "checkpoint_h": hour})
        if metric.get("available"):
            shift = float(metric["median_shift_robust_sigma"])
            if shift >= 3.5:
                severity = "ALERT"
            elif shift >= 2.0:
                severity = "WATCH"
            else:
                severity = "STABLE"
            metric["severity"] = severity
            severities.append(severity)
        metrics.append(metric)

    if "usable_for_ml" in df.columns and not reference.empty:
        ref_bad = 1.0 - reference["usable_for_ml"].astype(bool).mean()
        cur_bad = 1.0 - current["usable_for_ml"].astype(bool).mean()
        delta_pp = float((cur_bad - ref_bad) * 100.0)
        severity = "ALERT" if delta_pp >= 5 else "WATCH" if delta_pp >= 2 else "STABLE"
        metrics.append({
            "metric": "unusable_for_ml_rate",
            "available": True,
            "reference_pct": round(ref_bad * 100, 3),
            "current_pct": round(cur_bad * 100, 3),
            "delta_percentage_points": round(delta_pp, 3),
            "severity": severity,
        })
        severities.append(severity)

    overall = "UNAVAILABLE"
    if severities:
        overall = "ALERT" if "ALERT" in severities else "WATCH" if "WATCH" in severities else "STABLE"

    return {
        "available": bool(severities),
        "status": overall,
        "comparison": comparison,
        "reference_rows": int(len(reference)),
        "current_rows": int(len(current)),
        "metrics": metrics,
        "thresholds": {
            "median_shift_watch_robust_sigma": 2.0,
            "median_shift_alert_robust_sigma": 3.5,
            "unusable_rate_watch_delta_pp": 2.0,
            "unusable_rate_alert_delta_pp": 5.0,
        },
        "method": "ROBUST_POPULATION_SNAPSHOT",
        "continuous_semantics": (
            "Recompute this snapshot whenever new data are uploaded/activated; "
            "no background stream is claimed."
        ),
    }
