import json
from pathlib import Path

import pytest


def ride(order_id="a1", created="2024-03-05T08:15:00+0600", tariff="econom", cost=1200.0, *,
         currency="KZT", status="complete", duration="15 мин", driver=None, plate="123ABC02", model="Kia Rio",
         surge=1.0):
    """A minimal ridehistory.json record with the real export's field paths."""
    rec = {
        "calculation": {"surge_coefficient": surge},
        "created_at": created,
        "driver": {"call_mode": "regular"},
        "payment": {"cost": cost, "currency_code": currency},
        "status": status,
        "tariff_class": tariff,
        "tariff_internal_name": tariff,
        "vehicle": {"car_number": plate, "color": "белый", "model": model},
    }
    if order_id is not None:
        rec["order_id"] = order_id
        rec["item_id"] = {"order_id": order_id}
    if duration is not None:
        rec["formatted_duration"] = duration
    if driver:
        rec["driver"]["name"] = driver
    return rec


@pytest.fixture
def write_exports(tmp_path: Path):
    """Write each payload as <tmp>/<n>/ridehistory.json, like successive export folders."""
    def _write(*files: object) -> Path:
        for i, payload in enumerate(files):
            d = tmp_path / f"export{i}"
            d.mkdir()
            (d / "ridehistory.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return tmp_path
    return _write
