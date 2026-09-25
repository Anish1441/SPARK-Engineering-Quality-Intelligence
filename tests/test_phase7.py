from pathlib import Path

import pandas as pd

from core.pipeline_adapter import PipelineAdapter


REAL_PIPELINE = Path(
    r"C:\Users\anish\Downloads"
    r"\SIH26170_Prototype_Phase1"
    r"\sih26170_prototype"
)


def test_pipeline_fails_closed_without_real_pipeline(tmp_path):
    adapter = PipelineAdapter(str(tmp_path))

    result = adapter.assess(
        pd.DataFrame({"x": [1, 2, 3]}),
        0,
    )

    assert result["available"] is False
    assert result["prediction"] is None
    assert "Original SPARK pipeline" in result["message"]


def test_pipeline_status_without_real_pipeline(tmp_path):
    adapter = PipelineAdapter(str(tmp_path))

    status = adapter.status()

    assert status["prediction_available"] is False
    assert status["model_bundle_loaded"] is False


def test_real_pipeline_is_loaded():
    if not REAL_PIPELINE.exists():
        return

    adapter = PipelineAdapter(str(REAL_PIPELINE))
    status = adapter.status()

    assert status["pipeline_accessible"] is True
    assert status["feature_engineering_loaded"] is True
    assert status["inference_function_loaded"] is True
    assert status["model_exists"] is True
    assert status["model_bundle_loaded"] is True
    assert status["prediction_available"] is True
    assert status["selected_model"] == "median_ensemble"