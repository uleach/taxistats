from datetime import datetime, timezone

import pytest

from conftest import ride

from taxistats.schema import (RecordError, normalise_tariff, parse_formatted_duration, parse_money, parse_record,
                              parse_timestamp)


@pytest.mark.parametrize("text", [
    "2024-03-05T08:15:00+0600",
    "2024-03-05T08:15:00+06:00",
    "2024-03-05 08:15:00.000+0600",
    "05.03.2024 08:15:00+0600",
])
def test_timestamp_formats(text):
    ts = parse_timestamp(text)
    assert ts.replace(tzinfo=None) == datetime(2024, 3, 5, 8, 15)
    assert ts.astimezone(timezone.utc).hour == 2


def test_naive_timestamp_rejected():
    with pytest.raises(RecordError):
        parse_timestamp("2024-03-05T08:15:00")


@pytest.mark.parametrize("value,expected", [
    (1450, (1450.0, None)),
    ("1 450 ₸", (1450.0, "KZT")),
    ("1 450,50 KZT", (1450.5, "KZT")),
    ({"value": 990, "currency": "rub"}, (990.0, "RUB")),
    (None, (None, None)),
])
def test_parse_money(value, expected):
    assert parse_money(value) == expected


def test_tariff_names():
    assert normalise_tariff("comfortplus") == "Comfort+"
    assert normalise_tariff("Econom") == "Economy"
    assert normalise_tariff("cargo") == "Cargo"
    assert normalise_tariff(None) == "Unknown"


def test_real_export_record():
    r = parse_record(ride("abc", tariff="comfortplus", cost=2860.0, duration="1 ч 5 мин", driver="  Тестов  Арман ",
                          plate="482 kta 02", surge=1.4))
    assert (r.order_id, r.tariff, r.cost, r.currency) == ("abc", "Comfort+", 2860.0, "KZT")
    assert r.duration_min == 65 and r.wait_min is None and r.surge == 1.4
    assert r.driver_name == "Тестов Арман" and r.car_plate == "482KTA02" and r.car_model == "Kia Rio"


@pytest.mark.parametrize("text,minutes", [
    ("18 мин", 18), ("1 ч 5 мин", 65), ("2 ч", 120), ("1 h 05 min", 65), ("45 min", 45), ("1:05", 65),
    ("0:18:30", 18.5), ("", None), ("скоро", None),
])
def test_formatted_duration(text, minutes):
    assert parse_formatted_duration(text) == minutes


def test_local_time_is_wall_clock():
    r = parse_record({"id": 1, "created": "2024-12-31T23:30:00+0600", "cost": 1})
    assert r.local_time == datetime(2024, 12, 31, 23, 30)  # still New Year's Eve locally
    assert r.utc_time.hour == 17
    assert r.utc_offset_min == 360


def test_nested_driver_and_plate_normalised():
    r = parse_record({"id": "x", "created": "2024-01-01T10:00:00+0600",
                      "performer": {"name": "  Arman   K. ", "car": {"model": "Kia Rio", "number": "123 abc 02"}}})
    assert r.driver_name == "Arman K."
    assert r.car_plate == "123ABC02"
    assert r.car_model == "Kia Rio"


def test_missing_timestamp_rejected():
    with pytest.raises(RecordError):
        parse_record({"id": "x", "cost": 100})


def test_seconds_to_minutes_and_status():
    r = parse_record({"created": "2024-01-01T10:00:00+0600", "waiting_time": 90, "duration": 600, "status": "cancelled"})
    assert (r.wait_min, r.duration_min) == (1.5, 10.0)
    assert r.completed is False
