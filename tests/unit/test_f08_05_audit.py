"""AIS process output must not echo private Worker failure details (F08-05)."""
from email.message import Message
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from skippercast.fleet.ais import process
from skippercast.fleet.ais.__main__ import main
from skippercast.fleet.ais.label import refusal


ROW_ID = "synthetic-private-vessel-row"
BASE = "https://worker.invalid"


def worker_with(opener, **kwargs):
    return process.Worker(BASE, opener=opener, token_source=lambda: "synthetic", **kwargs)


@pytest.mark.parametrize("status", [200, 400])
def test_activity_response_at_process_cli(status, monkeypatch, capsys):
    body = (b'{"trips": 1}' if status == 200 else
            json.dumps({"error": f"unknown vessel {ROW_ID} in region XX"}).encode())
    stream = io.BytesIO(body)

    def open_activity(request, *, timeout):
        assert request.full_url == f"{BASE}/api/fleet/jobs/activity"
        assert request.method == "POST"
        if status == 400:
            raise HTTPError(request.full_url, status, f"Worker refused {ROW_ID}", Message(), stream)
        return stream

    worker = worker_with(open_activity)
    errors = []

    def push_activity(region, client, **kwargs):
        try:
            return client.post("activity", {"region": region})
        except process.WorkerError as error:
            errors.append(str(error))
            raise

    monkeypatch.setattr(process, "load_region", lambda region: region)
    monkeypatch.setattr(process, "worker_base", lambda: BASE)
    monkeypatch.setattr(process, "Worker", lambda _: worker)
    monkeypatch.setattr(process, "run", push_activity)

    code = main(["process", "--region", "XX"])
    output = capsys.readouterr()
    assert all(ROW_ID not in text for text in (*errors, output.err, output.out))
    assert stream.closed
    if status == 400:
        assert code == 2
        assert output.out == ""  # stdout is the workflow's step-summary input
        assert errors == ["activity: HTTP 400 http_error"]
        assert output.err == f"fleet ais process: {errors[0]}\n"
    else:
        assert code == 0
        assert output.err == ""
        assert json.loads(output.out) == {"trips": 1}


@pytest.mark.parametrize("status", [503, None])
def test_retries_keep_only_safe_failure_fields(status):
    streams, sleeps = [], []

    def fail(request, *, timeout):
        if status is None:
            raise URLError(ROW_ID)
        stream = io.BytesIO(ROW_ID.encode())
        streams.append(stream)
        raise HTTPError(request.full_url, status, ROW_ID, Message(), stream)

    worker = worker_with(fail, attempts=2, sleep=sleeps.append)
    with pytest.raises(process.WorkerError) as caught:
        worker.get(f"unknown/{ROW_ID}", cursor=ROW_ID)
    assert str(caught.value) == ("other: HTTP 503 http_error" if status else "other: transport_error")
    assert caught.value.__context__ is None
    assert sleeps == [2.0]
    if status:
        assert len(streams) == 2 and all(stream.closed for stream in streams)


@pytest.mark.parametrize(("status", "detail", "diagnostic"), [
    (409, f"labels[1]: overlaps the drift-anchor label from {ROW_ID}", "overlap, labels[1]"),
    (400, f"labels[0]: the range must fall within the trip ({ROW_ID})", "window, labels[0]"),
    (400, f"labels[0]: invalid {ROW_ID}", "validation, labels[0]"),
    (400, f"unknown field: {ROW_ID}", "validation"),
])
def test_label_refusal_preserves_only_known_diagnostic(status, detail, diagnostic):
    def reject(request, *, timeout):
        stream = io.BytesIO(json.dumps({"error": detail}).encode())
        raise HTTPError(request.full_url, status, "Rejected", Message(), stream)

    with pytest.raises(process.WorkerError) as caught:
        worker_with(reject).post("labels", {"labels": [{}, {}]})
    assert ROW_ID not in str(caught.value)
    assert refusal(str(caught.value)) == f"the Worker refused the labels (HTTP {status}, {diagnostic})"
