from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings
from core.pipeline_adapter import PipelineAdapter
from core.applicability import assess_model_applicability
from core.gates import data_confidence_gate, engineering_safety_gate
from core.rolling_forecast import rolling_forecast_update
from core.risk_engine import reliability_risk_engine
from core.lot_intelligence import build_lot_intelligence
from core.commonality import commonality_engine
from core.calibration import calibration_monitor


def _markdown_table(df: pd.DataFrame) -> str:
    """Render a simple GitHub-flavoured Markdown table without tabulate."""
    if df is None or df.empty:
        return "_No rows._"

    clean = df.copy()
    clean = clean.fillna("")
    cols = [str(c) for c in clean.columns]

    def esc(v: Any) -> str:
        s = str(v)
        return s.replace("|", "\\|").replace("\n", " ")

    lines = []
    lines.append("| " + " | ".join(esc(c) for c in cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for _, row in clean.iterrows():
        lines.append("| " + " | ".join(esc(row[c]) for c in clean.columns) + " |")
    return "\n".join(lines)


def _apply_applicability(model: dict[str, Any], applicability: dict[str, Any]) -> dict[str, Any]:
    if applicability.get("applicable") is True:
        return model
    safe = dict(model)
    raw_module_b = dict(model.get("module_b") or {})
    abstained = {
        "available": False,
        "mode": "SPARK MODULE-B APPLICABILITY GATE",
        "status": "ABSTAINED",
        "component_id": model.get("component_id"),
        "prediction_168h_uA": None,
        "prediction_lower_05_uA": None,
        "prediction_median_50_uA": None,
        "prediction_upper_95_uA": None,
        "conformal_safety_upper_uA": None,
        "reason": applicability.get("reason"),
    }
    safe["module_b_diagnostic"] = raw_module_b
    safe["module_b"] = abstained
    safe["module_b_available"] = False
    safe["available"] = False
    return safe


def _status(ok: bool | None) -> str:
    if ok is True:
        return "PASS"
    if ok is False:
        return "FAIL"
    return "INFO"


def _scenario_check(row: pd.Series) -> tuple[str, str]:
    s = str(row["scenario_family"])
    dc = str(row.get("data_confidence_status") or "")
    app = str(row.get("applicability_status") or "")
    hard = bool(row.get("engineering_hard_failure"))
    action = str(row.get("unified_action") or "")
    ma = str(row.get("module_a_action") or "")
    traj = str(row.get("rolling_trajectory") or "")

    if s in {"NOMINAL_BEST", "NOMINAL_TYPICAL"}:
        ok = dc == "PASS" and app in {"SUPPORTED", "SUPPORTED_WITH_CAUTION"} and not hard
        return _status(ok), "Data Trust PASS + applicable model domain + no hard failure"

    if s == "BORDERLINE_EARLY":
        return "INFO", f"Observe early-risk response; Module-A={ma or 'UNAVAILABLE'}"

    if s == "EARLY_SPIKE_RECOVERY":
        ok = ma in {"WATCH", "HOLD", "HOLD_FOR_REVIEW", "RETEST", "REJECT"}
        return _status(ok), "Early 24h excursion should create Module-A escalation evidence"

    if s == "PROGRESSIVE_DEGRADATION":
        ok = traj == "DETERIORATING" or action in {"WATCH", "HOLD", "REJECT"}
        return _status(ok), "Later trajectory or unified action should indicate degradation"

    if s == "LATE_ACCELERATION":
        ok = traj == "DETERIORATING"
        return _status(ok), "96h evidence should update the trajectory toward DETERIORATING"

    if s == "FORECAST_IMPROVING":
        ok = traj == "IMPROVING"
        return _status(ok), "Rolling 96h update should classify IMPROVING"

    if s == "FORECAST_DETERIORATING":
        ok = traj == "DETERIORATING"
        return _status(ok), "Rolling 96h update should classify DETERIORATING"

    if s == "OOD_HIGH_BELOW_LIMIT":
        ok = app == "OUT_OF_DOMAIN" and not bool(row.get("model_applicable"))
        return _status(ok), "Applicability gate should abstain as OUT_OF_DOMAIN"

    if s == "HARD_LIMIT_BREACH_24H":
        ok = hard and action == "REJECT"
        return _status(ok), "Early engineering limit breach must force REJECT"

    if s == "HARD_LIMIT_BREACH_168H":
        return "INFO", "168h breach is evaluation truth; early safety gate intentionally uses <=24h only"

    if s in {"MISSING_24H", "MISSING_0H", "CONDITION_MISMATCH", "UNUSABLE_FOR_ML"}:
        ok = dc == "RETEST"
        return _status(ok), "Data Trust gate should force RETEST"

    if s in {"LOT_WIDE_SHIFT", "BATCH_LOCAL_SHIFT", "INSTRUMENT_COMMONALITY", "CALIBRATION_STRESS"}:
        return "INFO", "Validated at population level"

    return "INFO", "No strict rule defined"


def main() -> None:
    settings = load_settings()
    challenge_path = REPO_ROOT / "validation" / "generated" / "spark_validation_challenge.csv"
    truth_path = REPO_ROOT / "validation" / "generated" / "spark_validation_truth.csv"
    out_dir = REPO_ROOT / "validation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not challenge_path.exists() or not truth_path.exists():
        raise FileNotFoundError("Generate the validation challenge first.")

    df = pd.read_csv(challenge_path)
    truth = pd.read_csv(truth_path)
    ref_path = settings.pipeline_root / "data" / "processed" / "02_clean_measurements_long.csv"
    reference = pd.read_csv(ref_path)
    train_reference = reference[
        reference["dataset_split"].astype(str).str.lower().eq("train")
    ].copy()

    ml = PipelineAdapter(settings.pipeline_root)
    pipeline_status = ml.status()
    if not pipeline_status.get("module_a_available") or not pipeline_status.get("module_b_available"):
        raise RuntimeError("Original Phase-1 Module A/B are not both available.")

    # Phase-1 feature engineering requires historical training lots in the
    # dataframe so it can calculate training-only baselines. The challenge file
    # intentionally contains only held-out/test components, therefore build the
    # model evidence on a temporary combined dataframe:
    #
    #   original TRAIN rows + challenge TEST rows
    #
    # The original training rows are context only. They are never reported as
    # validation components and challenge truth is never fed into the models.
    combined_df = pd.concat([train_reference, df], ignore_index=True, sort=False)

    evidence_all = ml.evidence_tables(combined_df, cache_key="validation-challenge-combined")

    challenge_ids = set(truth["component_id"].astype(str))

    def _challenge_only(table):
        if isinstance(table, pd.DataFrame) and "component_id" in table.columns:
            return table[table["component_id"].astype(str).isin(challenge_ids)].copy()
        return table

    evidence = {
        **evidence_all,
        "features": _challenge_only(evidence_all["features"]),
        "module_a": _challenge_only(evidence_all["module_a"]),
        "module_b": _challenge_only(evidence_all["module_b"]),
    }
    module_a_table = evidence["module_a"]
    module_b_table = evidence["module_b"]

    result_rows = []
    first_index = (
        combined_df.reset_index()
        .groupby("component_id", sort=False)["index"]
        .first()
        .to_dict()
    )

    for _, t in truth.iterrows():
        cid = str(t["component_id"])
        idx = int(first_index[cid])

        applicability = assess_model_applicability(combined_df, idx, reference_df=train_reference)
        model = ml.assess(combined_df, idx, cache_key="validation-challenge-combined")
        model = _apply_applicability(model, applicability)
        data_conf = data_confidence_gate(combined_df, idx)
        safety = engineering_safety_gate(combined_df, idx)

        module_a = model.get("module_a") or {}
        module_b = model.get("module_b") or model
        rolling = rolling_forecast_update(combined_df, idx, module_b)
        risk = reliability_risk_engine(data_conf, safety, module_a, module_b)

        row = {
            "component_id": cid,
            "scenario_family": t["scenario_family"],
            "scenario_group": t["scenario_group"],
            "lot_id": t["lot_id"],
            "burnin_batch_id": t["burnin_batch_id"],
            "instrument_id": t["instrument_id"],
            "data_confidence_status": data_conf.get("status"),
            "data_confidence_score_pct": data_conf.get("score_pct"),
            "engineering_safety_status": safety.get("status"),
            "engineering_hard_failure": safety.get("hard_failure"),
            "applicability_status": applicability.get("status"),
            "model_applicable": applicability.get("applicable"),
            "max_robust_distance": applicability.get("max_robust_distance"),
            "module_a_action": module_a.get("action"),
            "module_a_reason": module_a.get("primary_reason"),
            "module_b_available": module_b.get("available"),
            "module_b_prediction_168h_uA": module_b.get("prediction_168h_uA"),
            "module_b_upper_95_uA": module_b.get("prediction_upper_95_uA"),
            "rolling_status": rolling.get("status"),
            "rolling_trajectory": rolling.get("trajectory"),
            "rolling_updated_168h_uA": rolling.get("updated_168h_uA"),
            "rolling_shift_uA": rolling.get("forecast_shift_uA"),
            "unified_action": risk.get("unified_action"),
            "risk_band": risk.get("risk_band"),
            "risk_score": risk.get("reliability_risk_score"),
        }
        check_status, check_detail = _scenario_check(pd.Series(row))
        row["validation_status"] = check_status
        row["validation_detail"] = check_detail
        result_rows.append(row)

    component_results = pd.DataFrame(result_rows)

    summary = (
        component_results.groupby("scenario_family", sort=True)
        .agg(
            components=("component_id", "count"),
            pass_count=("validation_status", lambda s: int((s == "PASS").sum())),
            fail_count=("validation_status", lambda s: int((s == "FAIL").sum())),
            info_count=("validation_status", lambda s: int((s == "INFO").sum())),
            data_trust_retest_pct=("data_confidence_status", lambda s: round(100*(s == "RETEST").mean(), 2)),
            ood_pct=("applicability_status", lambda s: round(100*(s == "OUT_OF_DOMAIN").mean(), 2)),
            hard_fail_pct=("engineering_hard_failure", lambda s: round(100*pd.Series(s).fillna(False).astype(bool).mean(), 2)),
            accept_pct=("unified_action", lambda s: round(100*(s == "ACCEPT").mean(), 2)),
            watch_pct=("unified_action", lambda s: round(100*(s == "WATCH").mean(), 2)),
            hold_pct=("unified_action", lambda s: round(100*(s == "HOLD").mean(), 2)),
            retest_pct=("unified_action", lambda s: round(100*(s == "RETEST").mean(), 2)),
            reject_pct=("unified_action", lambda s: round(100*(s == "REJECT").mean(), 2)),
        )
        .reset_index()
    )

    lot = build_lot_intelligence(
        evidence["features"],
        module_a_table,
        module_b_table,
        [],
    )
    commonality = commonality_engine(df, evidence["features"], module_a_table)
    calibration = calibration_monitor(module_b_table)

    # Population-specific checks.
    population_checks = []

    lot_rows = {str(x.get("lot_id")): x for x in lot.get("lots", [])}
    shifted = lot_rows.get("CH_LOT_SHIFT")
    population_checks.append({
        "check": "LOT_WIDE_SHIFT_HEALTH",
        "status": "PASS" if shifted and shifted.get("health_state") in {"ELEVATED", "ALERT"} else "FAIL",
        "observed": shifted.get("health_state") if shifted else "NOT_FOUND",
        "expected": "ELEVATED or ALERT",
    })

    common = commonality.get("commonalities", [])
    batch_hit = any(
        x.get("field") == "burnin_batch_id" and x.get("value") == "CH_MIXED_BAD_BATCH"
        for x in common
    )
    population_checks.append({
        "check": "BATCH_LOCAL_COMMONALITY",
        "status": "PASS" if batch_hit else "FAIL",
        "observed": "FOUND" if batch_hit else "NOT_IN_TOP_COMMONALITIES",
        "expected": "CH_MIXED_BAD_BATCH enriched in risky population",
    })

    inst_hit = any(
        x.get("field") == "instrument_id" and x.get("value") == "SMU-COMMONALITY"
        for x in common
    )
    population_checks.append({
        "check": "INSTRUMENT_COMMONALITY",
        "status": "PASS" if inst_hit else "FAIL",
        "observed": "FOUND" if inst_hit else "NOT_IN_TOP_COMMONALITIES",
        "expected": "SMU-COMMONALITY enriched in risky population",
    })

    calibration_stress_ids = set(
        truth.loc[truth["scenario_family"].eq("CALIBRATION_STRESS"), "component_id"].astype(str)
    )
    cal_subset = module_b_table[
        module_b_table["component_id"].astype(str).isin(calibration_stress_ids)
    ].copy() if isinstance(module_b_table, pd.DataFrame) else None
    cal_stress = calibration_monitor(cal_subset)
    population_checks.append({
        "check": "CALIBRATION_STRESS",
        "status": "PASS" if cal_stress.get("status") in {"WATCH", "RECALIBRATION_REVIEW"} else "FAIL",
        "observed": cal_stress.get("status"),
        "expected": "WATCH or RECALIBRATION_REVIEW",
    })

    population_df = pd.DataFrame(population_checks)

    component_results.to_csv(out_dir / "component_validation_results.csv", index=False)
    summary.to_csv(out_dir / "scenario_validation_summary.csv", index=False)
    population_df.to_csv(out_dir / "population_validation_checks.csv", index=False)

    report = {
        "mode": "SPARK EXPECTED-VS-ACTUAL VALIDATION",
        "components": int(len(component_results)),
        "scenario_families": int(component_results["scenario_family"].nunique()),
        "strict_component_passes": int((component_results["validation_status"] == "PASS").sum()),
        "strict_component_failures": int((component_results["validation_status"] == "FAIL").sum()),
        "informational_components": int((component_results["validation_status"] == "INFO").sum()),
        "population_checks": population_checks,
        "calibration_full_challenge": calibration,
        "commonality_causal_claim": commonality.get("causal_claim"),
        "note": (
            "PASS/FAIL rules are applied only where the implemented contract gives a clear "
            "expected behavior. INFO scenarios are diagnostic/model-response observations and "
            "are not silently converted into failures."
        ),
    }
    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md = []
    md.append("# SPARK Validation Challenge Report")
    md.append("")
    md.append(f"- Components: **{report['components']}**")
    md.append(f"- Scenario families: **{report['scenario_families']}**")
    md.append(f"- Strict component PASS: **{report['strict_component_passes']}**")
    md.append(f"- Strict component FAIL: **{report['strict_component_failures']}**")
    md.append(f"- Informational/model-response cases: **{report['informational_components']}**")
    md.append("")
    md.append("## Scenario summary")
    md.append("")
    md.append(_markdown_table(summary))
    md.append("")
    md.append("## Population checks")
    md.append("")
    md.append(_markdown_table(population_df))
    md.append("")
    md.append("## Interpretation")
    md.append("")
    md.append(
        "Strict rules are reserved for deterministic contracts such as Data Trust, "
        "Engineering Safety, OOD abstention, and explicitly designed rolling-trajectory cases. "
        "Model-response scenarios that do not have a deterministic contract remain INFO rather "
        "than being falsely labeled failures."
    )
    (out_dir / "VALIDATION_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("SPARK EXPECTED-VS-ACTUAL VALIDATION COMPLETE")
    print(f"Components            : {report['components']}")
    print(f"Scenario families     : {report['scenario_families']}")
    print(f"Strict PASS           : {report['strict_component_passes']}")
    print(f"Strict FAIL           : {report['strict_component_failures']}")
    print(f"Informational         : {report['informational_components']}")
    print("")
    print("Population checks:")
    print(population_df.to_string(index=False))
    print("")
    print(f"Results directory     : {out_dir}")


if __name__ == "__main__":
    main()
