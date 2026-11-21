"""F23-07: both private Point Buchon block files exist, from this run, before the CMECS comparison.

The workflow is replayed from its own text in a clean temporary tree: each step "runs" by
writing synthetic placeholder files for the outputs it names, and only after its named inputs
exist. The comparison step is the real ``block_paths`` check from the audit script (loaded
with stub GIS modules, so this file needs no survey stack). Every file is synthetic.
"""
import importlib.util
import re
import sys
import types

import pytest

from tests._support import ROOT

WORKFLOW = ROOT / ".github/workflows/research-fish-survey.yml"
SCRIPT = ROOT / "research/scripts/audit_point_buchon_cmecs_blocks.py"
JOB = "point-buchon-original-pair"
COMPARISON = "audit_point_buchon_cmecs_blocks.py"
ROV_PRODUCER = "audit_point_buchon_rov_access_blocks.py"
CSUMB_PRODUCER = "audit_point_buchon_2009_access_blocks.py"
INPUT_FLAGS = r"--(?:mpas|federal|enc|blocks|access|archive)"
OUTPUT_FLAGS = r"--(?:output|private-blocks)"


def job_steps():
    text = WORKFLOW.read_text()
    job = re.search(rf"^  {JOB}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n)", text, re.S | re.M).group(1)
    steps = re.split(r"^      - ", job.split("    steps:\n", 1)[1], flags=re.M)
    return [step for step in steps if step.strip()]


def paths(flags, step):
    return [m.strip("'\"") for m in re.findall(rf"{flags}\s+(\S+)", step)]


def find(steps, needle):
    hits = [i for i, step in enumerate(steps) if needle in step]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


@pytest.fixture
def cmecs(monkeypatch):
    shapefile = types.ModuleType("shapefile")
    geometry = types.ModuleType("shapely.geometry")
    geometry.box = geometry.shape = lambda *a, **k: None
    strtree = types.ModuleType("shapely.strtree")
    strtree.STRtree = object
    shapely = types.ModuleType("shapely")
    for name, mod in (("shapefile", shapefile), ("shapely", shapely),
                      ("shapely.geometry", geometry), ("shapely.strtree", strtree)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("f23_07_cmecs_blocks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(steps, tmp_path, cmecs):
    """Run the steps in order in an empty tree; return the step names reached before a failure."""
    reached = []
    for step in steps:
        for need in paths(INPUT_FLAGS, step):
            assert (tmp_path / need).is_file(), f"{need} used before any step wrote it"
        if COMPARISON in step:
            cmecs.block_paths(tmp_path / "var/review")
            reached.append("comparison")
            continue
        for out in paths(OUTPUT_FLAGS, step):
            target = tmp_path / out
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("synthetic current-run placeholder\n")
        reached.append(step.splitlines()[0])
    return reached


def test_both_private_block_producers_precede_the_comparison():
    steps = job_steps()
    comparison = find(steps, COMPARISON)
    for producer in (CSUMB_PRODUCER, ROV_PRODUCER):
        index = find(steps, producer)
        assert "--private-blocks" in steps[index]
        assert index < comparison
    # The research-only access check for the ROV blocks also runs before the comparison.
    assert find(steps, "check_point_buchon_rov_access_change.py") < comparison


def test_clean_tree_reaches_comparison_with_two_current_run_inputs(tmp_path, cmecs):
    for name in cmecs.BLOCK_FILES.values():
        assert not (tmp_path / "var/review" / name).exists()
    reached = replay(job_steps(), tmp_path, cmecs)
    assert "comparison" in reached
    for name in cmecs.BLOCK_FILES.values():
        assert (tmp_path / "var/review" / name).read_text().startswith("synthetic current-run")


def test_rov_producer_after_comparison_fails_explicitly(tmp_path, cmecs):
    steps = job_steps()
    steps.append(steps.pop(find(steps, ROV_PRODUCER)))  # old order: ROV blocks produced later
    with pytest.raises(FileNotFoundError, match="historical_rov.*" + ROV_PRODUCER):
        replay(steps, tmp_path, cmecs)
    assert not (tmp_path / "var/review/point-buchon-rov-100m-blocks.geojson").exists()


def test_missing_producer_is_named_and_stops_before_hashing(tmp_path, cmecs):
    with pytest.raises(FileNotFoundError) as both:
        cmecs.audit(tmp_path / "absent.zip", tmp_path)
    assert CSUMB_PRODUCER in str(both.value) and ROV_PRODUCER in str(both.value)
    (tmp_path / cmecs.BLOCK_FILES["original_csumb_depth"]).write_text("{}")
    with pytest.raises(FileNotFoundError) as one:
        cmecs.audit(tmp_path / "absent.zip", tmp_path)
    assert ROV_PRODUCER in str(one.value) and CSUMB_PRODUCER not in str(one.value)
    assert "absent.zip" not in str(one.value)  # failed on the block file, before the archive


def test_both_present_blocks_are_accepted(tmp_path, cmecs):
    for name in cmecs.BLOCK_FILES.values():
        (tmp_path / name).write_text("{}")
    assert set(cmecs.block_paths(tmp_path)) == set(cmecs.BLOCK_FILES)


def test_no_private_block_geojson_is_uploaded():
    text = WORKFLOW.read_text()
    for block in re.findall(r"upload-artifact.*?path: \|\n((?:            .*\n)+)", text):
        assert "blocks.geojson" not in block
    assert not re.search(r"path:.*blocks\.geojson", text)
