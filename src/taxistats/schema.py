"""Normalise raw export records into a flat, typed :class:`Ride`.

This is the **only** module that knows the shape of the export. If a real
export uses different key names, adjust :data:`FIELD_ALIASES` (or
:func:`parse_record`) and the rest of the pipeline is unaffected.

Design notes
------------
* **Local time is kept as the primary clock.** A ride at 08:15+0600 was a
  morning ride for the passenger, so month/hour buckets use the wall-clock
  time printed in the export, not UTC. The UTC instant is kept alongside for
  ordering and for de-duplication, where two exports might render the same
  instant with different offsets.
* **Parsing is lenient but explicit.** Missing optional fields become
  ``None``; a record without a timestamp is rejected with a
  :class:`RecordError` so callers can count and report bad rows instead of
  silently dropping them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping

# Candidate key names for each logical field, tried in order. Dotted paths
# walk into nested objects ("performer.car.model").
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": ("order_id", "item_id.order_id", "id"),
    "created": ("created_at", "created", "datetime"),
    "status": ("status", "taxi_status", "state"),
    "tariff": ("tariff_internal_name", "tariff_class", "tariff"),
    "cost": ("payment.cost", "payment.final_cost", "cost", "price"),
    "currency": ("payment.currency_code", "currency", "cost.currency"),
    "wait": ("waiting_time", "wait_time"),  # not present in Yandex Go exports
    "duration": ("duration", "trip_duration"),  # numeric seconds, if a source has it
    "formatted_duration": ("formatted_duration",),  # "18 мин", "1 ч 5 мин"
    "surge": ("calculation.surge_coefficient",),
    "country": ("country_id",),
    "driver_name": ("driver.name", "performer.name", "driver_name"),
    "car_model": ("vehicle.model", "performer.car.model", "car.model"),
    "car_color": ("vehicle.color", "performer.car.color", "car.color"),
    "car_plate": ("vehicle.car_number", "performer.car.number", "car.plate", "car_number"),
}

# Raw tariff codes -> display names. Unknown codes are title-cased.
TARIFF_NAMES: dict[str, str] = {
    # Keys are tariff_internal_name values; extend from your own export.
    "econom": "Economy",
    "start": "Start",
    "ultimate": "Ultima",
    "express": "Delivery",
    "economy": "Economy",
    "comfort": "Comfort",
    "comfortplus": "Comfort+",
    "comfort_plus": "Comfort+",
    "business": "Business",
    "vip": "Business",
    "minivan": "Minivan",
    "child_tariff": "Kids",
    "kids": "Kids",
}

COMPLETED_STATUSES = {"complete", "completed", "finished", "done", "transporting_finished"}


class RecordError(ValueError):
    """A raw record could not be turned into a :class:`Ride`."""


@dataclass(frozen=True, slots=True)
class Ride:
    order_id: str | None
    local_time: datetime  # naive wall-clock time as shown in the export
    utc_time: datetime  # aware, UTC
    utc_offset_min: int
    status: str
    completed: bool
    tariff: str
    cost: float | None
    currency: str | None
    wait_min: float | None
    duration_min: float | None
    surge: float | None
    country: str | None
    driver_name: str | None
    car_model: str | None
    car_color: str | None
    car_plate: str | None
    source_file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]


# --------------------------------------------------------------------------
# Field helpers
# --------------------------------------------------------------------------

def _lookup(record: Mapping[str, Any], path: str) -> Any:
    node: Any = record
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _first(record: Mapping[str, Any], logical: str) -> Any:
    for path in FIELD_ALIASES[logical]:
        value = _lookup(record, path)
        if value not in (None, ""):
            return value
    return None


_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%d.%m.%Y %H:%M:%S%z",
    "%d.%m.%Y %H:%M%z",
)


def parse_timestamp(value: Any) -> datetime:
    """Parse an offset-bearing timestamp such as ``2023-04-12T08:15:31+0600``.

    Accepts ``+0600`` and ``+06:00`` offsets, optional fractional seconds and
    a space instead of ``T``. Naive timestamps are rejected: without an
    offset we cannot place the ride on the UTC timeline, and guessing would
    silently corrupt de-duplication.
    """
    if not isinstance(value, str):
        raise RecordError(f"timestamp must be a string, got {value!r}")
    text = value.strip().replace("Z", "+0000")
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RecordError(f"unrecognised timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise RecordError(f"timestamp has no UTC offset: {value!r}")
    return parsed


_CURRENCY_SYMBOLS = {"₸": "KZT", "₽": "RUB", "$": "USD", "€": "EUR", "сум": "UZS", "֏": "AMD", "Br": "BYN"}
_NUM_RE = re.compile(r"-?\d[\d\s  ]*(?:[.,]\d+)?")


def parse_money(value: Any) -> tuple[float | None, str | None]:
    """Return ``(amount, currency)`` from a number, string or ``{value, currency}`` object.

    Strings like ``"1 450 ₸"`` or ``"1450,50 KZT"`` are handled: thin/no-break
    spaces are thousands separators and a comma before 1–2 trailing digits is
    a decimal separator.
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        raise RecordError(f"bad cost {value!r}")
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, Mapping):
        amount, _ = parse_money(value.get("value", value.get("amount")))
        currency = value.get("currency")
        return amount, (str(currency).upper() if currency else None)
    if isinstance(value, str):
        match = _NUM_RE.search(value)
        if not match:
            return None, None
        number = re.sub(r"[\s  ]", "", match.group()).replace(",", ".")
        currency = None
        rest = (value[: match.start()] + value[match.end():]).strip()
        if rest:
            currency = _CURRENCY_SYMBOLS.get(rest, rest.upper() if rest.isalpha() and len(rest) == 3 else None)
        return float(number), currency
    raise RecordError(f"bad cost {value!r}")


def parse_seconds_as_minutes(value: Any) -> float | None:
    """Durations in the export are seconds; we report minutes."""
    if value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"bad duration {value!r}") from exc
    if seconds < 0:
        raise RecordError(f"negative duration {value!r}")
    return round(seconds / 60.0, 2)


_DURATION_RE = re.compile(
    r"^\s*(?:(?P<h>\d+)\s*(?:ч|час\w*|h|hr|hours?)\.?)?\s*(?:(?P<m>\d+)\s*(?:мин\w*|min\w*|m)\.?)?\s*$",
    re.IGNORECASE,
)


def parse_formatted_duration(value: Any) -> float | None:
    """Minutes from a display string: ``"18 мин"``, ``"1 ч 5 мин"``, ``"1 h 5 min"``, ``"1:05"``.

    Returns ``None`` (not an error) for an unrecognised string, so one odd
    value never costs the whole ride.
    """
    if value in (None, ""):
        return None
    text = str(value).replace("\u00a0", " ").strip()
    clock = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", text)
    if clock:
        h, m, sec = int(clock[1]), int(clock[2]), int(clock[3] or 0)
        return float(h * 60 + m + sec / 60)
    match = _DURATION_RE.match(text)
    if not match or not (match["h"] or match["m"]):
        return None
    return float(int(match["h"] or 0) * 60 + int(match["m"] or 0))


def normalise_tariff(raw: Any) -> str:
    if raw in (None, ""):
        return "Unknown"
    key = str(raw).strip().lower().replace(" ", "").replace("-", "")
    return TARIFF_NAMES.get(key, str(raw).strip().title())


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def normalise_plate(value: Any) -> str | None:
    """Upper-case and strip spaces so '123 abc 02' and '123ABC02' match."""
    text = _clean_str(value)
    return re.sub(r"\s+", "", text).upper() if text else None


# --------------------------------------------------------------------------
# Record -> Ride
# --------------------------------------------------------------------------

def parse_record(record: Mapping[str, Any], source_file: str = "") -> Ride:
    if not isinstance(record, Mapping):
        raise RecordError(f"record is not an object: {type(record).__name__}")

    created = _first(record, "created")
    if created is None:
        raise RecordError("record has no timestamp")
    ts = parse_timestamp(created)
    offset = ts.utcoffset()
    assert offset is not None  # guaranteed by parse_timestamp

    cost, cost_currency = parse_money(_first(record, "cost"))
    currency_field = _first(record, "currency")
    currency = cost_currency or (str(currency_field).upper() if isinstance(currency_field, str) else None)

    status = str(_first(record, "status") or "complete").strip().lower()
    order_id = _first(record, "order_id")

    return Ride(
        order_id=str(order_id) if order_id is not None else None,
        local_time=ts.replace(tzinfo=None),
        utc_time=ts.astimezone(timezone.utc),
        utc_offset_min=int(offset.total_seconds() // 60),
        status=status,
        completed=status in COMPLETED_STATUSES,
        tariff=normalise_tariff(_first(record, "tariff")),
        cost=cost,
        currency=currency,
        wait_min=parse_seconds_as_minutes(_first(record, "wait")),
        duration_min=(parse_seconds_as_minutes(_first(record, "duration"))
                      if _first(record, "duration") is not None
                      else parse_formatted_duration(_first(record, "formatted_duration"))),
        surge=_float_or_none(_first(record, "surge")),
        country=_clean_str(_first(record, "country")),
        driver_name=_clean_str(_first(record, "driver_name")),
        car_model=_clean_str(_first(record, "car_model")),
        car_color=_clean_str(_first(record, "car_color")),
        car_plate=normalise_plate(_first(record, "car_plate")),
        source_file=source_file,
    )
