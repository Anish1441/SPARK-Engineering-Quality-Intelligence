from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def governed_feedback_learning(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn governed QA feedback into candidate engineering-review items.

    No threshold or model is changed. Output is a review queue only.
    """
    governed = [r for r in rows if int(r.get("schema_version") or 0) >= 7]
    overrides = [r for r in governed if bool(r.get("override_applied"))]
    reason_counts = Counter(str(r.get("override_reason_code") or "").strip() for r in overrides)
    transition_counts = Counter(
        f"{r.get('machine_recommended_action') or 'UNKNOWN'}→{r.get('final_action') or 'UNKNOWN'}"
        for r in overrides
    )
    lot_flags: defaultdict[str, int] = defaultdict(int)
    for r in overrides:
        if r.get("model_threshold_review_flag"):
            lot = str(r.get("lot_id") or "UNKNOWN")
            lot_flags[lot] += 1

    candidates: list[dict[str, Any]] = []
    model_review_count = sum(1 for r in overrides if r.get("model_threshold_review_flag"))
    if model_review_count:
        candidates.append({
            "candidate_id": "FB-MODEL-001",
            "type": "MODEL_THRESHOLD_REVIEW",
            "priority": "HIGH" if model_review_count >= 5 else "MEDIUM",
            "evidence_count": model_review_count,
            "reason": "Governed QA overrides explicitly flagged a suspected model/threshold limitation.",
            "recommended_next_step": "Offline engineering review and champion/challenger validation.",
        })

    for code, count in reason_counts.most_common():
        if not code or count < 2:
            continue
        candidates.append({
            "candidate_id": f"FB-REASON-{code}",
            "type": "RECURRING_OVERRIDE_REASON",
            "priority": "MEDIUM",
            "evidence_count": count,
            "reason": f"Override reason {code} recurred {count} times.",
            "recommended_next_step": "Review common evidence before changing any model, threshold or procedure.",
        })

    for transition, count in transition_counts.most_common():
        if count < 2:
            continue
        candidates.append({
            "candidate_id": f"FB-TRANS-{transition.replace('→', '-')}",
            "type": "RECURRING_DISAGREEMENT_TRANSITION",
            "priority": "MEDIUM",
            "evidence_count": count,
            "reason": f"Machine-to-human transition {transition} recurred {count} times.",
            "recommended_next_step": "Review whether the disagreement is data-, policy-, or model-driven.",
        })

    return {
        "available": True,
        "status": "REVIEW_QUEUE_READY" if candidates else "NO_REVIEW_CANDIDATES",
        "governed_entries": len(governed),
        "override_entries": len(overrides),
        "model_threshold_review_flags": model_review_count,
        "reason_counts": dict(reason_counts),
        "transition_counts": dict(transition_counts),
        "lot_model_review_flags": dict(sorted(lot_flags.items())),
        "candidates": candidates,
        "automatic_retraining": False,
        "automatic_threshold_change": False,
        "semantics": "Candidate queue for offline engineering review only.",
    }
