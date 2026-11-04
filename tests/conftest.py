import json
from pathlib import Path

import pytest


def ride(id_="a1", created="2024-03-05T08:15:00+0600", tariff="econom", cost=1200.0, **extra):
    rec = {"id": id_, "created": created, "status": "complete", "tariff": tariff, "cost": cost,
           "currency": "KZT", "waiting_time": 240, "duration": 900}
    rec.update(extra)
    return rec


@pytest.fixture
def write_exports(tmp_path: Path):
    def _write(*files: object) -> Path:
        for i, payload in enumerate(files):
            (tmp_path / f"export_{i}.json").write_text(json.dumps(payload), encoding="utf-8")
        return tmp_path
    return _write
