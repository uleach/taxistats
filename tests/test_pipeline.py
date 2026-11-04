import json

from taxistats.pipeline import run
from taxistats.synthetic import write_sample


def test_end_to_end_on_synthetic_sample(tmp_path):
    sample = tmp_path / "sample"
    files = write_sample(sample, seed=7)
    assert len(files) == 4

    res = run([sample], tmp_path / "out")
    rep = res.report
    assert rep["duplicates_removed"] > 0          # overlapping windows
    assert rep["rejected"] == 1                   # the planted malformed record
    assert rep["unique_rides"] == rep["raw_records"] - rep["duplicates_removed"] - rep["rejected"]
    assert res.rides["order_id"].is_unique

    html = res.outputs["dashboard"].read_text(encoding="utf-8")
    assert "<svg" in html and "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    summary = json.loads(res.outputs["summary_json"].read_text(encoding="utf-8"))
    assert summary["overview"]["completed"] > 0


def test_sample_is_deterministic(tmp_path):
    a = write_sample(tmp_path / "a", seed=1)
    b = write_sample(tmp_path / "b", seed=1)
    assert [p.read_bytes() for p in a] == [p.read_bytes() for p in b]


def test_anonymise_hides_names(tmp_path):
    write_sample(tmp_path / "s", seed=3)
    real = run([tmp_path / "s"], tmp_path / "real")
    res = run([tmp_path / "s"], tmp_path / "out", anonymise_drivers=True)
    assert res.rides["driver_name"].dropna().str.match(r"^Driver \d{3}$").all()
    assert res.rides["car_plate"].dropna().str.match(r"^CAR \d{3}$").all()
    # Pseudonyms are consistent, so repeat-driver counts are unchanged.
    assert res.stats["drivers"] == real.stats["drivers"]
    leaked = set(real.rides["driver_name"].dropna()) | set(real.rides["car_plate"].dropna())
    for path in res.outputs.values():
        text = path.read_text(encoding="utf-8")
        assert not any(v in text for v in leaked), path
