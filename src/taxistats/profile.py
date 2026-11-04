"""Describe the *structure* of an export without revealing its values.

``taxistats profile <export folder>`` prints, for every JSON file, each field
path with how often it occurs, its JSON type(s), what string values look like,
how many distinct values it has, and the longest string length. No value is
ever printed. Use this to compare a real export with the synthetic sample,
or to share an export's shape safely when asking for help.

``tests/test_synthetic_schema.py`` checks the generated sample against such a
report.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

DISTINCT_CAP = 5000

_PATTERNS = [
    ("datetime", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("uuid/hex id", re.compile(r"^[0-9a-f]{24,40}$|^[0-9a-f]{8}-[0-9a-f]{4}-")),
    ("url", re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)),
    ("phone-like", re.compile(r"^\+\d{10,14}$")),
    ("number-as-text", re.compile(r"^-?\d+(?:[.,]\d+)?$")),
]


def looks_like(value: str) -> str:
    for name, rx in _PATTERNS:
        if rx.search(value):
            return name
    return "text"


@dataclass
class FieldStats:
    present: int = 0
    types: set[str] = field(default_factory=set)
    kinds: dict[str, int] = field(default_factory=dict)
    values: set[str] = field(default_factory=set)
    capped: bool = False
    max_len: int = 0

    def add(self, value: Any) -> None:
        self.present += 1
        self.types.add(type(value).__name__)
        if isinstance(value, str):
            k = looks_like(value)
            self.kinds[k] = self.kinds.get(k, 0) + 1
            self.max_len = max(self.max_len, len(value))
        if len(self.values) < DISTINCT_CAP:
            self.values.add(json.dumps(value, sort_keys=True, ensure_ascii=False))
        else:
            self.capped = True

    @property
    def distinct(self) -> str:
        return f">{DISTINCT_CAP}" if self.capped else str(len(self.values))


def walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(path, leaf_value)``; lists add ``[]`` to the path."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, f"{path}[]")
    else:
        yield path, node


def profile_file(path: Path) -> tuple[str, dict[str, FieldStats]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    stats: dict[str, FieldStats] = defaultdict(FieldStats)
    for p, v in walk(payload):
        stats[p].add(v)
    top = f"{type(payload).__name__} with {len(payload)} items, size: {path.stat().st_size // 1024} KB"
    return top, dict(sorted(stats.items()))


def render_markdown(folder: Path) -> str:
    files = sorted(folder.glob("*.json"))
    lines = [f"# Export structure ({len(files)} files)", ""]
    for f in files:
        top, stats = profile_file(f)
        lines += [f"## {f.name}", "", f"- format: json, top level: {top}", "",
                  "| field path | present | type(s) | looks like | distinct | max len |",
                  "|---|---|---|---|---|---|"]
        for p, s in stats.items():
            kinds = ", ".join(sorted(s.kinds, key=lambda k: -s.kinds[k])) or "-"  # most common first
            max_len = str(s.max_len) if s.max_len else "-"
            lines.append(f"| `{p}` | {s.present} | {', '.join(sorted(s.types))} | {kinds} | {s.distinct} | {max_len} |")
        lines.append("")
    return "\n".join(lines)


def parse_markdown(text: str) -> dict[str, dict[str, dict[str, str]]]:
    """Parse a report produced by :func:`render_markdown` back into ``{file: {path: row}}``."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = {}
        elif current and line.startswith("| `"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out[current][cells[0].strip("`")] = dict(zip(
                ["present", "types", "looks_like", "distinct", "max_len"], cells[1:]))
    return out
