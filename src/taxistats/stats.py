"""Descriptive statistics over the merged ride table.

Every function takes the DataFrame from :func:`to_frame` and returns plain
pandas objects or dicts, so results can be rendered to HTML, written as JSON,
or inspected in a notebook.

Methodological choices
----------------------
* **Only completed rides are analysed.** Cancelled orders have no meaningful
  cost/duration; they are counted separately in :func:`overview`.
* **Calendar gaps count.** For month/year breakdowns the index is reindexed
  over the full span, so a month with zero rides is a real "least" month
  rather than being invisible.
* **Cost aggregates use one currency.** Summing tenge and roubles is
  meaningless; if several currencies occur, money stats are restricted to the
  most common one and :func:`overview` says so.
* **Identity of drivers is approximate.** The export gives a driver's name
  on only a minority of rides, and names can collide. A *repeat driver* is
  therefore keyed on name **plus** plate; name-only matches are reported
  separately as weaker evidence. The vehicle is present on every ride, so
  repeat *cars* (by plate) are the more complete signal.
* **Missing metrics are absent, not zero.** If a field never occurs in the
  export (Yandex Go has no wait time), its columns are all-NaN and the
  dashboard hides them.
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .schema import Ride

METRICS = {"cost": "cost", "wait_min": "wait (min)", "duration_min": "trip (min)", "surge": "surge"}


def to_frame(rides: Iterable[Ride]) -> pd.DataFrame:
    df = pd.DataFrame([r.to_dict() for r in rides], columns=Ride.columns())
    df["local_time"] = pd.to_datetime(df["local_time"])
    df["utc_time"] = pd.to_datetime(df["utc_time"], utc=True)
    for col in ("cost", "wait_min", "duration_min", "surge"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["year"] = df["local_time"].dt.year
    df["month"] = df["local_time"].dt.to_period("M")
    df["month_of_year"] = df["local_time"].dt.month
    df["weekday"] = df["local_time"].dt.day_name()
    df["hour"] = df["local_time"].dt.hour
    return df


def primary_currency(df: pd.DataFrame) -> str | None:
    cur = df["currency"].dropna()
    return cur.mode().iat[0] if not cur.empty else None


def completed(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["completed"]]


def money_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Completed rides in the primary currency (or with no currency recorded)."""
    done = completed(df)
    cur = primary_currency(done)
    if cur is None:
        return done
    return done[done["currency"].isna() | (done["currency"] == cur)]


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def overview(df: pd.DataFrame) -> dict[str, Any]:
    done = completed(df)
    money = money_frame(df)
    currencies = sorted(done["currency"].dropna().unique().tolist())
    offsets = (
        done["utc_offset_min"].value_counts().sort_index()
        .rename(lambda m: f"UTC{'+' if m >= 0 else '-'}{abs(m) // 60:02d}{abs(m) % 60:02d}")
    )
    return {
        "orders": int(len(df)),
        "completed": int(len(done)),
        "cancelled_or_other": int(len(df) - len(done)),
        "first_ride": done["local_time"].min(),
        "last_ride": done["local_time"].max(),
        "currency": primary_currency(done),
        "currencies": currencies,
        "excluded_other_currency": int(len(done) - len(money)),
        "total_spend": float(money["cost"].sum()),
        "mean_cost": float(money["cost"].mean()) if len(money) else None,
        "median_cost": float(money["cost"].median()) if len(money) else None,
        "mean_wait_min": float(done["wait_min"].mean()) if done["wait_min"].notna().any() else None,
        "mean_duration_min": float(done["duration_min"].mean()) if done["duration_min"].notna().any() else None,
        "total_ride_hours": float(done["duration_min"].sum() / 60),
        "with_driver_info": int(done["driver_name"].notna().sum()),
        "surged_share": float((done["surge"] > 1).mean()) if done["surge"].notna().any() else None,
        "mean_surge_when_surged": float(done.loc[done["surge"] > 1, "surge"].mean()) if (done["surge"] > 1).any() else None,
        "countries": done["country"].value_counts().to_dict(),
        "utc_offsets": offsets.to_dict(),
    }


# --------------------------------------------------------------------------
# Group breakdowns: tariff / month / year
# --------------------------------------------------------------------------

def breakdown(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Count, spend and min/mean/max of each metric per group.

    ``by`` is a column name: ``"tariff"``, ``"month"``, ``"year"``, ``"weekday"``…
    """
    done = completed(df)
    money = money_frame(df)

    g = done.groupby(by, observed=True)
    out = pd.DataFrame({"rides": g.size()})
    out["spend"] = money.groupby(by, observed=True)["cost"].sum()
    for col in METRICS:
        src = money if col == "cost" else done
        agg = src.groupby(by, observed=True)[col].agg(["min", "mean", "max"])
        for stat in ("min", "mean", "max"):
            out[f"{col}_{stat}"] = agg[stat]
    out["surged_share"] = done.groupby(by, observed=True)["surge"].agg(lambda s: (s > 1).mean() if s.notna().any() else float("nan"))
    out["share"] = out["rides"] / out["rides"].sum()

    if by == "month" and len(out):
        full = pd.period_range(out.index.min(), out.index.max(), freq="M")
        out = out.reindex(full)
        out.index.name = "month"
    elif by == "year" and len(out):
        out = out.reindex(range(int(out.index.min()), int(out.index.max()) + 1))
        out.index.name = "year"
    elif by == "weekday":
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        out = out.reindex([d for d in order if d in out.index])
    elif by == "tariff":
        out = out.sort_values("rides", ascending=False)

    out[["rides", "spend"]] = out[["rides", "spend"]].fillna(0)
    out["share"] = out["share"].fillna(0)
    return out


def has_data(df: pd.DataFrame, col: str) -> bool:
    """False when a metric is absent from the export (e.g. wait time in Yandex Go)."""
    return bool(completed(df)[col].notna().any())


def highlights(table: pd.DataFrame) -> dict[str, Any]:
    """Most / average / least of rides and spend across the groups of a breakdown."""
    if table.empty:
        return {}
    res: dict[str, Any] = {}
    for col in ("rides", "spend"):
        s = table[col]
        res[col] = {
            "most": (s.idxmax(), float(s.max())),
            "least": (s.idxmin(), float(s.min())),
            "average": float(s.mean()),
        }
    for col in ("cost_mean", "wait_min_mean", "duration_min_mean", "surge_mean"):
        s = table[col].dropna()
        if not s.empty:
            res[col] = {
                "most": (s.idxmax(), float(s.max())),
                "least": (s.idxmin(), float(s.min())),
                "average": float(s.mean()),
            }
    return res


def ride_extremes(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """The single most / least extreme rides for each metric."""
    out: dict[str, dict[str, Any]] = {}
    for col, label in METRICS.items():
        src = (money_frame(df) if col == "cost" else completed(df)).dropna(subset=[col])
        if src.empty:
            continue
        hi, lo = src.loc[src[col].idxmax()], src.loc[src[col].idxmin()]
        out[label] = {
            "max": {"value": float(hi[col]), "when": hi["local_time"], "tariff": hi["tariff"]},
            "mean": float(src[col].mean()),
            "median": float(src[col].median()),
            "min": {"value": float(lo[col]), "when": lo["local_time"], "tariff": lo["tariff"]},
        }
    return out


# --------------------------------------------------------------------------
# Repeat drivers & cars
# --------------------------------------------------------------------------

def _repeat_table(df: pd.DataFrame, keys: list[str], min_rides: int) -> pd.DataFrame:
    sub = completed(df).dropna(subset=keys)
    if sub.empty:
        return pd.DataFrame()
    g = sub.groupby(keys)
    t = pd.DataFrame({
        "rides": g.size(),
        "first_seen": g["local_time"].min(),
        "last_seen": g["local_time"].max(),
        "tariffs": g["tariff"].agg(lambda s: ", ".join(sorted(set(s)))),
    })
    t = t[t["rides"] >= min_rides]
    t["span_days"] = (t["last_seen"] - t["first_seen"]).dt.days
    return t.sort_values(["rides", "last_seen"], ascending=[False, False]).reset_index()


def repeat_drivers(df: pd.DataFrame, min_rides: int = 2) -> pd.DataFrame:
    """Same driver name **and** same plate: strong evidence of the same person."""
    t = _repeat_table(df, ["driver_name", "car_plate"], min_rides)
    if not t.empty:
        models = completed(df).dropna(subset=["car_plate"]).groupby("car_plate")["car_model"].first()
        t.insert(2, "car_model", t["car_plate"].map(models))
    return t


def repeat_driver_names(df: pd.DataFrame, min_rides: int = 2) -> pd.DataFrame:
    """Name-only matches (weaker: common names collide). Shows how many plates each name had."""
    t = _repeat_table(df, ["driver_name"], min_rides)
    if not t.empty:
        plates = completed(df).groupby("driver_name")["car_plate"].nunique()
        t.insert(2, "distinct_cars", t["driver_name"].map(plates))
    return t


def repeat_cars(df: pd.DataFrame, min_rides: int = 2) -> pd.DataFrame:
    """Same plate seen more than once; lists every driver name seen in it."""
    t = _repeat_table(df, ["car_plate"], min_rides)
    if not t.empty:
        sub = completed(df).dropna(subset=["car_plate"])
        meta = sub.groupby("car_plate").agg(
            car_model=("car_model", "first"),
            car_color=("car_color", "first"),
            drivers=("driver_name", lambda s: ", ".join(sorted(set(s.dropna())))),
        )
        t = t.join(meta, on="car_plate")
        t = t[["car_plate", "car_model", "car_color", "rides", "drivers", "first_seen", "last_seen", "span_days", "tariffs"]]
    return t


def popular_models(df: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    sub = completed(df).dropna(subset=["car_model"])
    return (
        sub.groupby("car_model")
        .agg(rides=("car_model", "size"), distinct_cars=("car_plate", "nunique"))
        .sort_values("rides", ascending=False)
        .head(top)
        .reset_index()
    )


def driver_summary(df: pd.DataFrame) -> dict[str, Any]:
    done = completed(df)
    known = done.dropna(subset=["driver_name"])
    pairs = known.dropna(subset=["car_plate"]).groupby(["driver_name", "car_plate"]).size()
    plates = done["car_plate"].dropna().value_counts()
    return {
        "rides_with_driver": int(len(known)),
        "share_with_driver": float(len(known) / len(done)) if len(done) else 0.0,
        "distinct_drivers": int(len(pairs)),
        "repeat_drivers": int((pairs >= 2).sum()),
        "rides_with_repeat_driver": int(pairs[pairs >= 2].sum()),
        "distinct_cars": int(len(plates)),
        "repeat_cars": int((plates >= 2).sum()),
    }


# --------------------------------------------------------------------------
# Everything at once
# --------------------------------------------------------------------------

def compute_all(df: pd.DataFrame) -> dict[str, Any]:
    tables = {by: breakdown(df, by) for by in ("tariff", "year", "month", "weekday", "hour")}
    return {
        "overview": overview(df),
        "available": {c: has_data(df, c) for c in METRICS},
        "tables": tables,
        "highlights": {by: highlights(tables[by]) for by in ("tariff", "year", "month")},
        "extremes": ride_extremes(df),
        "drivers": driver_summary(df),
        "repeat_drivers": repeat_drivers(df),
        "repeat_driver_names": repeat_driver_names(df),
        "repeat_cars": repeat_cars(df),
        "models": popular_models(df),
    }
