from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.applicability import (
    assess_model_applicability,
    applicability_summary,
    SUPPORTED,
    OUT_OF_DOMAIN,
    INSUFFICIENT_EVIDENCE,
    SCHEMA_INCOMPATIBLE,
)
from core.drift import drift_snapshot
from core.model_registry import build_model_registry, dataset_schema_contract
from core.rolling_forecast import rolling_forecast_update


def _component(component_id: str, v0: float, v24: float, v96: float | None = None, v168: float | None = None, split: str = "test"):
    rows = []
    for hour, value in [(0, v0), (24, v24), (96, v96), (168, v168)]:
        if value is None:
            continue
        rows.append(
            {
                "component_id": component_id,
                "measurement_time_h": hour,
                "leakage_current_uA": value,
                "datasheet_upper_limit_uA": 175.0,
                "dataset_split": split,
                "usable_for_ml": True,
                "lot_id": "L1",
            }
        )
    return rows


def _reference(n: int = 60) -> pd.DataFrame:
    rows = []
    for i in range(n):
        base = 10 + (i % 7) * 0.1
        rows.extend(_component(f"T{i}", base, base + 0.5, split="train")[:2])
    return pd.DataFrame(rows)


def test_schema_contract_has_stable_fingerprint():
    df = pd.DataFrame(_component("C1", 10, 11))
    a = dataset_schema_contract(df)
    b = dataset_schema_contract(df.copy())
    assert a["base_contract_satisfied"] is True
    assert a["fingerprint"] == b["fingerprint"]
    assert len(a["fingerprint"]) == 64


def test_registry_surfaces_production_artifacts(tmp_path: Path):
    model_dir = tmp_path / "artifacts" / "models"
    model_dir.mkdir(parents=True)
    (model_dir / "module_a_24h.joblib").write_bytes(b"A")
    (model_dir / "module_b_24h.joblib").write_bytes(b"B")
    df = pd.DataFrame(_component("C1", 10, 11))
    status = {
        "module_a": {"available": True, "metadata": {"feature_columns": ["a", "b"]}},
        "module_b": {"available": True, "metadata": {"point_feature_sets": {"x": ["c", "d"]}}},
    }
    result = build_model_registry(tmp_path, status, df)
    assert result["production_models"] == ["MODULE-A-24H-v1", "MODULE-B-24H-v1"]
    assert all(m["artifact_sha256"] for m in result["models"])
    assert result["discovered_96h_model"] is False


def test_registry_discovers_but_does_not_activate_96h_artifact(tmp_path: Path):
    model_dir = tmp_path / "artifacts" / "models"
    model_dir.mkdir(parents=True)
    for name in ("module_a_24h.joblib", "module_b_24h.joblib", "module_b_96h.joblib"):
        (model_dir / name).write_bytes(name.encode())
    df = pd.DataFrame(_component("C1", 10, 11))
    status = {"module_a": {"available": True}, "module_b": {"available": True}}
    result = build_model_registry(tmp_path, status, df)
    discovered = [m for m in result["models"] if m["module"] == "B96"][0]
    assert result["discovered_96h_model"] is True
    assert discovered["status"] == "DISCOVERED_NOT_ACTIVATED"


def test_applicability_supported_against_training_reference():
    ref = _reference()
    current = pd.DataFrame(_component("C1", 10.2, 10.7))
    result = assess_model_applicability(current, 0, reference_df=ref)
    assert result["status"] == SUPPORTED
    assert result["applicable"] is True
    assert result["uses_future_measurements"] is False


def test_applicability_abstains_on_out_of_domain_component():
    ref = _reference()
    current = pd.DataFrame(_component("C1", 90, 100))
    result = assess_model_applicability(current, 0, reference_df=ref)
    assert result["status"] == OUT_OF_DOMAIN
    assert result["applicable"] is False
    assert result["max_robust_distance"] >= 6


def test_applicability_requires_24h_evidence():
    ref = _reference()
    current = pd.DataFrame(_component("C1", 10, 11)[:1])
    result = assess_model_applicability(current, 0, reference_df=ref)
    assert result["status"] == INSUFFICIENT_EVIDENCE
    assert result["applicable"] is False


def test_applicability_fails_closed_on_schema_mismatch():
    df = pd.DataFrame({"component_id": ["C1"]})
    result = assess_model_applicability(df, 0)
    assert result["status"] == SCHEMA_INCOMPATIBLE
    assert result["applicable"] is False


def test_applicability_summary_counts_components():
    ref = _reference()
    df = pd.DataFrame(_component("C1", 10.2, 10.7) + _component("C2", 90, 100))
    result = applicability_summary(df, reference_df=ref, max_components=10)
    assert result["evaluated_components"] == 2
    assert result["counts"][SUPPORTED] == 1
    assert result["counts"][OUT_OF_DOMAIN] == 1
    assert result["status"] == "BLOCKED_PRESENT"


def test_drift_snapshot_stable_for_similar_populations():
    rows = []
    for i in range(50):
        rows += _component(f"T{i}", 10 + (i % 5) * 0.1, 11 + (i % 5) * 0.1, split="train")[:2]
        rows += _component(f"V{i}", 10.05 + (i % 5) * 0.1, 11.05 + (i % 5) * 0.1, split="test")[:2]
    result = drift_snapshot(pd.DataFrame(rows))
    assert result["available"] is True
    assert result["status"] == "STABLE"


def test_drift_snapshot_alerts_on_large_population_shift():
    rows = []
    for i in range(50):
        rows += _component(f"T{i}", 10 + (i % 5) * 0.1, 11 + (i % 5) * 0.1, split="train")[:2]
        rows += _component(f"V{i}", 40 + (i % 5) * 0.1, 50 + (i % 5) * 0.1, split="test")[:2]
    result = drift_snapshot(pd.DataFrame(rows))
    assert result["status"] == "ALERT"
    assert any(m.get("severity") == "ALERT" for m in result["metrics"])


def test_rolling_forecast_waits_for_96h_without_fabricating_update():
    df = pd.DataFrame(_component("C1", 10, 12))
    model_b = {"available": True, "prediction_168h_uA": 20.0}
    result = rolling_forecast_update(df, 0, model_b)
    assert result["status"] == "WAITING_FOR_96H"
    assert result["updated_168h_uA"] is None
    assert result["is_trained_96h_ml_model"] is False


def test_rolling_forecast_updates_transparently_at_96h():
    df = pd.DataFrame(_component("C1", 10, 12, 22, 32))
    model_b = {"available": True, "prediction_168h_uA": 18.0}
    result = rolling_forecast_update(df, 0, model_b)
    assert result["status"] == "UPDATED_AT_96H"
    assert result["updated_168h_uA"] == 32.0
    assert result["forecast_shift_uA"] == 14.0
    assert result["trajectory"] == "DETERIORATING"
    assert result["engineering_96h_update_absolute_error_uA"] == 0.0
