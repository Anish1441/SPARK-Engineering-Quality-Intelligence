from pathlib import Path

import pandas as pd
import pytest

from core.config import resolve_pipeline_root
from core.dataset_manager import DatasetError, DatasetManager
from core.pipeline_adapter import PipelineAdapter
from core.qa_manager import QAManager


def test_pipeline_fails_closed_without_real_pipeline(tmp_path):
    adapter = PipelineAdapter(tmp_path)

    result = adapter.assess(pd.DataFrame({"x": [1, 2, 3]}), 0)

    assert result["available"] is False
    assert result["module_a_available"] is False
    assert result["module_b_available"] is False
    assert result["prediction"] is None
    assert "failed safely" in result["message"]


def test_pipeline_status_without_real_pipeline(tmp_path):
    adapter = PipelineAdapter(tmp_path)
    status = adapter.status()

    assert status["module_a_available"] is False
    assert status["module_b_available"] is False
    assert status["prediction_available"] is False
    assert status["model_bundle_loaded"] is False
    assert status["cached_datasets"] == 0


def test_module_a_artifact_contract_accepts_phase1_model_key(tmp_path):
    adapter = PipelineAdapter(tmp_path)
    marker = object()

    model, metadata = adapter._extract_module_a_artifact(
        {
            "model": marker,
            "metadata": {"module": "A", "time_cutoff_h": 24},
        }
    )

    assert model is marker
    assert metadata["module"] == "A"
    assert metadata["time_cutoff_h"] == 24


def test_dual_module_evidence_is_cached_per_dataset(tmp_path):
    adapter = PipelineAdapter(tmp_path)

    calls = {"features": 0, "module_a": 0, "module_b": 0}

    def build_features(df):
        calls["features"] += 1
        return (
            pd.DataFrame(
                {
                    "component_id": ["C1", "C2"],
                    "usable_for_module_b_at_24h": [True, True],
                }
            ),
            None,
        )

    def score_module_a(features, model):
        calls["module_a"] += 1
        return pd.DataFrame(
            {
                "component_id": ["C1", "C2"],
                "ir_0h_uA": [5.0, 6.0],
                "ir_24h_uA": [5.2, 6.2],
                "within_lot_risk_score": [1.1, 3.9],
                "historical_risk_score": [0.9, 3.2],
                "lot_shift_risk_score": [0.4, 0.5],
                "batch_median_slope_0_24": [0.01, 0.02],
                "batch_slope_shift_score": [0.3, 0.4],
                "isolation_forest_raw_score": [0.02, 0.11],
                "isolation_forest_is_outlier": [False, True],
                "static_limit_failed_at_24h": [False, False],
                "module_a_action": ["ACCEPT", "HOLD_FOR_REVIEW"],
                "module_a_primary_reason": [
                    "No significant 24-hour anomaly detected.",
                    "Isolation Forest detected an unusual early-life pattern.",
                ],
            }
        )

    def predict_module_b(features, bundle):
        calls["module_b"] += 1
        return pd.DataFrame(
            {
                "component_id": ["C1", "C2"],
                "module_b_prediction_available": [True, True],
                "selected_model": ["fake", "fake"],
                "predicted_ir_168h_uA": [10.0, 20.0],
            }
        )

    adapter._feature_load_error = None
    adapter._feature_builder = build_features

    adapter._module_a_load_error = None
    adapter._module_a_score_function = score_module_a
    adapter._module_a_model = object()

    adapter._module_b_load_error = None
    adapter._module_b_predict_function = predict_module_b
    adapter._module_b_bundle = object()

    df = pd.DataFrame(
        {
            "component_id": ["C1", "C2"],
            "measurement_time_h": [24, 24],
            "leakage_current_uA": [5.0, 6.0],
            "usable_for_ml": [True, True],
        }
    )

    first = adapter.assess(df, 0, cache_key="dataset-a")
    second = adapter.assess(df, 1, cache_key="dataset-a")

    assert first["module_a"]["action"] == "ACCEPT"
    assert second["module_a"]["action"] == "HOLD_FOR_REVIEW"
    assert first["prediction_168h_uA"] == 10.0
    assert second["prediction_168h_uA"] == 20.0
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert calls == {"features": 1, "module_a": 1, "module_b": 1}

    adapter.invalidate("dataset-a")
    adapter.assess(df, 0, cache_key="dataset-a")
    assert calls == {"features": 2, "module_a": 2, "module_b": 2}


def test_dataset_manager_registers_bundled_sample_as_read_only(tmp_path):
    data_root = tmp_path / "runtime"
    sample_root = tmp_path / "samples"
    sample_root.mkdir()

    pd.DataFrame({"x": [1, 2, 3]}).to_csv(
        sample_root / DatasetManager.SAMPLE_FILENAME,
        index=False,
    )

    manager = DatasetManager(data_root, sample_root=sample_root)
    items = manager.list()

    sample = next(
        item
        for item in items
        if item["dataset_id"] == DatasetManager.SAMPLE_DATASET_ID
    )
    assert sample["read_only"] is True
    assert sample["source"] == "bundled_sample"

    with pytest.raises(DatasetError):
        manager.remove(DatasetManager.SAMPLE_DATASET_ID)


def test_qa_manager_persists_module_a_and_module_b_evidence(tmp_path):
    qa = QAManager(tmp_path)

    saved = qa.save(
        "dataset-a",
        {
            "record_index": 5,
            "component_id": "C005",
            "action": "WATCH",
            "response": "AGREE",
            "module_a_action": "HOLD_FOR_REVIEW",
            "module_a_primary_reason": "Early anomaly detected.",
            "module_a_within_lot_risk_score": 3.8,
            "ai_model": "median_ensemble",
            "ai_prediction_168h_uA": 42.5,
            "ai_prediction_upper_95_uA": 48.1,
            "analytical_score": 62,
            "analytical_state": "REVIEW",
            "model_snapshot": {
                "module_a": {"available": True},
                "module_b": {"available": True},
            },
        },
    )

    assert saved["final_action"] == "WATCH"
    assert saved["schema_version"] == 7

    rows = qa.list("dataset-a")
    assert rows[0]["module_a_action"] == "HOLD_FOR_REVIEW"
    assert rows[0]["ai_prediction_168h_uA"] == 42.5
    assert rows[0]["component_id"] == "C005"

    assert qa.delete_dataset("dataset-a") == 1
    assert qa.list("dataset-a") == []


def test_real_dual_module_pipeline_is_loaded_when_available():
    real_pipeline = Path(resolve_pipeline_root())
    required = [
        real_pipeline / "src" / "sih26170",
        real_pipeline / "artifacts" / "models" / "module_a_24h.joblib",
        real_pipeline / "artifacts" / "models" / "module_b_24h.joblib",
        real_pipeline
        / "data"
        / "processed"
        / "02_clean_measurements_long.csv",
    ]

    if not all(path.exists() for path in required):
        pytest.skip("External SPARK Phase-1 dual-module pipeline is unavailable.")

    adapter = PipelineAdapter(real_pipeline)
    status = adapter.status()

    assert status["pipeline_accessible"] is True
    assert status["feature_engineering_loaded"] is True
    assert status["module_a_available"] is True
    assert status["module_b_available"] is True
    assert status["module_a"]["model_exists"] is True
    assert status["module_a"]["model_loaded"] is True
    assert status["module_b"]["model_exists"] is True
    assert status["module_b"]["model_bundle_loaded"] is True
    assert status["prediction_available"] is True


def test_component_inspection_uses_one_item_per_component_and_prefers_24h():
    from core.inspection import resolve_inspection_target

    df = pd.DataFrame(
        {
            "component_id": ["C1", "C1", "C1", "C2", "C2"],
            "measurement_time_h": [0, 24, 168, 0, 96],
            "leakage_current_uA": [1, 2, 3, 4, 5],
        }
    )

    first = resolve_inspection_target(df, 0)
    second = resolve_inspection_target(df, 1)

    assert first["inspection_mode"] == "component"
    assert first["inspection_count"] == 2
    assert first["component_id"] == "C1"
    assert first["record_index"] == 1

    assert second["component_id"] == "C2"
    assert second["record_index"] == 3
