# SPARK Validation Challenge Report

- Components: **476**
- Scenario families: **19**
- Strict component PASS: **300**
- Strict component FAIL: **0**
- Informational/model-response cases: **176**

## Scenario summary

| scenario_family | components | pass_count | fail_count | info_count | data_trust_retest_pct | ood_pct | hard_fail_pct | accept_pct | watch_pct | hold_pct | retest_pct | reject_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BATCH_LOCAL_SHIFT | 32 | 0 | 0 | 32 | 0.0 | 0.0 | 0.0 | 0.0 | 56.25 | 43.75 | 0.0 | 0.0 |
| BORDERLINE_EARLY | 24 | 0 | 0 | 24 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| CALIBRATION_STRESS | 30 | 0 | 0 | 30 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| CONDITION_MISMATCH | 18 | 18 | 0 | 0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 |
| EARLY_SPIKE_RECOVERY | 24 | 24 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| FORECAST_DETERIORATING | 24 | 24 | 0 | 0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| FORECAST_IMPROVING | 24 | 24 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| HARD_LIMIT_BREACH_168H | 18 | 0 | 0 | 18 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| HARD_LIMIT_BREACH_24H | 18 | 18 | 0 | 0 | 0.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| INSTRUMENT_COMMONALITY | 32 | 0 | 0 | 32 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| LATE_ACCELERATION | 24 | 24 | 0 | 0 | 0.0 | 0.0 | 0.0 | 95.83 | 4.17 | 0.0 | 0.0 | 0.0 |
| LOT_WIDE_SHIFT | 40 | 0 | 0 | 40 | 0.0 | 0.0 | 0.0 | 0.0 | 95.0 | 5.0 | 0.0 | 0.0 |
| MISSING_0H | 18 | 18 | 0 | 0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 |
| MISSING_24H | 18 | 18 | 0 | 0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 |
| NOMINAL_BEST | 30 | 30 | 0 | 0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| NOMINAL_TYPICAL | 30 | 30 | 0 | 0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| OOD_HIGH_BELOW_LIMIT | 24 | 24 | 0 | 0 | 0.0 | 100.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| PROGRESSIVE_DEGRADATION | 30 | 30 | 0 | 0 | 0.0 | 0.0 | 0.0 | 76.67 | 10.0 | 13.33 | 0.0 | 0.0 |
| UNUSABLE_FOR_ML | 18 | 18 | 0 | 0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 |

## Population checks

| check | status | observed | expected |
| --- | --- | --- | --- |
| LOT_WIDE_SHIFT_HEALTH | PASS | ALERT | ELEVATED or ALERT |
| BATCH_LOCAL_COMMONALITY | PASS | FOUND | CH_MIXED_BAD_BATCH enriched in risky population |
| INSTRUMENT_COMMONALITY | PASS | FOUND | SMU-COMMONALITY enriched in risky population |
| CALIBRATION_STRESS | PASS | RECALIBRATION_REVIEW | WATCH or RECALIBRATION_REVIEW |

## Interpretation

Strict rules are reserved for deterministic contracts such as Data Trust, Engineering Safety, OOD abstention, and explicitly designed rolling-trajectory cases. Model-response scenarios that do not have a deterministic contract remain INFO rather than being falsely labeled failures.
