import pandas as pd

from core.calibration import calibration_monitor
from core.commonality import commonality_engine
from core.feedback_learning import governed_feedback_learning
from core.lot_intelligence import build_lot_intelligence


def _features():
    return pd.DataFrame([
        {"component_id":"A1","lot_id":"L1","burnin_batch_id":"B1","ir_0h_uA":10,"ir_24h_uA":11,"slope_0_24_uA_per_h":0.04,"robust_z_24h":0.2},
        {"component_id":"A2","lot_id":"L1","burnin_batch_id":"B1","ir_0h_uA":11,"ir_24h_uA":13,"slope_0_24_uA_per_h":0.08,"robust_z_24h":3.1},
        {"component_id":"B1","lot_id":"L2","burnin_batch_id":"B2","ir_0h_uA":10,"ir_24h_uA":10.5,"slope_0_24_uA_per_h":0.02,"robust_z_24h":0.1},
        {"component_id":"B2","lot_id":"L2","burnin_batch_id":"B2","ir_0h_uA":10.5,"ir_24h_uA":10.6,"slope_0_24_uA_per_h":0.01,"robust_z_24h":0.0},
    ])


def _module_a():
    return pd.DataFrame([
        {"component_id":"A1","action":"ACCEPT"},
        {"component_id":"A2","action":"REJECT"},
        {"component_id":"B1","action":"ACCEPT"},
        {"component_id":"B2","action":"ACCEPT"},
    ])


def test_lot_health_flags_escalated_lot():
    result = build_lot_intelligence(_features(), _module_a())
    assert result["available"] is True
    l1 = next(x for x in result["lots"] if x["lot_id"] == "L1")
    l2 = next(x for x in result["lots"] if x["lot_id"] == "L2")
    assert l1["health_state"] == "ALERT"
    assert l1["module_a_reject_pct"] == 50.0
    assert l2["health_state"] == "STABLE"


def test_commonality_is_association_not_causality():
    features = pd.concat([_features()] * 2, ignore_index=True)
    # unique component ids for duplicated rows
    features["component_id"] = [f"C{i}" for i in range(len(features))]
    actions = ["WATCH", "WATCH", "WATCH", "ACCEPT", "ACCEPT", "ACCEPT", "ACCEPT", "ACCEPT"]
    ma = pd.DataFrame({"component_id":features["component_id"], "action":actions})
    raw_rows=[]
    for i,cid in enumerate(features["component_id"]):
        lot = "RISKLOT" if i < 3 else "BASELOT"
        for h in (0,24):
            raw_rows.append({"component_id":cid,"measurement_time_h":h,"leakage_current_uA":10+i,"lot_id":lot,"burnin_batch_id":lot+"B","instrument_id":"SMU-X" if i<3 else "SMU-Y"})
    result = commonality_engine(pd.DataFrame(raw_rows), features, ma)
    assert result["available"] is True
    assert result["causal_claim"] is False
    assert result["risky_components"] == 3
    assert any(x["field"] == "lot_id" and x["value"] == "RISKLOT" for x in result["commonalities"])


def test_calibration_monitor_backtests_interval_coverage():
    rows=[]
    for i in range(100):
        actual=float(i)
        rows.append({
            "actual_ir_168h_uA":actual,
            "prediction_lower_05_uA":actual-1,
            "prediction_upper_95_uA":actual+1,
            "conformal_safety_upper_uA":actual+2,
        })
    result=calibration_monitor(pd.DataFrame(rows))
    assert result["available"] is True
    assert result["auto_recalibration"] is False
    assert len(result["metrics"]) == 2
    assert result["metrics"][0]["observed_pct"] == 100.0


def test_calibration_monitor_flags_undercoverage():
    rows=[]
    for i in range(100):
        actual=10.0
        covered=i < 70
        rows.append({
            "actual_ir_168h_uA":actual,
            "prediction_lower_05_uA":9.0 if covered else 0.0,
            "prediction_upper_95_uA":11.0 if covered else 5.0,
            "conformal_safety_upper_uA":12.0,
        })
    result=calibration_monitor(pd.DataFrame(rows))
    assert result["status"] == "RECALIBRATION_REVIEW"
    assert result["recalibration_review_required"] is True


def test_feedback_learning_builds_governed_review_candidate():
    rows=[]
    for i in range(3):
        rows.append({
            "schema_version":7,
            "override_applied":True,
            "override_reason_code":"QA-OVR-006",
            "model_threshold_review_flag":True,
            "machine_recommended_action":"WATCH",
            "final_action":"HOLD",
            "lot_id":"L1",
        })
    result=governed_feedback_learning(rows)
    assert result["automatic_retraining"] is False
    assert result["automatic_threshold_change"] is False
    assert result["model_threshold_review_flags"] == 3
    assert any(c["type"] == "MODEL_THRESHOLD_REVIEW" for c in result["candidates"])


def test_feedback_learning_empty_is_safe():
    result=governed_feedback_learning([])
    assert result["status"] == "NO_REVIEW_CANDIDATES"
    assert result["candidates"] == []
