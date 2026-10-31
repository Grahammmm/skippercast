"""RF1105-4: region_publish writes the LEDGER row before PUBLISH.md (a failed write never sticks the run folder),
refuses a linked --ledger on both paths and reports a non-UTF-8 REVIEW.md as a named error."""
import json
import os

import pytest

from tests.unit.test_region_publish import OLD, ROWS, publish, rp, tree, world


def row(w, held=False):
    identity = json.loads((w[1] / "BUILD.json").read_text())["build_sha256"]
    tail = "review,held,source-candidate:s-c" if held else "publish,reviewed,none"
    return ROWS.replace(OLD, f"syn-bay,{tail},run-20261105,{identity},{'PASS' if held else 'PASS (visual not inspected)'},gpt-test,,")


def fail_once(monkeypatch, name, attr):
    """Patch rp.<attr> so the first call whose path ends with `name` raises OSError; returns the list of failed paths."""
    real, failed = getattr(rp if attr == "put" else rp.os, attr), []

    def patched(path, *args, **kwargs):
        if str(path).endswith(name) and not failed:
            failed.append(path)
            raise OSError(f"{attr} failed")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(rp if attr == "put" else rp.os, attr, patched)
    return failed


@pytest.mark.parametrize("source,held", [("s-a", False), ("s-c", True)])
def test_ledger_write_failure_leaves_no_publish_md_and_the_rerun_writes_the_row_once(tmp_path, capsys, monkeypatch, source, held):
    w = world(tmp_path, source=source)
    failed = fail_once(monkeypatch, "LEDGER.csv", "put")
    assert publish(w) == 1
    assert failed and capsys.readouterr().err == "region_publish: put failed\n"
    assert not os.path.lexists(w[1] / "PUBLISH.md") and w[2].read_bytes() == ROWS.encode()
    monkeypatch.undo()
    assert publish(w) == int(held)
    assert w[2].read_text() == row(w, held) and w[2].read_text().count("\nsyn-bay,") == 1
    assert ("HELD: source-candidate:s-c\n" if held else "# PUBLISH syn-bay") in (w[1] / "PUBLISH.md").read_text()


def test_publish_md_create_failure_after_the_ledger_write_allows_an_identical_rerun(tmp_path, capsys, monkeypatch):
    w = world(tmp_path)
    failed = fail_once(monkeypatch, "PUBLISH.md", "open")
    assert publish(w) == 1
    assert failed and capsys.readouterr().err == "region_publish: open failed\n"
    assert not os.path.lexists(w[1] / "PUBLISH.md") and w[2].read_text() == row(w)
    first = w[2].read_bytes()
    monkeypatch.undo()
    assert publish(w) == 0
    assert w[2].read_bytes() == first and (w[1] / "PUBLISH.md").read_text().startswith("# PUBLISH syn-bay run-20261105\n")


def test_held_run_still_writes_held_publish_md_and_the_held_row(tmp_path):
    w = world(tmp_path, source="s-c")
    before = tree(w[0])
    assert publish(w) == 1
    assert "HELD: source-candidate:s-c\n" in (w[1] / "PUBLISH.md").read_text()
    assert w[2].read_text() == row(w, held=True) and tree(w[0]) == before


def test_publish_md_appearing_during_the_checks_is_refused_before_the_ledger(tmp_path, capsys, monkeypatch):
    w, real = world(tmp_path), rp.check

    def check(folder, *args):
        out = real(folder, *args)
        (folder / "PUBLISH.md").write_text("someone else\n")
        return out
    monkeypatch.setattr(rp, "check", check)
    assert publish(w) == 1
    assert "PUBLISH.md already exists" in capsys.readouterr().err
    assert w[2].read_bytes() == ROWS.encode() and (w[1] / "PUBLISH.md").read_text() == "someone else\n"


def linked(tmp_path, w, dangling):
    link = tmp_path / "link" / "LEDGER.csv"
    link.parent.mkdir()
    link.symlink_to(tmp_path / "gone.csv" if dangling else w[2])
    return link


@pytest.mark.parametrize("dangling", [False, True])
def test_linked_ledger_is_refused_for_publish(tmp_path, capsys, dangling):
    w = world(tmp_path)
    w2, before = (w[0], w[1], linked(tmp_path, w, dangling)), tree(w[0])
    assert publish(w2) == 1
    assert capsys.readouterr().err == "region_publish: --ledger must be a regular file, not a link\n"
    assert w[2].read_bytes() == ROWS.encode() and not os.path.lexists(w[1] / "PUBLISH.md") and tree(w[0]) == before
    assert not (tmp_path / "gone.csv").exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_linked_ledger_is_refused_for_record_pr(tmp_path, capsys, dangling):
    w = world(tmp_path)
    link = linked(tmp_path, w, dangling)
    assert rp.main(["--record-pr", str(w[1]), "--pr", "1234", "--published-at", "2026-11-05", "--ledger", str(link)]) == 1
    assert capsys.readouterr().err == "region_publish: --ledger must be a regular file, not a link\n"
    assert w[2].read_bytes() == ROWS.encode() and link.is_symlink() and not (tmp_path / "gone.csv").exists()


def test_non_utf8_review_md_is_a_named_error_not_a_traceback(tmp_path, capsys):
    w = world(tmp_path)
    (w[1] / "REVIEW.md").write_bytes(b"\xff" + (w[1] / "REVIEW.md").read_bytes())
    before = tree(w[0])
    assert publish(w) == 1
    err = capsys.readouterr().err
    assert err.startswith("region_publish: ") and "utf-8" in err and "Traceback" not in err
    assert not os.path.lexists(w[1] / "PUBLISH.md") and w[2].read_bytes() == ROWS.encode() and tree(w[0]) == before


def test_utf8_review_md_is_read_as_utf8_whatever_the_locale(tmp_path, monkeypatch):
    w = world(tmp_path)
    review = (w[1] / "REVIEW.md").read_text().replace("gpt-test", "gpt-tést")
    (w[1] / "REVIEW.md").write_bytes(review.encode("utf-8"))
    real = rp.Path.read_text
    monkeypatch.setattr(rp.Path, "read_text", lambda self, encoding="latin-1", **kw: real(self, encoding=encoding, **kw))
    assert rp.parse_review(w[1])["Reviewer-Runtime"] == "gpt-tést"
