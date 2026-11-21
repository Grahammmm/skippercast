"""Contract fixtures for the offline half of a relief live check."""

import pytest

from skippercast.relief.live_deploy import LiveError, deploy_verdict, parse_deploy, pointer_verdict


MERGE = "ab0123456789" * 3 + "cdef"
DESCENDANT = "1" * 40
OLDER = "2" * 40
SIDE_BRANCH = "f" * 40
UNKNOWN = "0" * 40
POINTER = b'{"schema":"sc-relief-pointer/1","region":"fixture-region"}\n'


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param({"commit": MERGE}, id="C1: accept a full SHA without requiring optional fields"),
        pytest.param(
            {"commit": MERGE, "variables": {"FLEET_ENABLED": "false"}},
            id="C1: read commit from the deploy snapshot even with variables present",
        ),
    ],
)
def test_parse_deploy(doc):
    assert parse_deploy(doc) == MERGE


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param({"sha": MERGE}, id="C1: refuse missing commit even with a plausible alias"),
        pytest.param({"commit": MERGE[:-1]}, id="C1: refuse an abbreviated SHA"),
        pytest.param({"commit": MERGE + "a"}, id="C1: refuse an overlong SHA"),
        pytest.param({"commit": MERGE.upper()}, id="C1: refuse uppercase rather than normalize"),
        pytest.param({"commit": MERGE[:-1] + "g"}, id="C1: refuse non-hex at the correct length"),
        pytest.param({"commit": MERGE + "\n"}, id="C1: refuse trailing newline rather than trim"),
        pytest.param({"commit": 123}, id="C1: refuse a non-string commit without coercion"),
        pytest.param([MERGE], id="C1: refuse a non-object document as LiveError"),
        pytest.param(
            {"commit": "https://example.invalid/private/path", "body": "fixture-only-body"},
            id="C1: refuse malformed input without echoing its URL, path or body",
        ),
    ],
)
def test_parse_deploy_refusal(doc):
    with pytest.raises(LiveError) as caught:
        parse_deploy(doc)
    assert type(caught.value) is LiveError
    assert isinstance(caught.value, ValueError)
    assert str(caught.value) == "Expected a full lowercase hexadecimal deploy commit"


@pytest.mark.parametrize(
    ("deployed", "ancestry", "expected"),
    [
        pytest.param(MERGE, {}, {"check": "deploy", "status": "PASS", "reason": "equal"},
                     id="C2: equal commits pass without a lookup"),
        pytest.param(DESCENDANT, {(MERGE, DESCENDANT): True},
                     {"check": "deploy", "status": "PASS", "reason": "ancestor"},
                     id="C2: descendant passes even with a lexically smaller SHA"),
        pytest.param(OLDER, {(MERGE, OLDER): False, (OLDER, MERGE): True},
                     {"check": "deploy", "status": "FAIL", "reason": "stale"},
                     id="C2: older deployment is stale, not diverged"),
        pytest.param(SIDE_BRANCH, {(MERGE, SIDE_BRANCH): False, (SIDE_BRANCH, MERGE): False},
                     {"check": "deploy", "status": "FAIL", "reason": "diverged"},
                     id="C2: lexically greater side branch does not pass"),
        pytest.param(UNKNOWN, {(MERGE, UNKNOWN): None},
                     {"check": "deploy", "status": "FAIL", "reason": "unknown-commit"},
                     id="C2: unknown commit is not a negative ancestry result"),
        pytest.param(UNKNOWN, {(MERGE, UNKNOWN): False, (UNKNOWN, MERGE): None},
                     {"check": "deploy", "status": "FAIL", "reason": "unknown-commit"},
                     id="C2: inconclusive reverse lookup is not divergence"),
    ],
)
def test_deploy_verdict(deployed, ancestry, expected):
    def is_ancestor(a, b):
        return ancestry[a, b]

    assert deploy_verdict(MERGE, deployed, is_ancestor) == expected


@pytest.mark.parametrize(
    ("served", "expected"),
    [
        pytest.param(POINTER, {"check": "pointer", "status": "PASS", "reason": "identical"},
                     id="C3: byte-identical pointer passes"),
        pytest.param(None, {"check": "pointer", "status": "FAIL", "reason": "missing"},
                     id="C3: an absent response is missing"),
        pytest.param(b"", {"check": "pointer", "status": "FAIL", "reason": "differs"},
                     id="C3: empty response is present, not missing"),
        pytest.param(POINTER.rstrip(b"\n"), {"check": "pointer", "status": "FAIL", "reason": "differs"},
                     id="C3: equivalent JSON with different bytes fails"),
    ],
)
def test_pointer_verdict(served, expected):
    assert pointer_verdict(POINTER, served) == expected
