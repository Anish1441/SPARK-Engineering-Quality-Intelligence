from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pandas as pd


class DatasetError(Exception):
    pass


SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class DatasetManager:
    """
    Dataset manager for SPARK Phase 7.

    Supports:
    1. Normal user-uploaded CSV/Excel datasets.
    2. The original SPARK clean measurement dataset used by the
       production ML pipeline.

    The original SPARK dataset is referenced directly from the
    configured SPARK_PIPELINE_ROOT. It is not copied or modified.
    """

    ORIGINAL_FILENAME = "02_clean_measurements_long.csv"

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        self.registry = self.root / "registry.json"

        if not self.registry.exists():
            self.registry.write_text("[]", encoding="utf-8")

        self._register_original_spark_dataset()

    def _read(self):
        try:
            data = json.loads(self.registry.read_text(encoding="utf-8"))

            if not isinstance(data, list):
                return []

            return data

        except Exception as exc:
            raise DatasetError(
                f"Dataset registry could not be read: {exc}"
            ) from exc

    def _write(self, data):
        temporary = self.registry.with_suffix(".tmp")

        temporary.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

        temporary.replace(self.registry)

    def _load(self, path):
        path = Path(path)

        try:
            suffix = path.suffix.lower()

            if suffix == ".csv":
                return pd.read_csv(
                    path,
                    low_memory=False,
                )

            if suffix in {".xlsx", ".xls"}:
                return pd.read_excel(path)

        except Exception as exc:
            raise DatasetError(
                f"Dataset could not be read: {exc}"
            ) from exc

        raise DatasetError(
            "Only CSV and Excel datasets are supported."
        )

    @staticmethod
    def _is_original_spark_dataset(item):
        return (
            item.get("source") == "original_spark_pipeline"
            or item.get("filename") == DatasetManager.ORIGINAL_FILENAME
        )

    def _original_spark_path(self):
        pipeline_root = os.environ.get(
            "SPARK_PIPELINE_ROOT",
            "",
        ).strip()

        if not pipeline_root:
            return None

        path = (
            Path(pipeline_root).expanduser().resolve()
            / "data"
            / "processed"
            / self.ORIGINAL_FILENAME
        )

        return path

    def _register_original_spark_dataset(self):
        """
        Register the original SPARK clean measurement dataset.

        This dataset is the authoritative input for the original
        feature engineering and Module-B ML pipeline.
        """

        path = self._original_spark_path()

        if path is None or not path.exists():
            return

        rows = self._read()

        existing = next(
            (
                item
                for item in rows
                if self._is_original_spark_dataset(item)
            ),
            None,
        )

        try:
            df = self._load(path)
        except DatasetError:
            return

        if df.empty:
            return

        item = {
            "dataset_id": "original-spark-module-b",
            "filename": self.ORIGINAL_FILENAME,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "numeric_columns": int(
                len(df.select_dtypes(include="number").columns)
            ),
            "missing_cells": int(df.isna().sum().sum()),
            "size_bytes": int(path.stat().st_size),
            "source": "original_spark_pipeline",
            "read_only": True,
            "path": str(path),
            "active": bool(existing.get("active", False)) if existing else False
        }

        if existing:
            changed = False

            for key, value in item.items():
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True

            if changed:
                self._write(rows)

            return

        # Make the original SPARK dataset the active dataset when it
        # is first registered. Existing user datasets are preserved.
        if not any(x.get("active") for x in rows):
            item["active"] = True

        self._write([item] + rows)

    def save_upload(self, file):
        name = SAFE.sub(
            "_",
            Path(file.filename).name,
        ).strip("._")

        if (
            not name
            or Path(name).suffix.lower()
            not in {".csv", ".xlsx", ".xls"}
        ):
            raise DatasetError(
                "Only CSV and Excel datasets are supported."
            )

        dataset_id = uuid.uuid4().hex

        target = (
            self.root
            / (
                dataset_id
                + Path(name).suffix.lower()
            )
        )

        try:
            file.save(target)
            df = self._load(target)

        except DatasetError:
            target.unlink(missing_ok=True)
            raise

        except Exception as exc:
            target.unlink(missing_ok=True)

            raise DatasetError(
                f"Dataset could not be saved: {exc}"
            ) from exc

        if df.empty:
            target.unlink(missing_ok=True)

            raise DatasetError(
                "The dataset contains no records."
            )

        item = {
            "dataset_id": dataset_id,
            "filename": name,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "numeric_columns": int(
                len(df.select_dtypes(include="number").columns)
            ),
            "missing_cells": int(df.isna().sum().sum()),
            "size_bytes": int(target.stat().st_size),
            "source": "user_upload",
            "read_only": False,
            "active": False,
        }

        rows = self._read()

        # Preserve existing active dataset.
        if not any(x.get("active") for x in rows):
            item["active"] = True

        self._write([item] + rows)

        return item

    def list(self):
        self._register_original_spark_dataset()
        return self._read()

    def get(self, dataset_id):
        self._register_original_spark_dataset()

        for item in self._read():

            if item["dataset_id"] != dataset_id:
                continue

            # Original SPARK dataset is read directly from its
            # authoritative pipeline location.
            if self._is_original_spark_dataset(item):
                path = Path(item["path"])

                if not path.exists():
                    raise DatasetError(
                        "Original SPARK dataset file is missing."
                    )

                return item, self._load(path)

            # Normal Phase-7 uploaded dataset.
            path = next(
                iter(
                    self.root.glob(
                        dataset_id + ".*"
                    )
                ),
                None,
            )

            if path is None:
                raise DatasetError(
                    "Dataset file is missing."
                )

            return item, self._load(path)

        raise DatasetError(
            "Dataset not found."
        )

    def activate(self, dataset_id):
        item, _ = self.get(dataset_id)

        rows = self._read()

        for row in rows:
            row["active"] = (
                row["dataset_id"] == dataset_id
            )

        self._write(rows)

        item["active"] = True

        return item

    def remove(self, dataset_id):
        item, _ = self.get(dataset_id)

        if self._is_original_spark_dataset(item):
            raise DatasetError(
                "The original SPARK ML dataset is read-only "
                "and cannot be removed."
            )

        for path in self.root.glob(
            dataset_id + ".*"
        ):
            path.unlink(missing_ok=True)

        rows = [
            row
            for row in self._read()
            if row["dataset_id"] != dataset_id
        ]

        self._write(rows)

        return {
            "removed": dataset_id
        }