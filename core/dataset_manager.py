from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pandas as pd


class DatasetError(Exception):
    pass


SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


class DatasetManager:
    """Manage uploaded, bundled-demo, and original SPARK datasets."""

    ORIGINAL_FILENAME = "02_clean_measurements_long.csv"
    ORIGINAL_DATASET_ID = "original-spark-module-b"
    SAMPLE_FILENAME = "spark_igbt_demo_dataset.csv"
    SAMPLE_DATASET_ID = "sample-igbt-demo"

    def __init__(
        self,
        root: str | Path,
        *,
        pipeline_root: str | Path | None = None,
        sample_root: str | Path | None = None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        self.pipeline_root = (
            Path(pipeline_root).expanduser().resolve(strict=False)
            if pipeline_root is not None
            else None
        )
        self.sample_root = (
            Path(sample_root).expanduser().resolve(strict=False)
            if sample_root is not None
            else None
        )

        self.registry = self.root / "registry.json"
        if not self.registry.exists():
            self.registry.write_text("[]", encoding="utf-8")

        self._frame_cache: dict[str, tuple[str, int, int, pd.DataFrame]] = {}
        self._sync_managed_datasets()

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.registry.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DatasetError(
                f"Dataset registry could not be read: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise DatasetError("Dataset registry must contain a JSON list.")

        return [item for item in data if isinstance(item, dict)]

    def _write(self, data: list[dict]) -> None:
        temporary = self.registry.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.registry)

    def _load(self, path: str | Path) -> pd.DataFrame:
        path = Path(path)

        try:
            suffix = path.suffix.lower()
            if suffix == ".csv":
                return pd.read_csv(path, low_memory=False)
            if suffix in {".xlsx", ".xls"}:
                return pd.read_excel(path)
        except Exception as exc:
            raise DatasetError(f"Dataset could not be read: {exc}") from exc

        raise DatasetError("Only CSV and Excel datasets are supported.")

    def _load_cached(self, dataset_id: str, path: str | Path) -> pd.DataFrame:
        path = Path(path)
        try:
            stat = path.stat()
        except OSError as exc:
            raise DatasetError(f"Dataset file is missing: {exc}") from exc

        signature = (str(path.resolve(strict=False)), stat.st_mtime_ns, stat.st_size)
        cached = self._frame_cache.get(dataset_id)
        if cached is not None and cached[:3] == signature:
            return cached[3]

        df = self._load(path)
        self._frame_cache[dataset_id] = (*signature, df)
        return df

    def invalidate_cache(self, dataset_id: str | None = None) -> None:
        if dataset_id is None:
            self._frame_cache.clear()
        else:
            self._frame_cache.pop(dataset_id, None)

    @staticmethod
    def _metadata(
        df: pd.DataFrame,
        *,
        dataset_id: str,
        filename: str,
        source: str,
        read_only: bool,
        path: Path,
        active: bool = False,
    ) -> dict:
        component_count = 0
        if "component_id" in df.columns:
            component_count = int(df["component_id"].dropna().nunique())

        inspection_mode = "component" if component_count > 0 else "record"
        inspection_count = component_count if component_count > 0 else int(len(df))

        return {
            "dataset_id": dataset_id,
            "filename": filename,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "numeric_columns": int(
                len(df.select_dtypes(include="number").columns)
            ),
            "missing_cells": int(df.isna().sum().sum()),
            "component_count": component_count,
            "inspection_count": inspection_count,
            "inspection_mode": inspection_mode,
            "size_bytes": int(path.stat().st_size),
            "source": source,
            "read_only": bool(read_only),
            "path": str(path) if read_only else None,
            "active": bool(active),
        }

    def _managed_path_original(self) -> Path | None:
        if self.pipeline_root is None:
            return None
        return (
            self.pipeline_root
            / "data"
            / "processed"
            / self.ORIGINAL_FILENAME
        )

    def _managed_path_sample(self) -> Path | None:
        if self.sample_root is None:
            return None
        return self.sample_root / self.SAMPLE_FILENAME

    def _upsert_read_only(
        self,
        rows: list[dict],
        *,
        dataset_id: str,
        filename: str,
        source: str,
        path: Path | None,
    ) -> tuple[list[dict], bool]:
        existing_index = next(
            (
                idx
                for idx, item in enumerate(rows)
                if item.get("dataset_id") == dataset_id
            ),
            None,
        )

        if path is None or not path.exists():
            if existing_index is not None:
                rows.pop(existing_index)
                return rows, True
            return rows, False

        try:
            df = self._load_cached(dataset_id, path)
        except DatasetError:
            if existing_index is not None:
                rows.pop(existing_index)
                return rows, True
            return rows, False

        if df.empty:
            if existing_index is not None:
                rows.pop(existing_index)
                return rows, True
            return rows, False

        active = (
            bool(rows[existing_index].get("active", False))
            if existing_index is not None
            else False
        )
        item = self._metadata(
            df,
            dataset_id=dataset_id,
            filename=filename,
            source=source,
            read_only=True,
            path=path,
            active=active,
        )

        if existing_index is None:
            rows.insert(0, item)
            return rows, True

        if rows[existing_index] != item:
            rows[existing_index] = item
            return rows, True

        return rows, False

    def _sync_managed_datasets(self) -> None:
        rows = self._read()
        changed = False

        rows, local_changed = self._upsert_read_only(
            rows,
            dataset_id=self.ORIGINAL_DATASET_ID,
            filename=self.ORIGINAL_FILENAME,
            source="original_spark_pipeline",
            path=self._managed_path_original(),
        )
        changed = changed or local_changed

        rows, local_changed = self._upsert_read_only(
            rows,
            dataset_id=self.SAMPLE_DATASET_ID,
            filename=self.SAMPLE_FILENAME,
            source="bundled_sample",
            path=self._managed_path_sample(),
        )
        changed = changed or local_changed

        # Remove stale user-upload registry rows whose file no longer exists.
        cleaned: list[dict] = []
        for item in rows:
            if item.get("source") == "user_upload":
                dataset_id = str(item.get("dataset_id", ""))
                path = self._user_file(dataset_id)
                if path is None:
                    changed = True
                    continue
            cleaned.append(item)
        rows = cleaned

        if rows and not any(bool(item.get("active")) for item in rows):
            preferred = next(
                (
                    item
                    for item in rows
                    if item.get("dataset_id") == self.ORIGINAL_DATASET_ID
                ),
                rows[0],
            )
            preferred["active"] = True
            changed = True

        if changed:
            self._write(rows)

    def _user_file(self, dataset_id: str) -> Path | None:
        for path in self.root.glob(dataset_id + ".*"):
            if path.name in {"registry.json", "registry.tmp"}:
                continue
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                return path
        return None

    def save_upload(self, file) -> dict:
        name = SAFE.sub("_", Path(file.filename).name).strip("._")
        suffix = Path(name).suffix.lower()

        if not name or suffix not in SUPPORTED_EXTENSIONS:
            raise DatasetError("Only CSV and Excel datasets are supported.")

        dataset_id = uuid.uuid4().hex
        target = self.root / f"{dataset_id}{suffix}"

        try:
            file.save(target)
            df = self._load_cached(dataset_id, target)
        except DatasetError:
            target.unlink(missing_ok=True)
            raise
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise DatasetError(f"Dataset could not be saved: {exc}") from exc

        if df.empty:
            target.unlink(missing_ok=True)
            raise DatasetError("The dataset contains no records.")

        rows = self._read()
        item = self._metadata(
            df,
            dataset_id=dataset_id,
            filename=name,
            source="user_upload",
            read_only=False,
            path=target,
            active=not any(bool(x.get("active")) for x in rows),
        )
        item.pop("path", None)

        self._write([item] + rows)
        return item

    def list(self) -> list[dict]:
        self._sync_managed_datasets()
        return self._read()

    def get(self, dataset_id: str) -> tuple[dict, pd.DataFrame]:
        for item in self._read():
            if item.get("dataset_id") != dataset_id:
                continue

            if bool(item.get("read_only")):
                path_value = item.get("path")
                if not path_value:
                    raise DatasetError("Read-only dataset path is missing.")
                path = Path(path_value)
            else:
                path = self._user_file(dataset_id)
                if path is None:
                    raise DatasetError("Dataset file is missing.")

            if not path.exists():
                raise DatasetError("Dataset file is missing.")

            return item, self._load_cached(dataset_id, path)

        raise DatasetError("Dataset not found.")

    def activate(self, dataset_id: str) -> dict:
        item, _ = self.get(dataset_id)
        rows = self._read()

        for row in rows:
            row["active"] = row.get("dataset_id") == dataset_id

        self._write(rows)
        return {**item, "active": True}

    def remove(self, dataset_id: str) -> dict:
        item, _ = self.get(dataset_id)

        if bool(item.get("read_only")):
            raise DatasetError("Read-only datasets cannot be removed.")

        path = self._user_file(dataset_id)
        if path is not None:
            path.unlink(missing_ok=True)

        self.invalidate_cache(dataset_id)

        rows = [
            row
            for row in self._read()
            if row.get("dataset_id") != dataset_id
        ]

        if rows and not any(bool(row.get("active")) for row in rows):
            rows[0]["active"] = True

        self._write(rows)
        return {
            "removed": True,
            "dataset_id": dataset_id,
            "filename": item.get("filename"),
        }
