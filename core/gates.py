from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


EARLY_CHECKPOINTS = (0.0, 24.0)


def _native(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_native(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _component_id_for(df: pd.DataFrame, index: int) -> Any:
    if index < 0 or index >= len(df):
        raise IndexError("Record index is out of range.")
    if "component_id" not in df.columns:
        return None
    return df.iloc[index].get("component_id")


def _component_rows(df: pd.DataFrame, index: int) -> pd.DataFrame:
    component_id = _component_id_for(df, index)
    if component_id is None or "component_id" not in df.columns:
        return df.iloc[[index]].copy()
    return df.loc[df["component_id"].astype(str) == str(component_id)].copy()


def _checkpoint_rows(component: pd.DataFrame) -> pd.DataFrame:
    if "measurement_time_h" not in component.columns:
        return component.copy()
    time_h = pd.to_numeric(component["measurement_time_h"], errors="coerce")
    return component.loc[time_h.le(24.0)].copy()


def data_confidence_gate(df: pd.DataFrame, index: int) -> dict[str, Any]:
    """Evaluate whether early 0h/24h evidence is suitable for screening.

    The score is deliberately transparent: it is the percentage of applicable
    evidence-quality checks that pass. Required checkpoint/value failures force
    RETEST. The gate does not infer component reliability; it only judges input
    evidence quality.
    """

    component_id = _component_id_for(df, index)
    component = _component_rows(df, index)
    early = _checkpoint_rows(component)

    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: str, required: bool = True):
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "required": bool(required),
                "detail": detail,
            }
        )

    if "measurement_time_h" in component.columns:
        times = pd.to_numeric(component["measurement_time_h"], errors="coerce")
        available = {float(v) for v in times.dropna().tolist()}
        missing_checkpoints = [
            int(t) for t in EARLY_CHECKPOINTS if float(t) not in available
        ]
        add_check(
            "required_checkpoints",
            not missing_checkpoints,
            (
                "0h and 24h checkpoints are present."
                if not missing_checkpoints
                else "Missing checkpoint(s): " + ", ".join(f"{x}h" for x in missing_checkpoints)
            ),
        )
    else:
        add_check(
            "required_checkpoints",
            False,
            "measurement_time_h is unavailable.",
        )

    if "leakage_current_uA" in early.columns:
        leakage = pd.to_numeric(early["leakage_current_uA"], errors="coerce")
        valid_leakage = int(leakage.notna().sum())
        add_check(
            "numeric_measurements",
            valid_leakage >= 2,
            f"{valid_leakage} finite early leakage measurement(s) available.",
        )
    else:
        add_check(
            "numeric_measurements",
            False,
            "leakage_current_uA is unavailable.",
        )

    if "usable_for_ml" in early.columns:
        values = early["usable_for_ml"].fillna(False).astype(bool)
        add_check(
            "usable_for_ml",
            bool(len(values) >= 2 and values.all()),
            (
                "All early measurements are marked usable_for_ml."
                if len(values) >= 2 and values.all()
                else "One or more early measurements are not usable_for_ml."
            ),
        )

    if "missing_value_flag" in early.columns:
        flags = early["missing_value_flag"].fillna(False).astype(bool)
        add_check(
            "missing_value_flags",
            not bool(flags.any()),
            (
                "No early missing-value flags are set."
                if not flags.any()
                else "An early missing-value flag is set."
            ),
        )

    if "condition_mismatch_flag" in early.columns:
        flags = early["condition_mismatch_flag"].fillna(False).astype(bool)
        add_check(
            "condition_comparability",
            not bool(flags.any()),
            (
                "Early measurements are condition-comparable."
                if not flags.any()
                else "At least one early measurement has a condition mismatch."
            ),
        )

    if "quality_status" in early.columns:
        status = early["quality_status"].astype(str).str.upper().str.strip()
        quality_ok = bool(len(status) >= 2 and status.eq("PASS").all())
        add_check(
            "quality_status",
            quality_ok,
            (
                "Early quality_status values are PASS."
                if quality_ok
                else "At least one early quality_status value is not PASS."
            ),
            required=False,
        )

    applicable = len(checks)
    passed = sum(1 for item in checks if item["passed"])
    score = round(100.0 * passed / applicable, 1) if applicable else 0.0
    required_failures = [
        item for item in checks if item["required"] and not item["passed"]
    ]

    if required_failures:
        status = "RETEST"
        action = "RETEST"
        reason = required_failures[0]["detail"]
    elif score < 100.0:
        status = "HOLD"
        action = "HOLD"
        reason = "Required evidence is usable, but a non-critical quality check needs review."
    else:
        status = "PASS"
        action = "CONTINUE"
        reason = "Required early evidence passed all applicable data-confidence checks."

    return {
        "available": True,
        "mode": "SPARK DATA TRUST GATE",
        "component_id": _native(component_id),
        "status": status,
        "action": action,
        "score_pct": score,
        "passed_checks": passed,
        "total_checks": applicable,
        "required_failures": len(required_failures),
        "reason": reason,
        "checks": checks,
        "time_cutoff_h": 24,
    }


def engineering_safety_gate(df: pd.DataFrame, index: int) -> dict[str, Any]:
    """Apply non-negotiable early engineering limit checks through 24h.

    The gate evaluates observed early leakage against each row's documented
    datasheet_upper_limit_uA. It is intentionally independent of Module A/B.
    ML evidence can never turn a hard observed limit failure into a pass.
    """

    component_id = _component_id_for(df, index)
    component = _component_rows(df, index)
    early = _checkpoint_rows(component)

    required = {"leakage_current_uA", "datasheet_upper_limit_uA"}
    missing = sorted(required - set(early.columns))
    if missing:
        return {
            "available": False,
            "mode": "SPARK ENGINEERING SAFETY GATE",
            "component_id": _native(component_id),
            "status": "UNAVAILABLE",
            "action": "HOLD",
            "hard_failure": None,
            "reason": "Engineering limit evidence unavailable: " + ", ".join(missing),
            "time_cutoff_h": 24,
            "observations_checked": 0,
            "failures": [],
            "minimum_margin_uA": None,
            "engineering_limit_uA": None,
            "maximum_observed_early_uA": None,
        }

    values = pd.to_numeric(early["leakage_current_uA"], errors="coerce")
    limits = pd.to_numeric(early["datasheet_upper_limit_uA"], errors="coerce")
    times = (
        pd.to_numeric(early["measurement_time_h"], errors="coerce")
        if "measurement_time_h" in early.columns
        else pd.Series([np.nan] * len(early), index=early.index)
    )

    valid = values.notna() & limits.notna()
    if not valid.any():
        return {
            "available": False,
            "mode": "SPARK ENGINEERING SAFETY GATE",
            "component_id": _native(component_id),
            "status": "UNAVAILABLE",
            "action": "HOLD",
            "hard_failure": None,
            "reason": "No finite early measurement/engineering-limit pairs are available.",
            "time_cutoff_h": 24,
            "observations_checked": 0,
            "failures": [],
            "minimum_margin_uA": None,
            "engineering_limit_uA": None,
            "maximum_observed_early_uA": None,
        }

    failures = []
    margins = []
    for pos in early.index[valid]:
        value = float(values.loc[pos])
        limit = float(limits.loc[pos])
        margin = limit - value
        margins.append(margin)
        if value > limit:
            failures.append(
                {
                    "row_index": int(pos),
                    "measurement_time_h": _native(times.loc[pos]),
                    "value_uA": value,
                    "upper_limit_uA": limit,
                    "exceedance_uA": value - limit,
                }
            )

    hard_failure = bool(failures)
    if hard_failure:
        status = "FAIL"
        action = "REJECT"
        first = failures[0]
        reason = (
            f"Observed leakage {first['value_uA']:.3f} uA exceeds the documented "
            f"upper limit {first['upper_limit_uA']:.3f} uA."
        )
    else:
        status = "PASS"
        action = "CONTINUE"
        reason = "All finite early leakage measurements remain within documented upper limits."

    return {
        "available": True,
        "mode": "SPARK ENGINEERING SAFETY GATE",
        "component_id": _native(component_id),
        "status": status,
        "action": action,
        "hard_failure": hard_failure,
        "reason": reason,
        "time_cutoff_h": 24,
        "observations_checked": int(valid.sum()),
        "failures": failures,
        "minimum_margin_uA": _native(min(margins) if margins else None),
        "engineering_limit_uA": _native(float(limits.loc[valid].min())),
        "maximum_observed_early_uA": _native(float(values.loc[valid].max())),
    }
