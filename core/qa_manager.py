from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.governance import ACTIONS, evaluate_qa_governance, feedback_summary


RESPONSES = {"AGREE", "OVERRIDE", "NOTE"}


class QAManager:
    """Atomic local QA ledger with governance and deterministic integrity evidence.

    Schema v7 retains the v6 SHA-256 controls and adds normalized QA-governance
    fields: machine recommendation, human final action, disagreement class,
    controlled override reason and mandatory override justification.

    The hash chain is an integrity aid, not a digital signature or external
    timestamp authority.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, dataset_id: str) -> Path:
        return self.root / f"{dataset_id}.json"

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value).encode("utf-8")).hexdigest()

    @classmethod
    def _evidence_payload(cls, item: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "dataset_id",
            "inspection_index",
            "record_index",
            "inspection_mode",
            "component_id",
            "measurement_time_h",
            "lot_id",
            "burnin_batch_id",
            "analytical_score",
            "analytical_state",
            "analytical_contributors",
            "data_confidence_snapshot",
            "engineering_safety_snapshot",
            "reliability_risk_snapshot",
            "explanation_snapshot",
            "model_snapshot",
            "assessment_source",
        ]
        if int(item.get("schema_version") or 0) >= 7:
            keys.extend(
                [
                    "machine_recommended_action",
                    "human_selected_action",
                    "disagreement_class",
                    "override_reason_code",
                    "override_reason_category",
                    "override_review_target",
                    "override_justification",
                ]
            )
        return {key: item.get(key) for key in keys}

    def list(self, dataset_id: str) -> list[dict[str, Any]]:
        path = self._path(dataset_id)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"QA ledger could not be read: {exc}") from exc

        if not isinstance(data, list):
            raise ValueError("QA ledger must contain a JSON list.")

        return [item for item in data if isinstance(item, dict)]

    def save(self, dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = str(payload.get("response", "")).upper().strip() or "AGREE"
        if response not in RESPONSES:
            raise ValueError("Invalid QA response.")

        governance = evaluate_qa_governance(payload)
        rows = self.list(dataset_id)
        prior_ledger_hash = self._sha256(rows)

        item = dict(payload)
        item.update(governance)
        item.update(
            {
                "id": uuid.uuid4().hex,
                "schema_version": 7,
                "dataset_id": dataset_id,
                "ledger_position": len(rows) + 1,
                "action": governance["human_selected_action"],
                "response": response,
                "override_action": (
                    governance["final_action"] if response == "OVERRIDE" else ""
                ),
                "final_action": governance["final_action"],
                "comment": str(payload.get("comment", "")).strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prior_ledger_hash": prior_ledger_hash,
            }
        )

        item["evidence_fingerprint"] = self._sha256(self._evidence_payload(item))
        item_without_hash = dict(item)
        item_without_hash.pop("entry_hash", None)
        item["entry_hash"] = self._sha256(item_without_hash)

        rows.append(item)
        path = self._path(dataset_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        temporary.replace(path)
        return item

    def verify(self, dataset_id: str) -> dict[str, Any]:
        rows = self.list(dataset_id)
        checked = 0
        legacy = 0
        v6 = 0
        v7 = 0
        issues: list[dict[str, Any]] = []

        for index, item in enumerate(rows):
            schema = int(item.get("schema_version") or 0)
            if schema < 6:
                legacy += 1
                continue

            checked += 1
            v6 += schema == 6
            v7 += schema >= 7
            position = index + 1
            prefix = rows[:index]
            expected_prefix_hash = self._sha256(prefix)
            if item.get("prior_ledger_hash") != expected_prefix_hash:
                issues.append(
                    {
                        "ledger_position": position,
                        "type": "PRIOR_LEDGER_HASH_MISMATCH",
                    }
                )

            expected_evidence = self._sha256(self._evidence_payload(item))
            if item.get("evidence_fingerprint") != expected_evidence:
                issues.append(
                    {
                        "ledger_position": position,
                        "type": "EVIDENCE_FINGERPRINT_MISMATCH",
                    }
                )

            candidate = dict(item)
            stored_entry_hash = candidate.pop("entry_hash", None)
            expected_entry_hash = self._sha256(candidate)
            if stored_entry_hash != expected_entry_hash:
                issues.append(
                    {
                        "ledger_position": position,
                        "type": "ENTRY_HASH_MISMATCH",
                    }
                )

        if issues:
            status = "FAILED"
        elif checked:
            status = "VERIFIED"
        elif rows:
            status = "LEGACY_UNSEALED"
        else:
            status = "EMPTY"

        return {
            "dataset_id": dataset_id,
            "status": status,
            "integrity_ok": not issues,
            "entries": len(rows),
            "verified_hashed_entries": checked,
            "verified_v6_entries": v6,
            "verified_v7_entries": v7,
            "legacy_entries": legacy,
            "issues": issues,
            "algorithm": "SHA-256",
            "scope": (
                "Local append-ledger integrity check; not a digital signature or "
                "external timestamp authority."
            ),
        }

    def feedback_summary(self, dataset_id: str) -> dict[str, Any]:
        return feedback_summary(self.list(dataset_id))

    def delete_dataset(self, dataset_id: str) -> int:
        """Delete the QA ledger when the user explicitly deletes a dataset."""
        path = self._path(dataset_id)
        if not path.exists():
            return 0

        count = len(self.list(dataset_id))
        path.unlink(missing_ok=True)
        return count
