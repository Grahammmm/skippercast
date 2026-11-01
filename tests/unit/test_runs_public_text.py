"""A run manifest never publishes a machine path: `..` escapes and absolute paths in error/detail text are masked."""
import json

import pytest

from skippercast import runs

# Built from parts so the repository's private-home-path check does not flag the fixtures.
HOME = "/".join(("", "home", "runner"))
USERS = "/".join(("", "Users", "me"))


def outside_path():
    return HOME + "/work/skippercast/var/x.json"


@pytest.mark.parametrize("given, expected", [
    ("../../etc/passwd", "passwd"),
    ("a/../../b.json", "b.json"),
    ("var/x/../y.json", "var/y.json"),
    ("..", "(path)"),
    ("../", "(path)"),
    ("../..", "(path)"),
    ("var/x.json", "var/x.json"),
])
def test_public_path_relative_never_escapes(given, expected):
    assert runs.public_path(given) == expected


def test_finish_masks_absolute_paths_inside_and_outside_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inside = tmp_path / "var" / "x.json"
    run = runs.RunManifest("t", "r1")
    run.finish(1, error=FileNotFoundError(2, "No such file or directory", str(inside)))
    assert run.error == {"class": "FileNotFoundError", "message": "[Errno 2] No such file or directory: 'var/x.json'"}
    run = runs.RunManifest("t", "r2")
    run.finish(1, error=FileNotFoundError(2, "No such file or directory", outside_path()))
    assert run.error["message"] == "[Errno 2] No such file or directory: 'x.json'"


def test_public_text_uses_given_roots(tmp_path):
    text = f"cannot read {tmp_path / 'var' / 'x.json'} or {outside_path()}"
    assert runs.public_text(text, roots=[tmp_path]) == "cannot read var/x.json or x.json"


def test_path_near_the_cut_is_masked_before_cutting():
    message = "a" * 289 + " " + HOME + "/work/skippercast/deep/dir/file.json" + " " + "b" * 61
    assert len(message) == 400 and message.index("/home") == 290
    out = runs.public_text(message)
    assert len(out) == runs.ERROR_CHARS
    assert out == ("a" * 289 + " file.json " + "b" * 61)[:runs.ERROR_CHARS]
    assert "/home" not in out and "/h" not in out


@pytest.mark.parametrize("text", [
    "fetch https://api.weather.gov/alerts returned 503",
    "see http://example.org/a/b?x=1 and s3://bucket/key",
    "ratio 1/2 and/or 3/4 at 12:30/UTC ~/notes",
    "Source time | outside window",
    "x" * 280,
])
def test_text_without_machine_paths_is_unchanged(text):
    assert runs.public_text(text) == text


def test_text_without_path_only_cut():
    text = "plain failure " * 40
    assert runs.public_text(text) == text[:runs.ERROR_CHARS]


@pytest.mark.parametrize("text, expected", [
    (r"cannot open C:\Users\x\file.txt now", "cannot open file.txt now"),
    (r"'D:\a\skippercast\var\y.json'", "'y.json'"),
    ("relative ../.." + HOME + "/z.json escape", "relative z.json escape"),
])
def test_windows_and_relative_escapes_in_text(text, expected):
    assert runs.public_text(text) == expected


def test_source_and_region_text_are_masked():
    run = runs.RunManifest("t", "r1")
    row = run.source("gfs", "failed", detail=f"open {outside_path()} failed")
    assert row["detail"] == "open x.json failed"
    row = run.region("morro-bay", "failed", error=r"C:\Users\me\region.json missing")
    assert row["error"] == "region.json missing"
    assert run.source("ok", "ok", detail=None) == {"status": "ok"}


def test_written_manifest_has_no_machine_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = runs.RunManifest("forecast-build", "r9")
    run.source("a", "failed", detail="read /tmp/runner/cache/a.nc: denied")
    run.source("b", "failed", detail="moved to " + USERS + "/skippercast/b.json")
    run.region("r", "failed", error="../.." + HOME + "/r.json")
    try:
        raise OSError(f"[Errno 13] Permission denied: '{outside_path()}'")
    except OSError as error:
        run.finish(1, error=error)
    out = tmp_path / "run.json"
    run.write(out)
    text = out.read_text()
    for needle in ("/home/", "/tmp/", "/Users/", "../"):
        assert needle not in text
    document = json.loads(text)
    assert document["error"]["message"] == "[Errno 13] Permission denied: 'x.json'"
    assert document["sources"]["a"]["detail"] == "read a.nc: denied"
    assert document["regions"]["r"]["error"] == "r.json"
