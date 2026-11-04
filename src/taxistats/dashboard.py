"""Render the statistics as a single self-contained HTML file.

Design choices
--------------
* **Zero external requests.** Charts are inline SVG generated here; CSS and the
  tiny tooltip script are inline. The dashboard can be opened offline and
  never leaks that you are viewing personal data to a CDN.
* **Every chart has a table.** Hover tooltips enhance but never gate: each
  value plotted is also in a table beneath it.
* **Light and dark themes** come from CSS custom properties, switched by
  ``prefers-color-scheme``.
* **All user data is HTML-escaped**, including driver names, since exports are
  untrusted input.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Callable, Sequence

import pandas as pd

# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fmt_num(x: Any, digits: int = 0) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.{digits}f}".replace(",", " ")


def fmt_money(x: Any, currency: str | None) -> str:
    s = fmt_num(x)
    return s if s == "—" or not currency else f"{s} {currency}"


def fmt_date(x: Any, with_time: bool = False) -> str:
    if x is None or pd.isna(x):
        return "—"
    return pd.Timestamp(x).strftime("%d %b %Y %H:%M" if with_time else "%d %b %Y")


def fmt_label(x: Any) -> str:
    if isinstance(x, pd.Period):
        return x.strftime("%b %Y")
    return str(x)


# --------------------------------------------------------------------------
# SVG charts
# --------------------------------------------------------------------------

def _nice_ticks(vmax: float, n: int = 4) -> list[float]:
    if vmax <= 0:
        return [0.0]
    raw = vmax / n
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [step * i for i in range(n + 2) if step * i <= vmax * 1.0001 + step][: n + 2]


def _top_rounded_bar(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    if h <= 0:
        return ""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    tip: Callable[[int], str],
    label_every: int = 1,
    tick_fmt: Callable[[float], str] = fmt_num,
    title: str,
    width: int = 920,
    height: int = 240,
) -> str:
    """Vertical bars anchored to a zero baseline, one series."""
    ml, mr, mt, mb = 56, 8, 12, 30
    pw, ph = width - ml - mr, height - mt - mb
    vals = [0.0 if v is None or pd.isna(v) else float(v) for v in values]
    ticks = _nice_ticks(max(vals) if vals else 0)
    top = ticks[-1] or 1
    n = max(len(vals), 1)
    slot = pw / n
    gap = 2 if slot > 6 else 1
    bw = max(slot - gap, 1)

    cls = "chart wide" if n > 24 else "chart"
    parts = [f'<div class="scroll"><svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" class="{cls}">']
    for t in ticks:
        y = mt + ph - t / top * ph
        parts.append(f'<line class="grid" x1="{ml}" x2="{width - mr}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{ml - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(tick_fmt(t))}</text>')
    for i, (lab, v) in enumerate(zip(labels, vals)):
        x = ml + i * slot + gap / 2
        h = v / top * ph
        y = mt + ph - h
        tip_text = escape(tip(i), quote=True)
        # Hit target spans the full plot height so short bars are still easy to hover.
        parts.append(f'<g class="hit" data-tip="{tip_text}" tabindex="0">'
                     f'<rect class="hitbox" x="{ml + i * slot:.1f}" y="{mt}" width="{slot:.1f}" height="{ph}"/>')
        if h > 0:
            parts.append(f'<path class="bar" d="{_top_rounded_bar(x, y, bw, h)}"/>')
        parts.append("</g>")
        if i % label_every == 0:
            parts.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{height - 10}" text-anchor="middle">{escape(lab)}</text>')
    parts.append(f'<line class="axis" x1="{ml}" x2="{width - mr}" y1="{mt + ph}" y2="{mt + ph}"/>')
    parts.append("</svg></div>")
    return "".join(parts)


def hbar_chart(labels: Sequence[str], values: Sequence[float], *, tip: Callable[[int], str],
               value_fmt: Callable[[float], str], title: str, width: int = 440) -> str:
    """Horizontal bars with direct value labels — for a handful of categories."""
    row, ml, mr = 30, 92, 92
    height = row * len(labels) + 8
    vmax = max([float(v) for v in values] or [1]) or 1
    pw = width - ml - mr
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" class="chart">']
    for i, (lab, v) in enumerate(zip(labels, values)):
        y = 4 + i * row
        w = float(v) / vmax * pw
        r = min(4, w / 2, (row - 10) / 2)
        parts.append(f'<g class="hit" data-tip="{escape(tip(i), quote=True)}" tabindex="0">'
                     f'<rect class="hitbox" x="0" y="{y}" width="{width}" height="{row}"/>'
                     f'<text class="lab" x="{ml - 10}" y="{y + row / 2 + 4}" text-anchor="end">{escape(lab)}</text>')
        if w > 0:
            parts.append(f'<path class="bar" d="M{ml},{y + 5}H{ml + w - r:.1f}Q{ml + w:.1f},{y + 5} {ml + w:.1f},{y + 5 + r:.1f}'
                         f'V{y + row - 5 - r:.1f}Q{ml + w:.1f},{y + row - 5} {ml + w - r:.1f},{y + row - 5}H{ml}Z"/>')
        parts.append(f'<text class="val" x="{ml + w + 8:.1f}" y="{y + row / 2 + 4}">{escape(value_fmt(v))}</text></g>')
    parts.append(f'<line class="axis" x1="{ml}" x2="{ml}" y1="0" y2="{height}"/></svg>')
    return "".join(parts)


# --------------------------------------------------------------------------
# HTML building blocks
# --------------------------------------------------------------------------

def table(df: pd.DataFrame, columns: dict[str, tuple[str, Callable[[Any], str]]], *, index_label: str | None = None,
          index_fmt: Callable[[Any], str] = fmt_label, max_rows: int | None = None, numeric: set[str] | None = None) -> str:
    """Render a DataFrame. ``columns`` maps column -> (header, formatter)."""
    if df is None or df.empty:
        return '<p class="muted">No data.</p>'
    numeric = numeric if numeric is not None else set(columns)
    rows = df if max_rows is None else df.head(max_rows)
    head = (f"<th>{escape(index_label)}</th>" if index_label else "") + "".join(
        f'<th class="{"num" if c in numeric else ""}">{escape(h)}</th>' for c, (h, _) in columns.items())
    body = []
    for idx, r in rows.iterrows():
        cells = (f"<td>{escape(index_fmt(idx))}</td>" if index_label else "") + "".join(
            f'<td class="{"num" if c in numeric else ""}">{escape(f(r[c]))}</td>' for c, (_, f) in columns.items())
        body.append(f"<tr>{cells}</tr>")
    more = "" if max_rows is None or len(df) <= max_rows else f'<p class="muted">Showing {max_rows} of {len(df)}.</p>'
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


def details(summary: str, inner: str) -> str:
    return f"<details><summary>{escape(summary)}</summary>{inner}</details>"


def tile(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="tile"><div class="tile-label">{escape(label)}</div>'
            f'<div class="tile-value">{escape(value)}</div>'
            + (f'<div class="tile-sub">{escape(sub)}</div>' if sub else "") + "</div>")


def highlight_block(title: str, hl: dict[str, Any], currency: str | None, unit: str) -> str:
    if not hl:
        return ""
    rows = []
    spec = [
        ("rides", "Rides", lambda v: fmt_num(v)),
        ("spend", "Spend", lambda v: fmt_money(v, currency)),
        ("cost_mean", "Avg fare", lambda v: fmt_money(v, currency)),
        ("wait_min_mean", "Avg wait (min)", lambda v: fmt_num(v, 1)),
        ("duration_min_mean", "Avg trip (min)", lambda v: fmt_num(v, 1)),
    ]
    for key, label, f in spec:
        if key not in hl:
            continue
        h = hl[key]
        rows.append(
            f"<tr><th scope='row'>{escape(label)}</th>"
            f"<td><span class='hl-key'>{escape(fmt_label(h['most'][0]))}</span> {escape(f(h['most'][1]))}</td>"
            f"<td class='num'>{escape(f(h['average']))}</td>"
            f"<td><span class='hl-key'>{escape(fmt_label(h['least'][0]))}</span> {escape(f(h['least'][1]))}</td></tr>")
    return (f'<div class="card"><h3>{escape(title)}</h3><div class="tablewrap"><table class="hl">'
            f"<thead><tr><th></th><th>Most</th><th class='num'>Average / {escape(unit)}</th><th>Least</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div></div>")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

CSS = """
:root{color-scheme:light;--bg:#f6f5f2;--surface:#fcfcfb;--border:#e4e2dc;--text:#0b0b0b;--text-2:#52514e;
--muted:#77756f;--grid:#ebe9e4;--axis:#c9c7c0;--series:#2a78d6;--series-hover:#1c5cab;--tip-bg:#0b0b0b;--tip-text:#fcfcfb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--border:#2e2e2b;--text:#f0efec;--text-2:#c3c2b7;--muted:#97968e;--grid:#2a2a28;--axis:#4a4a46;--series:#3987e5;
--series-hover:#86b6ef;--tip-bg:#f0efec;--tip-text:#121211}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--border:#2e2e2b;--text:#f0efec;--text-2:#c3c2b7;
--muted:#97968e;--grid:#2a2a28;--axis:#4a4a46;--series:#3987e5;--series-hover:#86b6ef;--tip-bg:#f0efec;--tip-text:#121211}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:19px;margin:40px 0 12px}
h3{font-size:15px;margin:0 0 10px;color:var(--text-2);font-weight:600}
p{margin:0 0 12px}.muted{color:var(--muted);font-size:13px}
.banner{border:1px solid var(--border);background:var(--surface);border-radius:8px;padding:10px 14px;margin:16px 0;font-size:13px;color:var(--text-2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.tile,.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile-label{font-size:12px;color:var(--text-2);text-transform:uppercase;letter-spacing:.04em}
.tile-value{font-size:24px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.tile-sub{font-size:12px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:16px}
.card{margin-bottom:16px;min-width:0}
.chart{width:100%;height:auto;display:block;overflow:visible}
.chart .bar{fill:var(--series)}.chart .hit:hover .bar,.chart .hit:focus .bar{fill:var(--series-hover)}
.chart .hitbox{fill:transparent}.chart .hit{outline:none;cursor:default}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.chart .lab{fill:var(--text-2);font-size:13px}.chart .val{fill:var(--text);font-size:13px;font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto;margin-top:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
th{color:var(--text-2);font-weight:600}td.num,th.num{text-align:right}
table.hl td{white-space:nowrap;vertical-align:top}.hl-key{display:block;color:var(--muted);font-size:12px}
.scroll{overflow-x:auto}.scroll .chart.wide{min-width:640px}
details{margin-top:8px}summary{cursor:pointer;color:var(--text-2);font-size:13px}
#tip{position:fixed;pointer-events:none;background:var(--tip-bg);color:var(--tip-text);padding:6px 9px;border-radius:6px;
font-size:12px;line-height:1.4;white-space:pre;opacity:0;transition:opacity .08s;z-index:10;max-width:280px}
footer{margin-top:48px;font-size:12px;color:var(--muted)}
"""

JS = """
(()=>{const t=document.getElementById('tip');
function show(e,el){t.textContent=el.dataset.tip;t.style.opacity=1;
 const r=el.getBoundingClientRect(),x=e&&e.clientX!=null?e.clientX:r.left+r.width/2,y=e&&e.clientY!=null?e.clientY:r.top;
 const w=t.offsetWidth;t.style.left=Math.min(Math.max(8,x-w/2),innerWidth-w-8)+'px';t.style.top=Math.max(8,y-t.offsetHeight-12)+'px';}
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('pointermove',e=>show(e,el));el.addEventListener('focus',()=>show(null,el));
 el.addEventListener('pointerleave',()=>t.style.opacity=0);el.addEventListener('blur',()=>t.style.opacity=0);});})();
"""


def render(results: dict[str, Any], report: dict[str, Any], *, title: str = "Ride history", note: str = "") -> str:
    ov = results["overview"]
    cur = ov["currency"]
    tables = results["tables"]
    money = lambda v: fmt_money(v, cur)  # noqa: E731
    dur = lambda v: fmt_num(v, 1)  # noqa: E731
    drv = results["drivers"]

    group_cols = {
        "rides": ("Rides", fmt_num),
        "share": ("Share", lambda v: f"{v:.0%}"),
        "spend": ("Spend", money),
        "cost_min": ("Min fare", money),
        "cost_mean": ("Avg fare", money),
        "cost_max": ("Max fare", money),
        "wait_min_mean": ("Avg wait", dur),
        "wait_min_max": ("Max wait", dur),
        "duration_min_mean": ("Avg trip", dur),
        "duration_min_max": ("Max trip", dur),
    }

    # ---- monthly charts
    m = tables["month"]
    mlabels = [p.strftime("%b") if p.month != 1 else str(p.year) for p in m.index]
    every = 1 if len(m) <= 18 else 3
    mlabels = [lab if (p.month - 1) % every == 0 else "" for lab, p in zip(mlabels, m.index)]
    month_tip = lambda i: (f"{fmt_label(m.index[i])}\n{fmt_num(m['rides'].iat[i])} rides · "  # noqa: E731
                           f"{money(m['spend'].iat[i])}\navg fare {money(m['cost_mean'].iat[i])}")
    rides_chart = bar_chart(mlabels, m["rides"].tolist(), tip=month_tip, title="Rides per month")
    spend_chart = bar_chart(mlabels, m["spend"].tolist(), tip=month_tip, title="Spend per month",
                            tick_fmt=lambda v: fmt_num(v / 1000) + "k" if v else "0")

    # ---- tariff
    t = tables["tariff"]
    tariff_tip = lambda i: (f"{t.index[i]}\n{fmt_num(t['rides'].iat[i])} rides ({t['share'].iat[i]:.0%})\n"  # noqa: E731
                            f"avg fare {money(t['cost_mean'].iat[i])}")
    tariff_rides = hbar_chart(list(t.index), t["rides"].tolist(), tip=tariff_tip, value_fmt=fmt_num, title="Rides by tariff")
    tariff_fare = hbar_chart(list(t.index), t["cost_mean"].fillna(0).tolist(), tip=tariff_tip, value_fmt=money,
                             title="Average fare by tariff")

    # ---- year
    y = tables["year"]
    year_tip = lambda i: f"{y.index[i]}\n{fmt_num(y['rides'].iat[i])} rides · {money(y['spend'].iat[i])}"  # noqa: E731
    year_chart = hbar_chart([str(i) for i in y.index], y["spend"].tolist(), tip=year_tip, value_fmt=money, title="Spend by year",
                             width=920)

    # ---- weekday / hour
    w = tables["weekday"]
    wd_chart = bar_chart([d[:3] for d in w.index], w["rides"].tolist(), height=200, title="Rides by weekday",
                         tip=lambda i: f"{w.index[i]}\n{fmt_num(w['rides'].iat[i])} rides · avg wait {dur(w['wait_min_mean'].iat[i])} min")
    h = tables["hour"].reindex(range(24)).fillna({"rides": 0})
    hr_chart = bar_chart([f"{i:02d}" for i in h.index], h["rides"].tolist(), height=200, label_every=3, title="Rides by hour",
                         tip=lambda i: f"{i:02d}:00–{i:02d}:59\n{fmt_num(h['rides'].iat[i])} rides · avg wait {dur(h['wait_min_mean'].iat[i])} min")

    # ---- extremes
    ex_rows = []
    for label, e in results["extremes"].items():
        f = money if label == "cost" else (lambda v: f"{fmt_num(v, 1)} min")
        ex_rows.append(
            f"<tr><th scope='row'>{escape(label.capitalize())}</th>"
            f"<td class='num'>{escape(f(e['max']['value']))}</td><td>{escape(fmt_date(e['max']['when'], True))} · {escape(e['max']['tariff'])}</td>"
            f"<td class='num'>{escape(f(e['mean']))}</td><td class='num'>{escape(f(e['median']))}</td>"
            f"<td class='num'>{escape(f(e['min']['value']))}</td><td>{escape(fmt_date(e['min']['when'], True))} · {escape(e['min']['tariff'])}</td></tr>")
    extremes = ("<div class='tablewrap'><table><thead><tr><th></th><th class='num'>Highest</th><th>When</th>"
                "<th class='num'>Mean</th><th class='num'>Median</th><th class='num'>Lowest</th><th>When</th></tr></thead>"
                f"<tbody>{''.join(ex_rows)}</tbody></table></div>")

    rd = results["repeat_drivers"]
    rc = results["repeat_cars"]
    rn = results["repeat_driver_names"]
    rd_cols = {"driver_name": ("Driver", str), "car_model": ("Car", lambda v: v or "—"), "car_plate": ("Plate", str),
               "rides": ("Rides", fmt_num), "first_seen": ("First", fmt_date), "last_seen": ("Last", fmt_date),
               "span_days": ("Span (days)", fmt_num), "tariffs": ("Tariffs", str)}
    rc_cols = {"car_plate": ("Plate", str), "car_model": ("Model", lambda v: v or "—"), "car_color": ("Colour", lambda v: v or "—"),
               "rides": ("Rides", fmt_num), "drivers": ("Driver(s)", str), "first_seen": ("First", fmt_date),
               "last_seen": ("Last", fmt_date), "span_days": ("Span (days)", fmt_num)}
    rn_cols = {"driver_name": ("Name", str), "rides": ("Rides", fmt_num), "distinct_cars": ("Distinct cars", fmt_num),
               "first_seen": ("First", fmt_date), "last_seen": ("Last", fmt_date)}
    num = {"rides", "span_days", "distinct_cars"}

    currency_note = ""
    if len(ov["currencies"]) > 1:
        currency_note = (f'<div class="banner">Several currencies found ({", ".join(ov["currencies"])}). Money figures use '
                         f'{cur} only; {ov["excluded_other_currency"]} rides in other currencies are excluded from them.</div>')
    offsets = ", ".join(f"{k}: {v}" for k, v in ov["utc_offsets"].items())

    body = f"""
<main>
<h1>{escape(title)}</h1>
<p class="muted">{escape(fmt_date(ov['first_ride']))} – {escape(fmt_date(ov['last_ride']))} · all times are local wall-clock time as recorded ({escape(offsets)})</p>
{f'<div class="banner">{escape(note)}</div>' if note else ''}
{currency_note}
<div class="tiles">
{tile("Completed rides", fmt_num(ov['completed']), f"{ov['cancelled_or_other']} cancelled/other")}
{tile("Total spend", money(ov['total_spend']))}
{tile("Average fare", money(ov['mean_cost']), f"median {money(ov['median_cost'])}")}
{tile("Average wait", f"{fmt_num(ov['mean_wait_min'], 1)} min")}
{tile("Average trip", f"{fmt_num(ov['mean_duration_min'], 1)} min", f"{fmt_num(ov['total_ride_hours'])} h in total")}
{tile("Repeat drivers", fmt_num(drv['repeat_drivers']), f"of {fmt_num(drv['distinct_drivers'])} identified")}
</div>

<h2>Over time</h2>
<div class="card"><h3>Rides per month</h3>{rides_chart}</div>
<div class="card"><h3>Spend per month ({escape(cur or '')})</h3>{spend_chart}
{details("Monthly table", table(m.iloc[::-1], group_cols, index_label="Month"))}</div>

<h2>Most, average and least</h2>
<p class="muted">Months and years with no rides count as zero, so an empty month can be the “least”.</p>
<div class="grid2">
{highlight_block("By tariff", results['highlights']['tariff'], cur, "tariff")}
{highlight_block("By year", results['highlights']['year'], cur, "year")}
</div>
{highlight_block("By month", results['highlights']['month'], cur, "month")}

<h2>Tariffs</h2>
<div class="grid2">
<div class="card"><h3>Rides by tariff</h3>{tariff_rides}</div>
<div class="card"><h3>Average fare by tariff</h3>{tariff_fare}</div>
</div>
<div class="card">{table(t, group_cols, index_label="Tariff")}</div>

<h2>Years</h2>
<div class="card"><h3>Spend by year</h3>{year_chart}{table(y, group_cols, index_label="Year")}</div>

<h2>When I ride</h2>
<div class="grid2">
<div class="card"><h3>By weekday</h3>{wd_chart}</div>
<div class="card"><h3>By hour of day</h3>{hr_chart}</div>
</div>

<h2>Individual rides</h2>
<div class="card">{extremes}</div>

<h2>Drivers and cars</h2>
<p class="muted">Driver details are present on {fmt_num(drv['rides_with_driver'])} of {fmt_num(ov['completed'])} completed rides
({drv['share_with_driver']:.0%}). {fmt_num(drv['rides_with_repeat_driver'])} of those rides were with a driver who appears on more than one ride.
A repeat driver is matched on name <em>and</em> plate; name-only matches are weaker because display names collide.</p>
<div class="tiles">
{tile("Identified drivers", fmt_num(drv['distinct_drivers']))}
{tile("Repeat drivers", fmt_num(drv['repeat_drivers']))}
{tile("Distinct cars", fmt_num(drv['distinct_cars']))}
{tile("Repeat cars", fmt_num(drv['repeat_cars']))}
</div>
<div class="card" style="margin-top:16px"><h3>Repeat drivers (name + plate)</h3>{table(rd, rd_cols, numeric=num, max_rows=25)}</div>
<div class="card"><h3>Repeat cars (by plate)</h3>{table(rc, rc_cols, numeric=num, max_rows=25)}</div>
<div class="grid2">
<div class="card"><h3>Repeat driver names (any car)</h3>{table(rn, rn_cols, numeric=num, max_rows=15)}</div>
<div class="card"><h3>Most common car models</h3>{table(results['models'], {"car_model": ("Model", str), "rides": ("Rides", fmt_num), "distinct_cars": ("Distinct cars", fmt_num)}, numeric=num)}</div>
</div>

<h2>Data quality</h2>
<div class="card">
<p>{len(report['files'])} export files · {fmt_num(report['raw_records'])} raw records → <strong>{fmt_num(report['unique_rides'])} unique orders</strong>.
{fmt_num(report['duplicates_removed'])} duplicates merged, {fmt_num(report['conflicts'])} field conflicts resolved, {fmt_num(report['rejected'])} records rejected.</p>
<p class="muted">Files: {escape(', '.join(report['files']))}</p>
</div>

<footer>Generated {datetime.now():%d %b %Y %H:%M} by taxistats. Self-contained; makes no network requests.</footer>
</main>
<div id="tip" role="tooltip"></div>
"""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body>{body}<script>{JS}</script></body></html>")
