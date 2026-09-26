"""Central project paths and domain constants."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by data, ML, API and dashboard layers."""

    project_root: Path = PROJECT_ROOT
    parameter_name: str = "IR"
    expected_part_number: str = "JANS1N5806US"
    expected_timepoints_h: tuple[int, ...] = (0, 24, 96, 168)
    nominal_temperature_c: float = 125.0
    temperature_tolerance_c: float = 1.0
    datasheet_upper_limit_uA: float = 175.0

    @property
    def data_dir(self) -> Path:
        configured = os.getenv("SIH26170_DATA_DIR")
        return Path(configured).expanduser().resolve() if configured else self.project_root / "data"

    @property
    def raw_data_path(self) -> Path:
        return self.data_dir / "raw" / "01_raw_dirty_measurements.csv"

    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def clean_long_data_path(self) -> Path:
        return self.processed_data_dir / "02_clean_measurements_long.csv"

    @property
    def feature_table_path(self) -> Path:
        return self.processed_data_dir / "03_ml_ready_components_wide.csv"

    @property
    def feature_manifest_path(self) -> Path:
        return self.processed_data_dir / "03_feature_manifest.json"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def eda_report_dir(self) -> Path:
        return self.reports_dir / "eda"


settings = Settings()
