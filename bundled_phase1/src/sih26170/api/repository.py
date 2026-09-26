"""Read dashboard facts from generated pipeline artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from sih26170.config import Settings, settings


@dataclass(frozen=True)
class ArtifactRepository:
    """Provide read-only, label-blind dashboard data."""

    config: Settings = settings

    @property
    def final_report_path(self) -> Path:
        return self.config.reports_dir / "final_screening_decisions.csv"

    @property
    def combined_report_path(self) -> Path:
        return self.config.reports_dir / "combined_safety_decisions.csv"

    def _features(self) -> pd.DataFrame:
        path = self.config.feature_table_path
        if not path.is_file():
            raise FileNotFoundError(f"Feature table not found: {path}")
        return pd.read_csv(path)

    def _optional_csv(self, path: Path) -> pd.DataFrame | None:
        return pd.read_csv(path) if path.is_file() else None

    def screening_status(self) -> dict[str, Any]:
        """Describe existing screening outputs without executing the pipeline.

        Only operational artifacts are inspected.  In particular, the synthetic
        ground-truth file is never opened by this dashboard repository.
        """

        stage_specs = (
            (
                "cleaning",
                "Data cleaning",
                (self.config.clean_long_data_path,),
            ),
            (
                "features",
                "Feature engineering",
                (self.config.feature_table_path,),
            ),
            (
                "module_a",
                "Module A anomaly detection",
                (
                    self.config.reports_dir / "module_a_24h_screening.csv",
                    self.config.reports_dir / "module_a_predictions.csv",
                    self.config.reports_dir / "module_a_results.csv",
                ),
            ),
            (
                "module_b_24h",
                "Module B 24-hour forecast",
                (self.config.reports_dir / "module_b_24h_predictions.csv",),
            ),
            (
                "module_b_96h",
                "Module B 96-hour update",
                (self.config.reports_dir / "module_b_96h_predictions.csv",),
            ),
            (
                "safety_gate",
                "Safety decision gate",
                (self.combined_report_path,),
            ),
            (
                "final_screening",
                "Final 168-hour screening",
                (self.final_report_path,),
            ),
        )

        stages: list[dict[str, Any]] = []
        for stage_id, label, candidates in stage_specs:
            artifact = next((path for path in candidates if path.is_file()), None)
            stages.append(
                {
                    "id": stage_id,
                    "label": label,
                    "status": "AVAILABLE" if artifact else "MISSING",
                    "artifact": (
                        artifact.relative_to(self.config.project_root).as_posix()
                        if artifact
                        else None
                    ),
                }
            )

        final_decisions: dict[str, Any] = {
            "available": False,
            "total": 0,
            "counts": {},
        }
        final_stage = stages[-1]
        if final_stage["status"] == "AVAILABLE":
            try:
                final = pd.read_csv(self.final_report_path, usecols=["final_decision"])
                counts = final["final_decision"].dropna().astype(str).value_counts()
                final_decisions = {
                    "available": True,
                    "total": int(counts.sum()),
                    "counts": {
                        str(decision): int(count) for decision, count in counts.items()
                    },
                }
            except (OSError, ValueError, pd.errors.ParserError):
                # A present but unreadable report is not valid stage evidence.
                final_stage["status"] = "INVALID"
                final_decisions["error"] = (
                    "Final decision report is unreadable or missing final_decision."
                )

        available_count = sum(stage["status"] == "AVAILABLE" for stage in stages)
        if available_count == len(stages):
            pipeline_status = "COMPLETE"
        elif available_count:
            pipeline_status = "PARTIAL"
        else:
            pipeline_status = "NOT_STARTED"

        return {
            "pipeline_status": pipeline_status,
            "available_stage_count": available_count,
            "total_stage_count": len(stages),
            "stages": stages,
            "final_decisions": final_decisions,
            "read_only": True,
            "hidden_truth_accessed": False,
        }

    def summary(self) -> dict[str, Any]:
        """Return the best available real summary without truth labels."""

        features = self._features()
        final = self._optional_csv(self.final_report_path)
        combined = self._optional_csv(self.combined_report_path)
        source = "feature_store"
        decisions: dict[str, int] = {}
        released = 0

        if final is not None and "final_decision" in final:
            source = "final_screening"
            decisions = {
                str(key): int(value)
                for key, value in final["final_decision"]
                .value_counts()
                .to_dict()
                .items()
            }
            released = int(final["final_decision"].eq("ACCEPT_FINAL").sum())
        elif combined is not None and "decision_at_96h" in combined:
            source = "combined_96h_screening"
            decisions = {
                str(key): int(value)
                for key, value in combined["decision_at_96h"]
                .value_counts()
                .to_dict()
                .items()
            }

        split_counts = features["dataset_split"].value_counts().to_dict()
        available_timepoints = [
            hour
            for hour in self.config.expected_timepoints_h
            if f"ir_{hour}h_uA" in features
        ]
        return {
            "source": source,
            "component_count": int(features["component_id"].nunique()),
            "lot_count": int(features["lot_id"].nunique()),
            "batch_count": int(features["burnin_batch_id"].nunique()),
            "released_count": released,
            "split_counts": {
                str(key): int(value) for key, value in split_counts.items()
            },
            "decisions": decisions,
            "timepoints_h": available_timepoints,
            "temperature_c": self.config.nominal_temperature_c,
            "datasheet_limit_uA": self.config.datasheet_upper_limit_uA,
            "parameter": self.config.parameter_name,
            "part_number": self.config.expected_part_number,
        }

    def component_preview(self, limit: int = 24) -> list[dict[str, Any]]:
        """Return component passports for the chamber and inspector view."""

        features = self._features()
        columns = [
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "dataset_split",
            "ir_0h_uA",
            "ir_24h_uA",
            "ir_96h_uA",
            "ir_168h_uA",
        ]
        available = [column for column in columns if column in features]
        sample = features.loc[:, available].copy()
        final = self._optional_csv(self.final_report_path)
        combined = self._optional_csv(self.combined_report_path)
        if final is not None and "component_id" in final:
            passport_columns = [
                "component_id",
                "final_decision",
                "final_decision_reason",
                "qa_inspector_summary",
                "final_component_anomaly_score",
                "release_permitted",
                "module_a_action",
                "module_a_primary_reason",
                "batch_slope_shift_score",
                "decision_at_24h",
                "decision_reason_at_24h",
                "decision_at_96h",
                "decision_reason_at_96h",
                "predicted_ir_168h_uA_at_24h",
                "conformal_safety_upper_uA_at_24h",
                "predicted_ir_168h_uA_at_96h",
                "conformal_safety_upper_uA_at_96h",
                "robust_z_96h_at_96h",
                "acceleration_indicator_at_96h",
            ]
            available_passport = [
                column for column in passport_columns if column in final
            ]
            sample = sample.merge(
                final.loc[:, available_passport].drop_duplicates("component_id"),
                on="component_id",
                how="left",
            )
            # Put representative QA actions into the preview instead of showing
            # only the first rows of the feature table. This keeps the chamber
            # useful while the endpoint remains bounded and label-blind.
            decision_priority = {
                "REJECT_FINAL": 0,
                "QUARANTINE_LOT_BATCH": 1,
                "HOLD_FOR_REVIEW": 2,
                "RETEST": 3,
                "ACCEPT_FINAL": 4,
            }
            sample["_decision_priority"] = (
                sample.get(
                    "final_decision",
                    pd.Series(index=sample.index, dtype=object),
                )
                .map(decision_priority)
                .fillna(5)
            )
            sample["_anomaly_priority"] = pd.to_numeric(
                sample.get(
                    "final_component_anomaly_score",
                    pd.Series(index=sample.index, dtype=float),
                ),
                errors="coerce",
            ).fillna(-1.0)
            sample = sample.sort_values(
                ["_decision_priority", "_anomaly_priority", "component_id"],
                ascending=[True, False, True],
                kind="stable",
            ).drop(columns=["_decision_priority", "_anomaly_priority"])
        elif combined is not None and "component_id" in combined:
            combined_columns = [
                "component_id",
                "module_a_action",
                "module_a_primary_reason",
                "batch_slope_shift_score",
                "decision_at_24h",
                "decision_reason_at_24h",
                "decision_at_96h",
                "decision_reason_at_96h",
                "predicted_ir_168h_uA_at_24h",
                "conformal_safety_upper_uA_at_24h",
                "predicted_ir_168h_uA_at_96h",
                "conformal_safety_upper_uA_at_96h",
                "robust_z_96h_at_96h",
                "acceleration_indicator_at_96h",
            ]
            available_combined = [
                column for column in combined_columns if column in combined
            ]
            sample = sample.merge(
                combined.loc[:, available_combined].drop_duplicates("component_id"),
                on="component_id",
                how="left",
            )
        sample = sample.head(limit).copy()
        sample = sample.astype(object)
        sample = sample.where(pd.notna(sample), None)
        return sample.to_dict(orient="records")

    def validate_upload(self, content: bytes, filename: str) -> dict[str, Any]:
        """Validate an uploaded raw measurement CSV without persisting it."""

        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV datasets are supported in this prototype.")
        if not content:
            raise ValueError("The uploaded CSV is empty.")

        try:
            frame = pd.read_csv(BytesIO(content))
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ValueError("The file is not a readable UTF-8 CSV dataset.") from exc

        required = {
            "component_id",
            "lot_id",
            "burnin_batch_id",
            "measurement_time_h",
            "raw_value",
            "raw_unit",
            "temperature_c",
        }
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        numeric_time = pd.to_numeric(frame["measurement_time_h"], errors="coerce")
        invalid_time_rows = int(numeric_time.isna().sum())
        timepoints = sorted(int(value) for value in numeric_time.dropna().unique())
        expected = set(self.config.expected_timepoints_h)
        unexpected_timepoints = sorted(set(timepoints).difference(expected))
        missing_timepoints = sorted(expected.difference(timepoints))
        duplicate_rows = int(frame.duplicated().sum())
        null_measurements = int(frame["raw_value"].isna().sum())
        valid = not (invalid_time_rows or unexpected_timepoints or missing_timepoints)

        return {
            "filename": filename,
            "valid": valid,
            "row_count": int(len(frame)),
            "component_count": int(frame["component_id"].nunique()),
            "lot_count": int(frame["lot_id"].nunique()),
            "batch_count": int(frame["burnin_batch_id"].nunique()),
            "timepoints_h": timepoints,
            "duplicate_rows": duplicate_rows,
            "null_measurements": null_measurements,
            "invalid_time_rows": invalid_time_rows,
            "missing_timepoints_h": missing_timepoints,
            "unexpected_timepoints_h": unexpected_timepoints,
            "stages_completed": [
                "FILE_RECEIVED",
                "SCHEMA_CHECKED",
                "TIMEPOINTS_CHECKED",
                "QUALITY_PROFILED",
            ],
        }
