import io
import json
from datetime import datetime, timezone
from unittest import mock

import pytest

from scripts import site_uptime_alert as uptime

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
CANARY = "BODY-CANARY"
HEALTH = "/api/health"
MANIFEST = "/feeds/tiles/seafloor/manifest-morro-bay.json"
DEEP_ARRAYS = ('{"nested":' + "[" * 10000 + "0" + "]" * 10000 + "}").encode()
DEEP_OBJECTS = ('{"a":' * 10000 + '"' + CANARY + '"' + "}" * 10000).encode()
GOOD_MANIFEST = json.dumps({"status": "ready", "region": "morro-bay", "expires_at": "2099-01-01T00:00:00Z"}).encode()
GOOD = {HEALTH: b'{"ok": {"a": [1, {"b": 2}]}}', MANIFEST: GOOD_MANIFEST}
MAPPING = {HEALTH: {"path": HEALTH, "status": 200, "error": "not JSON"},
           MANIFEST: {"path": MANIFEST, "status": 200, "error": "habitat unavailable"}}


class Response(io.BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body)
        self.limits = []

    def read(self, size=-1):
        self.limits.append(size)
        return super().read(size)


class Opener:
    """Serves queued bodies per path as HTTP 200 through the real json decoder; never touches the network."""

    def __init__(self, bodies, fail=None):
        self.bodies, self.urls, self.responses, self.fail = {p: list(b) for p, b in bodies.items()}, [], [], fail

    def open(self, req, timeout=None):
        if self.fail:
            raise self.fail
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.urls.append("/" + path)
        queue = self.bodies["/" + path]
        response = Response(queue.pop(0) if len(queue) > 1 else queue[0])
        self.responses.append(response)
        return response


def run(bodies, tmp_path, fail=None):
    opener, runner, sleeps = Opener(bodies, fail), mock.Mock(side_effect=AssertionError("gh must not run")), []
    report = tmp_path / "report.json"
    with mock.patch.object(uptime.request, "build_opener", return_value=opener):
        code = uptime.main(["--base", "http://site.test", "--report", str(report), "--dry-run", "--paths", *bodies],
                           runner=runner, now=NOW, sleep=sleeps.append)
    return code, opener, runner, sleeps, report


@pytest.mark.parametrize("path", [HEALTH, MANIFEST])
@pytest.mark.parametrize("body", [DEEP_ARRAYS, DEEP_OBJECTS], ids=["arrays", "objects"])
def test_real_deep_json_is_classified_per_path(path, body):
    opener = Opener({path: [body]})
    with mock.patch.object(uptime.request, "build_opener", return_value=opener):
        result = uptime.probe("http://site.test", path, 1)
    assert result == MAPPING[path]
    assert len(opener.urls) == 1 and opener.responses[0].closed
    assert CANARY not in json.dumps(result) and result.keys() == {"path", "status", "error"}


@pytest.mark.parametrize("path", [HEALTH, MANIFEST])
def test_deep_body_retries_once_then_reports_down(path, tmp_path):
    code, opener, runner, sleeps, report = run({path: [DEEP_ARRAYS]}, tmp_path)
    assert code == 0 and opener.urls == [path, path] and sleeps == [uptime.RETRY_DELAY]
    assert json.loads(report.read_text()) == {"down": True, "failures": [MAPPING[path]], "checked_at": NOW.isoformat()}
    runner.assert_not_called()


@pytest.mark.parametrize("path", [HEALTH, MANIFEST])
def test_deep_first_body_then_healthy_retry_recovers(path, tmp_path):
    code, opener, runner, sleeps, report = run({path: [DEEP_OBJECTS, GOOD[path]]}, tmp_path)
    assert code == 0 and opener.urls == [path, path] and len(sleeps) == 1
    assert json.loads(report.read_text()) == {"down": False, "failures": [], "checked_at": NOW.isoformat()}
    runner.assert_not_called()


def test_healthy_json_and_html_paths_remain_compatible(tmp_path):
    bodies = {HEALTH: [GOOD[HEALTH]], MANIFEST: [GOOD[MANIFEST]], "/": [b"<html>" + DEEP_ARRAYS], "/map": [b"not json"]}
    code, opener, runner, sleeps, report = run(bodies, tmp_path)
    assert code == 0 and sleeps == [] and len(opener.urls) == 4
    assert json.loads(report.read_text())["down"] is False
    assert all(r.limits == [1 << 20] for r in opener.responses[:2])


def test_internal_probe_errors_still_propagate(tmp_path):
    with pytest.raises(RuntimeError):
        run({HEALTH: [b"{}"]}, tmp_path, fail=RuntimeError("bug"))
    assert not (tmp_path / "report.json").exists()
