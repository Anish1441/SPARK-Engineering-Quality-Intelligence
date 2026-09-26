from __future__ import annotations

from collections import Counter
from typing import Any


ACTIONS = {
    "ACCEPT",
    "WATCH",
    "RETEST",
    "HOLD",
    "REJECT",
    "QUARANTINE",
    "ABSTAIN",
}

OVERRIDE_REASON_CATALOG: dict[str, dict[str, str]] = {
    "QA-OVR-001": {
        "title": "Verified measurement context",
        "category": "MEASUREMENT_CONTEXT",
        "review_target": "PROCESS",
    },
    "QA-OVR-002": {
        "title": "Tester or instrument evidence",
        "category": "TESTER_INSTRUMENT",
        "review_target": "DATA_TRUST",
    },
    "QA-OVR-003": {
        "title": "Verified component history",
        "category": "COMPONENT_HISTORY",
        "review_target": "ENGINEERING",
    },
    "QA-OVR-004": {
        "title": "Approved engineering review",
        "category": "ENGINEERING_REVIEW",
        "review_target": "ENGINEERING",
    },
    "QA-OVR-005": {
        "title": "Controlled procedure requirement",
        "category": "PROCEDURAL_REQUIREMENT",
        "review_target": "PROCESS",
    },
    "QA-OVR-006": {
        "title": "Suspected model or threshold limitation",
        "category": "MODEL_REVIEW",
        "review_target": "MODEL_THRESHOLD",
    },
    "QA-OVR-007": {
        "title": "Other controlled exception",
        "category": "CONTROLLED_EXCEPTION",
        "review_target": "QA_GOVERNANCE",
    },
}

MIN_OVERRIDE_JUSTIFICATION_CHARS = 20

# Ordinal values are used only to describe direction of a disagreement. They
# are not a reliability score. RETEST/ABSTAIN/QUARANTINE are process states and
# therefore handled explicitly rather than being forced onto this scale.
_ACTION_SEVERITY = {
    "ACCEPT": 0,
    "WATCH": 1,
    "HOLD": 2,
    "REJECT": 3,
}
_PROCESS_ACTIONS = {"RETEST", "ABSTAIN", "QUARANTINE"}


def _clean_action(value: Any) -> str:
    return str(value or "").upper().strip()


def classify_disagreement(machine_action: str, human_action: str) -> str:
    machine = _clean_action(machine_action)
    human = _clean_action(human_action)

    if machine == human:
        return "AGREEMENT"

    if machine in _PROCESS_ACTIONS or human in _PROCESS_ACTIONS:
        return "PROCESS_DISAGREEMENT"

    machine_rank = _ACTION_SEVERITY.get(machine)
    human_rank = _ACTION_SEVERITY.get(human)
    if machine_rank is None or human_rank is None:
        return "UNCLASSIFIED_DISAGREEMENT"
    if human_rank > machine_rank:
        return "CONSERVATIVE_OVERRIDE"
    return "RELAXATION_OVERRIDE"


def _machine_action(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("machine_recommended_action"),
        payload.get("reliability_unified_action"),
        (payload.get("reliability_risk_snapshot") or {}).get("unified_action"),
        (payload.get("explanation_snapshot") or {}).get("recommended_action"),
        payload.get("action"),
    ]
    for candidate in candidates:
        action = _clean_action(candidate)
        if action in ACTIONS:
            return action
    return ""


def evaluate_qa_governance(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate human-vs-machine QA governance and return normalized fields.

    Hard guardrails remain non-negotiable:
    - a hard engineering failure cannot be relaxed below REJECT containment;
    - failed Data Trust evidence cannot be converted to ACCEPT.
    """

    response = str(payload.get("response", "")).upper().strip() or "AGREE"
    selected_action = _clean_action(payload.get("action"))
    override_action = _clean_action(payload.get("override_action"))
    machine_action = _machine_action(payload)

    if machine_action not in ACTIONS:
        raise ValueError("Machine recommendation is unavailable for QA governance.")
    if selected_action not in ACTIONS:
        raise ValueError("Invalid QA action.")

    if response == "OVERRIDE":
        if override_action not in ACTIONS:
            raise ValueError("An override action is required.")
        final_action = override_action
    else:
        final_action = selected_action

    disagreement = classify_disagreement(machine_action, final_action)
    reason_code = str(payload.get("override_reason_code", "")).upper().strip()
    justification = str(payload.get("override_justification", "")).strip()

    if response in {"AGREE", "NOTE"} and final_action != machine_action:
        raise ValueError(
            "AGREE/NOTE cannot change the machine recommendation. Use OVERRIDE."
        )

    if response == "OVERRIDE":
        if final_action == machine_action:
            raise ValueError(
                "Override action must differ from the machine recommendation."
            )
        if reason_code not in OVERRIDE_REASON_CATALOG:
            raise ValueError("Select a valid override reason code.")
        if len(justification) < MIN_OVERRIDE_JUSTIFICATION_CHARS:
            raise ValueError(
                f"Override justification must contain at least "
                f"{MIN_OVERRIDE_JUSTIFICATION_CHARS} characters."
            )
    else:
        reason_code = ""
        justification = ""

    hard_failure = bool(payload.get("engineering_safety_hard_failure")) or bool(
        (payload.get("engineering_safety_snapshot") or {}).get("hard_failure")
    )
    data_action = _clean_action(payload.get("data_confidence_action")) or _clean_action(
        (payload.get("data_confidence_snapshot") or {}).get("action")
    )

    # Hard observed electrical failures remain non-negotiable. QUARANTINE is
    # accepted as equal-or-stronger containment; all other relaxation is blocked.
    if hard_failure and final_action not in {"REJECT", "QUARANTINE"}:
        raise ValueError(
            "Hard engineering failure cannot be overridden below REJECT/QUARANTINE."
        )

    # Incomplete/unusable required evidence can never silently become ACCEPT.
    if data_action == "RETEST" and final_action == "ACCEPT":
        raise ValueError("Data Trust RETEST evidence cannot be overridden to ACCEPT.")

    catalog = OVERRIDE_REASON_CATALOG.get(reason_code, {})
    feedback_flag = response == "OVERRIDE"
    model_review_flag = catalog.get("review_target") == "MODEL_THRESHOLD"

    return {
        "governance_version": 1,
        "machine_recommended_action": machine_action,
        "human_selected_action": selected_action,
        "final_action": final_action,
        "response": response,
        "disagreement_class": disagreement,
        "override_applied": response == "OVERRIDE",
        "override_reason_code": reason_code,
        "override_reason_title": catalog.get("title", ""),
        "override_reason_category": catalog.get("category", ""),
        "override_review_target": catalog.get("review_target", ""),
        "override_justification": justification,
        "feedback_review_flag": feedback_flag,
        "model_threshold_review_flag": model_review_flag,
        "hard_safety_locked": hard_failure,
        "data_trust_locked": data_action == "RETEST",
    }


def feedback_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    governed = [r for r in rows if int(r.get("schema_version") or 0) >= 7]
    disagreements = Counter(
        str(r.get("disagreement_class") or "UNKNOWN") for r in governed
    )
    reasons = Counter(
        str(r.get("override_reason_code"))
        for r in governed
        if r.get("override_reason_code")
    )
    transitions = Counter(
        f"{r.get('machine_recommended_action', '—')}→{r.get('final_action', '—')}"
        for r in governed
        if r.get("override_applied")
    )
    machine_actions = Counter(str(r.get("machine_recommended_action") or "UNKNOWN") for r in governed)
    final_actions = Counter(str(r.get("final_action") or "UNKNOWN") for r in governed)

    overrides = sum(bool(r.get("override_applied")) for r in governed)
    agreements = sum(r.get("disagreement_class") == "AGREEMENT" for r in governed)
    model_review_flags = sum(bool(r.get("model_threshold_review_flag")) for r in governed)

    return {
        "governance_schema": 7,
        "governed_entries": len(governed),
        "legacy_entries": len(rows) - len(governed),
        "agreements": agreements,
        "overrides": overrides,
        "override_rate_pct": round((overrides / len(governed) * 100.0), 2) if governed else 0.0,
        "model_threshold_review_flags": model_review_flags,
        "disagreement_classes": dict(disagreements),
        "override_reason_codes": dict(reasons),
        "override_transitions": dict(transitions),
        "machine_action_counts": dict(machine_actions),
        "final_action_counts": dict(final_actions),
        "purpose": (
            "QA feedback evidence for future model/threshold review; not automatic "
            "online learning and not a model-retraining trigger by itself."
        ),
    }
