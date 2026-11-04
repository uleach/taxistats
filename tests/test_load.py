from conftest import ride

from taxistats.load import extract_records, load_exports


def test_container_shapes():
    assert len(list(extract_records([{"id": 1}, {"id": 2}]))) == 2
    assert len(list(extract_records({"orders": [{"id": 1}]}))) == 1
    assert len(list(extract_records({"data": {"orders": [{"id": 1}, {"id": 2}]}}))) == 2
    assert len(list(extract_records({"id": 1, "created": "x"}))) == 1


def test_duplicate_ids_across_files_merge(write_exports):
    d = write_exports({"orders": [ride("a"), ride("b")]}, {"orders": [ride("b"), ride("c")]})
    rides, rep = load_exports([d])
    assert sorted(r.order_id for r in rides) == ["a", "b", "c"]
    assert rep.raw_records == 4 and rep.duplicates_removed == 1 and rep.unique_rides == 3


def test_coalescing_fills_driver_from_later_file(write_exports):
    old = ride("a")
    new = ride("a", performer={"name": "Arman K.", "car": {"model": "Kia Rio", "number": "111AAA02"}})
    rides, _ = load_exports([write_exports([old], [new])])
    assert len(rides) == 1 and rides[0].driver_name == "Arman K."
    assert rides[0].source_file == "export_0.json;export_1.json"


def test_conflicting_cost_counted_and_complete_copy_wins(write_exports):
    old = ride("a", cost=1100.0)
    new = ride("a", cost=1200.0, performer={"name": "X"})
    rides, rep = load_exports([write_exports([old], [new])])
    assert rides[0].cost == 1200.0
    assert rep.conflicts == 1


def test_same_instant_different_offset_is_duplicate_without_id(write_exports):
    a = ride(None, created="2024-03-05T08:15:00+0600")
    b = ride(None, created="2024-03-05T07:15:00+0500")
    a.pop("id"); b.pop("id")
    rides, rep = load_exports([write_exports([a], [b])])
    assert len(rides) == 1 and rep.duplicates_removed == 1


def test_idless_copy_attaches_to_id_ride(write_exports):
    a = ride("a")
    b = ride(None); b.pop("id")
    rides, _ = load_exports([write_exports([b], [a])])
    assert len(rides) == 1 and rides[0].order_id == "a"


def test_bad_records_reported_not_fatal(write_exports):
    rides, rep = load_exports([write_exports([ride("a"), {"id": "bad"}, "not-an-object"])])
    assert len(rides) == 1
    assert len(rep.rejected) == 1  # non-object entries are ignored, not counted as orders
