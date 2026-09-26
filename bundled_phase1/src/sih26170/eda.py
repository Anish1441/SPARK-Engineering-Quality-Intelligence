"""Label-blind exploratory analysis for cleaned burn-in measurements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from sih26170.config import settings

CLEAN_REQUIRED_COLUMNS = frozenset(
    {
        "measurement_id",
        "component_id",
        "lot_id",
        "burnin_batch_id",
        "dataset_split",
        "measurement_time_h",
        "leakage_current_uA",
        "datasheet_upper_limit_uA",
        "quality_status",
        "missing_value_flag",
        "condition_mismatch_flag",
        "usable_for_ml",
    }
)


@dataclass(frozen=True)
class EDAReport:
    """Paths and headline counts produced by one EDA run."""

    output_dir: Path
    summary_path: Path
    timepoint_statistics_path: Path
    lot_time_statistics_path: Path
    figure_paths: tuple[Path, ...]
    components: int
    measurements: int
    usable_measurements: int


def load_clean_measurements(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate the cleaned long-format dataset."""

    source = Path(path) if path is not None else settings.clean_long_data_path
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(
            f"Clean dataset not found: {source}. Run scripts/02_clean_data.py first."
        )

    frame = pd.read_csv(source, low_memory=False)
    missing_columns = CLEAN_REQUIRED_COLUMNS.difference(frame.columns)
    if missing_columns:
        names = ", ".join(sorted(missing_columns))
        raise ValueError(f"Clean dataset is missing required columns: {names}.")
    if frame["measurement_id"].duplicated().any():
        raise ValueError("Clean measurement_id values must be unique.")
    return frame


def build_overview(clean: pd.DataFrame) -> pd.DataFrame:
    """Create evaluator-friendly headline metrics without using hidden labels."""

    usable = clean["usable_for_ml"].astype(bool)
    above_limit = usable & (
        clean["leakage_current_uA"] > clean["datasheet_upper_limit_uA"]
    )
    metrics = [
        ("Measurements", len(clean)),
        ("Unique components", clean["component_id"].nunique()),
        ("Manufacturing lots", clean["lot_id"].nunique()),
        ("Burn-in batches", clean["burnin_batch_id"].nunique()),
        ("Usable measurements", int(usable.sum())),
        ("Unusable measurements", int((~usable).sum())),
        ("Missing measurements", int(clean["missing_value_flag"].astype(bool).sum())),
        (
            "Condition mismatches",
            int(clean["condition_mismatch_flag"].astype(bool).sum()),
        ),
        ("Observed static-limit exceedances", int(above_limit.sum())),
    ]
    return pd.DataFrame(metrics, columns=["metric", "value"])


def build_timepoint_statistics(clean: pd.DataFrame) -> pd.DataFrame:
    """Summarize usable leakage distributions independently at every checkpoint."""

    usable = clean.loc[clean["usable_for_ml"].astype(bool)].copy()
    grouped = usable.groupby("measurement_time_h")["leakage_current_uA"]
    stats = grouped.agg(
        usable_count="count",
        mean_uA="mean",
        median_uA="median",
        std_uA="std",
        minimum_uA="min",
        q1_uA=lambda values: values.quantile(0.25),
        q3_uA=lambda values: values.quantile(0.75),
        maximum_uA="max",
    ).reset_index()
    numeric_columns = stats.columns.difference(["measurement_time_h", "usable_count"])
    stats[numeric_columns] = stats[numeric_columns].round(6)
    return stats


def _median_absolute_deviation(values: pd.Series) -> float:
    median = values.median()
    return float((values - median).abs().median())


def build_lot_time_statistics(clean: pd.DataFrame) -> pd.DataFrame:
    """Calculate robust lot baselines needed to understand Module A behaviour."""

    usable = clean.loc[clean["usable_for_ml"].astype(bool)].copy()
    stats = (
        usable.groupby(["lot_id", "dataset_split", "measurement_time_h"])[
            "leakage_current_uA"
        ]
        .agg(
            usable_count="count",
            lot_mean_uA="mean",
            lot_median_uA="median",
            lot_mad_uA=_median_absolute_deviation,
        )
        .reset_index()
    )
    for column in ["lot_mean_uA", "lot_median_uA", "lot_mad_uA"]:
        stats[column] = stats[column].round(6)
    return stats


def build_quality_status_counts(clean: pd.DataFrame) -> pd.DataFrame:
    counts = clean["quality_status"].value_counts().rename_axis("quality_status")
    return counts.reset_index(name="measurement_count")


def _configure_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 160,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
        }
    )


def _save_figure(figure: plt.Figure, path: Path) -> Path:
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)
    return path


def plot_quality_statuses(clean: pd.DataFrame, destination: Path) -> Path:
    counts = build_quality_status_counts(clean).sort_values("measurement_count")
    figure, axis = plt.subplots(figsize=(9, 4.8))
    sns.barplot(data=counts, x="measurement_count", y="quality_status", ax=axis)
    axis.set_title("Measurement Quality Outcomes")
    axis.set_xscale("log")
    axis.set_xlabel("Component-time measurements (log scale)")
    axis.set_ylabel("")
    axis.tick_params(axis="y", labelsize=8)
    for container in axis.containers:
        axis.bar_label(container, fmt="{:,.0f}", padding=3, fontsize=8)
    return _save_figure(figure, destination)


def plot_leakage_distributions(clean: pd.DataFrame, destination: Path) -> Path:
    usable = clean.loc[clean["usable_for_ml"].astype(bool)].copy()
    figure, axis = plt.subplots(figsize=(9, 5.2))
    sns.boxplot(
        data=usable,
        x="measurement_time_h",
        y="leakage_current_uA",
        showfliers=True,
        fliersize=1.5,
        ax=axis,
    )
    axis.axhline(
        settings.datasheet_upper_limit_uA,
        color="#B22222",
        linestyle="--",
        linewidth=1.5,
        label="175 uA datasheet maximum",
    )
    axis.set_yscale("log")
    axis.set_title("Leakage Distribution at Each Burn-In Checkpoint")
    axis.set_xlabel("Burn-in time (hours)")
    axis.set_ylabel("Reverse leakage current, IR (uA, log scale)")
    axis.legend(loc="upper left")
    return _save_figure(figure, destination)


def plot_lot_median_trajectories(
    lot_stats: pd.DataFrame,
    destination: Path,
) -> Path:
    figure, axis = plt.subplots(figsize=(9, 5.4))
    sns.lineplot(
        data=lot_stats,
        x="measurement_time_h",
        y="lot_median_uA",
        hue="lot_id",
        style="dataset_split",
        markers=True,
        dashes=False,
        ax=axis,
        palette="tab20",
    )
    axis.set_title("Lot Median Leakage Trajectories")
    axis.set_xlabel("Burn-in time (hours)")
    axis.set_ylabel("Lot median IR (uA)")
    axis.set_xticks(list(settings.expected_timepoints_h))
    axis.legend(title="Lot / split", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=7)
    return _save_figure(figure, destination)


def plot_measurement_usability(clean: pd.DataFrame, destination: Path) -> Path:
    categories = np.select(
        [
            clean["missing_value_flag"].astype(bool),
            clean["condition_mismatch_flag"].astype(bool),
        ],
        ["Missing", "Condition mismatch"],
        default="Usable",
    )
    counts = (
        clean.assign(usability=categories)
        .groupby(["measurement_time_h", "usability"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=["Usable", "Missing", "Condition mismatch"], fill_value=0)
    )
    issue_counts = counts[["Missing", "Condition mismatch"]]
    figure, axis = plt.subplots(figsize=(9, 4.8))
    issue_counts.plot(
        kind="bar",
        stacked=True,
        color=["#D99000", "#B22222"],
        ax=axis,
    )
    axis.set_title("Unusable Measurements by Burn-In Checkpoint")
    axis.set_xlabel("Burn-in time (hours)")
    axis.set_ylabel("Missing or condition-mismatched measurements")
    axis.tick_params(axis="x", rotation=0)
    axis.legend(title="Issue requiring exclusion or retest")
    for position, time_h in enumerate(counts.index):
        issue_total = int(issue_counts.loc[time_h].sum())
        usable_total = int(counts.loc[time_h, "Usable"])
        axis.text(
            position,
            issue_total + 0.7,
            f"Usable: {usable_total:,}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    return _save_figure(figure, destination)


def plot_early_reading_relationship(clean: pd.DataFrame, destination: Path) -> Path:
    usable = clean.assign(
        ml_value=clean["leakage_current_uA"].where(clean["usable_for_ml"].astype(bool))
    )
    pivot = usable.pivot(index="component_id", columns="measurement_time_h", values="ml_value")
    metadata = clean.drop_duplicates("component_id").set_index("component_id")[["lot_id"]]
    early = pivot[[0, 24]].dropna().join(metadata).rename(columns={0: "ir_0h", 24: "ir_24h"})

    figure, axis = plt.subplots(figsize=(7.2, 6.2))
    sns.scatterplot(
        data=early,
        x="ir_0h",
        y="ir_24h",
        hue="lot_id",
        s=16,
        alpha=0.55,
        linewidth=0,
        palette="tab20",
        ax=axis,
    )
    maximum = max(early["ir_0h"].max(), early["ir_24h"].max())
    axis.plot([0, maximum], [0, maximum], color="#333333", linestyle="--", linewidth=1)
    axis.axvline(settings.datasheet_upper_limit_uA, color="#B22222", linestyle=":")
    axis.axhline(settings.datasheet_upper_limit_uA, color="#B22222", linestyle=":")
    axis.set_title("Early Burn-In Relationship: 0 h versus 24 h")
    axis.set_xlabel("IR at 0 h (uA)")
    axis.set_ylabel("IR at 24 h (uA)")
    axis.legend(title="Lot", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=7)
    return _save_figure(figure, destination)


def _atomic_csv(frame: pd.DataFrame, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(destination)


def generate_eda_report(
    clean: pd.DataFrame,
    output_dir: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> EDAReport:
    """Generate all label-blind tables and figures for evaluator inspection."""

    destination = Path(output_dir) if output_dir is not None else settings.eda_report_dir
    destination = destination.expanduser().resolve()
    expected_outputs = [
        destination / "eda_summary.csv",
        destination / "timepoint_statistics.csv",
        destination / "lot_time_statistics.csv",
        destination / "quality_status_counts.csv",
        destination / "01_quality_statuses.png",
        destination / "02_leakage_distributions.png",
        destination / "03_lot_median_trajectories.png",
        destination / "04_measurement_usability.png",
        destination / "05_early_0h_vs_24h.png",
    ]
    existing = [path for path in expected_outputs if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"EDA output already exists: {existing[0]}. Use overwrite=True to replace reports."
        )
    destination.mkdir(parents=True, exist_ok=True)

    overview = build_overview(clean)
    timepoint_stats = build_timepoint_statistics(clean)
    lot_stats = build_lot_time_statistics(clean)
    quality_counts = build_quality_status_counts(clean)

    _atomic_csv(overview, expected_outputs[0])
    _atomic_csv(timepoint_stats, expected_outputs[1])
    _atomic_csv(lot_stats, expected_outputs[2])
    _atomic_csv(quality_counts, expected_outputs[3])

    _configure_style()
    figure_paths = (
        plot_quality_statuses(clean, expected_outputs[4]),
        plot_leakage_distributions(clean, expected_outputs[5]),
        plot_lot_median_trajectories(lot_stats, expected_outputs[6]),
        plot_measurement_usability(clean, expected_outputs[7]),
        plot_early_reading_relationship(clean, expected_outputs[8]),
    )
    return EDAReport(
        output_dir=destination,
        summary_path=expected_outputs[0],
        timepoint_statistics_path=expected_outputs[1],
        lot_time_statistics_path=expected_outputs[2],
        figure_paths=figure_paths,
        components=clean["component_id"].nunique(),
        measurements=len(clean),
        usable_measurements=int(clean["usable_for_ml"].astype(bool).sum()),
    )
