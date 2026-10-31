"""RF1105-24: region_build and region_review refuse planted symlinks before any builder call or write."""
import json

import pytest

from tests.unit.test_region_build import build, world  # noqa: F401  (pytest fixture)
from tests.unit.test_region_review import CLEAN, make_run, region, rr  # noqa: F401  (pytest fixture)


def plant(w, name, setup):
    """build()'s INTAKE edit hook, used to plant links after intake and before region_build runs."""
    def edit(text):
        setup(w["tmp"] / name)
        return text
    return build(w, name, edit)


@pytest.mark.parametrize("name", ["BUILD.json.tmp", "BUILD.json"])
def test_build_refuses_a_linked_record_file(world, capsys, name):
    outside = world["tmp"] / "outside.json"
    outside.write_text("keep")
    code, folder, _ = plant(world, "run", lambda f: (f / name).symlink_to(outside))
    assert code == 1 and f"refusing a symlinked {name} in the run folder" in capsys.readouterr().err
    other = {"BUILD.json": "BUILD.json.tmp", "BUILD.json.tmp": "BUILD.json"}[name]
    assert outside.read_text() == "keep" and world["log"] == [] and (folder / name).is_symlink() and not (folder / other).exists()


def test_build_refuses_a_dangling_build_json(world, capsys):
    code, folder, _ = plant(world, "run", lambda f: (f / "BUILD.json").symlink_to(world["tmp"] / "nowhere.json"))
    assert code == 1 and "symlinked BUILD.json" in capsys.readouterr().err
    assert world["log"] == [] and not (world["tmp"] / "nowhere.json").exists()


@pytest.mark.parametrize("name", ["candidate", "held"])
def test_build_refuses_a_linked_output_dir(world, capsys, name):
    elsewhere = world["tmp"] / "elsewhere"
    elsewhere.mkdir()
    code, folder, _ = plant(world, "run", lambda f: (f / name).symlink_to(elsewhere, target_is_directory=True))
    assert code == 1 and f"refusing a symlinked {name} in the run folder" in capsys.readouterr().err
    assert world["log"] == [] and list(elsewhere.iterdir()) == [] and not (folder / "BUILD.json").exists()


def test_build_regular_stale_tmp_is_overwritten_and_build_proceeds(world):
    code, folder, calls = plant(world, "run", lambda f: (f / "BUILD.json.tmp").write_text("stale"))
    assert code == 0 and len(calls) == 2 and not (folder / "BUILD.json.tmp").exists()
    assert json.loads((folder / "BUILD.json").read_text())["schema"] == "region-build-v1"


def test_build_regular_existing_build_json_still_refused(world, capsys):
    code, folder, _ = plant(world, "run", lambda f: (f / "BUILD.json").write_text("old"))
    assert code == 1 and "Refusing to overwrite" in capsys.readouterr().err
    assert world["log"] == [] and (folder / "BUILD.json").read_text() == "old"


@pytest.fixture
def run(tmp_path, region):
    """A clean reviewed run whose REVIEW-PACKET is moved aside so a fresh review would write again."""
    make_run(tmp_path / "run", region, CLEAN)
    (tmp_path / "run/REVIEW-PACKET").rename(tmp_path / "old-packet")
    return tmp_path / "run"


def test_review_refuses_a_linked_packet_dir(run, capsys):
    outside = run.parent / "outside"
    outside.mkdir()
    (run / "REVIEW-PACKET").symlink_to(outside, target_is_directory=True)
    assert rr.main([str(run)]) == 2 and "refusing a symlinked REVIEW-PACKET in the run folder" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", ["review.json.tmp", "review.json"])
def test_review_refuses_a_linked_packet_file(run, capsys, name):
    outside = run.parent / "outside.json"
    outside.write_text("keep")
    (run / "REVIEW-PACKET").mkdir()
    (run / "REVIEW-PACKET" / name).symlink_to(outside)
    assert rr.main([str(run)]) == 2 and f"refusing a symlinked REVIEW-PACKET/{name}" in capsys.readouterr().err
    assert outside.read_text() == "keep" and sorted(p.name for p in (run / "REVIEW-PACKET").iterdir()) == [name]


def test_review_refuses_a_dangling_review_json(run, capsys):
    (run / "REVIEW-PACKET").mkdir()
    (run / "REVIEW-PACKET/review.json").symlink_to(run.parent / "nowhere.json")
    assert rr.main([str(run)]) == 2 and "symlinked REVIEW-PACKET/review.json" in capsys.readouterr().err
    assert not (run.parent / "nowhere.json").exists()


def test_review_regular_stale_tmp_is_overwritten(run):
    (run / "REVIEW-PACKET").mkdir()
    (run / "REVIEW-PACKET/review.json.tmp").write_text("stale")
    assert rr.main([str(run)]) == 0 and not (run / "REVIEW-PACKET/review.json.tmp").exists()
    assert json.loads((run / "REVIEW-PACKET/review.json").read_text())["schema"] == "region-review-v1"


def test_review_check_reads_through_a_linked_packet_unchanged(run, capsys):
    (run / "REVIEW-PACKET").symlink_to(run.parent / "old-packet", target_is_directory=True)
    rows = "".join(f"| {c['id']} | PASS | confirmed |\n" for c in json.loads((run / "REVIEW-PACKET/review.json").read_text())["checks"])
    (run / "REVIEW.md").write_text(
        f"# REVIEW syn-bay run\n{rr.MD_BANNER}\nBuild-SHA256: {'f' * 64}\nReviewer-Runtime: gpt-6.1-sol\nReviewer-Family: openai\n"
        f"| check | verdict | reason |\n|---|---|---|\n{rows}| visual | not-visually-inspected | none |\nOverall: PASS\n")
    before = sorted(p.name for p in (run.parent / "old-packet").iterdir())
    assert rr.main(["--check", str(run)]) == 0 and "REVIEW OK syn-bay PASS" in capsys.readouterr().out
    assert sorted(p.name for p in (run.parent / "old-packet").iterdir()) == before
