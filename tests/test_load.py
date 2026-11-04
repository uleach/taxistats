import json

from conftest import ride

from taxistats.load import discover_files, extract_records, load_exports


def test_container_shapes():
    assert len(list(extract_records([{"id": 1}, {"id": 2}]))) == 2
    assert len(list(extract_records({"orders": [{"id": 1}]}))) == 1
    assert len(list(extract_records({"data": {"orders": [{"id": 1}, {"id": 2}]}}))) == 2


def test_only_ridehistory_files_are_read(tmp_path):
    (tmp_path / "ridehistory.json").write_text(json.dumps([ride("a")]))
    # routehistory entries have a "created" timestamp and would parse as rides if read.
    (tmp_path / "routehistory.json").write_text(json.dumps({"history": [{"created": "2024-01-01T10:00:00.000+0600"}]}))
    (tmp_path / "cardstorage.json").write_text(json.dumps({"cards": [{"number": "400000****0000"}]}))
    assert [p.name for p in discover_files([tmp_path])] == ["ridehistory.json"]
    rides, rep = load_exports([tmp_path])
    assert len(rides) == 1 and rep.raw_records == 1


def test_duplicate_ids_across_exports_merge(write_exports):
    d = write_exports([ride("a"), ride("b")], [ride("a"), ride("b"), ride("c")])
    rides, rep = load_exports([d])
    assert sorted(r.order_id for r in rides) == ["a", "b", "c"]
    assert rep.raw_records == 5 and rep.duplicates_removed == 2 and rep.unique_rides == 3
    assert rep.files == ["export0/ridehistory.json", "export1/ridehistory.json"]


def test_coalescing_fills_missing_field_from_other_copy(write_exports):
    rides, _ = load_exports([write_exports([ride("a")], [ride("a", driver="Тестов Арман Тестович")])])
    assert len(rides) == 1 and rides[0].driver_name == "Тестов Арман Тестович"
    assert rides[0].source_file == "export0/ridehistory.json;export1/ridehistory.json"


def test_conflicting_cost_counted_and_later_export_wins_tie(write_exports):
    rides, rep = load_exports([write_exports([ride("a", cost=1300.0)], [ride("a", cost=1200.0)])])
    assert rides[0].cost == 1200.0
    assert rep.conflicts == 1


def test_same_instant_different_offset_is_duplicate_without_id(write_exports):
    a = ride(None, created="2024-03-05T08:15:00+0600")
    b = ride(None, created="2024-03-05T07:15:00+0500")
    rides, rep = load_exports([write_exports([a], [b])])
    assert len(rides) == 1 and rep.duplicates_removed == 1


def test_idless_copy_attaches_to_id_ride(write_exports):
    rides, _ = load_exports([write_exports([ride(None)], [ride("a")])])
    assert len(rides) == 1 and rides[0].order_id == "a"


def test_bad_records_reported_not_fatal(write_exports):
    rides, rep = load_exports([write_exports([ride("a"), {"order_id": "bad"}, "not-an-object"])])
    assert len(rides) == 1
    assert len(rep.rejected) == 1  # non-object entries are ignored, not counted as orders
