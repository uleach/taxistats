"""The synthetic sample must have exactly the structure of a real Yandex Go export.

``fixtures/export_structure.json`` lists, per file, every field path with its
JSON type(s), the kind of string values, and the longest string. It was taken
from a ``taxistats profile`` report of a real export and holds no values,
counts or other personal data.
"""

import json
from pathlib import Path

import pytest

from taxistats.profile import profile_file
from taxistats.synthetic import write_sample

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "export_structure.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def export_folder(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample")
    write_sample(out, seed=42)
    return sorted(p for p in out.iterdir() if p.is_dir())[-1]


def test_same_files(export_folder):
    assert sorted(p.name for p in export_folder.glob("*.json")) == sorted(EXPECTED)


@pytest.mark.parametrize("file_name", sorted(EXPECTED))
def test_same_field_paths_types_and_lengths(export_folder, file_name):
    _, stats = profile_file(export_folder / file_name)
    expected = EXPECTED[file_name]
    assert sorted(stats) == sorted(expected), "field paths differ"
    for path, exp in expected.items():
        got = stats[path]
        assert ", ".join(sorted(got.types)) == exp["types"], path
        kinds = ", ".join(sorted(got.kinds, key=lambda k: -got.kinds[k])) or "-"
        assert kinds == exp["looks_like"], path
        if exp["max_len"] is None:
            assert got.max_len == 0, path
        else:
            assert 0 < got.max_len <= exp["max_len"], path
