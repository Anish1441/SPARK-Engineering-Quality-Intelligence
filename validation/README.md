# SPARK Validation Challenge Dataset

This pack adds a deterministic validation-data generator for the final SPARK verification stage.

## Purpose

The generator starts from the real cleaned Phase-1 dataset schema and metadata. It learns robust reference medians/MADs at 0h, 24h, 96h, and 168h, then creates a separate challenge population with deliberately injected engineering scenarios.

It does **not** retrain SPARK and it does **not** use hidden truth to influence SPARK predictions.

## Generated files

Running the generator creates:

- `validation/generated/spark_validation_challenge.csv`
- `validation/generated/spark_validation_truth.csv`
- `validation/generated/spark_validation_manifest.json`

Only `spark_validation_challenge.csv` should be uploaded to SPARK.

The truth CSV is held out for expected-vs-actual evaluation.

## Scenario families

The current generator includes:

- NOMINAL_BEST
- NOMINAL_TYPICAL
- BORDERLINE_EARLY
- EARLY_SPIKE_RECOVERY
- PROGRESSIVE_DEGRADATION
- LATE_ACCELERATION
- FORECAST_IMPROVING
- FORECAST_DETERIORATING
- OOD_HIGH_BELOW_LIMIT
- HARD_LIMIT_BREACH_24H
- HARD_LIMIT_BREACH_168H
- MISSING_24H
- MISSING_0H
- CONDITION_MISMATCH
- UNUSABLE_FOR_ML
- LOT_WIDE_SHIFT
- BATCH_LOCAL_SHIFT
- INSTRUMENT_COMMONALITY
- CALIBRATION_STRESS

## Run

From the SPARK repository with its `.venv` activated:

```cmd
python tools\generate_validation_challenge.py
```

The script resolves the original Phase-1 clean dataset through `core.config.load_settings()`.

You can also pass an explicit source:

```cmd
python tools\generate_validation_challenge.py --source "C:\path\to\02_clean_measurements_long.csv"
```

## Validation principle

The truth file describes the scenario that was injected and the engineering behavior that should be exercised.

It intentionally does not claim exact final SPARK actions in advance. Exact pass/fail behavior must be measured by running the challenge CSV through the implemented application and comparing the actual evidence to the hidden truth.
