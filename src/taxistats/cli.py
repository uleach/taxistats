"""Command-line interface.

    taxistats sample  [--out data/sample] [--seed 42]
    taxistats run     INPUT [INPUT ...] [--out output] [--anonymise]
    taxistats profile EXPORT_FOLDER [--out report.md]
"""

from __future__ import annotations

import argparse
import logging
import sys

from pathlib import Path

from .pipeline import run
from .profile import render_markdown
from .synthetic import write_sample


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="taxistats", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true", help="log every skipped record")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="write the synthetic sample dataset")
    s.add_argument("--out", default="data/sample")
    s.add_argument("--seed", type=int, default=42)

    r = sub.add_parser("run", help="merge exports, compute stats, build the dashboard")
    r.add_argument("inputs", nargs="+", help="export .json files or folders containing them")
    r.add_argument("--out", default="output", help="output folder (git-ignored by default)")
    r.add_argument("--anonymise", action="store_true", help="replace driver names and plates with pseudonyms")
    r.add_argument("--title", default="Ride history")

    pr = sub.add_parser("profile", help="print the structure of an export folder (field paths, types; no values)")
    pr.add_argument("folder")
    pr.add_argument("--out", help="write the report to this file instead of stdout")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.ERROR, format="%(levelname)s %(message)s")

    if a.cmd == "sample":
        for path in write_sample(a.out, a.seed):
            print(f"wrote {path}")
        return 0

    if a.cmd == "profile":
        report = render_markdown(Path(a.folder))
        if a.out:
            Path(a.out).write_text(report + "\n", encoding="utf-8")
            print(f"wrote {a.out}")
        else:
            print(report)
        return 0

    try:
        res = run(a.inputs, a.out, anonymise_drivers=a.anonymise, title=a.title)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rep, ov = res.report, res.stats["overview"]
    print(f"{len(rep['files'])} files, {rep['raw_records']} records -> {rep['unique_rides']} unique orders "
          f"({rep['duplicates_removed']} duplicates merged, {rep['conflicts']} conflicts, {rep['rejected']} rejected)")
    print(f"{ov['completed']} completed rides, total {_fmt(ov['total_spend'])} {ov['currency'] or ''}, "
          f"avg {_fmt(ov['mean_cost'])}")
    for name, path in res.outputs.items():
        print(f"  {name:13} {path}")
    return 0
