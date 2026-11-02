"""scripts/showcase.py refuses a bad --date or a malformed pages file before git, node or any file write."""
import importlib.util
import json

import pytest

from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("showcase_inputs_under_test", ROOT / "scripts/showcase.py")
showcase = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(showcase)

VALID = {"timezone": "America/Los_Angeles", "tolerance": 8, "serve": {"cmd": ["true"]},
         "pages": [{"id": "chart-phone", "route": "/map", "path": "/map"}, {"id": "landing", "route": "/", "path": "/"}]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """main() against a fake repository: git and capture_revision are recorded, never real."""
    root = tmp_path / "repo"
    (root / "node_modules/@playwright/test").mkdir(parents=True)
    monkeypatch.setattr(showcase, "ROOT", root)
    calls = {"git": [], "capture": []}

    def fake_git(*args, cwd=None):
        calls["git"].append(args)
        return {"rev-parse": "a" * 40, "show": "2026-10-30T23:30:00-07:00"}.get(args[0], "") + "\n"

    def fake_capture(sha, label, config, work, log, reuse=False):
        calls["capture"].append(label)
        return {p["id"]: {"status": "failed", "error": "stub"} for p in config["pages"]}

    monkeypatch.setattr(showcase, "git", fake_git)
    monkeypatch.setattr(showcase, "capture_revision", fake_capture)
    out = tmp_path / "a" / "out"
    out.mkdir(parents=True)
    for d in (tmp_path, tmp_path / "a", out, tmp_path / "pics"):   # every directory a bad --date could reach
        d.mkdir(exist_ok=True)
        (d / "keep.png").write_bytes(b"png")

    def go(config=VALID, *extra, raw=None):
        pages = tmp_path / "pages.json"
        pages.write_bytes(raw if raw is not None else json.dumps(config).encode())
        argv = ["--before", "b", "--after", "a", "--pages", str(pages), "--out", str(out), "--work", str(tmp_path / "work"), *extra]
        return showcase.main(argv)

    go.calls, go.out, go.tmp = calls, out, tmp_path
    return go


def _refused(run, capsys, code, text):
    err = capsys.readouterr().err
    assert code == 2 and err == f"showcase: {text}\n"
    assert run.calls == {"git": [], "capture": []}
    assert all((d / "keep.png").exists() for d in (run.tmp, run.tmp / "a", run.out, run.tmp / "pics"))
    assert not (run.out / "showcase-2026-11-01.html").exists() and not (run.tmp / "work").exists()


@pytest.mark.parametrize("date", ["../..", "..", ".", "/tmp/x", "{pics}", "2026-13-01", "2026-02-30", "20261101", "2026-11-01/x",
                                  "2026-11-01/..", "", " 2026-11-01", "2026-11-01\n", "２０２６-１１-０１", "2026-W44-7"])
def test_a_date_that_is_not_yyyy_mm_dd_is_refused_before_anything_runs(run, capsys, date):
    _refused(run, capsys, run(VALID, "--date", date.replace("{pics}", str(run.tmp / "pics"))), "--date must be YYYY-MM-DD")


@pytest.mark.parametrize("raw, text", [
    (b"{not json", "cannot read the pages file"),
    (b"\xff\xfe{}", "cannot read the pages file"),
    (b"[]", "the pages file must be a JSON object"),
])
def test_an_unreadable_pages_file_is_refused(run, capsys, raw, text):
    _refused(run, capsys, run(raw=raw), text)


def test_a_missing_pages_file_is_refused(run, capsys):
    code = showcase.main(["--before", "b", "--after", "a", "--pages", str(run.tmp / "absent.json"), "--out", str(run.out)])
    _refused(run, capsys, code, "cannot read the pages file")


ID = "pages[{}].id must be a unique name of 1-48 lowercase letters, digits or hyphens"
ROUTE = "pages[{}].route must be a string starting with /"


@pytest.mark.parametrize("change, text", [
    ({"pages": []}, "pages must be a non-empty list"),
    ({"pages": {"id": "x"}}, "pages must be a non-empty list"),
    ({"pages": None}, "pages must be a non-empty list"),
    ({"pages": [VALID["pages"][0], "landing"]}, "pages[1] must be an object"),
    ({"pages": [{"route": "/"}]}, ID.format(0)),
    ({"pages": [VALID["pages"][0], {"id": "../x", "route": "/"}]}, ID.format(1)),
    ({"pages": [{"id": "Upper", "route": "/"}]}, ID.format(0)),
    ({"pages": [{"id": "-lead", "route": "/"}]}, ID.format(0)),
    ({"pages": [{"id": "a" * 49, "route": "/"}]}, ID.format(0)),
    ({"pages": [{"id": 7, "route": "/"}]}, ID.format(0)),
    ({"pages": [VALID["pages"][0], VALID["pages"][1], dict(VALID["pages"][0])]}, ID.format(2)),
    ({"pages": [{"id": "x", "route": "x"}]}, ROUTE.format(0)),
    ({"pages": [VALID["pages"][0], {"id": "y"}]}, ROUTE.format(1)),
    ({"serve": None, "drop": "serve"}, "serve is missing"),
    ({"tolerance": "x"}, "tolerance must be an integer 0..255"),
    ({"tolerance": -1}, "tolerance must be an integer 0..255"),
    ({"tolerance": 256}, "tolerance must be an integer 0..255"),
    ({"tolerance": True}, "tolerance must be an integer 0..255"),
    ({"tolerance": 8.0}, "tolerance must be an integer 0..255"),
    ({"timezone": "Mars/Base"}, "timezone must be an IANA time zone name"),
    ({"timezone": "../etc/passwd"}, "timezone must be an IANA time zone name"),
    ({"timezone": 5}, "timezone must be an IANA time zone name"),
])
def test_a_malformed_pages_file_is_refused_naming_the_key_never_the_value(run, capsys, change, text):
    config = {**VALID, **change}
    config.pop(config.pop("drop", None), None)
    _refused(run, capsys, run(config, "--date", "2026-11-01"), text)
    assert "../x" not in text and "Mars" not in text


@pytest.mark.parametrize("change", [{"tolerance": 0}, {"tolerance": 255}, {"drop": "tolerance"}, {"drop": "timezone"}])
def test_a_valid_pages_file_and_date_proceed_to_git(run, capsys, change):
    config = {**VALID, **change}
    config.pop(config.pop("drop", None), None)
    assert run(config, "--date", "2026-11-01") == 0
    assert run.calls["git"][0][0] == "rev-parse" and run.calls["capture"] == ["before", "after"]
    assert (run.out / "showcase-2026-11-01.html").exists() and (run.out / "2026-11-01").is_dir()
    assert all((d / "keep.png").exists() for d in (run.tmp, run.tmp / "a", run.out, run.tmp / "pics"))


def test_without_date_the_after_commits_local_date_is_used(run, capsys):
    assert run(VALID) == 0
    assert any(call[0] == "show" for call in run.calls["git"])
    assert (run.out / "showcase-2026-10-30.html").exists() and (run.out / "2026-10-30").is_dir()


def test_the_png_clean_up_never_leaves_out_even_if_the_date_check_is_bypassed(run, capsys, monkeypatch):
    monkeypatch.setattr(showcase, "_check_date", lambda text: None)
    for date in ("..", "../..", str(run.tmp / "pics")):
        assert run(VALID, "--date", date) == 2
        assert capsys.readouterr().err == "showcase: --date must be YYYY-MM-DD\n"
    assert run.calls["capture"] == []
    assert all((d / "keep.png").exists() for d in (run.tmp, run.tmp / "a", run.out, run.tmp / "pics"))
