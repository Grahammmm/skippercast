"""region_intake writes INTAKE.csv/INTAKE.md as a UTF-8 pair or not at all, and never through a link (RF1105-23)."""
import os

import pytest

from tests.unit.test_region_intake import ri, rows_of, run, world  # noqa: F401

PAIR = {"INTAKE.csv", "INTAKE.md"}


def listing(folder):
    return sorted(os.listdir(folder))


def temps(folder):
    return [n for n in os.listdir(folder) if n.startswith(".INTAKE.")]


def test_pair_written_utf8_without_temps(world):
    world["sources"]["syn-approved"]["documentation_url"] = "https://example.org/fiché"
    world["region"]["id"] = "synthétic-bay"
    code, folder = run(world, "one")
    assert code == 0 and listing(folder) == sorted(PAIR)
    assert "https://example.org/fiché".encode() in (folder / "INTAKE.csv").read_bytes()
    assert (folder / "INTAKE.md").read_bytes().startswith("# INTAKE synthétic-bay\n".encode())
    assert rows_of(folder)[0]["official_url"] == "https://example.org/fiché"
    assert ri.main(["--check", str(folder)], world["loader"]) == 0


def test_render_failure_writes_nothing(world, monkeypatch, capsys):
    (world["tmp"] / "one").mkdir()

    def broken(*_a, **_k):
        raise KeyError("render")
    monkeypatch.setattr(ri, "summary", broken)
    code, folder = run(world, "one")
    assert code == 1 and "render" in capsys.readouterr().err and listing(folder) == []


@pytest.mark.parametrize("step,fail_on", [("replace", 2), ("replace", 1), ("mkstemp", 2)])
def test_write_failure_leaves_no_half_pair(world, monkeypatch, capsys, step, fail_on):
    module = ri.os if step == "replace" else ri.tempfile
    real, calls = getattr(module, step), []

    def flaky(*a, **k):
        calls.append(a)
        if len(calls) == fail_on:
            raise OSError(f"{step} failed")
        return real(*a, **k)
    monkeypatch.setattr(module, step, flaky)
    code, folder = run(world, "one")
    monkeypatch.undo()
    assert code == 1 and f"{step} failed" in capsys.readouterr().err
    assert listing(folder) == []
    assert run(world, "one")[0] == 0 and listing(folder) == sorted(PAIR)  # the next run is not refused


@pytest.mark.parametrize("name", sorted(PAIR))
def test_dangling_link_refused(world, capsys, name):
    folder, target = world["tmp"] / "one", world["tmp"] / "target.txt"
    folder.mkdir()
    (folder / name).symlink_to(target)
    assert run(world, "one")[0] == 1
    assert f"Refusing to overwrite {name}" in capsys.readouterr().err
    assert not target.exists() and listing(folder) == [name] and os.path.islink(folder / name)


def test_half_pair_md_only_refused(world, capsys):
    folder = world["tmp"] / "one"
    folder.mkdir()
    (folder / "INTAKE.md").write_bytes(b"# INTAKE old\n")
    assert run(world, "one")[0] == 1
    assert "Refusing to overwrite INTAKE.md" in capsys.readouterr().err
    assert listing(folder) == ["INTAKE.md"] and (folder / "INTAKE.md").read_bytes() == b"# INTAKE old\n"


@pytest.mark.parametrize("kind", ["link", "link/", "dangling", "file"])
def test_run_must_be_real_folder(world, capsys, kind):
    tmp, real = world["tmp"], world["tmp"] / "real"
    real.mkdir()
    if kind == "file":
        (tmp / "one").write_text("x")
    else:
        (tmp / "one").symlink_to(real if kind != "dangling" else tmp / "nowhere")
    code = ri.main(["synthetic-bay", "--run", str(tmp / "one") + ("/" if kind == "link/" else ""), "--locations",
                    str(tmp / "locations.json"), "--screens", str(tmp / "screens.tsv")], world["loader"])
    assert code == 1 and "--run must be a real folder" in capsys.readouterr().err
    assert listing(real) == [] and not (tmp / "nowhere").exists()


def test_rerun_after_success_refused_and_unchanged(world, capsys):
    code, folder = run(world, "one")
    before = {n: (folder / n).read_bytes() for n in PAIR}
    assert code == 0 and run(world, "one")[0] == 1
    assert "Refusing to overwrite INTAKE.csv" in capsys.readouterr().err
    assert listing(folder) == sorted(PAIR) and {n: (folder / n).read_bytes() for n in PAIR} == before


@pytest.mark.parametrize("name", sorted(PAIR))
def test_check_non_utf8_is_unreadable(world, capsys, name):
    code, folder = run(world, "one")
    capsys.readouterr()
    (folder / name).write_bytes((folder / name).read_bytes() + b"\xff\xfe\n")
    assert code == 0 and ri.main(["--check", str(folder)], world["loader"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("region_intake: Run folder unreadable") and "Traceback" not in err
