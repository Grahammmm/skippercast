"""RF0550-7: inventory bodies are read up to a bound; stored station names are plain one-line text (offline; fake opener)."""
import io
import json

import pytest

from scripts import build_station_locations as bsl
from tests.unit.test_build_station_locations import (  # noqa: F401  (root is a fixture)
    GOOD_COOPS, GOOD_NDBC, Opener, assert_untouched, coops, ndbc, root, run)

BOUND = 2048


def padded(body, size, pad=b" "):
    assert len(body) <= size  # whitespace padding keeps the XML and the JSON valid
    return body[:-len(b"</stations>")] + pad * (size - len(body)) + b"</stations>" if body.startswith(b"<?xml") \
        else body + pad * (size - len(body))


class Recording(Opener):  # records the size passed to each read()
    def __init__(self, **bodies):
        super().__init__(**bodies)
        self.sizes = []

    def __call__(self, url, timeout):
        sizes = self.sizes

        class Response(io.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                return super().read(size)
        return Response(super().__call__(url, timeout).getvalue())


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr(bsl, "MAX_INVENTORY_BYTES", BOUND)


def test_body_of_exactly_the_bound_is_accepted_and_the_read_is_bounded(root, capsys, bound):
    opener = Recording(ndbc_body=padded(ndbc(), BOUND), coops_body=padded(coops(), BOUND))
    assert run(root, opener, capsys) == (0, "")
    assert opener.sizes == [BOUND + 1, BOUND + 1]  # never an unbounded read()
    assert (root / "var/station-locations/ndbc.xml").read_bytes() == opener.bodies["ndbc"]
    assert len(json.loads((root / "catalog/station-locations.json").read_text())["stations"]) == 4


def test_one_byte_over_names_the_provider_and_writes_nothing(root, capsys, bound):
    opener = Recording(ndbc_body=padded(ndbc(), BOUND + 1))
    code, err = run(root, opener, capsys)
    assert (code, err) == (1, "build_station_locations: ndbc: inventory over 32 MiB (1 error)\n")
    assert opener.calls == ["ndbc", "coops"] and opener.sizes == [BOUND + 1, BOUND + 1]
    assert not (root / "var").exists()
    assert_untouched(root)


def test_far_over_body_is_read_only_to_the_bound(root, capsys, bound):
    opener = Recording(coops_body=padded(coops(), BOUND * 50))
    code, err = run(root, opener, capsys)
    assert (code, err) == (1, "build_station_locations: coops: inventory over 32 MiB (1 error)\n")
    assert opener.sizes == [BOUND + 1, BOUND + 1]
    assert_untouched(root)


def test_both_providers_over_are_both_named(root, capsys, bound):
    code, err = run(root, Opener(ndbc_body=padded(ndbc(), BOUND + 1), coops_body=padded(coops(), BOUND + 7)), capsys)
    assert (code, err) == (1, "build_station_locations: ndbc: inventory over 32 MiB; coops: inventory over 32 MiB"
                              " (2 errors)\n")
    assert_untouched(root)


def test_real_bound_is_32_mib():
    assert bsl.MAX_INVENTORY_BYTES == 32 * 1024 * 1024


@pytest.mark.parametrize("name", ["Port San Luis\n", "A\tB", "X\x85", "N" * 121, " " + "N" * 121 + " ", "\rPort",
                                  "Del\x7f", "C1\x80", "C1\x9f", "Unit\x1f"])
def test_name_that_is_not_plain_one_line_text_is_refused_without_echo(root, capsys, name):
    code, err = run(root, Opener(coops_body=coops([dict(GOOD_COOPS[0], name=name)])), capsys)
    assert (code, err) == (1, "build_station_locations: coops:9412110: name is not plain one-line text (1 error)\n")
    assert_untouched(root)  # the exact message above never carries the refused text


@pytest.mark.parametrize("name, stored", [
    ("  Avila Beach  ", "Avila Beach"), ("N" * 120, "N" * 120), ("  " + "N" * 120 + "  ", "N" * 120),
    ("Bahía ☃ \xa0Ñ", "Bahía ☃ \xa0Ñ"),
])
def test_plain_name_is_stored_trimmed(root, capsys, name, stored):
    assert run(root, Opener(coops_body=coops([dict(GOOD_COOPS[0], name=name)])), capsys) == (0, "")
    catalog = json.loads((root / "catalog/station-locations.json").read_text())
    assert catalog["stations"]["coops:9412110"]["name"] == stored


def test_ndbc_name_with_an_encoded_newline_is_refused(root, capsys):
    rows = dict(GOOD_NDBC, **{"46028": 'lat="35.77" lon="-121.903" name="Cape&#10;San Martin"'})
    code, err = run(root, Opener(ndbc_body=ndbc(rows)), capsys)
    assert (code, err) == (1, "build_station_locations: ndbc:46028: name is not plain one-line text (1 error)\n")
    assert_untouched(root)


def test_name_error_and_coordinate_error_are_counted_together(root, capsys):
    rows = dict(GOOD_NDBC, **{"46215": 'lat="95" lon="-120.859" name="Diablo Canyon"'})
    code, err = run(root, Opener(ndbc_body=ndbc(rows), coops_body=coops([dict(GOOD_COOPS[0], name="A\tB")])), capsys)
    assert code == 1 and "ndbc:46215: lat '95' is not a finite number within ±90" in err
    assert "coops:9412110: name is not plain one-line text" in err and err.endswith(" (2 errors)\n")
    assert "A\tB" not in err
    assert_untouched(root)
