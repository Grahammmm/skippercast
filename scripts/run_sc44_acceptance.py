"""Run the four bounded SC44 acceptance modes in process, offline.

Receipts are unique and hash-bind source bytes, raw output and the exact HEAD.
No receipt claims full-suite CI or scientific/publication acceptance.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "src/skippercast/coastal/live_discovery.py"
TEST = "tests/unit/test_sc44_regression.py"
GOLDEN = "tests/fixtures/sc44/golden.json"
COMPAT = "tests/unit/test_coastal_live_discovery.py"
GUARD = "scripts/check_repository.py"
AUTHORED = (SOURCE, TEST, GOLDEN, "scripts/run_sc44_acceptance.py")
PINNED = {COMPAT: "6e60240928756923715e4a2f28bd58df34501bec744e1272f2366d8a1d86afbb",
          GUARD: "cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def hashes():
    return {name: sha((ROOT / name).read_bytes()) for name in (*AUTHORED, *PINNED)}


def head():
    git = ROOT / ".git"
    if git.is_file():
        git = (ROOT / git.read_text().strip().split(": ", 1)[1]).resolve()
    value = (git / "HEAD").read_text().strip()
    if value.startswith("ref: "):
        ref = value[5:]
        loose = git / ref
        if loose.exists():
            value = loose.read_text().strip()
        else:
            value = next(line.split()[0] for line in (git / "packed-refs").read_text().splitlines()
                         if line.endswith(" " + ref))
    require(re.fullmatch(r"[0-9a-f]{40}", value) is not None, "invalid full HEAD")
    return value


class Offline:
    """Side-effect seams plus a process-lifetime audit backstop, not a sandbox."""
    def __init__(self):
        self.attempts = []

    def deny(self, *args, **kwargs):
        self.attempts.append("socket/subprocess seam")
        raise RuntimeError("SC44 offline socket/subprocess boundary")

    def audit(self, event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen",
                     "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec"}:
            self.attempts.append(event)
            raise RuntimeError("SC44 offline audit boundary: " + event)

    def install(self):
        socket.socket.connect = self.deny
        socket.socket.connect_ex = self.deny
        socket.create_connection = self.deny
        socket.getaddrinfo = self.deny
        subprocess.Popen = self.deny
        sys.addaudithook(self.audit)


class Results:
    def __init__(self):
        self.collected = []
        self.reports = []
        self.collection_errors = []

    def pytest_collection_modifyitems(self, items):
        self.collected = [item.nodeid for item in items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(str(report.longrepr))

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.outcome != "passed":
            self.reports.append(dict(nodeid=report.nodeid, phase=report.when,
                                     outcome=report.outcome, reason=str(report.longrepr) if report.longrepr else None))


def run_tests(pytest, selected, directory, label, sessions, confcut=None):
    plugin = Results()
    args = ["-q", "-p", "no:cacheprovider", "-o", "addopts=", "--strict-markers",
            "--basetemp", str(directory / (label + "-tmp"))]
    if confcut is not None:
        args += ["--confcutdir", str(confcut)]
    args += [str(item) for item in selected]
    code = int(pytest.main(args, plugins=[plugin]))
    session = dict(label=label, pytest_argv=args, exit=code, collected=plugin.collected,
                   executed=sum(r["phase"] == "call" for r in plugin.reports),
                   reports=plugin.reports, collection_errors=plugin.collection_errors)
    sessions.append(session)
    print("SC44_SESSION", json.dumps(session, sort_keys=True))
    require(not plugin.collection_errors, "collection failure")
    require(all(r["phase"] == "call" for r in plugin.reports), "setup/teardown failure or skip")
    require(len(plugin.reports) == len(plugin.collected) > 0, "nonzero complete execution required")
    return session


def passed(session, count):
    require(session["exit"] == 0, "pytest positive exit nonzero")
    require(session["executed"] == count, "unexpected executed case count")
    require(all(r["outcome"] == "passed" for r in session["reports"]), "positive skip/failure")


def origins():
    found = {}
    for name, module in sorted(sys.modules.items()):
        if name == "skippercast" or name.startswith("skippercast.") or name == "tests" or name.startswith("tests."):
            origin = getattr(module, "__file__", None)
            if origin:
                path = Path(origin).resolve()
                require(path.is_relative_to(ROOT), "ambient module origin: " + name)
                found[name] = str(path)
    require("skippercast.coastal.live_discovery" in found, "production module not exercised")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("regression", "mutation", "compatibility", "portability"))
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--baseline-red", action="store_true", help="one pre-fix defect witness; never final acceptance")
    args = parser.parse_args()
    require(not args.baseline_red or args.mode == "regression", "baseline witness must use regression")
    output = args.output_root.resolve()
    require(output.is_relative_to(ROOT.parent) and not output.is_relative_to(ROOT), "receipts must be outside repository inside candidate root")
    output.mkdir(parents=True, exist_ok=True)
    directory = output / (args.mode + ("-expected-red-" if args.baseline_red else "-") + uuid.uuid4().hex)
    directory.mkdir()
    home = directory / "home"
    home.mkdir()
    os.environ["HOME"] = str(home)
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_ADDOPTS", None)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    offline = Offline()
    offline.install()
    before = hashes()
    identity = head()
    receipt = dict(mode=args.mode, baseline_red=args.baseline_red, argv=sys.argv, cwd=str(Path.cwd()),
                   head=identity, source_hashes=before, output_root=str(directory), home=str(home),
                   author_runtime="gpt-6.1-sol/openai-codex; sol-reviewer build t_38041a26 run 1431",
                   sessions=[], review_required=True, mapping_accepted=False, execution_authorized=False)
    raw = io.StringIO()
    exit_code = 1
    with contextlib.redirect_stdout(raw), contextlib.redirect_stderr(raw):
        try:
            require(Path.cwd().resolve() == ROOT, "acceptance cwd must be candidate root")
            for name, digest in PINNED.items():
                require(before[name] == digest, "unchanged compatibility/guard pin mismatch: " + name)
            for name in ("numpy", "rasterio", "pytest", "jsonschema"):
                module = importlib.import_module(name)
                print("RUNTIME", name, module.__file__)
            import pytest
            from skippercast.coastal import live_discovery as ld
            origins()
            test = ROOT / TEST
            count = 31
            sessions = receipt["sessions"]
            if args.baseline_red:
                session = run_tests(pytest, [str(test) + "::test_byte_compatibility",
                                    str(test) + "::test_input_detachment[metadata]"], directory, "baseline", sessions)
                require(session["exit"] == 1 and session["executed"] == 2, "expected-red exit/count mismatch")
                require([r["outcome"] for r in session["reports"]] == ["passed", "failed"], "expected-red status mismatch")
                require("input_alias:metadata" in session["reports"][1]["reason"], "wrong baseline failure reason")
                receipt["expected_red_confirmed"] = True
                print("EXPECTED_RED_CONFIRMED: baseline_catalog_bytes compatible; input_alias:metadata detected")
                exit_code = 1
            elif args.mode == "mutation":
                original = ld.frozen_catalog
                for key in ("metadata", "bbox"):
                    def broken(manifest, manifest_bytes, key=key):
                        result = original(manifest, manifest_bytes)
                        if key == "metadata":
                            result["candidates"][0][key] = manifest["candidates"][0][key]
                        else:
                            result[key] = manifest[key]
                        return result
                    try:
                        ld.frozen_catalog = broken
                        session = run_tests(pytest, [str(test) + "::test_byte_compatibility",
                                            str(test) + "::test_input_detachment[" + key + "]"],
                                            directory, "mutant-" + key, sessions)
                        require(session["exit"] == 1 and session["executed"] == 2, "mutant not detected")
                        require([r["outcome"] for r in session["reports"]] == ["passed", "failed"], "mutant control failed")
                        require("input_alias:" + key in session["reports"][1]["reason"], "wrong mutation failure reason")
                    finally:
                        ld.frozen_catalog = original
                require(ld.frozen_catalog is original, "monkeypatch not restored")
                passed(run_tests(pytest, [test], directory, "restored", sessions), count)
                exit_code = 0
            elif args.mode == "compatibility":
                tree = ast.parse((ROOT / COMPAT).read_text())
                names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
                session = run_tests(pytest, [ROOT / COMPAT], directory, "compatibility", sessions)
                passed(session, len(names))
                require({r["nodeid"].rsplit("::", 1)[1] for r in session["reports"]} == names, "compatibility omission")
                exit_code = 0
            else:
                if args.mode == "portability":
                    # Synthetic test tree is repository-relative, differently named on every run.
                    relocated = ROOT / "var" / ("sc44-portable-" + uuid.uuid4().hex)
                    relocated.mkdir(parents=True)
                    for relative in (TEST, GOLDEN):
                        destination = relocated / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(ROOT / relative, destination)
                        require(destination.read_bytes() == (ROOT / relative).read_bytes(), "relocation changed fixture")
                    test = relocated / TEST
                    receipt["relocated_test_root"] = str(relocated.relative_to(ROOT))
                    for relative in AUTHORED[1:]:
                        text = (ROOT / relative).read_text()
                        # Construct tokens so the scanner itself contains no private path literals.
                        require(not any(token in text for token in ("/" + "home/", "/" + "Users/")), "box-only path in authored bytes")
                    passed(run_tests(pytest, [test], directory, "portable", sessions, confcut=relocated), count)
                else:
                    passed(run_tests(pytest, [test], directory, "regression", sessions), count)
                exit_code = 0
            receipt["module_origins"] = origins()
            require(not offline.attempts, "offline boundary attempted even if caught")
            require(before == hashes(), "authored/pinned input bytes changed during acceptance")
            require(identity == head(), "HEAD changed during acceptance")
            receipt["inputs_unchanged"] = True
        except Exception:
            traceback.print_exc()
            exit_code = 1
    raw_bytes = raw.getvalue().encode()
    receipt.update(exit=exit_code, offline_attempts=offline.attempts,
                   executed_checks=sum(s["executed"] for s in receipt["sessions"]),
                   raw_output_sha256=sha(raw_bytes), raw_output="raw-output.txt")
    (directory / "raw-output.txt").write_bytes(raw_bytes)
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(raw.getvalue(), end="")
    print("SC44_RECEIPT", directory / "receipt.json")
    print("SC44_RESULT", args.mode, "exit", exit_code, "executed", receipt["executed_checks"])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
