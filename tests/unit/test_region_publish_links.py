"""RF1120-5: region_publish writes through fresh temps and never follows a planted PUBLISH.md link."""
import hashlib
import json
import os

import pytest

from tests.unit.test_region_publish import FROZEN, OLD, ROWS, SRC, publish, rp, runner, tree, world


def passed_ledger(w):
    identity = json.loads((w[1] / "BUILD.json").read_text())["build_sha256"]
    return ROWS.replace(OLD, f"syn-bay,publish,reviewed,none,run-20261105,{identity},PASS (visual not inspected),gpt-test,,")


def outside(base, text="outside\n"):
    target = base / "outside" / "victim.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def leftovers(*folders):
    return sorted(p.name for f in folders for p in f.iterdir() if p.name.endswith(".tmp") and not p.is_symlink())


def test_approved_run_publishes_byte_for_byte_as_before(tmp_path):
    w = world(tmp_path)
    assert publish(w) == 0
    assert hashlib.sha256((w[1] / "PUBLISH.md").read_bytes()).hexdigest() == FROZEN
    assert w[2].read_text() == passed_ledger(w)
    assert (w[0] / "catalog/depth-contours/syn-bay.geojson").read_bytes() == (w[1] / "candidate/syn-bay.geojson").read_bytes()
    assert leftovers(tmp_path, w[0] / "catalog/depth-contours") == []


def test_planted_ledger_tmp_link_is_never_followed(tmp_path):
    w, victim = world(tmp_path), outside(tmp_path)
    link = tmp_path / "LEDGER.csv.tmp"
    link.symlink_to(victim)
    assert publish(w) == 0
    assert w[2].read_text() == passed_ledger(w) and not w[2].is_symlink()
    assert victim.read_text() == "outside\n" and link.is_symlink() and os.readlink(link) == str(victim)


def test_planted_catalog_tmp_link_is_never_followed_and_the_result_is_unchanged(tmp_path):
    clean, w, victim = world(tmp_path / "clean"), world(tmp_path / "w"), outside(tmp_path)
    link = w[0] / "catalog/depth-contours/syn-bay.geojson.tmp"
    link.symlink_to(victim)
    assert publish(clean) == 0 and publish(w) == 0
    assert victim.read_text() == "outside\n" and link.is_symlink()
    target = w[0] / "catalog/depth-contours/syn-bay.geojson"
    assert not target.is_symlink() and target.read_bytes() == (w[1] / "candidate/syn-bay.geojson").read_bytes()
    assert (w[1] / "PUBLISH.md").read_text() == (clean[1] / "PUBLISH.md").read_text()
    assert w[2].read_text() == passed_ledger(w)


@pytest.mark.parametrize("dangling", [True, False])
def test_publish_md_link_is_refused_like_an_existing_file(tmp_path, capsys, dangling):
    w = world(tmp_path)
    victim = outside(tmp_path).with_name("new.md") if dangling else outside(tmp_path)
    (w[1] / "PUBLISH.md").symlink_to(victim)
    before = tree(w[0])
    assert publish(w) == 1
    assert "PUBLISH.md already exists" in capsys.readouterr().err
    assert (victim.exists() is not dangling) and (dangling or victim.read_text() == "outside\n")
    assert tree(w[0]) == before and w[2].read_text() == ROWS and (w[1] / "PUBLISH.md").is_symlink()


def test_publish_md_link_planted_after_the_check_is_not_written_through(tmp_path, capsys):
    w, victim, inner = world(tmp_path), outside(tmp_path).with_name("late.md"), runner()

    def run(cmd, cwd=None, env=None):
        if cmd[1].endswith("region_review.py") and not os.path.lexists(w[1] / "PUBLISH.md"):
            (w[1] / "PUBLISH.md").symlink_to(victim)
        return inner(cmd, cwd, env)
    code = rp.main([str(w[1]), "--repo", str(w[0]), "--ledger", str(w[2])], run=run,
                   loader=lambda root, rid: ({"id": rid, "name": "Syn Bay", "status": "preview"}, SRC))
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("region_publish: ") and "Traceback" not in err
    assert not victim.exists() and w[2].read_text() == ROWS


def test_write_failure_in_put_leaves_no_temp_and_is_reported_by_main(tmp_path, capsys, monkeypatch):
    w, real, failed = world(tmp_path), os.replace, []

    def replace(src, dst):
        if str(dst).endswith("LEDGER.csv") and not failed:
            failed.append(dst)
            raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(rp.os, "replace", replace)
    assert publish(w) == 1
    err = capsys.readouterr().err
    assert failed and err == "region_publish: disk full\n"
    assert w[2].read_text() == ROWS and leftovers(tmp_path, w[0] / "catalog/depth-contours") == []


def test_held_run_still_writes_held_publish_md_and_the_ledger_row(tmp_path):
    w, victim = world(tmp_path, source="s-c"), outside(tmp_path)
    (tmp_path / "LEDGER.csv.tmp").symlink_to(victim)
    before = tree(w[0])
    assert publish(w) == 1
    assert "HELD: source-candidate:s-c\n" in (w[1] / "PUBLISH.md").read_text() and not (w[1] / "PUBLISH.md").is_symlink()
    identity = json.loads((w[1] / "BUILD.json").read_text())["build_sha256"]
    assert w[2].read_text() == ROWS.replace(OLD, f"syn-bay,review,held,source-candidate:s-c,run-20261105,{identity},PASS,gpt-test,,")
    assert tree(w[0]) == before and victim.read_text() == "outside\n"
