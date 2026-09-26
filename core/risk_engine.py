from __future__ import annotations

from typing import Any

import numpy as np


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _normalise_action(action: Any) -> str:
    value = str(action or "").upper().strip()
    aliases = {
        "HOLD_FOR_REVIEW": "HOLD",
        "REVIEW": "HOLD",
    }
    return aliases.get(value, value)


def reliability_risk_engine(
    data_confidence: dict[str, Any],
    engineering_safety: dict[str, Any],
    module_a: dict[str, Any],
    module_b: dict[str, Any],
) -> dict[str, Any]:
    """Fuse SPARK evidence without allowing ML to override guardrails.

    The returned risk score is a transparent prioritisation index, not a
    calibrated probability of failure. Decision precedence is deterministic:

    1. unusable/incomplete required evidence -> RETEST
    2. observed hard electrical failure -> REJECT
    3. non-critical data-quality concern -> HOLD
    4. unavailable engineering limit -> HOLD
    5. original Module-A action
    6. original Module-B forecast/uncertainty against the engineering limit

    A model can escalate review, but it can never convert a hard observed
    safety failure or unusable evidence into ACCEPT.
    """

    component_id = (
        data_confidence.get("component_id")
        or engineering_safety.get("component_id")
        or module_a.get("component_id")
        or module_b.get("component_id")
    )

    data_status = str(data_confidence.get("status") or "UNAVAILABLE").upper()
    data_action = _normalise_action(data_confidence.get("action"))
    safety_status = str(engineering_safety.get("status") or "UNAVAILABLE").upper()
    hard_failure = engineering_safety.get("hard_failure") is True
    module_a_available = bool(module_a.get("available"))
    module_b_available = bool(module_b.get("available"))
    module_a_action = _normalise_action(module_a.get("action"))

    limit = _finite(engineering_safety.get("engineering_limit_uA"))
    p95 = _finite(module_b.get("prediction_upper_95_uA"))
    conformal_upper = _finite(module_b.get("conformal_safety_upper_uA"))
    point_prediction = _finite(module_b.get("prediction_168h_uA"))

    forecast_reference = p95 if p95 is not None else point_prediction
    forecast_utilisation = None
    if forecast_reference is not None and limit is not None and limit > 0:
        forecast_utilisation = round(100.0 * forecast_reference / limit, 2)

    # Evidence completeness is intentionally simple and auditable. The Data
    # Trust score is one pillar; the other three pillars are binary availability
    # of safety, Module A and Module B evidence.
    data_score = _finite(data_confidence.get("score_pct")) or 0.0
    availability_scores = [
        data_score,
        100.0 if engineering_safety.get("available") else 0.0,
        100.0 if module_a_available else 0.0,
        100.0 if module_b_available else 0.0,
    ]
    evidence_completeness = round(sum(availability_scores) / len(availability_scores), 1)

    contributors: list[dict[str, Any]] = []

    # A component reliability score is not asserted when required evidence is
    # unusable. RETEST/HOLD is the correct engineering outcome instead.
    if data_action == "RETEST" or data_status == "RETEST":
        return {
            "available": True,
            "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
            "component_id": component_id,
            "reliability_risk_score": None,
            "risk_band": "INDETERMINATE",
            "evidence_completeness_pct": evidence_completeness,
            "unified_action": "RETEST",
            "reason": data_confidence.get("reason") or "Required early evidence is incomplete.",
            "safety_override": False,
            "engineering_limit_uA": limit,
            "forecast_limit_utilization_pct": forecast_utilisation,
            "forecast_reference_uA": forecast_reference,
            "conformal_safety_upper_uA": conformal_upper,
            "contributors": [{"source": "DATA_TRUST", "severity": "RETEST"}],
            "score_is_probability": False,
        }

    if hard_failure:
        return {
            "available": True,
            "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
            "component_id": component_id,
            "reliability_risk_score": 100.0,
            "risk_band": "CRITICAL",
            "evidence_completeness_pct": evidence_completeness,
            "unified_action": "REJECT",
            "reason": engineering_safety.get("reason") or "Observed engineering limit failure.",
            "safety_override": True,
            "engineering_limit_uA": limit,
            "forecast_limit_utilization_pct": forecast_utilisation,
            "forecast_reference_uA": forecast_reference,
            "conformal_safety_upper_uA": conformal_upper,
            "contributors": [{"source": "ENGINEERING_SAFETY", "severity": "HARD_FAIL"}],
            "score_is_probability": False,
        }

    if data_action == "HOLD" or data_status == "HOLD":
        return {
            "available": True,
            "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
            "component_id": component_id,
            "reliability_risk_score": None,
            "risk_band": "INDETERMINATE",
            "evidence_completeness_pct": evidence_completeness,
            "unified_action": "HOLD",
            "reason": data_confidence.get("reason") or "Evidence quality requires human review.",
            "safety_override": False,
            "engineering_limit_uA": limit,
            "forecast_limit_utilization_pct": forecast_utilisation,
            "forecast_reference_uA": forecast_reference,
            "conformal_safety_upper_uA": conformal_upper,
            "contributors": [{"source": "DATA_TRUST", "severity": "HOLD"}],
            "score_is_probability": False,
        }

    if not engineering_safety.get("available") or safety_status != "PASS":
        return {
            "available": True,
            "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
            "component_id": component_id,
            "reliability_risk_score": None,
            "risk_band": "INDETERMINATE",
            "evidence_completeness_pct": evidence_completeness,
            "unified_action": "HOLD",
            "reason": engineering_safety.get("reason") or "Engineering limit evidence is unavailable.",
            "safety_override": False,
            "engineering_limit_uA": limit,
            "forecast_limit_utilization_pct": forecast_utilisation,
            "forecast_reference_uA": forecast_reference,
            "conformal_safety_upper_uA": conformal_upper,
            "contributors": [{"source": "ENGINEERING_SAFETY", "severity": "UNAVAILABLE"}],
            "score_is_probability": False,
        }

    # Module-A action anchors. These are prioritisation values, not probabilities.
    action_anchor = {
        "ACCEPT": 0.0,
        "WATCH": 50.0,
        "HOLD": 75.0,
        "REJECT": 100.0,
    }

    if not module_a_available:
        contributors.append({"source": "MODULE_A", "severity": "UNAVAILABLE"})
        module_a_score = 0.0
    elif module_a_action == "RETEST":
        return {
            "available": True,
            "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
            "component_id": component_id,
            "reliability_risk_score": None,
            "risk_band": "INDETERMINATE",
            "evidence_completeness_pct": evidence_completeness,
            "unified_action": "RETEST",
            "reason": module_a.get("primary_reason") or "Module A requires retest.",
            "safety_override": False,
            "engineering_limit_uA": limit,
            "forecast_limit_utilization_pct": forecast_utilisation,
            "forecast_reference_uA": forecast_reference,
            "conformal_safety_upper_uA": conformal_upper,
            "contributors": [{"source": "MODULE_A", "severity": "RETEST"}],
            "score_is_probability": False,
        }
    else:
        module_a_score = action_anchor.get(module_a_action, 50.0)
        contributors.append({"source": "MODULE_A", "severity": module_a_action or "UNKNOWN"})

    if module_a_action == "REJECT":
        unified_action = "REJECT"
        reason = module_a.get("primary_reason") or "Module A returned REJECT."
    elif module_a_action == "HOLD":
        unified_action = "HOLD"
        reason = module_a.get("primary_reason") or "Module A requires review."
    elif not module_b_available:
        unified_action = "HOLD"
        reason = "Module-B forecast is unavailable; reliability release is held for review."
        contributors.append({"source": "MODULE_B", "severity": "UNAVAILABLE"})
    elif limit is not None and conformal_upper is not None and conformal_upper >= limit:
        unified_action = "HOLD"
        reason = (
            f"Conservative Module-B upper bound {conformal_upper:.3f} uA reaches/exceeds "
            f"the engineering limit {limit:.3f} uA."
        )
        contributors.append({"source": "MODULE_B", "severity": "FORECAST_LIMIT_CROSSING"})
    elif limit is not None and p95 is not None and p95 >= limit:
        unified_action = "HOLD"
        reason = (
            f"Module-B 95% upper forecast {p95:.3f} uA reaches/exceeds "
            f"the engineering limit {limit:.3f} uA."
        )
        contributors.append({"source": "MODULE_B", "severity": "P95_LIMIT_CROSSING"})
    elif module_a_action == "WATCH":
        unified_action = "WATCH"
        reason = module_a.get("primary_reason") or "Module A returned WATCH."
    else:
        unified_action = "ACCEPT"
        reason = "Guardrails passed and available Module-A/Module-B evidence does not require escalation."

    forecast_score = 0.0
    if forecast_utilisation is not None:
        forecast_score = min(100.0, max(0.0, forecast_utilisation))
        contributors.append(
            {
                "source": "MODULE_B",
                "severity": "FORECAST_UTILIZATION",
                "value_pct": forecast_utilisation,
            }
        )

    risk_score = round(max(module_a_score, forecast_score), 1)
    if unified_action == "REJECT":
        risk_score = 100.0
        risk_band = "CRITICAL"
    elif unified_action == "HOLD":
        risk_band = "HIGH"
    elif unified_action == "WATCH":
        risk_band = "ELEVATED"
    else:
        risk_band = "LOW"

    return {
        "available": True,
        "mode": "SPARK UNIFIED RELIABILITY RISK ENGINE",
        "component_id": component_id,
        "reliability_risk_score": risk_score,
        "risk_band": risk_band,
        "evidence_completeness_pct": evidence_completeness,
        "unified_action": unified_action,
        "reason": reason,
        "safety_override": False,
        "engineering_limit_uA": limit,
        "forecast_limit_utilization_pct": forecast_utilisation,
        "forecast_reference_uA": forecast_reference,
        "conformal_safety_upper_uA": conformal_upper,
        "contributors": contributors,
        "score_is_probability": False,
    }
