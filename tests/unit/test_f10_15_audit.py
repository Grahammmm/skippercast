"""Malformed nested durations fail one manifest without suppressing the next."""
import json

import pytest

from skippercast import report, runs


def manifest(job, **rows):
    return {"schema_version": 1, "job": job, "run_id": "1",
            "started_at": "2026-01-01T00:00:00Z", "status": "ok",
            "inputs": [], "outputs": [], "sources": {}, **rows}


@pytest.mark.parametrize("section", ["sources", "regions"])
@pytest.mark.parametrize("value", ["fixture-value", True, float("nan"), float("inf"),
                                   float("-inf"), 10**400],
                         ids=["text", "bool", "nan", "inf", "negative-inf", "overflow"])
def test_nested_duration_error_names_only_the_field(section, value):
    doc = manifest("bad-job", **{section: {"fixture-row": {"status": "ok", "duration_ms": value}}})
    with pytest.raises(ValueError) as caught:
        runs.validate(doc)
    assert str(caught.value) == f"Run manifest {section}.duration_ms must be a finite number or null"


def test_bad_regional_manifest_does_not_hide_good_summary(tmp_path, capsys):
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text(json.dumps(manifest("bad-job", regions={
        "fixture-row": {"status": "ok", "duration_ms": "fixture-value"},
    })))
    good.write_text(json.dumps(manifest("good-job", regions={
        "fixture-region": {"status": "ok", "duration_ms": 1500},
    }, sources={"fixture-source": {"status": "degraded", "duration_ms": None}})))

    assert report.main([str(good)]) == 0
    valid = capsys.readouterr()
    assert "### good-job:" in valid.out
    assert "| fixture-region | ✅ ok | – | 1.5 s |" in valid.out
    assert "| fixture-source | ⚠️ degraded | – |" in valid.out
    assert not valid.err

    assert report.main([str(bad), str(good)]) == 1
    result = capsys.readouterr()
    assert result.out == valid.out
    assert result.err == f"{bad}: ValueError: Run manifest regions.duration_ms must be a finite number or null\n"
