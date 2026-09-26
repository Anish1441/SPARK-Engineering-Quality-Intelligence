import json

from core.qa_manager import QAManager


def _payload(component="C1"):
    return {
        "action": "WATCH",
        "response": "AGREE",
        "override_action": "",
        "comment": "reviewed",
        "inspection_index": 0,
        "record_index": 1,
        "inspection_mode": "component",
        "component_id": component,
        "analytical_score": 50,
        "data_confidence_snapshot": {"status": "PASS"},
        "engineering_safety_snapshot": {"status": "PASS"},
        "reliability_risk_snapshot": {"unified_action": "WATCH"},
        "explanation_snapshot": {"primary_reason_code": "MA-WATCH-001"},
        "model_snapshot": {"module_a": {"action": "WATCH"}},
        "assessment_source": {"module_a": "original"},
    }


def test_v7_ledger_entry_has_integrity_fields(tmp_path):
    manager = QAManager(tmp_path)
    item = manager.save("ds", _payload())
    assert item["schema_version"] == 7
    assert len(item["evidence_fingerprint"]) == 64
    assert len(item["entry_hash"]) == 64
    result = manager.verify("ds")
    assert result["status"] == "VERIFIED"
    assert result["integrity_ok"] is True
    assert result["verified_v7_entries"] == 1


def test_tampered_entry_is_detected(tmp_path):
    manager = QAManager(tmp_path)
    manager.save("ds", _payload())
    path = tmp_path / "ds.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["comment"] = "tampered after save"
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    result = manager.verify("ds")
    assert result["status"] == "FAILED"
    assert result["integrity_ok"] is False
    assert any(issue["type"] == "ENTRY_HASH_MISMATCH" for issue in result["issues"])


def test_new_entry_seals_prior_legacy_prefix(tmp_path):
    path = tmp_path / "ds.json"
    path.write_text(json.dumps([{"schema_version": 5, "action": "ACCEPT"}]), encoding="utf-8")
    manager = QAManager(tmp_path)
    manager.save("ds", _payload("C2"))
    result = manager.verify("ds")
    assert result["status"] == "VERIFIED"
    assert result["legacy_entries"] == 1
    assert result["verified_v7_entries"] == 1

    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["action"] = "REJECT"
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    result = manager.verify("ds")
    assert result["status"] == "FAILED"
    assert any(issue["type"] == "PRIOR_LEDGER_HASH_MISMATCH" for issue in result["issues"])


def test_schema_v6_entry_remains_verifiable_after_v7_upgrade(tmp_path):
    manager = QAManager(tmp_path)
    row = _payload("C6")
    row.update(
        {
            "id": "legacy-v6",
            "schema_version": 6,
            "dataset_id": "ds",
            "ledger_position": 1,
            "final_action": "WATCH",
            "timestamp": "2026-09-26T00:00:00+00:00",
            "prior_ledger_hash": manager._sha256([]),
        }
    )
    row["evidence_fingerprint"] = manager._sha256(manager._evidence_payload(row))
    candidate = dict(row)
    candidate.pop("entry_hash", None)
    row["entry_hash"] = manager._sha256(candidate)
    (tmp_path / "ds.json").write_text(json.dumps([row], indent=2), encoding="utf-8")

    result = manager.verify("ds")
    assert result["status"] == "VERIFIED"
    assert result["integrity_ok"] is True
    assert result["verified_v6_entries"] == 1
    assert result["verified_v7_entries"] == 0
