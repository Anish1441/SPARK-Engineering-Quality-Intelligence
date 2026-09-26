from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Allow this script to be executed directly from <repo>\\tools while still
# importing the SPARK package modules from the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

try:
    from core.config import load_settings
except Exception:
    load_settings = None


TIMES = [0, 24, 96, 168]
DEFAULT_LIMIT_UA = 175.0
SEED = 26170


def _mode(series: pd.Series, fallback):
    s = series.dropna()
    if s.empty:
        return fallback
    try:
        return s.mode().iloc[0]
    except Exception:
        return s.iloc[0]


def _robust_stats(df: pd.DataFrame) -> Dict[int, Tuple[float, float]]:
    out = {}
    for h in TIMES:
        s = pd.to_numeric(
            df.loc[df["measurement_time_h"].eq(h), "leakage_current_uA"],
            errors="coerce",
        ).dropna()
        if s.empty:
            out[h] = (10.0 + h * 0.01, 2.0)
            continue
        med = float(s.median())
        mad = float((s - med).abs().median())
        if not np.isfinite(mad) or mad < 1e-6:
            mad = max(float(s.std(ddof=0)), 1.0)
        out[h] = (med, mad)
    return out


def _schema_row_defaults(df: pd.DataFrame) -> Dict[str, object]:
    defaults = {}
    for col in df.columns:
        if col in {
            "measurement_id",
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "measurement_time_h",
            "leakage_current_uA",
        }:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            vals = pd.to_numeric(df[col], errors="coerce")
            defaults[col] = float(vals.median()) if vals.notna().any() else 0.0
        else:
            defaults[col] = _mode(df[col], "")
    return defaults


def _series_from_points(points: Dict[int, float]) -> Dict[int, float]:
    return {int(h): float(points[h]) for h in TIMES}


def _scenario_values(name: str, stats: Dict[int, Tuple[float, float]], rng: np.random.Generator, idx: int) -> Dict[int, float]:
    m0, d0 = stats[0]
    m24, d24 = stats[24]
    m96, d96 = stats[96]
    m168, d168 = stats[168]

    jitter = lambda d: float(rng.normal(0.0, max(d * 0.10, 0.03)))

    if name == "NOMINAL_BEST":
        return _series_from_points({
            0: max(0.1, m0 - 0.7*d0 + jitter(d0)),
            24: max(0.1, m24 - 0.7*d24 + jitter(d24)),
            96: max(0.1, m96 - 0.6*d96 + jitter(d96)),
            168: max(0.1, m168 - 0.5*d168 + jitter(d168)),
        })

    if name == "NOMINAL_TYPICAL":
        return _series_from_points({
            0: max(0.1, m0 + jitter(d0)),
            24: max(0.1, m24 + jitter(d24)),
            96: max(0.1, m96 + jitter(d96)),
            168: max(0.1, m168 + jitter(d168)),
        })

    if name == "BORDERLINE_EARLY":
        return _series_from_points({
            0: m0 + 2.6*d0 + jitter(d0),
            24: m24 + 2.8*d24 + jitter(d24),
            96: m96 + 2.0*d96 + jitter(d96),
            168: m168 + 1.8*d168 + jitter(d168),
        })

    if name == "EARLY_SPIKE_RECOVERY":
        return _series_from_points({
            0: m0 + 0.2*d0 + jitter(d0),
            24: m24 + 4.5*d24 + jitter(d24),
            96: m96 + 1.3*d96 + jitter(d96),
            168: m168 + 0.8*d168 + jitter(d168),
        })

    if name == "PROGRESSIVE_DEGRADATION":
        start = m0 + 0.3*d0 + jitter(d0)
        return _series_from_points({
            0: start,
            24: max(start + 0.8*d24, m24 + 0.8*d24),
            96: max(m96 + 3.5*d96, start + 4.0*d96),
            168: max(m168 + 6.0*d168, start + 8.0*d168),
        })

    if name == "LATE_ACCELERATION":
        # Early evidence remains ordinary, but the 96h checkpoint accelerates
        # strongly enough that the transparent 24->96 extrapolation should move
        # beyond the configured rolling-forecast stability tolerance.
        return _series_from_points({
            0: m0 + jitter(d0),
            24: m24 + 0.2*d24 + jitter(d24),
            96: min(DEFAULT_LIMIT_UA - 45.0, max(m96 + 7.0*d96 + 18.0, m24 + 18.0)),
            168: min(DEFAULT_LIMIT_UA - 8.0, max(m168 + 11.0*d168 + 28.0, m96 + 30.0)),
        })

    if name == "FORECAST_IMPROVING":
        return _series_from_points({
            0: m0 + 1.8*d0,
            24: m24 + 3.0*d24,
            96: max(0.1, m96 + 0.6*d96),
            168: max(0.1, m168 + 0.2*d168),
        })

    if name == "FORECAST_DETERIORATING":
        return _series_from_points({
            0: m0 + 0.2*d0,
            24: m24 + 0.5*d24,
            96: m96 + 4.0*d96 + 5.0,
            168: min(DEFAULT_LIMIT_UA - 3.0, m168 + 8.0*d168 + 15.0),
        })

    if name == "OOD_HIGH_BELOW_LIMIT":
        return _series_from_points({
            0: min(DEFAULT_LIMIT_UA - 35.0, max(70.0, m0 + 20*d0)),
            24: min(DEFAULT_LIMIT_UA - 25.0, max(85.0, m24 + 24*d24)),
            96: min(DEFAULT_LIMIT_UA - 18.0, max(95.0, m96 + 26*d96)),
            168: min(DEFAULT_LIMIT_UA - 10.0, max(105.0, m168 + 28*d168)),
        })

    if name == "HARD_LIMIT_BREACH_24H":
        return _series_from_points({
            0: m0,
            24: DEFAULT_LIMIT_UA + 12.0 + idx % 5,
            96: DEFAULT_LIMIT_UA + 20.0 + idx % 7,
            168: DEFAULT_LIMIT_UA + 30.0 + idx % 9,
        })

    if name == "HARD_LIMIT_BREACH_168H":
        return _series_from_points({
            0: m0,
            24: m24 + 0.5*d24,
            96: min(DEFAULT_LIMIT_UA - 15.0, m96 + 5.0*d96 + 15.0),
            168: DEFAULT_LIMIT_UA + 8.0 + idx % 8,
        })

    if name == "LOT_WIDE_SHIFT":
        # Shift the entire lot relative to historical training while keeping
        # components mutually similar. This is designed to exercise historical
        # lot-shift evidence rather than within-lot outlier detection.
        return _series_from_points({
            0: m0 + 5.2*d0 + jitter(d0),
            24: m24 + 5.4*d24 + jitter(d24),
            96: m96 + 5.2*d96 + jitter(d96),
            168: m168 + 5.0*d168 + jitter(d168),
        })

    if name == "BATCH_LOCAL_SHIFT":
        return _series_from_points({
            0: m0 + 2.8*d0 + jitter(d0),
            24: m24 + 3.4*d24 + jitter(d24),
            96: m96 + 3.0*d96 + jitter(d96),
            168: m168 + 3.1*d168 + jitter(d168),
        })

    if name == "INSTRUMENT_COMMONALITY":
        return _series_from_points({
            0: m0 + 3.4*d0 + jitter(d0),
            24: m24 + 4.3*d24 + jitter(d24),
            96: m96 + 4.0*d96 + jitter(d96),
            168: m168 + 4.2*d168 + jitter(d168),
        })

    if name == "CALIBRATION_STRESS":
        # Early points resemble ordinary data while late truth is pushed outside a
        # typical narrow forecast band. This is for coverage/backtest stress only.
        return _series_from_points({
            0: m0 + 0.1*d0 + jitter(d0),
            24: m24 + 0.2*d24 + jitter(d24),
            96: m96 + 2.5*d96 + 5.0,
            168: min(DEFAULT_LIMIT_UA - 4.0, m168 + 9.0*d168 + 25.0),
        })

    if name in {"MISSING_24H", "MISSING_0H", "CONDITION_MISMATCH", "UNUSABLE_FOR_ML"}:
        return _series_from_points({
            0: m0 + jitter(d0),
            24: m24 + jitter(d24),
            96: m96 + jitter(d96),
            168: m168 + jitter(d168),
        })

    raise KeyError(name)


SCENARIOS = [
    ("NOMINAL_BEST", 30, "Baseline / best case", "Normal low stable trajectory", "Normal processing; no forced escalation"),
    ("NOMINAL_TYPICAL", 30, "Baseline", "Typical in-domain stable trajectory", "Normal processing"),
    ("BORDERLINE_EARLY", 24, "Module A / Risk", "Early robust-z near watch region", "Elevated early-life evidence"),
    ("EARLY_SPIKE_RECOVERY", 24, "Module A / Rolling forecast", "24h spike followed by recovery", "Early anomaly with later improvement"),
    ("PROGRESSIVE_DEGRADATION", 30, "Module B / Risk", "Monotonic degradation", "Forecast/risk escalation"),
    ("LATE_ACCELERATION", 24, "Rolling forecast / evaluation", "Early evidence mild, late truth accelerates", "24h forecast stress / 96h deterioration"),
    ("FORECAST_IMPROVING", 24, "Rolling forecast", "High 24h then recovery by 96h", "IMPROVING trajectory candidate"),
    ("FORECAST_DETERIORATING", 24, "Rolling forecast", "24h mild, 96h sharply worse", "DETERIORATING trajectory candidate"),
    ("OOD_HIGH_BELOW_LIMIT", 24, "Applicability / OOD", "Very high early evidence but below hard limit", "OUT_OF_DOMAIN / abstain candidate"),
    ("HARD_LIMIT_BREACH_24H", 18, "Engineering Safety", "24h exceeds datasheet limit", "Hard safety rejection candidate"),
    ("HARD_LIMIT_BREACH_168H", 18, "Engineering Safety / evaluation", "Late datasheet-limit breach", "Late hard-fail truth"),
    ("MISSING_24H", 18, "Data Trust", "Required 24h row absent", "RETEST / insufficient evidence candidate"),
    ("MISSING_0H", 18, "Data Trust", "Required 0h row absent", "RETEST / insufficient evidence candidate"),
    ("CONDITION_MISMATCH", 18, "Data Trust", "Condition mismatch flag injected", "Data Trust failure candidate"),
    ("UNUSABLE_FOR_ML", 18, "Data Trust", "usable_for_ml=False on early evidence", "Data Trust failure candidate"),
    ("LOT_WIDE_SHIFT", 40, "Lot Intelligence / Drift", "Entire lot shifted upward", "Lot health escalation / population drift"),
    ("BATCH_LOCAL_SHIFT", 32, "Lot Intelligence / Commonality", "Single batch shifted within mixed lot", "Batch commonality candidate"),
    ("INSTRUMENT_COMMONALITY", 32, "Commonality", "Abnormal population concentrated on one instrument", "Instrument enrichment candidate"),
    ("CALIBRATION_STRESS", 30, "Calibration Monitor", "Late truth intentionally difficult for early forecast", "Coverage stress candidate"),
]


def generate(source_csv: Path, output_dir: Path, seed: int = SEED) -> None:
    rng = np.random.default_rng(seed)
    source = pd.read_csv(source_csv)

    required = {
        "component_id", "lot_id", "burnin_batch_id", "dataset_split",
        "measurement_time_h", "leakage_current_uA",
        "datasheet_upper_limit_uA", "usable_for_ml"
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"Source dataset is missing required columns: {missing}")

    output_dir.mkdir(parents=True, exist_ok=True)

    stats = _robust_stats(source)
    defaults = _schema_row_defaults(source)
    columns = list(source.columns)

    part_default = _mode(source.get("part_number", pd.Series(dtype=object)), "J1N5806US")
    qual_default = _mode(source.get("qualification_level", pd.Series(dtype=object)), "SPACE")
    param_default = _mode(source.get("parameter_name", pd.Series(dtype=object)), "leakage_current")
    instrument_default = _mode(source.get("instrument_id", pd.Series(dtype=object)), "SMU-BASE")

    challenge_rows: List[Dict[str, object]] = []
    truth_rows: List[Dict[str, object]] = []

    comp_counter = 1

    for s_idx, (scenario, count, layer, injected, expected) in enumerate(SCENARIOS, start=1):
        # Population scenarios intentionally share lots/batches/instruments.
        if scenario == "LOT_WIDE_SHIFT":
            lot_id = "CH_LOT_SHIFT"
        elif scenario in {"BATCH_LOCAL_SHIFT", "NOMINAL_TYPICAL"}:
            lot_id = "CH_MIXED_LOT"
        elif scenario == "INSTRUMENT_COMMONALITY":
            lot_id = "CH_INSTRUMENT_LOT"
        else:
            lot_id = f"CH_{s_idx:02d}"

        for j in range(count):
            component_id = f"SPARK_CH_{comp_counter:05d}"
            comp_counter += 1

            if scenario == "BATCH_LOCAL_SHIFT":
                batch_id = "CH_MIXED_BAD_BATCH"
            elif scenario == "NOMINAL_TYPICAL" and j < 15:
                batch_id = "CH_MIXED_GOOD_BATCH"
            elif scenario == "LOT_WIDE_SHIFT":
                batch_id = "CH_LOT_SHIFT_B1" if j < count // 2 else "CH_LOT_SHIFT_B2"
            elif scenario == "INSTRUMENT_COMMONALITY":
                batch_id = "CH_INSTRUMENT_B1" if j < count // 2 else "CH_INSTRUMENT_B2"
            else:
                batch_id = f"{lot_id}_B{1 + (j % 2)}"

            values = _scenario_values(scenario, stats, rng, j)

            omit_times = set()
            if scenario == "MISSING_24H":
                omit_times.add(24)
            if scenario == "MISSING_0H":
                omit_times.add(0)

            for h in TIMES:
                if h in omit_times:
                    continue

                row = dict(defaults)
                row.update({
                    "measurement_id": f"{component_id}_{h:03d}H",
                    "component_id": component_id,
                    "lot_id": lot_id,
                    "burnin_batch_id": batch_id,
                    "dataset_split": "test",
                    "part_number": part_default,
                    "qualification_level": qual_default,
                    "parameter_name": param_default,
                    "measurement_time_h": h,
                    "leakage_current_uA": round(values[h], 6),
                    "datasheet_upper_limit_uA": DEFAULT_LIMIT_UA,
                    "instrument_id": "SMU-COMMONALITY" if scenario == "INSTRUMENT_COMMONALITY" else instrument_default,
                    "raw_row_count": 1,
                    "duplicate_count": 0,
                    "source_quality_issues": "",
                    "quality_status": "PASS",
                    "cleaning_actions": "",
                    "missing_value_flag": False,
                    "condition_mismatch_flag": False,
                    "usable_for_ml": True,
                })

                if scenario == "CONDITION_MISMATCH" and h in (0, 24):
                    row["condition_mismatch_flag"] = True
                    row["quality_status"] = "HOLD"
                    row["source_quality_issues"] = "INJECTED_CONDITION_MISMATCH"
                    if "recorded_temperature_c" in row:
                        base_temp = float(row.get("nominal_temperature_c", 125.0) or 125.0)
                        row["recorded_temperature_c"] = base_temp + 15.0

                if scenario == "UNUSABLE_FOR_ML" and h in (0, 24):
                    row["usable_for_ml"] = False
                    row["quality_status"] = "HOLD"
                    row["source_quality_issues"] = "INJECTED_UNUSABLE_FOR_ML"

                # Keep all source columns and only source columns.
                challenge_rows.append({c: row.get(c, np.nan) for c in columns})

            truth_rows.append({
                "component_id": component_id,
                "scenario_family": scenario,
                "scenario_group": layer,
                "injected_condition": injected,
                "expected_primary_behavior": expected,
                "lot_id": lot_id,
                "burnin_batch_id": batch_id,
                "instrument_id": "SMU-COMMONALITY" if scenario == "INSTRUMENT_COMMONALITY" else instrument_default,
                "expected_required_checkpoint_issue": (
                    "MISSING_24H" if scenario == "MISSING_24H"
                    else "MISSING_0H" if scenario == "MISSING_0H"
                    else ""
                ),
                "expected_hard_limit_breach": scenario in {"HARD_LIMIT_BREACH_24H", "HARD_LIMIT_BREACH_168H"},
                "expected_ood_candidate": scenario == "OOD_HIGH_BELOW_LIMIT",
                "expected_population_signal": scenario in {"LOT_WIDE_SHIFT", "BATCH_LOCAL_SHIFT", "INSTRUMENT_COMMONALITY"},
                "expected_calibration_stress": scenario == "CALIBRATION_STRESS",
                "seed": seed,
            })

    challenge = pd.DataFrame(challenge_rows, columns=columns)
    truth = pd.DataFrame(truth_rows)

    challenge_path = output_dir / "spark_validation_challenge.csv"
    truth_path = output_dir / "spark_validation_truth.csv"
    manifest_path = output_dir / "spark_validation_manifest.json"

    challenge.to_csv(challenge_path, index=False)
    truth.to_csv(truth_path, index=False)

    manifest = {
        "generator": "SPARK Validation Challenge Generator",
        "seed": seed,
        "source_csv": str(source_csv),
        "source_columns": columns,
        "measurement_times_h": TIMES,
        "component_count": int(truth["component_id"].nunique()),
        "measurement_row_count": int(len(challenge)),
        "scenario_count": int(truth["scenario_family"].nunique()),
        "scenario_component_counts": truth["scenario_family"].value_counts().sort_index().to_dict(),
        "important_note": (
            "Expected behavior in the truth file describes the injected engineering intent. "
            "It is not a fabricated assertion that SPARK must produce an exact final action. "
            "Actual behavior must be measured by running the challenge dataset through SPARK."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("SPARK VALIDATION CHALLENGE GENERATED")
    print(f"Source             : {source_csv}")
    print(f"Challenge CSV      : {challenge_path}")
    print(f"Truth CSV          : {truth_path}")
    print(f"Manifest           : {manifest_path}")
    print(f"Components         : {manifest['component_count']}")
    print(f"Measurement rows   : {manifest['measurement_row_count']}")
    print(f"Scenario families  : {manifest['scenario_count']}")


def resolve_source(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    if load_settings is None:
        raise RuntimeError("Pass --source because core.config could not be imported.")

    settings = load_settings()
    source = settings.pipeline_root / "data" / "processed" / "02_clean_measurements_long.csv"
    return source.resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Path to original 02_clean_measurements_long.csv")
    parser.add_argument("--output-dir", default="validation/generated")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    source = resolve_source(args.source)
    if not source.exists():
        raise FileNotFoundError(f"Source dataset not found: {source}")

    generate(source, Path(args.output_dir).resolve(), seed=args.seed)


if __name__ == "__main__":
    main()
