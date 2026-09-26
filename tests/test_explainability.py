from core.explainability import build_decision_explanation


def _base():
    data = {"available": True, "status": "PASS", "action": "CONTINUE", "score_pct": 100}
    safety = {"available": True, "status": "PASS", "action": "CONTINUE", "hard_failure": False}
    module_a = {"available": True, "action": "ACCEPT", "primary_reason": "No anomaly"}
    module_b = {"available": True, "prediction_upper_95_uA": 40, "conformal_safety_upper_uA": 60}
    risk = {
        "unified_action": "ACCEPT",
        "risk_band": "LOW",
        "reliability_risk_score": 20,
        "evidence_completeness_pct": 100,
        "engineering_limit_uA": 175,
        "forecast_limit_utilization_pct": 22.86,
        "reason": "Guardrails passed.",
    }
    return data, safety, module_a, module_b, risk


def test_accept_explanation_is_deterministic_and_non_llm():
    result = build_decision_explanation(*_base())
    assert result["recommended_action"] == "ACCEPT"
    assert result["deterministic"] is True
    assert result["uses_llm"] is False
    assert result["primary_reason_code"].startswith("MA-") or result["primary_reason_code"].startswith("REL-")
    assert len(result["decision_path"]) == 5


def test_hard_failure_is_primary_reason():
    data, safety, module_a, module_b, risk = _base()
    safety.update({"status": "FAIL", "hard_failure": True, "reason": "180 exceeds 175"})
    risk.update({"unified_action": "REJECT", "risk_band": "CRITICAL", "reliability_risk_score": 100})
    result = build_decision_explanation(data, safety, module_a, module_b, risk)
    assert result["primary_reason_code"] == "ES-FAIL-001"
    assert result["recommended_action"] == "REJECT"


def test_module_a_watch_has_clear_reason_code():
    data, safety, module_a, module_b, risk = _base()
    module_a.update({"action": "WATCH", "primary_reason": "Dynamic anomaly detected"})
    risk.update({"unified_action": "WATCH", "risk_band": "ELEVATED", "reliability_risk_score": 50})
    result = build_decision_explanation(data, safety, module_a, module_b, risk)
    codes = [item["code"] for item in result["reason_codes"]]
    assert "MA-WATCH-001" in codes
    assert result["recommended_action"] == "WATCH"


def test_module_b_limit_crossing_has_hold_reason_code():
    data, safety, module_a, module_b, risk = _base()
    module_b.update({"conformal_safety_upper_uA": 180})
    risk.update({"unified_action": "HOLD", "risk_band": "HIGH", "reliability_risk_score": 85})
    result = build_decision_explanation(data, safety, module_a, module_b, risk)
    codes = [item["code"] for item in result["reason_codes"]]
    assert "MB-HOLD-001" in codes
