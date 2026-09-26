import pandas as pd

from core.gates import data_confidence_gate, engineering_safety_gate


def _base_component():
    return pd.DataFrame(
        {
            "component_id": ["C1", "C1", "C1", "C1"],
            "measurement_time_h": [0, 24, 96, 168],
            "leakage_current_uA": [10.0, 12.0, 13.0, 14.0],
            "datasheet_upper_limit_uA": [175.0, 175.0, 175.0, 175.0],
            "usable_for_ml": [True, True, True, True],
            "missing_value_flag": [False, False, False, False],
            "condition_mismatch_flag": [False, False, False, False],
            "quality_status": ["PASS", "PASS", "PASS", "PASS"],
        }
    )


def test_data_confidence_passes_clean_0h_24h_evidence():
    result = data_confidence_gate(_base_component(), 1)

    assert result["status"] == "PASS"
    assert result["action"] == "CONTINUE"
    assert result["score_pct"] == 100.0
    assert result["required_failures"] == 0
    assert result["time_cutoff_h"] == 24


def test_data_confidence_retests_when_24h_checkpoint_is_missing():
    df = _base_component()
    df = df[df["measurement_time_h"] != 24].reset_index(drop=True)

    result = data_confidence_gate(df, 0)

    assert result["status"] == "RETEST"
    assert result["action"] == "RETEST"
    assert result["required_failures"] >= 1
    assert "24h" in result["reason"]


def test_engineering_safety_gate_rejects_hard_limit_breach():
    df = _base_component()
    df.loc[df["measurement_time_h"] == 24, "leakage_current_uA"] = 180.0

    result = engineering_safety_gate(df, 1)

    assert result["available"] is True
    assert result["status"] == "FAIL"
    assert result["action"] == "REJECT"
    assert result["hard_failure"] is True
    assert result["minimum_margin_uA"] == -5.0
    assert len(result["failures"]) == 1


def test_engineering_safety_gate_passes_when_early_values_within_limit():
    result = engineering_safety_gate(_base_component(), 1)

    assert result["status"] == "PASS"
    assert result["action"] == "CONTINUE"
    assert result["hard_failure"] is False
    assert result["observations_checked"] == 2
    assert result["minimum_margin_uA"] == 163.0
    assert result["engineering_limit_uA"] == 175.0
    assert result["maximum_observed_early_uA"] == 12.0


def test_engineering_safety_gate_fails_closed_without_limit_column():
    df = _base_component().drop(columns=["datasheet_upper_limit_uA"])

    result = engineering_safety_gate(df, 1)

    assert result["available"] is False
    assert result["status"] == "UNAVAILABLE"
    assert result["action"] == "HOLD"
    assert result["hard_failure"] is None
