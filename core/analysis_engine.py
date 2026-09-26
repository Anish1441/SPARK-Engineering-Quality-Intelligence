from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------

def _num(df: pd.DataFrame) -> pd.DataFrame:
    """Return numeric columns only."""
    return df.select_dtypes(include="number")


def _finite(series: pd.Series) -> np.ndarray:
    """Return finite numeric values as a float NumPy array."""
    values = pd.to_numeric(series, errors="coerce")

    values = values.replace(
        [np.inf, -np.inf],
        np.nan,
    ).dropna()

    return values.to_numpy(dtype=float)


def _safe_float(value):
    """Convert numeric values safely for JSON serialization."""
    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    return value if np.isfinite(value) else None


# ---------------------------------------------------------------------------
# ROBUST STATISTICS
# ---------------------------------------------------------------------------

def robust_stats(series: pd.Series) -> dict:
    """
    Calculate robust and descriptive statistics for one signal.

    These values are descriptive analytical evidence only.
    They are not engineering specifications.
    """

    x = _finite(series)

    if len(x) == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "range": None,
            "mad": None,
            "q05": None,
            "q25": None,
            "q75": None,
            "q95": None,
            "iqr": None,
            "cv_pct": None,
            "skewness": None,
        }

    median = float(np.median(x))
    mad = float(np.median(np.abs(x - median)))

    std = (
        float(np.std(x, ddof=1))
        if len(x) > 1
        else 0.0
    )

    minimum = float(np.min(x))
    maximum = float(np.max(x))

    q05, q25, q75, q95 = np.percentile(
        x,
        [5, 25, 75, 95],
    )

    iqr = float(q75 - q25)

    mean = float(np.mean(x))

    if abs(mean) > 1e-12:
        cv_pct = abs(std / mean) * 100.0
    else:
        cv_pct = None

    if len(x) >= 3 and std > 1e-12:
        skewness = float(
            np.mean(((x - mean) / std) ** 3)
        )
    else:
        skewness = None

    return {
        "count": int(len(x)),
        "mean": mean,
        "median": median,
        "std": std,
        "min": minimum,
        "max": maximum,
        "range": float(maximum - minimum),
        "mad": mad,
        "q05": float(q05),
        "q25": float(q25),
        "q75": float(q75),
        "q95": float(q95),
        "iqr": iqr,
        "cv_pct": _safe_float(cv_pct),
        "skewness": _safe_float(skewness),
    }


# ---------------------------------------------------------------------------
# DATASET HEALTH
# ---------------------------------------------------------------------------

def dataset_health(df: pd.DataFrame) -> dict:
    """Return high-level dataset quality information."""

    rows = int(len(df))
    columns = int(len(df.columns))

    missing = int(df.isna().sum().sum())

    numeric = _num(df)

    total_cells = max(
        1,
        rows * max(1, columns),
    )

    completeness = 100.0 * (
        1.0 - missing / total_cells
    )

    usable_numeric_signals = sum(
        numeric[column].notna().sum() >= 3
        for column in numeric.columns
    )

    return {
        "rows": rows,
        "columns": columns,
        "numeric_signals": int(len(numeric.columns)),
        "missing_cells": missing,
        "duplicate_rows": int(df.duplicated().sum()),
        "completeness_pct": round(completeness, 1),
        "usable_numeric_signals": int(
            usable_numeric_signals
        ),
    }


# ---------------------------------------------------------------------------
# CONTROL / STATISTICAL SCREEN
# ---------------------------------------------------------------------------

def signal_control(
    df: pd.DataFrame,
    column: str,
) -> dict:
    """
    Calculate descriptive control limits and robust outlier screening.

    outlier_indices are positional indices in the ORIGINAL dataframe, even
    when the signal contains missing/non-finite values. This is important for
    traceability back to the source record.

    These limits are analytical screening limits, not engineering
    specifications.
    """

    if column not in df.columns:
        raise KeyError("Signal not found.")

    numeric = pd.to_numeric(df[column], errors="coerce")
    raw = numeric.to_numpy(dtype=float, na_value=np.nan)
    finite_mask = np.isfinite(raw)
    positions = np.flatnonzero(finite_mask)
    x = raw[finite_mask]

    if len(x) < 3:
        return {
            "signal": column,
            "eligible": False,
            "reason": "At least 3 finite observations are required.",
            "values": [float(value) for value in x],
            "observation_indices": [int(i) for i in positions],
            "outlier_indices": [],
        }

    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1))
    median = float(np.median(x))
    mad = float(np.median(np.abs(x - median)))
    scale = 1.4826 * mad or std or 1.0
    robust_z = np.abs((x - median) / scale)

    outlier_indices = [
        int(positions[i])
        for i, value in enumerate(robust_z)
        if value >= 3.5
    ]

    return {
        "signal": column,
        "eligible": True,
        "mean": mean,
        "std": std,
        "ucl": mean + 3.0 * std,
        "center": mean,
        "lcl": mean - 3.0 * std,
        "median": median,
        "mad": mad,
        "values": [float(value) for value in x],
        "observation_indices": [int(i) for i in positions],
        "outlier_indices": outlier_indices,
        "method": "Shewhart 3-sigma + robust MAD screen",
        "note": (
            "Descriptive screening limits; not engineering specifications."
        ),
    }


# ---------------------------------------------------------------------------
# RECORD ASSESSMENT
# ---------------------------------------------------------------------------

def record_assessment(
    df: pd.DataFrame,
    index: int,
) -> dict:
    """Calculate the analytical evidence for one record."""

    if index < 0 or index >= len(df):
        raise IndexError(
            "Record index is out of range."
        )

    row = df.iloc[index]

    contributors = []

    numeric = _num(df)

    for column in numeric.columns:

        values = _finite(df[column])

        if len(values) < 3:
            continue

        value = pd.to_numeric(
            pd.Series([row[column]]),
            errors="coerce",
        ).iloc[0]

        if pd.isna(value):
            continue

        median = float(
            np.median(values)
        )

        mad = float(
            np.median(
                np.abs(values - median)
            )
        )

        scale = (
            1.4826 * mad
            or float(np.std(values))
            or 1.0
        )

        robust_z = (
            abs(float(value) - median)
            / scale
        )

        if robust_z >= 2.5:
            contributors.append(
                {
                    "signal": str(column),
                    "value": float(value),
                    "baseline": median,
                    "robust_z": round(
                        robust_z,
                        2,
                    ),
                }
            )

    contributors.sort(
        key=lambda item: item["robust_z"],
        reverse=True,
    )

    raw_score = (
        contributors[0]["robust_z"]
        if contributors
        else 0
    )

    score = int(
        round(
            min(
                100,
                raw_score / 5.0 * 100,
            )
        )
    )

    state = (
        "HIGH RISK"
        if score >= 70
        else "REVIEW"
        if score >= 40
        else "NORMAL"
    )

    evidence_coverage = (
        len(contributors)
        / max(1, len(numeric.columns))
        * 100
    )

    return {
        "record_index": int(index),
        "score": score,
        "state": state,
        "contributors": contributors[:5],
        "evidence_coverage": round(
            evidence_coverage,
            1,
        ),
        "mode": "STATISTICAL SCREEN",
    }


# ---------------------------------------------------------------------------
# SIGNAL RISK / QUALITY PROFILE
# ---------------------------------------------------------------------------

def _signal_profile(
    df: pd.DataFrame,
    column: str,
) -> dict:
    """
    Build a professional signal-level analytical profile.

    Used later by the frontend for:
    - risk bars
    - quality grading
    - box plots
    - distribution cards
    """

    series = df[column]

    values = _finite(series)

    stats = robust_stats(series)

    total = len(series)

    finite_count = len(values)

    missing_count = total - int(
        series.notna().sum()
    )

    non_finite_count = max(
        0,
        total
        - finite_count
        - missing_count,
    )

    control = signal_control(
        df,
        column,
    )

    outlier_count = len(
        control.get(
            "outlier_indices",
            [],
        )
    )

    outlier_pct = (
        outlier_count
        / max(1, finite_count)
        * 100.0
    )

    q25 = stats["q25"]
    q75 = stats["q75"]

    if q25 is not None and q75 is not None:
        iqr = q75 - q25

        lower_fence = q25 - 1.5 * iqr
        upper_fence = q75 + 1.5 * iqr
    else:
        lower_fence = None
        upper_fence = None

    return {
        "signal": str(column),
        "count": stats["count"],
        "missing": int(missing_count),
        "non_finite": int(non_finite_count),
        "completeness_pct": round(
            finite_count
            / max(1, total)
            * 100.0,
            1,
        ),
        "mean": stats["mean"],
        "median": stats["median"],
        "std": stats["std"],
        "min": stats["min"],
        "max": stats["max"],
        "range": stats["range"],
        "mad": stats["mad"],
        "q05": stats["q05"],
        "q25": q25,
        "q75": q75,
        "q95": stats["q95"],
        "iqr": stats["iqr"],
        "lower_fence": _safe_float(
            lower_fence
        ),
        "upper_fence": _safe_float(
            upper_fence
        ),
        "cv_pct": stats["cv_pct"],
        "skewness": stats["skewness"],
        "outlier_count": int(
            outlier_count
        ),
        "outlier_pct": round(
            outlier_pct,
            2,
        ),
        "control_ucl": control.get(
            "ucl"
        ),
        "control_center": control.get(
            "center"
        ),
        "control_lcl": control.get(
            "lcl"
        ),
    }


# ---------------------------------------------------------------------------
# COMPLETE DATASET ANALYSIS
# ---------------------------------------------------------------------------

def analyze_dataset(
    df: pd.DataFrame,
) -> dict:
    """
    Generate the complete analytical evidence package.

    Existing response keys are preserved for compatibility.
    Additional analytical views are returned for the upgraded UI.
    """

    health = dataset_health(df)

    stability = []
    distributions = []
    signal_profiles = []
    correlations = []

    numeric = _num(df)

    # ---------------------------------------------------------------
    # Signal-level analysis
    # ---------------------------------------------------------------

    for column in numeric.columns:

        column_name = str(column)

        control = signal_control(
            df,
            column_name,
        )

        stats = robust_stats(
            df[column]
        )

        profile = _signal_profile(
            df,
            column_name,
        )

        distributions.append(
            {
                "signal": column_name,
                "stats": stats,
            }
        )

        stability.append(
            {
                "signal": column_name,
                "mean": control.get("mean"),
                "std": control.get("std"),
                "outliers": len(
                    control.get(
                        "outlier_indices",
                        [],
                    )
                ),
                "eligible": control.get(
                    "eligible",
                    False,
                ),
            }
        )

        signal_profiles.append(
            profile
        )

    # ---------------------------------------------------------------
    # Correlation analysis
    # ---------------------------------------------------------------

    corr = numeric.corr()

    for i, first in enumerate(
        corr.columns
    ):
        for second in corr.columns[
            i + 1:
        ]:

            value = corr.loc[
                first,
                second,
            ]

            if pd.notna(value):
                correlations.append(
                    {
                        "x": str(first),
                        "y": str(second),
                        "correlation": float(
                            value
                        ),
                    }
                )

    correlations.sort(
        key=lambda item: abs(
            item["correlation"]
        ),
        reverse=True,
    )

    # ---------------------------------------------------------------
    # Full correlation matrix
    # ---------------------------------------------------------------

    correlation_matrix = []

    for row_name in corr.index:

        for column_name in corr.columns:

            value = corr.loc[
                row_name,
                column_name,
            ]

            correlation_matrix.append(
                {
                    "x": str(column_name),
                    "y": str(row_name),
                    "value": (
                        float(value)
                        if pd.notna(value)
                        else None
                    ),
                }
            )

    # ---------------------------------------------------------------
    # Dataset-level analytical summary
    # ---------------------------------------------------------------

    eligible_profiles = [
        item
        for item in signal_profiles
        if item["count"] >= 3
    ]

    if eligible_profiles:

        highest_outlier_signal = max(
            eligible_profiles,
            key=lambda item: item[
                "outlier_pct"
            ],
        )

        highest_variation_signal = max(
            eligible_profiles,
            key=lambda item: (
                item["cv_pct"]
                if item["cv_pct"] is not None
                else -1
            ),
        )

        lowest_completeness_signal = min(
            eligible_profiles,
            key=lambda item: item[
                "completeness_pct"
            ],
        )

        dataset_summary = {
            "signals_analyzed": int(
                len(eligible_profiles)
            ),
            "highest_outlier_signal": (
                highest_outlier_signal[
                    "signal"
                ]
            ),
            "highest_outlier_pct": (
                highest_outlier_signal[
                    "outlier_pct"
                ]
            ),
            "highest_variation_signal": (
                highest_variation_signal[
                    "signal"
                ]
            ),
            "highest_cv_pct": (
                highest_variation_signal[
                    "cv_pct"
                ]
            ),
            "lowest_completeness_signal": (
                lowest_completeness_signal[
                    "signal"
                ]
            ),
            "lowest_completeness_pct": (
                lowest_completeness_signal[
                    "completeness_pct"
                ]
            ),
        }

    else:

        dataset_summary = {
            "signals_analyzed": 0,
            "highest_outlier_signal": None,
            "highest_outlier_pct": None,
            "highest_variation_signal": None,
            "highest_cv_pct": None,
            "lowest_completeness_signal": None,
            "lowest_completeness_pct": None,
        }

    # ---------------------------------------------------------------
    # Return complete analysis package
    # ---------------------------------------------------------------

    return {
        # Existing API fields
        "health": health,
        "stability": stability,
        "distributions": distributions,
        "correlations": correlations[:20],

        # New professional analytical views
        "signal_profiles": signal_profiles,
        "correlation_matrix": correlation_matrix,
        "dataset_summary": dataset_summary,
    }


# ---------------------------------------------------------------------------
# SIMPLE DATASET COMPARISON
# ---------------------------------------------------------------------------

def dataset_comparison(
    df: pd.DataFrame,
) -> dict:
    """Return compact signal comparison statistics."""

    output = []

    for column in _num(df).columns:

        series = df[column].dropna()

        if len(series) == 0:
            continue

        output.append(
            {
                "signal": str(column),
                "mean": float(
                    series.mean()
                ),
                "median": float(
                    series.median()
                ),
                "std": (
                    float(
                        series.std(
                            ddof=1
                        )
                    )
                    if len(series) > 1
                    else 0.0
                ),
            }
        )

    return {
        "signals": output
    }