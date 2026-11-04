"""Generate a synthetic ride history that mimics the structure of a real export.

Nothing here is derived from real data: names, plates, prices and times are
drawn from simple parametric distributions with a fixed seed, so the sample
is reproducible and safe to publish.

What the generator deliberately reproduces, because the pipeline must cope
with it:

* **Several overlapping export files.** Each file covers a window that
  overlaps the previous one, so many orders appear twice.
* **Late enrichment.** Rides near the end of an export window sometimes lack
  driver details that a later export includes.
* **Occasional disagreement.** A small share of duplicated rides carry a
  slightly different cost in the older file (estimate vs. final price).
* **Mixed UTC offsets.** Most rides are ``+0600``; some are recorded while
  travelling (``+0300``, ``+0500``).
* **Partial driver data.** Only some rides have a driver name and car, and
  the share grows over time.
* **Repeat drivers.** A handful of "regular" drivers on the commute route,
  plus a long tail; a few drivers switch cars part-way through.
* **One malformed record** (missing timestamp) to exercise error reporting.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TARIFFS = {
    # code: (weight, base fare, per-minute, mean wait (min))
    "econom": (0.44, 450, 38, 4.0),
    "comfort": (0.30, 600, 50, 4.5),
    "comfortplus": (0.15, 800, 66, 5.5),
    "business": (0.05, 1500, 115, 8.0),
    "minivan": (0.04, 1100, 80, 9.0),
    "kids": (0.02, 750, 60, 7.0),
}

FIRST_NAMES = [
    "Arman", "Daulet", "Nurlan", "Yerlan", "Askar", "Marat", "Ruslan", "Timur", "Bauyrzhan",
    "Azamat", "Sergey", "Aleksandr", "Dmitry", "Ilya", "Oleg", "Yerzhan", "Kairat", "Murat",
    "Samat", "Olzhas", "Talgat", "Viktor", "Andrey", "Rustam", "Zhanibek", "Aidos", "Bekzat",
]
INITIALS = "ABDGKMNORSTVYZ"
CAR_MODELS = [
    ("Toyota Camry", 12), ("Hyundai Sonata", 9), ("Kia K5", 8), ("Hyundai Elantra", 7),
    ("Chevrolet Cobalt", 9), ("Kia Rio", 8), ("Hyundai Accent", 8), ("Volkswagen Polo", 6),
    ("Skoda Octavia", 5), ("Toyota Corolla", 5), ("Lexus ES", 2), ("Hyundai Staria", 2),
    ("Kia Carnival", 2), ("Chery Tiggo 7 Pro", 4), ("Haval Jolion", 3),
]
COLOURS = [("white", 9), ("black", 5), ("silver", 5), ("grey", 4), ("blue", 2), ("red", 1)]
OFFSETS = [(360, 0.92), (180, 0.06), (300, 0.02)]  # minutes east of UTC

START = date(2022, 1, 1)
END = date(2025, 10, 31)
EXPORT_WINDOWS = [
    (date(2022, 1, 1), date(2023, 6, 30)),
    (date(2023, 1, 1), date(2024, 3, 15)),
    (date(2024, 1, 1), date(2025, 1, 10)),
    (date(2024, 9, 1), date(2025, 10, 31)),
]


def _weighted(rng: random.Random, items: list[tuple[Any, float]]) -> Any:
    values, weights = zip(*items)
    return rng.choices(values, weights=weights, k=1)[0]


def _plate(rng: random.Random) -> str:
    letters = "".join(rng.choice("ABCEHKMOPTXY") for _ in range(3))
    return f"{rng.randint(100, 999)}{letters}{rng.choice(['02', '02', '02', '01', '05'])}"


@dataclass
class Driver:
    name: str
    cars: list[dict[str, str]]  # usually one; a few switch cars
    switch_on: date | None
    weight: float

    def car_on(self, day: date) -> dict[str, str]:
        if self.switch_on and day >= self.switch_on and len(self.cars) > 1:
            return self.cars[1]
        return self.cars[0]


def _car(rng: random.Random, model: str | None = None) -> dict[str, str]:
    return {
        "model": model or _weighted(rng, CAR_MODELS),
        "color": _weighted(rng, COLOURS),
        "number": _plate(rng),
    }


def build_drivers(rng: random.Random, n: int = 160) -> list[Driver]:
    drivers = []
    used: set[str] = set()
    for i in range(n):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(INITIALS)}."
            # allow some name collisions (realistic) but not too many
            if name not in used or rng.random() < 0.15:
                break
        used.add(name)
        cars = [_car(rng)]
        switch_on = None
        if rng.random() < 0.06:
            cars.append(_car(rng))
            switch_on = START + timedelta(days=rng.randint(200, (END - START).days - 100))
        # Zipf-like tail; the first few are the "regulars".
        weight = 6.0 if i < 3 else 2.0 if i < 10 else 1.0 / (1 + (i - 10) * 0.02)
        drivers.append(Driver(name, cars, switch_on, weight))
    return drivers


def _rides_today(rng: random.Random, day: date) -> int:
    seasonal = 1 + 0.45 * math.cos(2 * math.pi * (day.timetuple().tm_yday - 15) / 365)  # winter peak
    weekday = 1.25 if day.weekday() >= 4 else 0.9
    growth = 0.75 + 0.35 * (day - START).days / (END - START).days
    lam = 0.42 * seasonal * weekday * growth
    # Poisson via inversion — fine for small lambda
    k, p, u = 0, math.exp(-lam), rng.random()
    s = p
    while u > s:
        k += 1
        p *= lam / k
        s += p
    return k


def _hour(rng: random.Random, weekend: bool) -> int:
    if weekend:
        hours = [(h, 1.0) for h in range(24)]
        hours = [(h, w * (3.0 if 12 <= h <= 23 else 1.5 if h <= 3 else 0.3)) for h, w in hours]
    else:
        hours = [(h, 3.5 if h in (7, 8) else 3.0 if h in (18, 19) else 1.0 if 9 <= h <= 22 else 0.15) for h in range(24)]
    return _weighted(rng, hours)


def generate_rides(seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    drivers = build_drivers(rng)
    driver_weights = [d.weight for d in drivers]
    rides: list[dict[str, Any]] = []

    day = START
    while day <= END:
        for _ in range(_rides_today(rng, day)):
            offset_min = _weighted(rng, OFFSETS)
            tz = timezone(timedelta(minutes=offset_min))
            local = datetime(day.year, day.month, day.day, _hour(rng, day.weekday() >= 5),
                             rng.randint(0, 59), rng.randint(0, 59), tzinfo=tz)

            tariff = _weighted(rng, [(k, v[0]) for k, v in TARIFFS.items()])
            _, base, per_min, mean_wait = TARIFFS[tariff]
            duration_min = max(4.0, rng.lognormvariate(math.log(17), 0.45))
            wait_min = min(25.0, rng.expovariate(1 / mean_wait))
            inflation = 1.09 ** ((day - START).days / 365)
            surge = 1.0 + (rng.random() < 0.15) * rng.uniform(0.2, 0.9)
            cost = round((base + per_min * duration_min) * inflation * surge / 10) * 10

            status = "cancelled" if rng.random() < 0.035 else "complete"
            ride: dict[str, Any] = {
                "id": "%032x" % rng.getrandbits(128),
                "created": local.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "status": status,
                "tariff": tariff,
                "cost": float(cost) if status == "complete" else 0.0,
                "currency": "KZT",
                "waiting_time": int(wait_min * 60),
                "duration": int(duration_min * 60) if status == "complete" else 0,
            }
            share_with_driver = 0.35 + 0.45 * (day - START).days / (END - START).days
            if status == "complete" and rng.random() < share_with_driver:
                drv = rng.choices(drivers, weights=driver_weights, k=1)[0]
                ride["performer"] = {"name": drv.name, "car": dict(drv.car_on(day))}
            rides.append(ride)
        day += timedelta(days=1)
    return rides


def split_into_exports(rides: list[dict[str, Any]], seed: int = 42) -> dict[str, dict[str, Any]]:
    """Slice the ride list into overlapping export files with realistic quirks."""
    rng = random.Random(seed + 1)
    files: dict[str, dict[str, Any]] = {}
    for i, (lo, hi) in enumerate(EXPORT_WINDOWS):
        is_latest = i == len(EXPORT_WINDOWS) - 1
        orders = []
        for r in rides:
            d = datetime.strptime(r["created"][:10], "%Y-%m-%d").date()
            if not lo <= d <= hi:
                continue
            r = json.loads(json.dumps(r))  # deep copy
            if not is_latest:
                # Late enrichment: driver info missing for the last ~3 weeks of the window.
                if (hi - d).days < 21 and "performer" in r and rng.random() < 0.6:
                    del r["performer"]
                # Estimate vs final price disagreement.
                if r["status"] == "complete" and rng.random() < 0.02:
                    r["cost"] = float(round(r["cost"] * rng.uniform(0.9, 0.98) / 10) * 10)
            orders.append(r)
        orders.reverse()  # exports usually list newest first
        if i == 1:
            orders.insert(len(orders) // 2, {"id": "corrupt-record", "status": "complete", "cost": 999.0})
        files[f"rides_export_{hi.isoformat()}.json"] = {
            "export_created": f"{hi.isoformat()}T23:59:00+0600",
            "orders": orders,
        }
    return files


def write_sample(out_dir: str | Path, seed: int = 42) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in split_into_exports(generate_rides(seed), seed).items():
        path = out / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(path)
    return written
