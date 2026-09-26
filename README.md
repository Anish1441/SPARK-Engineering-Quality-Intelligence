# SPARK — Engineering Quality Intelligence

This repository contains the recovered and stabilized **Phase 7** SPARK dashboard for SIH26170: AI-Driven Anomaly Detection in Component Burn-In & Screening.

Phase 7 is a decision-support application around the validated original Phase-1 reliability pipeline. It does not fabricate ML output and it does not retrain or replace the original Phase-1 models during dashboard use.

## Current Phase 7 architecture

```text
Browser (HTML/CSS/JavaScript + local Plotly)
        |
        v
Flask app.py
        |
        +-- DatasetManager
        |     +-- user CSV / Excel uploads
        |     +-- bundled read-only demo dataset
        |     +-- original Phase-1 clean measurements
        |
        +-- analysis_engine.py
        |     +-- descriptive statistics
        |     +-- generic MAD / robust-z evidence
        |     +-- 3-sigma control limits
        |     +-- correlations / signal profiles
        |
        +-- PipelineAdapter
        |     +-- original build_feature_table()
        |     +-- Module A: module_a_24h.joblib + score_module_a()
        |     +-- Module B: module_b_24h.joblib + predict_module_b()
        |     +-- one shared component feature table
        |     +-- per-dataset Module-A/Module-B evidence cache
        |
        +-- Data Trust + Engineering Safety
        |     +-- fail-closed evidence checks
        |     +-- non-negotiable hard electrical limits
        |
        +-- Unified Reliability Risk Engine
        |     +-- deterministic evidence precedence
        |     +-- transparent QA prioritisation index
        |     +-- evidence completeness score
        |     +-- ACCEPT / WATCH / HOLD / RETEST / REJECT recommendation
        |
        +-- QAManager
              +-- atomic local QA decision ledger
              +-- guardrail + Module-A + Module-B evidence snapshot
              +-- unified reliability recommendation snapshot
              +-- explicit human final disposition
```

## Original Phase-1 contract

Phase 7 directly loads the existing Phase-1 project. There is no `SPARK_PIPELINE_ENTRYPOINT` contract.

The adapter expects the Phase-1 root to contain at minimum:

```text
src/sih26170/
artifacts/models/module_a_24h.joblib
artifacts/models/module_b_24h.joblib
data/processed/02_clean_measurements_long.csv
```

The original Module-A artifact contract is:

```python
{"model": model, "metadata": model_metadata(model)}
```

The original Module-B artifact contract is:

```python
{"bundle": bundle, "metadata": metadata}
```

Phase 7 automatically checks these historical locations when `SPARK_PIPELINE_ROOT` is not set:

```text
<parent of Phase7>/SPARK_PHASE1
%USERPROFILE%\Desktop\SPARK_PHASE1
%USERPROFILE%\Downloads\SPARK_PHASE1
%USERPROFILE%\Downloads\SIH26170_Prototype_Phase1\sih26170_prototype
%USERPROFILE%\OneDrive\Desktop\SPARK_PHASE1
```

For an explicit location:

```bat
set SPARK_PIPELINE_ROOT=C:\path\to\SPARK_PHASE1
```

A bad configured path is reported instead of silently substituting another source.





## Phase 7 final handoff status

Phase 7 is functionally complete through QA override governance. The validated end-to-end stack now includes Data Trust, Engineering Safety, original Phase-1 Module A and Module B inference, the Unified Reliability Risk Engine, deterministic explainability, hash-sealed QA traceability, and governed human overrides.

The closure criterion is a clean regression run, clean Git staging review, and successful push of the final Phase-7 source. Runtime QA records under `data/`, local virtual environments, caches, and obsolete `.bak` files are not part of the source handoff.

### Final closure commands

```bat
python -m compileall -q app.py core tests
node --check static\js\app.js
python -m pytest -q
git diff --check
git status
```

### Final demo path

Use the original Phase-1 dataset and demonstrate, in order: Data Trust -> Engineering Safety -> Unified Reliability Risk -> Explainable QA Decision -> Module A -> Module B -> human QA disposition -> Decision History / integrity -> QA feedback summary.

Do not describe the reliability score as a failure probability, the Data Trust percentage as ML confidence, or the local SHA-256 ledger as a digital signature/blockchain.

## Phase 7.6 — QA Override Governance + Feedback Ledger

Phase 7.6 hardens the human-in-the-loop boundary. `AGREE` and `NOTE` may no longer silently change the deterministic SPARK recommendation; any different final disposition must use `OVERRIDE`. Overrides require a controlled reason code and a minimum 20-character justification. Hard engineering failures remain locked to `REJECT`/`QUARANTINE`, and Data Trust `RETEST` evidence cannot be relaxed to `ACCEPT`.

Every schema-v7 QA entry records the machine recommendation, human-selected/final action, disagreement classification, override reason code/category, review target and justification. Disagreements are categorized as `AGREEMENT`, `CONSERVATIVE_OVERRIDE`, `RELAXATION_OVERRIDE`, `PROCESS_DISAGREEMENT`, or `UNCLASSIFIED_DISAGREEMENT`. The special reason `QA-OVR-006` flags suspected model/threshold limitations for later engineering review.

The `/api/qa/<dataset_id>/feedback-summary` endpoint aggregates governed decisions, override rate, disagreement classes, action transitions, reason-code counts and model/threshold review flags. This ledger is evidence for future offline threshold/model review; it does not automatically retrain models or perform online learning.

## Phase 7.5 — Explainable QA Decision + Traceability Hardening

Phase 7.5 adds a deterministic explanation layer and a tamper-evident local QA ledger without changing the underlying Module-A, Module-B, Data Trust, Engineering Safety or Unified Reliability Risk decisions.

The explanation layer generates a ranked reason-code hierarchy such as `DT-RETEST-001`, `ES-FAIL-001`, `MA-WATCH-001` and `MB-HOLD-001`, plus a five-step decision path from Data Trust through the Reliability Risk Engine. The layer is rule-based and explicitly reports `uses_llm: false`; it translates existing evidence but does not create or alter the recommendation.

The QA ledger is upgraded to schema v6. Every new entry stores an SHA-256 evidence fingerprint, an SHA-256 entry hash, and the hash of the full prior ledger prefix. The `/api/qa/<dataset_id>/integrity` endpoint verifies those controls. This is a local integrity mechanism for detecting ledger edits; it is not a digital signature, external timestamp, or immutable database. Existing schema-v5 history remains readable and is reported as legacy/unsealed until a v6 entry seals the preceding ledger prefix.

The QA Inspector now shows the primary reason code, ranked supporting reasons, and the deterministic decision path. Decision History shows ledger-integrity status, primary reason code and a short entry-hash reference for each v6 disposition.

## Phase 7.4 — Unified Reliability Risk Engine

Phase 7.4 combines the already-separated evidence layers into one deterministic QA recommendation without allowing a model to overrule a safety or data-quality gate. Decision precedence is:

1. unusable/missing 0h/24h evidence → `RETEST` or `HOLD`;
2. observed hard engineering-limit breach → `REJECT`;
3. unavailable engineering-limit evidence → `HOLD`;
4. original Module-A action (`ACCEPT`, `WATCH`, `HOLD_FOR_REVIEW`, `RETEST`, `REJECT`);
5. original Module-B forecast and conservative uncertainty bounds versus the documented engineering limit.

The **Reliability Risk Score (0–100)** is a transparent prioritisation index, not a probability of failure. It takes the stronger of the Module-A action severity and the Module-B 95% forecast utilisation of the engineering limit. Hard observed failures are fixed at 100. When required evidence is insufficient, no numerical reliability score is asserted and the risk band is `INDETERMINATE`.

The **Evidence Completeness Score** is also transparent: it averages the Data Trust percentage with binary availability of Engineering Safety, Module A and Module B evidence. It is not model confidence.

The QA Inspector now shows the unified recommendation, risk band, prioritisation score, evidence completeness and forecast/limit utilisation, while preserving the underlying guardrails and both original Phase-1 model outputs separately.

## Phase 7.3 — Data Trust and Engineering Safety gates

Phase 7.3 adds two deterministic guardrails ahead of model interpretation:

- **Data Trust Gate** — verifies that 0h/24h checkpoints, finite leakage values, ML usability, missing-value flags, condition comparability and quality status are suitable for screening. The displayed confidence score is simply the percentage of applicable checks that pass; it is not an ML probability. Required evidence failures produce `RETEST`.
- **Engineering Safety Gate** — compares observed early leakage values against the documented per-row `datasheet_upper_limit_uA`. A measured hard-limit breach produces `FAIL / REJECT`; Module A or Module B can never override it. Missing engineering-limit evidence produces `UNAVAILABLE / HOLD` rather than a silent pass.

Both gates are intentionally time-safe through 24h for the early screening view and are persisted in the QA evidence ledger.

## Module A — dynamic anomaly evidence

Phase 7.3 retains the original Phase-1 Module-A model and scoring function directly. The dashboard does **not** implement a replacement anomaly algorithm.

The original 24-hour Module-A evidence includes:

- 0h and 24h leakage values;
- within-lot robust risk;
- historical healthy-population risk;
- lot-shift risk;
- burn-in-batch early-slope shift;
- Isolation Forest score and outlier flag;
- the Phase-1 hard-limit result available in the Module-A output;
- original Module-A action and explanation.

The original Phase-1 implementation is time-safe: the 24-hour screen is based on evidence available through 24h and does not train on hidden defect labels or future 96h/168h measurements.

## Module B — 168-hour forecast evidence

The dashboard continues to use the original Phase-1 Module-B model. It presents:

- selected regression model;
- predicted 168h leakage;
- lower, median and upper prediction interval;
- prediction interval width;
- predicted 24h→168h slope;
- safety margin / conformal upper evidence;
- actual 168h and absolute error when the Phase-1 evaluation output supplies them.

## Important dependency reproducibility

The Phase-1 model artifacts were serialized with **scikit-learn 1.9.0**. Phase 7 therefore pins:

```text
scikit-learn==1.9.0
```

This avoids cross-version model-unpickling warnings and keeps inference consistent with the training environment.

## Phase 7 stabilization and integration fixes

The recovered code now includes:

- centralized Phase-1 path resolution;
- exact scikit-learn model-runtime version pin;
- required `joblib`, `scikit-learn` and `xlrd` dependencies;
- direct original Module-A and Module-B integration;
- shared feature engineering so both models use the same original component feature table;
- per-dataset caching of feature engineering and both model outputs;
- component-level QA navigation for long-form burn-in data, preferring the 24h representative row;
- QA history persistence of Data Trust, Engineering Safety, Module-A and complete Module-B evidence snapshots;
- QA ledger deletion when a user-uploaded dataset is explicitly removed;
- read-only protection for the original Phase-1 dataset and bundled demo dataset;
- bundled demo data under tracked `samples/` instead of runtime `data/`;
- source-row-correct outlier indices when missing values are present;
- explicit `ABSTAIN` QA disposition;
- local Plotly for offline demonstrations;
- pytest skip semantics when the external Phase-1 project is genuinely unavailable.

## Clean installation on Windows

From the repository root:

```bat
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python app.py
```

Or, after the environment has been installed:

```bat
run_phase7.bat
```

The browser opens at `http://127.0.0.1:5000` unless `SPARK_HOST` or `SPARK_PORT` is configured.

## Verify the original pipeline

```bat
python -c "from core.config import load_settings; print(load_settings().pipeline_root)"
```

Dual-module status:

```bat
python -c "from core.config import load_settings; from core.pipeline_adapter import PipelineAdapter; import pprint; pprint.pp(PipelineAdapter(load_settings().pipeline_root).status())"
```

For complete Module-A + Module-B integration, status should show both:

```text
module_a_available: True
module_b_available: True
```

The same status is available while the app is running from:

```text
GET /api/pipeline/status
```

## Dataset behavior

- User uploads are stored under runtime `data/` and ignored by Git.
- The bundled demo dataset is under tracked `samples/` and is read-only.
- The original Phase-1 clean measurements are referenced directly and are read-only.
- Deleting a user-uploaded dataset removes its local QA ledger and invalidates its model cache.

## QA workflow

Each inspection can persist:

- inspection/source-row and component context;
- generic analytical score/state and contributors;
- Data Trust Gate status, score, checks and snapshot;
- Engineering Safety Gate status, hard-failure evidence and margin snapshot;
- Module-A availability, action, primary reason and risk evidence;
- Module-A Isolation Forest and early static-limit evidence;
- Module-B availability and selected model;
- 168h prediction and prediction interval;
- predicted 24h→168h slope;
- safety margin / conformal upper value;
- evaluation actual/error fields when supplied;
- complete model/evidence snapshot;
- QA action, response, override and comment;
- UTC timestamp and final action.

All statistical and model outputs are decision-support evidence. The final disposition remains explicit and human-controlled.

## Safety and data handling

Runtime datasets, QA ledgers, virtual environments, secrets, logs, caches and backup files are excluded from Git. The original Phase-1 dataset and trained models are referenced in place and are not copied into this repository.
