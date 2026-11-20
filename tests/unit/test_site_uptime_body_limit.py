import io
import json
from datetime import datetime, timezone
from unittest import mock

from scripts import site_uptime_alert as uptime

CAP = 1 << 20
HEALTH = "/api/health"
MANIFEST = "/feeds/tiles/seafloor/manifest-morro-bay.json"
NOW = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)


def padded(obj_text, size=CAP):
    return obj_text + b" " * (size - len(obj_text))


MANIFEST_OK = json.dumps({"status": "ready", "region": "morro-bay", "expires_at": "2099-01-01T00:00:00Z"}).encode()


class Response(io.BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body)
        self.limits = []

    def read(self, size=-1):
        self.limits.append(size)
        return super().read(size)


class Opener:
    def __init__(self, bodies):
        self.bodies, self.responses = {p: list(b) for p, b in bodies.items()}, []

    def open(self, req, timeout=None):
        queue = self.bodies["/" + req.full_url.split("://", 1)[1].split("/", 1)[1]]
        response = Response(queue.pop(0) if len(queue) > 1 else queue[0])
        self.responses.append(response)
        return response


def probe(path, body):
    opener = Opener({path: [body]})
    with mock.patch.object(uptime.request, "build_opener", return_value=opener):
        return uptime.probe("http://site.test", path, 1), opener


def test_health_valid_prefix_with_trailing_garbage_is_down():
    result, opener = probe(HEALTH, padded(b"{}") + b"NOT-JSON")
    assert result == {"path": HEALTH, "status": 200, "error": "not JSON"}
    assert opener.responses[0].limits == [CAP, 1]


def test_manifest_valid_prefix_over_cap_is_unavailable():
    result, _ = probe(MANIFEST, padded(MANIFEST_OK) + b"x")
    assert result == {"path": MANIFEST, "status": 200, "error": "habitat unavailable"}


def test_exact_cap_at_eof_is_accepted():
    for path, body in ((HEALTH, b"{}"), (MANIFEST, MANIFEST_OK)):
        result, opener = probe(path, padded(body))
        assert result is None
        assert opener.responses[0].limits == [CAP, 1]


def test_short_body_preserves_single_read():
    result, opener = probe(HEALTH, b"{}")
    assert result is None and opener.responses[0].limits == [CAP]


def test_oversize_then_healthy_retry_recovers(tmp_path):
    opener = Opener({HEALTH: [padded(b"{}") + b"junk", b"{}"]})
    report, sleeps = tmp_path / "report.json", []
    with mock.patch.object(uptime.request, "build_opener", return_value=opener):
        code = uptime.main(["--base", "http://site.test", "--report", str(report), "--dry-run", "--paths", HEALTH],
                           runner=mock.Mock(side_effect=AssertionError("gh must not run")), now=NOW, sleep=sleeps.append)
    assert code == 0 and len(opener.responses) == 2 and len(sleeps) == 1
    assert json.loads(report.read_text())["failures"] == []
