import numpy as np
import pandas as pd

from core.analysis_engine import dataset_health, record_assessment, signal_control


def test_health_counts_numeric_signals():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    result = dataset_health(df)
    assert result["numeric_signals"] == 1
    assert result["rows"] == 3


def test_control_is_eligible_for_numeric_signal():
    df = pd.DataFrame({"a": [1, 2, 3, 100]})
    result = signal_control(df, "a")
    assert result["eligible"] is True
    assert len(result["values"]) == 4


def test_signal_control_preserves_original_row_positions_with_missing_values():
    df = pd.DataFrame({"a": [1.0, np.nan, 1.1, 1.2, 100.0]})
    result = signal_control(df, "a")

    assert result["observation_indices"] == [0, 2, 3, 4]
    assert 4 in result["outlier_indices"]
    assert 3 not in result["outlier_indices"]


def test_record_assessment_scores_large_deviation():
    df = pd.DataFrame({"a": [1, 2, 3, 100]})
    result = record_assessment(df, 3)
    assert result["score"] > 0
    assert result["state"] in {"NORMAL", "REVIEW", "HIGH RISK"}
