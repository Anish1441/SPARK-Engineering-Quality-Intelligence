import pytest

from core.governance import (
    classify_disagreement,
    evaluate_qa_governance,
    feedback_summary,
)
from core.qa_manager import QAManager


def base_payload(**updates):
    payload = {
        "action": "WATCH",
        "response": "AGREE",
        "override_action": "",
        "machine_recommended_action": "WATCH",
        "reliability_unified_action": "WATCH",
        "data_confidence_action": "CONTINUE",
        "engineering_safety_hard_failure": False,
        "component_id": "C1",
        "data_confidence_snapshot": {"status": "PASS", "action": "CONTINUE"},
        "engineering_safety_snapshot": {"status": "PASS", "hard_failure": False},
        "reliability_risk_snapshot": {"unified_action": "WATCH"},
        "explanation_snapshot": {"recommended_action": "WATCH"},
    }
    payload.update(updates)
    return payload


def test_agreement_is_normalized():
    result = evaluate_qa_governance(base_payload())
    assert result["final_action"] == "WATCH"
    assert result["disagreement_class"] == "AGREEMENT"
    assert result["override_applied"] is False


def test_override_requires_reason_and_justification():
    payload = base_payload(
        response="OVERRIDE",
        override_action="HOLD",
    )
    with pytest.raises(ValueError, match="reason code"):
        evaluate_qa_governance(payload)

    payload["override_reason_code"] = "QA-OVR-006"
    payload["override_justification"] = "too short"
    with pytest.raises(ValueError, match="at least 20"):
        evaluate_qa_governance(payload)


def test_model_review_override_is_classified_and_flagged():
    result = evaluate_qa_governance(
        base_payload(
            response="OVERRIDE",
            override_action="HOLD",
            override_reason_code="QA-OVR-006",
            override_justification="Validated engineering review indicates threshold sensitivity.",
        )
    )
    assert result["disagreement_class"] == "CONSERVATIVE_OVERRIDE"
    assert result["model_threshold_review_flag"] is True
    assert result["override_review_target"] == "MODEL_THRESHOLD"


def test_agree_cannot_silently_change_machine_action():
    with pytest.raises(ValueError, match="Use OVERRIDE"):
        evaluate_qa_governance(base_payload(action="ACCEPT"))


def test_hard_safety_failure_cannot_be_relaxed():
    with pytest.raises(ValueError, match="Hard engineering failure"):
        evaluate_qa_governance(
            base_payload(
                action="REJECT",
                machine_recommended_action="REJECT",
                reliability_unified_action="REJECT",
                engineering_safety_hard_failure=True,
                response="OVERRIDE",
                override_action="ACCEPT",
                override_reason_code="QA-OVR-004",
                override_justification="Engineering review requested but hard failure remains present.",
            )
        )


def test_data_retest_cannot_be_overridden_to_accept():
    with pytest.raises(ValueError, match="Data Trust RETEST"):
        evaluate_qa_governance(
            base_payload(
                action="RETEST",
                machine_recommended_action="RETEST",
                reliability_unified_action="RETEST",
                data_confidence_action="RETEST",
                response="OVERRIDE",
                override_action="ACCEPT",
                override_reason_code="QA-OVR-001",
                override_justification="Additional context was reviewed but required checkpoint is absent.",
            )
        )


def test_disagreement_direction():
    assert classify_disagreement("ACCEPT", "HOLD") == "CONSERVATIVE_OVERRIDE"
    assert classify_disagreement("HOLD", "ACCEPT") == "RELAXATION_OVERRIDE"
    assert classify_disagreement("RETEST", "HOLD") == "PROCESS_DISAGREEMENT"


def test_feedback_summary_counts_model_review_flags(tmp_path):
    manager = QAManager(tmp_path)
    manager.save("ds", base_payload())
    manager.save(
        "ds",
        base_payload(
            response="OVERRIDE",
            override_action="HOLD",
            override_reason_code="QA-OVR-006",
            override_justification="Repeated QA evidence suggests a threshold/model review is warranted.",
        ),
    )
    result = manager.feedback_summary("ds")
    assert result["governed_entries"] == 2
    assert result["overrides"] == 1
    assert result["agreements"] == 1
    assert result["model_threshold_review_flags"] == 1
    assert result["override_reason_codes"]["QA-OVR-006"] == 1
    assert result["override_transitions"]["WATCH→HOLD"] == 1
