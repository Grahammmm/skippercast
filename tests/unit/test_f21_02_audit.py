"""Exercise showcase cleanup on synthetic scratch paths without a browser or server."""
import base64
import importlib.util
import json
import subprocess

import pytest

from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("showcase_cleanup_under_test", ROOT / "scripts/showcase.py")
assert _spec is not None and _spec.loader is not None
showcase = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(showcase)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVBkAAAAASUVORK5CYII="
)


@pytest.mark.parametrize(("work_kind", "reuse", "keep"), [
    ("existing", False, False),
    ("existing", True, False),
    ("new", False, False),
    ("default", False, False),
    ("new", False, True),
])
def test_showcase_cleans_only_its_own_scratch(tmp_path, monkeypatch, work_kind, reuse, keep):
    root = tmp_path / "repo"
    (root / "node_modules/@playwright/test").mkdir(parents=True)
    monkeypatch.setattr(showcase, "ROOT", root)
    revs = {"before": "a" * 40, "after": "b" * 40}
    monkeypatch.setattr(showcase, "git", lambda cmd, *args, **kw: {
        "rev-parse": revs.get(args[-1].split("^")[0]), "show": "2026-01-02T00:00:00+00:00", "log": "",
    }[cmd])
    removals = []

    def fake_worktree_remove(argv, **kwargs):
        assert argv[:4] == ["git", "worktree", "remove", "--force"]
        removals.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(showcase.subprocess, "run", fake_worktree_remove)
    work = tmp_path / "work"
    trees = [work / f"tree-{rev[:12]}" for rev in revs.values()]
    if work_kind == "default":
        def make_temp(*, prefix):
            work.mkdir()
            return str(work)

        monkeypatch.setattr(showcase.tempfile, "mkdtemp", make_temp)
    if work_kind == "existing":
        trees[0].mkdir(parents=True)
        (work / "sentinel.txt").write_text("caller files")
        (trees[0] / "sentinel.txt").write_text("caller worktree files")

    def make_capture(label):
        out = work / label
        out.mkdir()
        result = {"id": "sample", "status": "missing" if label == "before" else "ok", "steady": True}
        (out / "results.json").write_text(json.dumps([result]))
        if label == "after":
            (out / "sample.png").write_bytes(PNG)
        return {"sample": {**result, "png": str(out / "sample.png")}}

    if reuse:
        make_capture("before")
        make_capture("after")
        # The real reuse path must read the fixtures without building or launching anything.
        monkeypatch.setattr(showcase, "run", lambda *args, **kw: pytest.fail("reuse tried to rebuild"))
    else:
        def fake_capture(sha, label, config, scratch, log, *, reuse):
            assert scratch == work and not reuse
            (scratch / f"tree-{sha[:12]}").mkdir(exist_ok=True)
            return make_capture(label)

        monkeypatch.setattr(showcase, "capture_revision", fake_capture)

    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps({"pages": [{"id": "sample", "route": "/example", "path": "/example"}], "serve": {}}))
    out = tmp_path / "out"
    argv = ["--before", "before", "--after", "after", "--pages", str(pages), "--out", str(out)]
    if work_kind != "default":
        argv.extend(["--work", str(work)])
    if reuse:
        argv.append("--reuse")
    if keep:
        argv.append("--keep")
    assert showcase.main(argv) == 0
    assert (out / "2026-01-02/sample-after.png").read_bytes() == PNG
    assert (out / "showcase-2026-01-02.html").is_file()

    if work_kind == "existing":
        assert (work / "sentinel.txt").read_text() == "caller files"
        assert (trees[0] / "sentinel.txt").read_text() == "caller worktree files"
    if work_kind == "existing" or keep:
        assert removals == []
        assert (work / "after/sample.png").read_bytes() == PNG
    else:
        assert removals == list(map(str, trees))
        assert not work.exists()
