"""Offline coverage of the regional dispatcher's previous-feed boundary."""
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from scripts import refresh_regions


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
REGION = {"id": "synthetic"}


@pytest.mark.parametrize(("kind", "module", "prior_name"), [
    ("intelligence", "intelligence", "intelligence.json"),
    ("habitat", "habitat_dynamics", "habitat-dynamics.json"),
])
@pytest.mark.parametrize("conditions", ['{}', '{'], ids=["valid", "malformed"])
def test_kind_specific_refresh_ignores_previous_conditions(tmp_path, kind, module, prior_name, conditions):
    # An eager conditions parse used to prevent either collector from running.
    previous = tmp_path / "previous"
    prior_region = previous / "regions" / REGION["id"]
    prior_region.mkdir(parents=True)
    (prior_region / prior_name).write_text('{}', encoding="utf-8")
    (prior_region / "latest.json").write_text(conditions, encoding="utf-8")
    output = tmp_path / "output"
    result = {"completed_at": NOW.isoformat(), "health": {"status": "ok", "issues": []}}

    with patch(f"skippercast.pipeline.{module}.run", return_value=result) as collector, \
            patch.object(refresh_regions, "publish_fronts"):
        row = refresh_regions.refresh_region(kind, REGION, output, previous, NOW, REGION["id"])

    collector.assert_called_once_with(REGION["id"], output, previous, NOW)
    assert row["status"] == "ok"


@pytest.mark.parametrize("kind", ["daily", "live"])
def test_condition_refresh_still_parses_default_region_alias(tmp_path, kind):
    # The legacy alias is still consumed, and malformed JSON must not reach a collector.
    latest = tmp_path / "latest.json"
    prior = {"sources": {}}
    latest.write_text(json.dumps(prior), encoding="utf-8")
    output = tmp_path / "output"
    args = kind, REGION, output, tmp_path, NOW, REGION["id"]

    # Stop at the collector so this test does not exercise the output writers.
    with patch.object(refresh_regions, kind, side_effect=RuntimeError("collector reached")) as collector:
        with pytest.raises(RuntimeError, match="collector reached"):
            refresh_regions.refresh_region(*args)
        collector.assert_called_once_with(NOW, prior, region_id=REGION["id"])
        collector.reset_mock()

        latest.write_text('{', encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            refresh_regions.refresh_region(*args)
        collector.assert_not_called()
