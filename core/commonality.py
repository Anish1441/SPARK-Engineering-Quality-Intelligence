from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


RISK_ACTIONS = {"WATCH", "HOLD", "HOLD_FOR_REVIEW", "RETEST", "REJECT"}


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 2) if den else 0.0


def commonality_engine(
    raw_df: pd.DataFrame,
    features: pd.DataFrame,
    module_a: pd.DataFrame | None,
    *,
    min_risky_components: int = 3,
) -> dict[str, Any]:
    """Find enriched characteristics in the escalated population.

    This is association/commonality analysis only. It deliberately does not
    claim causal attribution.
    """
    if module_a is None or module_a.empty or "component_id" not in module_a.columns:
        return {"available": False, "status": "UNAVAILABLE", "commonalities": []}

    a = module_a.copy()
    action_col = "action" if "action" in a.columns else "module_a_action"
    if action_col not in a.columns:
        return {"available": False, "status": "UNAVAILABLE", "commonalities": []}
    risky_ids = set(
        a.loc[a[action_col].fillna("").astype(str).str.upper().isin(RISK_ACTIONS), "component_id"]
        .astype(str)
        .tolist()
    )
    if len(risky_ids) < min_risky_components:
        return {
            "available": True,
            "status": "INSUFFICIENT_RISK_POPULATION",
            "risky_components": len(risky_ids),
            "commonalities": [],
            "numeric_shifts": [],
            "causal_claim": False,
        }

    # Representative early row (24h preferred) to obtain raw categorical context.
    raw = raw_df.copy()
    raw["component_id"] = raw["component_id"].astype(str)
    raw["measurement_time_h"] = pd.to_numeric(raw.get("measurement_time_h"), errors="coerce")
    early = raw[raw["measurement_time_h"].le(24)].copy()
    early["_pref"] = (early["measurement_time_h"] == 24).astype(int)
    early = early.sort_values(["component_id", "_pref", "measurement_time_h"], ascending=[True, False, False])
    representative = early.drop_duplicates("component_id", keep="first")

    population = representative["component_id"].astype(str)
    risky_mask = population.isin(risky_ids)
    risky = representative[risky_mask]
    reference = representative[~risky_mask]

    commonalities: list[dict[str, Any]] = []
    categorical_cols = [
        c for c in ["lot_id", "burnin_batch_id", "instrument_id", "part_number", "qualification_level"]
        if c in representative.columns
    ]
    for col in categorical_cols:
        for value, risky_count in risky[col].fillna("<missing>").astype(str).value_counts().items():
            if risky_count < 2:
                continue
            risky_support = _pct(int(risky_count), len(risky))
            ref_count = int((reference[col].fillna("<missing>").astype(str) == value).sum())
            ref_support = _pct(ref_count, len(reference))
            enrichment = round((risky_support + 0.5) / (ref_support + 0.5), 2)
            if enrichment < 1.5 and risky_support < 40.0:
                continue
            commonalities.append({
                "field": col,
                "value": value,
                "risky_count": int(risky_count),
                "risky_support_pct": risky_support,
                "reference_support_pct": ref_support,
                "enrichment_ratio": enrichment,
            })

    commonalities.sort(key=lambda x: (x["enrichment_ratio"], x["risky_support_pct"]), reverse=True)

    # Preserve cross-dimension visibility. A pure global top-N can be monopolised
    # by many lot/batch categories and hide a strong instrument/part commonality.
    # Keep the strongest association from each available categorical field first,
    # then fill the remaining slots by global rank.
    selected_commonalities: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    for field in categorical_cols:
        hit = next((x for x in commonalities if x["field"] == field), None)
        if hit is not None:
            selected_commonalities.append(hit)
            selected_keys.add((str(hit["field"]), str(hit["value"])))
    for item in commonalities:
        key = (str(item["field"]), str(item["value"]))
        if key in selected_keys:
            continue
        selected_commonalities.append(item)
        selected_keys.add(key)
        if len(selected_commonalities) >= 12:
            break

    f = features.copy()
    f["component_id"] = f["component_id"].astype(str)
    fr = f[f["component_id"].isin(risky_ids)]
    ff = f[~f["component_id"].isin(risky_ids)]
    numeric_shifts: list[dict[str, Any]] = []
    for col in ["slope_0_24_uA_per_h", "robust_z_24h", "historical_robust_z_24h", "lot_shift_score_at_24h"]:
        if col not in f.columns:
            continue
        r = pd.to_numeric(fr[col], errors="coerce").dropna()
        n = pd.to_numeric(ff[col], errors="coerce").dropna()
        if r.empty or n.empty:
            continue
        numeric_shifts.append({
            "feature": col,
            "risky_median": round(float(r.median()), 6),
            "reference_median": round(float(n.median()), 6),
            "median_delta": round(float(r.median() - n.median()), 6),
        })
    numeric_shifts.sort(key=lambda x: abs(x["median_delta"]), reverse=True)

    return {
        "available": True,
        "status": "READY",
        "mode": "SPARK COMMONALITY ENGINE",
        "risky_components": len(risky),
        "reference_components": len(reference),
        "commonalities": selected_commonalities[:12],
        "numeric_shifts": numeric_shifts[:8],
        "causal_claim": False,
        "semantics": (
            "Commonalities are statistical associations enriched in the escalated "
            "population; they are not proof of root cause or causality."
        ),
    }
