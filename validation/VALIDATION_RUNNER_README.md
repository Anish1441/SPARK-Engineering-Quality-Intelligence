# SPARK Expected-vs-Actual Validation Runner

Run this after generating `validation/generated/spark_validation_challenge.csv`
and `spark_validation_truth.csv`.

The runner executes the challenge population through the same core contracts used
by the Flask application:

- Phase-1 feature engineering
- Module A
- Module B
- Model applicability / OOD gate
- Data Trust gate
- Engineering Safety gate
- Rolling 96h engineering update
- Unified Reliability Risk Engine
- Lot / Batch Health
- Commonality
- Calibration monitoring

It creates:

- `validation/results/component_validation_results.csv`
- `validation/results/scenario_validation_summary.csv`
- `validation/results/population_validation_checks.csv`
- `validation/results/validation_report.json`
- `validation/results/VALIDATION_REPORT.md`

PASS/FAIL is used only when SPARK has a deterministic contract. Model-response
scenarios without a deterministic guarantee are kept as INFO so the report does
not manufacture failures or successes.
