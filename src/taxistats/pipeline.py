"""End-to-end run: load → (optionally anonymise) → stats → write outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import dashboard
from .load import load_exports
from .stats import compute_all, to_frame


def anonymise(df: pd.DataFrame) -> pd.DataFrame:
    """Replace driver names and plates with stable pseudonyms (order of first appearance).

    Repeat-driver analysis still works because the mapping is consistent within a run.
    Use this before sharing a dashboard built from real data.
    """
    df = df.sort_values("utc_time").copy()
    for col, prefix in (("driver_name", "Driver"), ("car_plate", "CAR")):
        codes = {v: f"{prefix} {i + 1:03d}" for i, v in enumerate(df[col].dropna().unique())}
        df[col] = df[col].map(codes)
    return df


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return [_jsonable(r) for r in obj.reset_index().to_dict(orient="records")]
    if isinstance(obj, dict):
        return {str(_jsonable(k)): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, pd.Period)):
        return str(obj)
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj


@dataclass
class RunResult:
    rides: pd.DataFrame
    stats: dict[str, Any]
    report: dict[str, Any]
    outputs: dict[str, Path]


def run(inputs: Iterable[str | Path], out_dir: str | Path, *, anonymise_drivers: bool = False,
        title: str = "Ride history", note: str = "") -> RunResult:
    rides, report = load_exports(inputs)
    df = to_frame(rides)
    if anonymise_drivers:
        df = anonymise(df)
    results = compute_all(df)
    rep = report.as_dict()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "rides_csv": out / "rides.csv",
        "summary_json": out / "summary.json",
        "dashboard": out / "dashboard.html",
    }
    export_cols = [c for c in df.columns if c not in ("month", "year", "month_of_year", "weekday", "hour")]
    df[export_cols].to_csv(paths["rides_csv"], index=False)
    paths["summary_json"].write_text(
        json.dumps(_jsonable({"load_report": rep, "rejected": report.rejected, **results}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["dashboard"].write_text(dashboard.render(results, rep, title=title, note=note), encoding="utf-8")
    return RunResult(df, results, rep, paths)
