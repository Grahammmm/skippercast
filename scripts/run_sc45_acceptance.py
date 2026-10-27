#!/usr/bin/env python3
"""In-process offline SC45 acceptance; receipts are never reused or overwritten."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
REGRESSION = Path("tests/unit/test_sc45_regression.py")
COMPATIBILITY = Path("tests/unit/test_coastal_live_discovery.py")
SOURCE = Path("src/skippercast/coastal/live_discovery.py")
RUNNER = Path("scripts/run_sc45_acceptance.py")
GUARD = Path("scripts/check_repository.py")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head():
    git = ROOT / ".git"
    if git.is_file():
        git = (ROOT / git.read_text().strip().removeprefix("gitdir: ")).resolve()
    value = (git / "HEAD").read_text().strip()
    if value.startswith("ref: "):
        ref = value[5:]
        if (git / ref).exists():
            value = (git / ref).read_text().strip()
        else:
            value = next(line.split()[0] for line in (git / "packed-refs").read_text().splitlines()
                         if line.endswith(" " + ref))
    require(bool(re.fullmatch(r"[0-9a-f]{40}", value)), "invalid HEAD")
    return value


def snapshot():
    paths = {ROOT / p for p in (SOURCE, REGRESSION, COMPATIBILITY, RUNNER, GUARD,
                               Path("pyproject.toml"), Path("tests/conftest.py"), Path("tests/_support.py"))}
    paths.update((ROOT / "src/skippercast").rglob("*.py"))
    paths.update((ROOT / "skills/skippercast-discover-coastal-sources/scripts").glob("*.py"))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def origins():
    found = {}
    for name, module in list(sys.modules.items()):
        if name == "skippercast" or name.startswith("skippercast.") or name == "tests" or name.startswith("tests."):
            path = getattr(module, "__file__", None)
            if path:
                path = Path(path).resolve()
                require(path.is_relative_to(ROOT), f"ambient module: {name}: {path}")
                found[name] = str(path)
    require("skippercast.coastal.live_discovery" in found, "candidate module not loaded")
    return found


class Reports:
    def __init__(self):
        self.collected = []
        self.reports = []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        self.reports.append(dict(nodeid=report.nodeid, phase=report.when, outcome=report.outcome,
                                 properties=list(report.user_properties),
                                 detail=str(report.longrepr) if report.longrepr else None))


def tests(pytest, target, directory, *, selection=None, expected_failures=False):
    reports = Reports()
    directory.mkdir(parents=True, exist_ok=False)
    args = [str(target), "-v", "-p", "no:cacheprovider", "--basetemp", str(directory / "temp"),
            "--confcutdir", str(ROOT), "-o", "addopts=", "-o", "pythonpath=", "--tb=short"]
    if selection:
        args.extend(["-k", selection])
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        status = int(pytest.main(args, plugins=[reports]))
    raw = output.getvalue()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pytest.txt").write_text(raw)
    result = dict(argv=args, exit=status, collected=reports.collected, reports=reports.reports,
                  executed=sum(r["phase"] == "call" for r in reports.reports),
                  passed=sum(r["phase"] == "call" and r["outcome"] == "passed" for r in reports.reports),
                  failed=sum(r["outcome"] == "failed" for r in reports.reports),
                  skipped=sum(r["outcome"] == "skipped" for r in reports.reports),
                  raw_path=str(directory / "pytest.txt"), raw_sha256=digest(directory / "pytest.txt"))
    (directory / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(raw, end="")
    require(result["executed"] > 0 and result["skipped"] == 0, "empty or skipped acceptance")
    require(not any(r["phase"] != "call" and r["outcome"] == "failed" for r in reports.reports),
            "setup/teardown failure")
    if not expected_failures:
        require(status == 0 and result["failed"] == 0, "pytest acceptance failed")
    return result


def old_setdefault(discover, row, allowed_hosts):
    """Synthetic negative control ONLY: reproduce the baseline first-link choice."""
    import urllib.parse

    original = old_setdefault.candidate

    class BaselineLinks:
        @staticmethod
        def response_links(text, base):
            found = {}
            for link in sorted(discover.response_links(text, base)):
                parts = urllib.parse.urlsplit(link)
                name = parts.path.rstrip("/").rsplit("/", 1)[-1]
                if parts.hostname in allowed_hosts and name.lower().endswith(original.__globals__["LISTING_SUFFIXES"]) and not parts.query:
                    found.setdefault(name, link)
            return list(found.values())

    return original(BaselineLinks, row, allowed_hosts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("regression", "mutation", "compatibility", "portability"))
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT, "acceptance cwd must be candidate root")
    output_root = args.output_root.resolve()
    require(output_root.is_relative_to(ROOT.parent), "output must remain in candidate write root")
    require(not output_root.is_relative_to(ROOT), "receipts must not enter committed source")
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / (args.mode + "-" + uuid.uuid4().hex)
    output.mkdir(mode=0o700)
    receipt = dict(mode=args.mode, argv=sys.argv, cwd=str(Path.cwd()), executable=sys.executable,
                   head=head(), output=str(output), author_runtime="caller-supplied provenance in build handoff")
    raw = io.StringIO()
    guard_events = []
    sys.dont_write_bytecode = True
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ["SKIPPERCAST_ROOT"] = str(ROOT)
    os.environ["HOME"] = str(output / "home")
    Path(os.environ["HOME"]).mkdir()
    os.environ["TMPDIR"] = str(output / "tmp")
    Path(os.environ["TMPDIR"]).mkdir()
    os.environ["XDG_CACHE_HOME"] = str(output / "cache")
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

    def audit(event, arguments):
        if (event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn"))
                or event in {"os.system", "os.fork", "os.forkpty", "os.posix_spawn", "pty.spawn"}):
            guard_events.append(event)
            raise RuntimeError("SC45 offline boundary: " + event)

    sys.addaudithook(audit)
    status = 1
    before = snapshot()
    receipt["input_sha256"] = before
    try:
        with contextlib.redirect_stdout(raw), contextlib.redirect_stderr(raw):
            import pytest
            import numpy
            import rasterio
            import jsonschema
            from skippercast.coastal import live_discovery as ld

            receipt["runtime_imports"] = {m.__name__: str(m.__file__) for m in (pytest, numpy, rasterio, jsonschema)}
            receipt["origins_before_tests"] = origins()
            discover, script = ld.load_script()
            require(script.resolve() == ROOT / ld.SCRIPT, "wrong discovery script origin")
            receipt["discovery_script"] = dict(path=str(script), sha256=digest(script))
            if args.mode == "mutation":
                candidate = ld.listing_annotation
                old_setdefault.candidate = candidate
                try:
                    ld.listing_annotation = old_setdefault
                    negative = tests(pytest, ROOT / REGRESSION, output / "negative",
                                     selection="distinct_paths_collide or duplicate_identical_control or unique_basename_control",
                                     expected_failures=True)
                finally:
                    ld.listing_annotation = candidate
                failures = [r for r in negative["reports"] if r["outcome"] == "failed"]
                require(negative["exit"] == 1 and len(failures) == 4 and negative["passed"] == 2
                        and negative["executed"] == 6, "mutation did not isolate collision defect")
                require(all("test_distinct_paths_collide" in r["nodeid"] and "DID NOT RAISE" in r["detail"]
                            for r in failures), "unexpected mutation failure")
                receipt["negative"] = negative
                receipt["positive"] = tests(pytest, ROOT / REGRESSION, output / "positive")
                require(ld.listing_annotation is candidate, "mutation not restored")
            elif args.mode == "portability":
                # Deliberately differently named test root, derived from the repo path.
                # It lives outside the frozen checkout, under this unique receipt root.
                relocated = output / "different-name-suite" / "checks"
                relocated.mkdir(parents=True)
                target = relocated / "test_sc45_relocated.py"
                shutil.copyfile(ROOT / REGRESSION, target)
                require(digest(target) == before[str(REGRESSION)], "relocated regression differs")
                receipt["relocated_root_relative_to_repo"] = os.path.relpath(relocated, ROOT)
                for relative in (REGRESSION, RUNNER):
                    text = (ROOT / relative).read_text()
                    require(not re.search(r"/(?:home|Users)/[^/\s]+/", text), "box-only absolute path")
                receipt["positive"] = tests(pytest, target, output / "positive")
                require(Path.home() == output / "home", "HOME redirect failed")
                receipt["portability"] = dict(home=str(Path.home()), bytecode_disabled=sys.dont_write_bytecode,
                                               relocated_test_sha256=digest(target), box_paths_found=False)
            else:
                target = COMPATIBILITY if args.mode == "compatibility" else REGRESSION
                receipt["positive"] = tests(pytest, ROOT / target, output / "positive")
            receipt["origins_after_tests"] = origins()
            require(snapshot() == before, "frozen inputs changed")
            require(not guard_events, "offline boundary attempted")
            status = 0
    except BaseException:
        traceback.print_exc(file=raw)
    finally:
        receipt.update(exit=status, guard_events=guard_events, inputs_unchanged=snapshot() == before)
        if not receipt["inputs_unchanged"] or guard_events:
            status = receipt["exit"] = 1
        (output / "raw.txt").write_text(raw.getvalue())
        receipt["raw_sha256"] = digest(output / "raw.txt")
        (output / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        print(raw.getvalue(), end="")
        print(json.dumps(dict(receipt=str(output / "receipt.json"), exit=status), sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
