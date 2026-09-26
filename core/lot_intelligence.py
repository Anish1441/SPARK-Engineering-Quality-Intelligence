from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd


ESCALATED_ACTIONS = {"WATCH", "HOLD", "HOLD_FOR_REVIEW", "RETEST", "REJECT"}


def _native(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def _safe_pct(num: float, den: float) -> float:
    return round(100.0 * float(num) / float(den), 2) if den else 0.0


def _health_state(escalated_pct: float, reject_pct: float) -> str:
    # Transparent population heuristic; not a probability of failure.
    if reject_pct >= 5.0 or escalated_pct >= 20.0:
        return "ALERT"
    if reject_pct >= 1.0 or escalated_pct >= 8.0:
        return "ELEVATED"
    return "STABLE"


def build_lot_intelligence(
    features: pd.DataFrame,
    module_a: pd.DataFrame | None = None,
    module_b: pd.DataFrame | None = None,
    qa_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate component evidence into lot/batch health intelligence.

    Uses existing time-safe Phase-1 feature/model outputs. Health states are
    transparent operational heuristics for prioritisation, not failure
    probabilities and not replacements for engineering limits.
    """
    if features is None or features.empty or "component_id" not in features.columns:
        return {
            "available": False,
            "status": "UNAVAILABLE",
            "reason": "Component feature evidence is unavailable.",
            "lots": [],
            "batches": [],
        }

    frame = features.copy()
    keep_a = [
        c for c in [
            "component_id", "module_a_action", "module_a_primary_reason",
            "within_lot_risk_score", "historical_risk_score",
            "lot_shift_risk_score", "batch_slope_shift_score",
        ] if module_a is not None and c in module_a.columns
    ]
    if module_a is not None and not module_a.empty:
        a = module_a.copy()
        # Original output uses action/primary_reason names.
        rename = {}
        if "action" in a.columns:
            rename["action"] = "module_a_action"
        if "primary_reason" in a.columns:
            rename["primary_reason"] = "module_a_primary_reason"
        a = a.rename(columns=rename)
        cols = [c for c in [
            "component_id", "module_a_action", "module_a_primary_reason",
            "within_lot_risk_score", "historical_risk_score",
            "lot_shift_risk_score", "batch_slope_shift_score",
        ] if c in a.columns]
        frame = frame.merge(a[cols], on="component_id", how="left", suffixes=("", "_a"))

    if module_b is not None and not module_b.empty:
        bcols = [c for c in [
            "component_id", "prediction_168h_uA", "prediction_upper_95_uA",
            "conformal_safety_upper_uA", "absolute_prediction_error_uA",
        ] if c in module_b.columns]
        frame = frame.merge(module_b[bcols], on="component_id", how="left", suffixes=("", "_b"))

    # Map QA counts without allowing them to change machine health state.
    qa_by_lot: Counter[str] = Counter()
    qa_override_by_lot: Counter[str] = Counter()
    for row in qa_rows or []:
        lot = str(row.get("lot_id") or "").strip()
        if not lot:
            continue
        qa_by_lot[lot] += 1
        if bool(row.get("override_applied")):
            qa_override_by_lot[lot] += 1

    def aggregate(group_col: str) -> list[dict[str, Any]]:
        if group_col not in frame.columns:
            return []
        output: list[dict[str, Any]] = []
        for key, group in frame.groupby(group_col, dropna=False, sort=True):
            key_text = str(key)
            count = len(group)
            actions = group.get("module_a_action", pd.Series(["UNAVAILABLE"] * count)).fillna("UNAVAILABLE").astype(str).str.upper()
            action_counts = Counter(actions.tolist())
            escalated = sum(action_counts.get(x, 0) for x in ESCALATED_ACTIONS)
            rejects = action_counts.get("REJECT", 0)
            escalated_pct = _safe_pct(escalated, count)
            reject_pct = _safe_pct(rejects, count)
            med_0 = pd.to_numeric(group.get("ir_0h_uA"), errors="coerce").median() if "ir_0h_uA" in group.columns else np.nan
            med_24 = pd.to_numeric(group.get("ir_24h_uA"), errors="coerce").median() if "ir_24h_uA" in group.columns else np.nan
            median_slope = pd.to_numeric(group.get("slope_0_24_uA_per_h"), errors="coerce").median() if "slope_0_24_uA_per_h" in group.columns else np.nan
            outlier_rate = 0.0
            if "robust_z_24h" in group.columns:
                rz = pd.to_numeric(group["robust_z_24h"], errors="coerce").abs()
                outlier_rate = _safe_pct((rz >= 2.5).sum(), rz.notna().sum())
            row = {
                group_col: key_text,
                "components": int(count),
                "health_state": _health_state(escalated_pct, reject_pct),
                "module_a_escalated_pct": escalated_pct,
                "module_a_reject_pct": reject_pct,
                "robust_z_24h_outlier_pct": outlier_rate,
                "median_ir_0h_uA": _native(med_0),
                "median_ir_24h_uA": _native(med_24),
                "median_slope_0_24_uA_per_h": _native(median_slope),
                "action_counts": dict(action_counts),
            }
            if group_col == "lot_id":
                decisions = qa_by_lot.get(key_text, 0)
                overrides = qa_override_by_lot.get(key_text, 0)
                row["qa_decisions"] = decisions
                row["qa_overrides"] = overrides
                row["qa_override_rate_pct"] = _safe_pct(overrides, decisions)
            output.append(row)
        return output

    lots = aggregate("lot_id")
    batches = aggregate("burnin_batch_id")
    state_counts = Counter(row["health_state"] for row in lots)
    overall = "ALERT" if state_counts.get("ALERT") else "ELEVATED" if state_counts.get("ELEVATED") else "STABLE"
    return {
        "available": True,
        "status": overall,
        "mode": "SPARK LOT / BATCH HEALTH INTELLIGENCE",
        "lots": lots,
        "batches": batches,
        "lot_count": len(lots),
        "batch_count": len(batches),
        "state_counts": dict(state_counts),
        "semantics": (
            "Population health is a transparent prioritisation heuristic built from "
            "existing early-life evidence; it is not a probability of failure."
        ),
    }
