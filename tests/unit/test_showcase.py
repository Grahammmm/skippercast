"""scripts/showcase.py: merge-log reading, PR-to-page matching and the gallery page (no browser, no server)."""
import importlib.util
import subprocess

from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("showcase_under_test", ROOT / "scripts/showcase.py")
showcase = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(showcase)


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_merged_prs_reads_merge_and_squash_commits_on_the_first_parent_line(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "web").mkdir()
    (tmp_path / "web/map.ts").write_text("x")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "inner commit, not a PR")
    _git(tmp_path, "checkout", "-q", "main")
    _git(tmp_path, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #7 from o/feature\n\nPhone Chart: attribution starts compact")
    (tmp_path / "b.txt").write_text("b")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "Fix the docs (#9)")
    prs = showcase.merged_prs("HEAD~2", "HEAD", cwd=tmp_path)
    assert [(p["number"], p["title"], p["files"]) for p in prs] == [
        (7, "Phone Chart: attribution starts compact", ["web/map.ts"]), (9, "Fix the docs", ["b.txt"])]


def test_a_page_lists_the_prs_that_changed_its_files_or_that_it_names():
    prs = [{"sha": "1", "number": 1, "title": "map", "files": ["web/map/chart.ts"]},
           {"sha": "2", "number": 2, "title": "tests", "files": ["tests/test_x.py"]},
           {"sha": "3", "number": 3, "title": "named", "files": ["server/x.ts"]}]
    page = {"paths": ["web/map/*"], "prs": [3]}
    assert [p["number"] for p in showcase.prs_for_page(page, prs)] == [1, 3]


def _row(page_id, kind, index, **extra):
    page = {"id": page_id, "route": f"/{page_id}", "path": f"/{page_id}"}
    return {"page": page, "kind": kind, "index": index, "width": 390, "height": 844, "prs": [], "summary": kind, **extra}


def test_identical_pairs_sort_last_and_a_new_page_has_no_broken_image():
    before, after = "a" * 40, "b" * 40
    rows = [_row("same", "same", 0, before_src="d/same.png", after_src="d/same.png", before_size=(390, 844), after_size=(390, 844)),
            _row("added", "new", 1, before_empty="New page: not in aaaaaaaaa", after_src="d/added-after.png", after_size=(390, 844)),
            _row("moved", "changed", 2, fraction=0.1, boxes=[{"x": 0, "y": 0, "w": 39, "h": 84}],
                 before_src="d/moved-before.png", after_src="d/moved-after.png", before_size=(390, 844), after_size=(390, 844))]
    meta = {"title": "T", "date": "2026-10-31", "before": before, "after": after, "before_date": "x", "after_date": "y", "prs": [],
            "now_text": "noon", "stable_text": "", "tolerance_text": "", "pages_file": "docs/showcase/pages.json"}
    page = showcase.render(rows, meta, [], [])
    assert page.index('id="moved"') < page.index('id="added"') < page.index('id="same"')
    assert "1</b> page changed" in page and "1</b> new page" in page and "1</b> no visible change" in page
    added = page[page.index('id="added"'):page.index('id="same"')]
    assert added.count("<img") == 1 and "New page: not in aaaaaaaaa" in added
    assert 'class="box" style="left:0.00%;top:0.00%;width:10.00%;height:9.95%"' in page
    assert "<script" not in page and "http" not in page.split("</style>")[0]


def test_classify_names_each_outcome():
    ok = {"status": "ok"}
    assert showcase.classify(ok, ok, {"changed": 0}, False) == "same"
    assert showcase.classify(ok, ok, {"changed": 5}, False) == "changed"
    assert showcase.classify({"status": "missing"}, ok, None, False) == "new"
    # A server error or a crashed page at the old revision is a failure, never a "new page".
    assert showcase.classify({"status": "failed", "http_status": 500}, ok, None, False) == "failed-before"
    assert showcase.classify(ok, ok, {"changed": 5}, True) == "unstable"
    assert showcase.classify(ok, {"status": "failed"}, None, False) == "failed"


def test_a_same_pair_says_whether_it_is_exact_or_within_the_noise_tolerance():
    page = {"path": "/"}
    exact = showcase.summary_for("same", page, None, None, {"exact": 0, "changed": 0}, "a" * 40, 2)
    noisy = showcase.summary_for("same", page, None, None, {"exact": 29, "changed": 0}, "a" * 40, 2)
    assert "identical, pixel for pixel" in exact
    assert "29 pixels differ by at most 2 colour levels" in noisy
