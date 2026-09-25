# SPARK — Engineering Quality Intelligence

Phase 7 closes the QA inspection workflow around the existing SPARK Flask product.

## ML pipeline boundary

SPARK is designed to use the existing validated ML pipeline for genuine inference. The pipeline is not replaced or retrained by this application.

Configure the existing pipeline root:

```bat
set SPARK_PIPELINE_ROOT=C:\Users\anish\OneDrive\Desktop\SPARK_PHASE1
```

The production inference contract is explicit:

```bat
set SPARK_PIPELINE_ENTRYPOINT=module_name:function_name
```

The callable must accept:

```text
(df, index)
```

and return a dictionary containing the genuine model result. SPARK will display that result in QA Inspector.

If the contract is not configured or inference fails, SPARK reports the pipeline as unavailable and does not fabricate a prediction.

## QA workflow

Each inspected record can show:

- Statistical assessment and evidence
- Validated ML pipeline prediction, score and confidence
- AI/analytical comparison
- Evidence-based engineering assessment
- QA disposition
- Agree / Override / Note
- Override action
- Inspector comment
- Dataset and record traceability

## Run

```bat
python -m pip install -r requirements.txt
python -m pytest -q
set SPARK_PIPELINE_ROOT=C:\Users\anish\OneDrive\Desktop\SPARK_PHASE1
python app.py
```

The browser opens automatically after startup.

## Safety

Runtime datasets and QA records remain local and are excluded from Git by `.gitignore`.
