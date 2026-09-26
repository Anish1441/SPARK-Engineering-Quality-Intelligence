from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def resolve_inspection_target(
    df: pd.DataFrame,
    inspection_index: int,
) -> dict[str, Any]:
    """Map a QA inspection index to a representative source-row position.

    For long-form burn-in data with component_id, one QA item represents one
    component. The representative source row is the 24h row when available;
    otherwise the latest finite checkpoint at or before 24h is used, then the
    component's first row as a final fallback.

    Generic datasets without component_id keep record-level navigation.
    """
    if "component_id" in df.columns:
        component_series = df["component_id"].astype("string")
        components = component_series.dropna().drop_duplicates().tolist()

        if components:
            if inspection_index < 0 or inspection_index >= len(components):
                raise IndexError("Inspection index is out of range.")

            component_id = components[inspection_index]
            mask = component_series.eq(component_id).fillna(False).to_numpy()
            positions = np.flatnonzero(mask)
            if len(positions) == 0:
                raise IndexError("Component has no source rows.")

            representative = int(positions[0])

            if "measurement_time_h" in df.columns:
                times = pd.to_numeric(
                    df.iloc[positions]["measurement_time_h"],
                    errors="coerce",
                ).to_numpy(dtype=float, na_value=np.nan)

                exact_24 = np.flatnonzero(
                    np.isclose(times, 24.0, equal_nan=False)
                )
                if len(exact_24):
                    representative = int(positions[int(exact_24[0])])
                else:
                    eligible = np.flatnonzero(
                        np.isfinite(times) & (times <= 24.0)
                    )
                    if len(eligible):
                        chosen = eligible[np.argmax(times[eligible])]
                        representative = int(positions[int(chosen)])

            return {
                "inspection_index": int(inspection_index),
                "inspection_count": int(len(components)),
                "inspection_mode": "component",
                "record_index": representative,
                "component_id": str(component_id),
            }

    if inspection_index < 0 or inspection_index >= len(df):
        raise IndexError("Inspection index is out of range.")

    return {
        "inspection_index": int(inspection_index),
        "inspection_count": int(len(df)),
        "inspection_mode": "record",
        "record_index": int(inspection_index),
        "component_id": None,
    }
