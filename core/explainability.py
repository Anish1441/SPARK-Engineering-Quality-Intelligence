from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ReasonItem:
    code: str
    rank: int
    severity: str
    source: str
    title: str
    detail: str
    recommended_action: str


def _normalise_action(value: Any) -> str:
    action = str(value or "").upper().strip()
    aliases = {
        "HOLD_FOR_REVIEW": "HOLD",
        "REVIEW": "HOLD",
    }
    return aliases.get(action, action)


def _reason(
    code: str,
    rank: int,
    severity: str,
    source: str,
    title: str,
    detail: str,
    recommended_action: str,
) -> ReasonItem:
    return ReasonItem(
        code=code,
        rank=rank,
        severity=severity,
        source=source,
        title=title,
        detail=detail,
        recommended_action=recommended_action,
    )


def build_decision_explanation(
    data_confidence: dict[str, Any],
    engineering_safety: dict[str, Any],
    module_a: dict[str, Any],
    module_b: dict[str, Any],
    reliability_risk: dict[str, Any],
) -> dict[str, Any]:
    """Build deterministic, inspector-readable decision reasons.

    This layer does not change the reliability recommendation. It translates
    already-computed guardrail/model evidence into ranked reason codes and a
    traceable decision path. No LLM is used.
    """

    reasons: list[ReasonItem] = []
    action = _normalise_action(reliability_risk.get("unified_action")) or "HOLD"

    # Highest priority: evidence quality and hard engineering constraints.
    data_status = str(data_confidence.get("status") or "UNAVAILABLE").upper()
    if data_status == "RETEST":
        reasons.append(_reason(
            "DT-RETEST-001", 1, "CRITICAL", "DATA_TRUST",
            "Required early evidence is incomplete or unusable",
            str(data_confidence.get("reason") or "0h/24h evidence requires retest."),
            "RETEST",
        ))
    elif data_status == "HOLD":
        reasons.append(_reason(
            "DT-HOLD-001", 2, "HIGH", "DATA_TRUST",
            "Evidence quality requires review",
            str(data_confidence.get("reason") or "Data confidence is insufficient for release."),
            "HOLD",
        ))

    if engineering_safety.get("hard_failure") is True:
        reasons.append(_reason(
            "ES-FAIL-001", 3, "CRITICAL", "ENGINEERING_SAFETY",
            "Observed electrical limit breach",
            str(engineering_safety.get("reason") or "A hard engineering limit was exceeded."),
            "REJECT",
        ))
    elif not engineering_safety.get("available") or str(
        engineering_safety.get("status") or "UNAVAILABLE"
    ).upper() != "PASS":
        reasons.append(_reason(
            "ES-HOLD-001", 4, "HIGH", "ENGINEERING_SAFETY",
            "Engineering limit evidence is unavailable",
            str(engineering_safety.get("reason") or "Safety-limit evidence is unavailable."),
            "HOLD",
        ))

    # Module A: preserve the original anomaly engine conclusion and reason.
    if module_a.get("available"):
        ma_action = _normalise_action(module_a.get("action"))
        ma_reason = str(module_a.get("primary_reason") or "Module-A evidence available.")
        ma_map = {
            "REJECT": ("MA-REJECT-001", 25, "CRITICAL", "Module A recommends rejection"),
            "HOLD": ("MA-HOLD-001", 35, "HIGH", "Module A requires human review"),
            "RETEST": ("MA-RETEST-001", 30, "HIGH", "Module A requires retest"),
            "WATCH": ("MA-WATCH-001", 50, "ELEVATED", "Dynamic anomaly detected"),
            "ACCEPT": ("MA-ACCEPT-001", 90, "LOW", "No significant early anomaly detected"),
        }
        code, rank, severity, title = ma_map.get(
            ma_action,
            ("MA-INFO-001", 85, "INFO", "Module-A evidence available"),
        )
        reasons.append(_reason(code, rank, severity, "MODULE_A", title, ma_reason, ma_action or "HOLD"))
    else:
        reasons.append(_reason(
            "MA-UNAVAILABLE-001", 40, "HIGH", "MODULE_A",
            "Module-A evidence unavailable",
            str(module_a.get("message") or "The original Module-A result is unavailable."),
            "HOLD",
        ))

    # Module B: use the same forecast values already used by the risk engine.
    if module_b.get("available"):
        limit = reliability_risk.get("engineering_limit_uA")
        p95 = module_b.get("prediction_upper_95_uA")
        conformal = module_b.get("conformal_safety_upper_uA")
        utilization = reliability_risk.get("forecast_limit_utilization_pct")

        if limit is not None and conformal is not None and float(conformal) >= float(limit):
            reasons.append(_reason(
                "MB-HOLD-001", 30, "HIGH", "MODULE_B",
                "Conservative forecast bound reaches the engineering limit",
                f"Conformal upper bound {float(conformal):.3f} uA reaches/exceeds the engineering limit {float(limit):.3f} uA.",
                "HOLD",
            ))
        elif limit is not None and p95 is not None and float(p95) >= float(limit):
            reasons.append(_reason(
                "MB-HOLD-002", 32, "HIGH", "MODULE_B",
                "95% forecast bound reaches the engineering limit",
                f"95% upper forecast {float(p95):.3f} uA reaches/exceeds the engineering limit {float(limit):.3f} uA.",
                "HOLD",
            ))
        else:
            detail = "Module-B forecast remains below the documented engineering limit."
            if utilization is not None:
                detail = f"Module-B forecast uses {float(utilization):.2f}% of the documented engineering limit."
            reasons.append(_reason(
                "MB-FORECAST-001", 95, "LOW", "MODULE_B",
                "Forecast does not require escalation",
                detail,
                "ACCEPT",
            ))
    else:
        reasons.append(_reason(
            "MB-UNAVAILABLE-001", 38, "HIGH", "MODULE_B",
            "Module-B forecast unavailable",
            str(module_b.get("message") or "The original Module-B forecast is unavailable."),
            "HOLD",
        ))

    # If nothing above explains an ACCEPT, add a clean system-level reason.
    if action == "ACCEPT" and not any(r.severity in {"CRITICAL", "HIGH", "ELEVATED"} for r in reasons):
        reasons.append(_reason(
            "REL-ACCEPT-001", 100, "LOW", "RISK_ENGINE",
            "All release guardrails passed",
            str(reliability_risk.get("reason") or "Available evidence does not require escalation."),
            "ACCEPT",
        ))

    reasons = sorted(reasons, key=lambda r: (r.rank, r.code))
    primary = reasons[0] if reasons else _reason(
        "REL-HOLD-999", 999, "HIGH", "RISK_ENGINE",
        "Decision explanation unavailable",
        str(reliability_risk.get("reason") or "Human review required."),
        action,
    )

    decision_path = [
        {
            "step": 1,
            "layer": "DATA_TRUST",
            "status": data_confidence.get("status"),
            "action": data_confidence.get("action"),
        },
        {
            "step": 2,
            "layer": "ENGINEERING_SAFETY",
            "status": engineering_safety.get("status"),
            "action": engineering_safety.get("action"),
        },
        {
            "step": 3,
            "layer": "MODULE_A",
            "status": "AVAILABLE" if module_a.get("available") else "UNAVAILABLE",
            "action": _normalise_action(module_a.get("action")),
        },
        {
            "step": 4,
            "layer": "MODULE_B",
            "status": "AVAILABLE" if module_b.get("available") else "UNAVAILABLE",
            "action": "FORECAST" if module_b.get("available") else "HOLD",
        },
        {
            "step": 5,
            "layer": "RELIABILITY_RISK",
            "status": reliability_risk.get("risk_band"),
            "action": action,
        },
    ]

    return {
        "available": True,
        "mode": "SPARK DETERMINISTIC QA EXPLAINABILITY",
        "deterministic": True,
        "uses_llm": False,
        "recommended_action": action,
        "primary_reason_code": primary.code,
        "primary_reason": primary.detail,
        "primary_reason_title": primary.title,
        "reason_codes": [asdict(item) for item in reasons],
        "decision_path": decision_path,
        "evidence_summary": {
            "data_confidence_status": data_confidence.get("status"),
            "engineering_safety_status": engineering_safety.get("status"),
            "engineering_safety_hard_failure": engineering_safety.get("hard_failure") is True,
            "module_a_action": _normalise_action(module_a.get("action")),
            "module_b_available": bool(module_b.get("available")),
            "risk_band": reliability_risk.get("risk_band"),
            "risk_score": reliability_risk.get("reliability_risk_score"),
            "evidence_completeness_pct": reliability_risk.get("evidence_completeness_pct"),
        },
    }
