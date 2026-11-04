"""Discover export files, extract their records, and merge them into one ride list.

Why de-duplication is needed
----------------------------
Ride-history exports are typically requested more than once (say, every few
months), and each export covers an overlapping window. The same order
therefore appears in several files — sometimes with *more* detail in a later
export (driver details filled in, a final cost instead of an estimate).

Strategy
--------
1. **Primary key: order id.** Records sharing an id are the same ride.
2. **Fallback key: fingerprint** = (UTC instant to the minute, tariff, cost).
   Used for records with no id, and to attach an id-less copy to an id'd ride.
   UTC — not local time — so the same instant written as ``+0600`` in one file
   and ``+05:00`` in another still collides.
3. **Field-level coalescing.** Rather than "keep the first copy", duplicates
   are ranked by completeness (number of populated fields, then file order so
   later exports win ties) and each field takes the first non-empty value.
   Disagreements on a populated field are counted as *conflicts* and reported.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from .schema import RecordError, Ride, parse_record

log = logging.getLogger(__name__)

# Keys under which a list of orders may be nested in an export file.
CONTAINER_KEYS = ("orders", "rides", "trips", "items", "data", "history", "results")

# Fields that should NOT be compared when looking for conflicts.
_META_FIELDS = {"source_file"}


@dataclass
class LoadReport:
    files: list[str] = field(default_factory=list)
    raw_records: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (file, reason)
    duplicates_removed: int = 0
    conflicts: int = 0
    unique_rides: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "raw_records": self.raw_records,
            "rejected": len(self.rejected),
            "duplicates_removed": self.duplicates_removed,
            "conflicts": self.conflicts,
            "unique_rides": self.unique_rides,
        }


# --------------------------------------------------------------------------
# Discovery & extraction
# --------------------------------------------------------------------------

def discover_files(paths: Iterable[str | Path]) -> list[Path]:
    """Expand files and directories (recursively) into a sorted list of ``*.json`` files."""
    found: set[Path] = set()
    for p in map(Path, paths):
        if p.is_dir():
            found.update(x for x in p.rglob("*.json") if x.is_file())
        elif p.is_file():
            found.add(p)
        else:
            raise FileNotFoundError(p)
    return sorted(found)


def extract_records(payload: Any) -> Iterator[dict[str, Any]]:
    """Yield order-like dicts from a decoded JSON document of unknown nesting.

    Accepts a bare list, ``{"orders": [...]}``, ``{"data": {"orders": [...]}}``
    and a single order object.
    """
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        for key in CONTAINER_KEYS:
            if key in payload and isinstance(payload[key], (list, dict)):
                yield from extract_records(payload[key])
                return
        yield payload


def read_file(path: Path, report: LoadReport) -> list[Ride]:
    with path.open(encoding="utf-8-sig") as fh:  # -sig tolerates a BOM
        payload = json.load(fh)
    rides: list[Ride] = []
    for rec in extract_records(payload):
        report.raw_records += 1
        try:
            rides.append(parse_record(rec, source_file=path.name))
        except RecordError as exc:
            report.rejected.append((path.name, str(exc)))
            log.warning("%s: skipped record: %s", path.name, exc)
    return rides


# --------------------------------------------------------------------------
# Merge & de-duplicate
# --------------------------------------------------------------------------

def fingerprint(ride: Ride) -> tuple[Any, ...]:
    minute = ride.utc_time.replace(second=0, microsecond=0)
    cost = round(ride.cost) if ride.cost is not None else None
    return (minute, ride.tariff, cost)


def _completeness(ride: Ride) -> int:
    return sum(getattr(ride, f.name) is not None for f in fields(Ride))


def coalesce(copies: list[tuple[int, Ride]]) -> tuple[Ride, int]:
    """Merge copies of one ride. ``copies`` holds ``(file_rank, ride)``.

    Returns the merged ride and the number of conflicting fields.
    """
    ranked = [r for _, r in sorted(copies, key=lambda c: (_completeness(c[1]), c[0]), reverse=True)]
    best = ranked[0]
    updates: dict[str, Any] = {}
    conflicts = 0
    for f in fields(Ride):
        if f.name in _META_FIELDS:
            continue
        values = [getattr(r, f.name) for r in ranked if getattr(r, f.name) is not None]
        if not values:
            continue
        if getattr(best, f.name) is None:
            updates[f.name] = values[0]
        if len(set(map(repr, values))) > 1:
            conflicts += 1
    sources = sorted({r.source_file for r in ranked})
    updates["source_file"] = ";".join(sources)
    return replace(best, **updates), conflicts


def merge_rides(per_file: list[list[Ride]], report: LoadReport | None = None) -> list[Ride]:
    """Merge rides from several files (given in priority order, oldest first)."""
    report = report or LoadReport()
    groups: dict[Any, list[tuple[int, Ride]]] = defaultdict(list)
    id_by_fp: dict[tuple[Any, ...], str] = {}
    orphans: list[tuple[int, Ride]] = []

    for rank, rides in enumerate(per_file):
        for ride in rides:
            if ride.order_id:
                groups[("id", ride.order_id)].append((rank, ride))
                id_by_fp.setdefault(fingerprint(ride), ride.order_id)
            else:
                orphans.append((rank, ride))

    # Second pass so an id-less copy can attach to an id'd ride from a later file.
    for rank, ride in orphans:
        fp = fingerprint(ride)
        key = ("id", id_by_fp[fp]) if fp in id_by_fp else ("fp", fp)
        groups[key].append((rank, ride))

    merged: list[Ride] = []
    for copies in groups.values():
        ride, conflicts = coalesce(copies)
        merged.append(ride)
        report.duplicates_removed += len(copies) - 1
        report.conflicts += conflicts

    merged.sort(key=lambda r: r.utc_time)
    report.unique_rides = len(merged)
    return merged


def load_exports(paths: Iterable[str | Path]) -> tuple[list[Ride], LoadReport]:
    """Discover, parse, merge and de-duplicate every export under ``paths``."""
    report = LoadReport()
    files = discover_files(paths)
    if not files:
        raise FileNotFoundError("no .json export files found")
    per_file = []
    for path in files:
        report.files.append(path.name)
        per_file.append(read_file(path, report))
    rides = merge_rides(per_file, report)
    log.info(
        "loaded %d records from %d files -> %d unique rides (%d duplicates, %d rejected)",
        report.raw_records, len(files), report.unique_rides, report.duplicates_removed, len(report.rejected),
    )
    return rides, report
