from core.risk_engine import reliability_risk_engine


def _data(status="PASS", action="CONTINUE", score=100.0):
    return {
        "available": True,
        "component_id": "C1",
        "status": status,
        "action": action,
        "score_pct": score,
        "reason": "data reason",
    }


def _safety(status="PASS", hard=False, limit=175.0):
    return {
        "available": status != "UNAVAILABLE",
        "component_id": "C1",
        "status": status,
        "action": "REJECT" if hard else "CONTINUE",
        "hard_failure": hard,
        "engineering_limit_uA": limit,
        "reason": "safety reason",
    }


def _module_a(action="ACCEPT", available=True):
    return {
        "available": available,
        "component_id": "C1",
        "action": action,
        "primary_reason": "module a reason",
    }


def _module_b(p95=40.0, conformal=60.0, available=True):
    return {
        "available": available,
        "component_id": "C1",
        "prediction_168h_uA": 30.0,
        "prediction_upper_95_uA": p95,
        "conformal_safety_upper_uA": conformal,
    }


def test_risk_engine_accepts_clean_low_risk_component():
    result = reliability_risk_engine(
        _data(), _safety(), _module_a(), _module_b()
    )
    assert result["unified_action"] == "ACCEPT"
    assert result["risk_band"] == "LOW"
    assert result["evidence_completeness_pct"] == 100.0
    assert result["score_is_probability"] is False
    assert result["reliability_risk_score"] < 50.0


def test_risk_engine_data_retest_has_precedence():
    result = reliability_risk_engine(
        _data("RETEST", "RETEST", 50.0),
        _safety(),
        _module_a("REJECT"),
        _module_b(p95=200.0, conformal=220.0),
    )
    assert result["unified_action"] == "RETEST"
    assert result["risk_band"] == "INDETERMINATE"
    assert result["reliability_risk_score"] is None


def test_risk_engine_hard_safety_failure_cannot_be_overridden():
    result = reliability_risk_engine(
        _data(), _safety("FAIL", True), _module_a("ACCEPT"), _module_b()
    )
    assert result["unified_action"] == "REJECT"
    assert result["risk_band"] == "CRITICAL"
    assert result["reliability_risk_score"] == 100.0
    assert result["safety_override"] is True


def test_risk_engine_preserves_module_a_watch():
    result = reliability_risk_engine(
        _data(), _safety(), _module_a("WATCH"), _module_b()
    )
    assert result["unified_action"] == "WATCH"
    assert result["risk_band"] == "ELEVATED"
    assert result["reliability_risk_score"] >= 50.0


def test_risk_engine_holds_when_conservative_forecast_crosses_limit():
    result = reliability_risk_engine(
        _data(),
        _safety(),
        _module_a("ACCEPT"),
        _module_b(p95=150.0, conformal=180.0),
    )
    assert result["unified_action"] == "HOLD"
    assert result["risk_band"] == "HIGH"
    assert "180.000" in result["reason"]


def test_risk_engine_holds_when_module_b_is_unavailable():
    result = reliability_risk_engine(
        _data(), _safety(), _module_a("ACCEPT"), _module_b(available=False)
    )
    assert result["unified_action"] == "HOLD"
    assert result["risk_band"] == "HIGH"
    assert result["evidence_completeness_pct"] == 75.0
