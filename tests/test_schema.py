from datetime import datetime, timezone

import pytest

from taxistats.schema import RecordError, normalise_tariff, parse_money, parse_record, parse_timestamp


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
