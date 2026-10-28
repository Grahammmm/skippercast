"""SC-CACHE-CLOCK acceptance runner (offline, write-once run roots).

    python3 scripts/accept_sc_cache_clock.py --suite {focused,contract,negative} --output <candidate>/out/<new-run>

Runs pytest in-process against THIS staged repository only: bytecode writing is
suppressed and the import path is set in code before any project import, from
this file's location (repository src, repository root and the repository-local
``.venv`` site-packages, added without .pth processing so no editable finder to
another checkout loads). Network/subprocess/model sentinels are installed first.
They are regression guards, not a hostile-code sandbox.

Exit status: 0 every named assertion passed; 1 an acceptance assertion failed;
2 usage or output-root refusal (nothing written); 3 input-identity refusal
(an input differs from tests/fixtures/sc_cache_clock/input-pins.json, or is a
symlink, special file or over the caps, checked through no-follow descriptors
before any import or write) or environment capability failure (missing
dependency or import-closure violation). Local success is
REVIEW REQUIRED, not CI, source qualification or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import errno  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import sysconfig  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(os.path.abspath(__file__)).parents[1]  # unresolved: ancestry is checked, not followed
CANDIDATE = REPO.parent
OUT_ROOT = CANDIDATE / "out"
SRC = REPO / "src"
VENV_SITE = REPO / ".venv" / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"
STDLIB = [Path(sysconfig.get_paths()[k]).resolve() for k in ("stdlib", "platstdlib")]
TEST_FILE = "tests/unit/test_sc_cache_clock.py"
PRODUCER_TEST = "tests/unit/test_coastal_cached_intake.py"
MODULE = "skippercast.coastal.cached_inventory"
INPUTS = ("scripts/accept_sc_cache_clock.py", "src/skippercast/coastal/cached_inventory.py", TEST_FILE,
          PRODUCER_TEST, "tests/fixtures/sc_cache_clock/vectors.json", "tests/conftest.py",
          "tests/_support.py", "pyproject.toml")
# Frozen expected identities of INPUTS; the pins file itself is the recorded root of trust.
PINS = "tests/fixtures/sc_cache_clock/input-pins.json"
PINS_SCHEMA = "sc-cache-clock-input-pins-v1"
PINS_CAP = 64 * 1024
FILE_CAP = 2 * 1024 * 1024
TOTAL_CAP = 16 * 1024 * 1024
OUTPUT_CAP = 8 * 1024 * 1024
ROW_CAP = 4096
INPUT_BYTES = {}
NETWORK_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
                  "socket.getnameinfo", "socket.sendto", "http.client.connect", "urllib.Request",
                  "ftplib.connect", "smtplib.connect", "webbrowser.open"}
PROCESS_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                  "os.forkpty", "os.startfile", "pty.spawn"}
MODEL_PACKAGES = {"openai", "anthropic", "ollama", "litellm", "google.generativeai", "transformers"}
NATIVE_SUFFIXES = (".bag", ".tif", ".tiff", ".zip", ".laz", ".las")
COUNTERS = dict(network_attempts=0, process_attempts=0, model_imports=0, native_source_read_opens=0)
TRIPS = []


def refuse(message, code):
    print(json.dumps(dict(status="REFUSED", reason=message, exit=code), sort_keys=True))
    raise SystemExit(code)


def audit(event, args):
    if event in NETWORK_EVENTS:
        COUNTERS["network_attempts"] += 1; TRIPS.append(event)
        raise RuntimeError("offline acceptance: network sentinel " + event)
    if event in PROCESS_EVENTS:
        COUNTERS["process_attempts"] += 1; TRIPS.append(event)
        raise RuntimeError("offline acceptance: process sentinel " + event)
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0]).lower()
        if name.endswith(NATIVE_SUFFIXES):
            mode, flags = (args[1], args[2]) if len(args) > 2 else (None, 0)
            reading = ("r" in mode or "+" in mode) if isinstance(mode, str) else \
                (flags & os.O_ACCMODE) in (os.O_RDONLY, os.O_RDWR)
            if reading:
                COUNTERS["native_source_read_opens"] += 1; TRIPS.append("native-open:" + Path(name).name)


class ModelSentinel:
    """Meta-path finder refusing model/provider client packages."""
    def find_spec(self, name, path=None, target=None):
        if name in MODEL_PACKAGES or name.split(".")[0] in MODEL_PACKAGES:
            COUNTERS["model_imports"] += 1; TRIPS.append("model-import:" + name)
            raise ImportError("offline acceptance: model sentinel " + name)
        return None


def within(path, roots):
    path = Path(path).resolve()
    return any(path == root or root in path.parents for root in roots)


def install_guards(run_dir):
    sys.addaudithook(audit)
    sys.meta_path.insert(0, ModelSentinel())
    import socket
    def blocked(*_a, **_k):
        COUNTERS["network_attempts"] += 1; TRIPS.append("socket-sentinel")
        raise RuntimeError("offline acceptance: socket sentinel")
    socket.socket.connect = blocked; socket.socket.connect_ex = blocked
    socket.create_connection = blocked; socket.getaddrinfo = blocked
    # Import path: this staged repository only; drop every non-stdlib entry and
    # any editable-install finder already registered by site processing.
    kept = [p for p in sys.path if p and not p.endswith((".zip",)) and within(p, STDLIB)
            and "site-packages" not in p and "dist-packages" not in p]
    sys.path[:] = [str(SRC), str(REPO), str(VENV_SITE)] + kept + [p for p in sys.path if p.endswith(".zip")]
    sys.meta_path[:] = [f for f in sys.meta_path if not type(f).__module__.startswith("__editable__")]
    sys.path_importer_cache.clear()
    tmp = run_dir / "tmp"; tmp.mkdir()
    tempfile.tempdir = str(tmp)
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"


def module_root(module):
    origin = getattr(module, "__file__", None)
    if not origin:
        return "builtin"
    path = Path(origin).resolve()
    for label, root in (("candidate-src", SRC.resolve()), ("candidate-venv", VENV_SITE.resolve()),
                        ("candidate-repo", REPO.resolve())):
        if path == root or root in path.parents:
            return label
    if within(path, STDLIB) and "site-packages" not in str(path) and "dist-packages" not in str(path):
        return "stdlib"
    return "OUTSIDE"


def read_chunk(fd, size):
    """Single bounded descriptor read (a seam for the synthetic growth control)."""
    return os.read(fd, size)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def pinned_read(root, relative, expected, budget, cap):
    """Read one input through no-follow descriptors from / down, bounded and pinned.

    Every component of the unresolved root and of ``relative`` is opened with
    O_NOFOLLOW relative to its parent descriptor, so a symlink anywhere in the
    ancestry, a special file or a non-regular leaf is refused before any byte is
    read. Size is checked against the per-file and aggregate caps (and the pin)
    on the open descriptor, at most size+1 bytes are read, the descriptor
    identity must be unchanged afterwards, and the SHA-256 must equal the pin.
    """
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError("relative input path required: " + str(relative))
    components = list(Path(os.path.abspath(root)).parts[1:]) + list(rel.parts)
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in components[:-1]:
            try:
                child = os.open(part, directory, dir_fd=fd)
            except OSError as error:
                raise ValueError(f"symlink or non-directory ancestry refused ({errno_name(error)}): {relative}") from None
            os.close(fd)
            fd = child
        try:
            child = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC,
                            dir_fd=fd)
        except OSError as error:
            raise ValueError(f"symlink or special input refused ({errno_name(error)}): {relative}") from None
        os.close(fd)
        fd = child
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("regular input file required: " + str(relative))
        if before.st_size > cap:
            raise ValueError("per-file input cap exceeded: " + str(relative))
        if budget[0] + before.st_size > TOTAL_CAP:
            raise ValueError("aggregate input cap exceeded: " + str(relative))
        if expected is not None and before.st_size != expected["bytes"]:
            raise ValueError(str(relative) + " does not match its frozen pin (size)")
        chunks, remaining = [], before.st_size + 1
        while remaining:
            data = read_chunk(fd, min(65536, remaining))
            if not data:
                break
            chunks.append(data)
            remaining -= len(data)
        payload = b"".join(chunks)
        if len(payload) != before.st_size or identity(os.fstat(fd)) != identity(before):
            raise ValueError("input changed during bounded read: " + str(relative))
    finally:
        os.close(fd)
    if expected is not None and hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError(str(relative) + " does not match its frozen pin (sha256)")
    budget[0] += len(payload)
    return payload


def errno_name(error):
    return errno.errorcode.get(error.errno, str(error.errno))


def preflight(repo, inputs, pins_relative):
    """Verify every declared input against the frozen pins before any import, decode or write."""
    budget = [0]
    raw = pinned_read(repo, pins_relative, None, budget, PINS_CAP)
    try:
        pins = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ValueError("input pins are not UTF-8 JSON") from None
    if (not isinstance(pins, dict) or set(pins) != {"schema", "inputs"} or pins["schema"] != PINS_SCHEMA
            or not isinstance(pins["inputs"], dict)):
        raise ValueError("input pins schema " + PINS_SCHEMA + " required")
    if len(set(inputs)) != len(inputs) or sorted(pins["inputs"]) != sorted(inputs):
        raise ValueError("input pins must cover exactly the declared inputs")
    for name, pin in pins["inputs"].items():
        if (not isinstance(pin, dict) or set(pin) != {"sha256", "bytes"} or type(pin["bytes"]) is not int
                or pin["bytes"] < 0 or not isinstance(pin["sha256"], str) or len(pin["sha256"]) != 64
                or set(pin["sha256"]) - set("0123456789abcdef")):
            raise ValueError("malformed input pin: " + name)
    data = {name: pinned_read(repo, name, pins["inputs"][name], budget, FILE_CAP) for name in inputs}
    return dict(data=data, sha256={name: hashlib.sha256(value).hexdigest() for name, value in data.items()},
                pins_sha256=hashlib.sha256(raw).hexdigest(), input_bytes_total=budget[0])


def git_head():
    git = REPO / ".git"
    if not git.is_dir():
        return None
    head = (git / "HEAD").read_text().strip()
    if not head.startswith("ref: "):
        return dict(ref=None, sha=head)
    ref = head[5:]
    loose = git / ref
    if loose.is_file():
        return dict(ref=ref, sha=loose.read_text().strip())
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            if line.endswith(" " + ref):
                return dict(ref=ref, sha=line.split()[0])
    return dict(ref=ref, sha=None)


class Recorder:
    def __init__(self):
        self.collected = []; self.reports = {}
    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]  # after -k deselection
    def pytest_runtest_logreport(self, report):
        entry = self.reports.setdefault(report.nodeid, dict(outcome="passed", reason=None, did_not_raise=False))
        if report.failed:
            text = str(report.longrepr)
            entry["outcome"] = "failed" if report.when == "call" else "error"
            entry["reason"] = text[-600:]
            entry["did_not_raise"] = "DID NOT RAISE" in text and "ValueError" in text
        elif report.skipped:
            entry["outcome"] = "skipped"; entry["reason"] = str(report.longrepr)[-300:]


def run_pytest(run_dir, index, name, args, collect_only=False):
    import pytest
    recorder = Recorder()
    argv = ["-c", str(REPO / "pyproject.toml"), "--rootdir", str(REPO), "-p", "no:cacheprovider",
            "--basetemp", str(run_dir / f"basetemp-{index}-{name}"), "-q"] + (["--collect-only"] if collect_only else []) + args
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = int(pytest.main(argv, plugins=[recorder]))
    log = run_dir / f"phase-{index}-{name}.log"
    payload = ("$ pytest " + " ".join(argv) + "\n--- stdout ---\n" + out.getvalue()
               + "\n--- stderr ---\n" + err.getvalue()).encode()
    write_once(log, payload)
    counts = dict(collected=len(recorder.collected))
    for state in ("passed", "failed", "error", "skipped"):
        counts[state] = sum(1 for r in recorder.reports.values() if r["outcome"] == state)
    if len(recorder.reports) > ROW_CAP or len(recorder.collected) > ROW_CAP:
        raise ValueError("row cap exceeded")
    return dict(index=index, name=name, pytest_argv=argv, exit=code, counts=counts,
                log=log.name, log_sha256=hashlib.sha256(payload).hexdigest(),
                collected=recorder.collected, outcomes=recorder.reports)


WRITTEN = [0]


def write_once(path, payload):
    if WRITTEN[0] + len(payload) > OUTPUT_CAP:
        raise ValueError("output cap exceeded")
    with open(path, "xb") as stream:
        stream.write(payload)
    WRITTEN[0] += len(payload)


def clean(phase, minimum=1, marker=None):
    """True when a phase ran >= minimum tests and every one passed (no skip/error).

    ``marker`` additionally requires every selected test name to carry it, so a
    ``-k`` expression cannot silently select an unrelated test.
    """
    c = phase["counts"]
    selected = all(marker in n.split("::")[-1] for n in phase["collected"]) if marker else True
    return (phase["exit"] == 0 and c["passed"] >= minimum and c["passed"] == c["collected"]
            and c["failed"] == c["error"] == c["skipped"] == 0 and selected)


def check(assertions, name, ok, detail=None):
    assertions.append(dict(name=name, ok=bool(ok), detail=detail))


def suite_focused(run_dir, assertions):
    phase = run_pytest(run_dir, 1, "a1", [TEST_FILE, "-k", "a1"])
    check(assertions, "A1 focused tests all pass with zero skips", clean(phase, 20, "test_a1_"), phase["counts"])
    return [phase]


def suite_contract(run_dir, assertions):
    import tomllib
    producer = run_pytest(run_dir, 1, "producer-existing", [PRODUCER_TEST])
    check(assertions, "existing test_coastal_cached_intake suite passes unchanged", clean(producer, 10), producer["counts"])
    a2 = run_pytest(run_dir, 2, "a2", [TEST_FILE, "-k", "a2"])
    check(assertions, "A2 timestamp contract tests pass with zero skips", clean(a2, 20, "test_a2_"), a2["counts"])
    fake = [n for n in a2["outcomes"] if "fake_host_offset" in n]
    check(assertions, "fake host-offset variants executed", len(fake) >= 18, len(fake))
    collect = run_pytest(run_dir, 3, "collect-tests-unit", ["tests/unit"], collect_only=True)
    mine = [n for n in collect["collected"] if n.startswith(TEST_FILE + "::")]
    config = tomllib.loads(INPUT_BYTES["pyproject.toml"].decode("utf-8"))["tool"]["pytest"]["ini_options"]
    check(assertions, "new test module discovered by existing testpaths/python_files",
          collect["exit"] == 0 and "tests" in config["testpaths"] and config["python_files"] == ["test_*.py"]
          and len(mine) >= 60, dict(discovered=len(mine), testpaths=config["testpaths"]))
    return [producer, a2, collect]


def suite_negative(run_dir, assertions):
    from unittest.mock import patch
    import importlib
    ci = importlib.import_module(MODULE)
    phases = [run_pytest(run_dir, 1, "a3", [TEST_FILE, "-k", "a3"])]
    check(assertions, "A3 negative/preservation tests pass with zero skips", clean(phases[0], 40, "test_a3_"), phases[0]["counts"])
    if not callable(getattr(ci, "aware_instant", None)):
        check(assertions, "awareness gate aware_instant present for isolated control", False)
        return phases
    # Isolated broken control: an in-memory double bypasses ONLY the awareness gate.
    with patch.object(ci, "aware_instant", side_effect=lambda parsed: parsed):
        broken = run_pytest(run_dir, 2, "bypass-naive-regression", [TEST_FILE, "-k", "naive_regression"])
        positive = run_pytest(run_dir, 3, "bypass-aware-positive", [TEST_FILE, "-k", "aware_positive"])
        gate = run_pytest(run_dir, 4, "bypass-completeness-gate", [TEST_FILE, "-k", "completeness_gate"])
    restored = run_pytest(run_dir, 5, "restored", [TEST_FILE, "-k", "naive_regression or aware_positive or completeness_gate"])
    phases += [broken, positive, gate, restored]
    detected = [n for n, r in broken["outcomes"].items() if r["outcome"] == "failed" and r["did_not_raise"]
                and "naive_regression" in n.split("::")[-1]]
    check(assertions, "bypassed awareness gate makes EVERY naive regression fail (DID NOT RAISE), pytest exit 1",
          broken["exit"] == 1 and broken["counts"]["collected"] >= 10
          and len(detected) == broken["counts"]["collected"] == broken["counts"]["failed"],
          dict(counts=broken["counts"], detected=len(detected)))
    check(assertions, "aware positive control stays green under the bypass", clean(positive, 20, "aware_positive"), positive["counts"])
    check(assertions, "separate completeness gate still refuses partial strings under the bypass",
          clean(gate, 8, "completeness_gate"), gate["counts"])
    check(assertions, "restored module passes regression, positive and completeness sets",
          clean(restored, 38) and restored["counts"]["collected"] == broken["counts"]["collected"]
          + positive["counts"]["collected"] + gate["counts"]["collected"], restored["counts"])
    return phases


SUITES = dict(focused=suite_focused, contract=suite_contract, negative=suite_negative)


def validated_output(raw):
    output = Path(raw)
    if not output.is_absolute() or output.parent != OUT_ROOT or output.name in ("", ".", ".."):
        refuse("output must be a new direct child of the candidate out/ directory", 2)
    for ancestor in [output] + list(output.parents):
        if ancestor.is_symlink():
            refuse("symlink output ancestry rejected", 2)
    if output.exists():
        refuse("write-once run root already exists; choose a new unique run root", 2)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = validated_output(args.output)
    try:
        checked = preflight(REPO, INPUTS, PINS)
    except (OSError, ValueError) as error:
        refuse("input check failed: " + str(error), 3)
    INPUT_BYTES.clear()
    INPUT_BYTES.update(checked["data"])
    inputs = checked["sha256"]
    if not VENV_SITE.is_dir():
        refuse("repository-local dependency site-packages absent; no install attempted", 3)
    OUT_ROOT.mkdir(exist_ok=True)
    output.mkdir()
    before = set(sys.modules)
    preexisting = sorted(n for n in before if module_root(sys.modules[n]) == "OUTSIDE")
    install_guards(output)
    try:
        import pytest  # noqa: F401
        import jsonschema  # noqa: F401
        import importlib
        import importlib.metadata as metadata
        ci = importlib.import_module(MODULE)
        versions = dict(pytest=metadata.version("pytest"), jsonschema=metadata.version("jsonschema"))
    except ImportError as error:
        refuse("required dependency import failed: " + str(error), 3)
    if Path(ci.__file__).resolve() != (SRC / "skippercast/coastal/cached_inventory.py").resolve():
        refuse("target module did not resolve to this staged repository", 3)
    defaults = [f"{name}={value!r}" for name, fn in vars(ci).items() if callable(fn)
                for value in (list(getattr(fn, "__defaults__", None) or ()) + list((getattr(fn, "__kwdefaults__", None) or {}).values()))
                if isinstance(value, (str, os.PathLike))]
    assertions = []
    check(assertions, "target module has no bound path/string defaults to redirect", not defaults, defaults)
    phases = SUITES[args.suite](output, assertions)
    imported = {n: module_root(m) for n, m in list(sys.modules.items()) if n not in before}
    outside = sorted(n for n, root in imported.items() if root == "OUTSIDE")
    check(assertions, "transitive import closure stays in stdlib + this candidate repository", not outside, outside[:50])
    check(assertions, "zero network, process, model or native-source-read activity",
          not any(COUNTERS.values()), dict(COUNTERS, trips=TRIPS[:50]))
    status = 0 if all(a["ok"] for a in assertions) else 1
    receipt = dict(schema="sc-cache-clock-acceptance-receipt-v1", suite=args.suite, exit=status,
                   verdict="PASS_REVIEW_REQUIRED" if status == 0 else "FAIL",
                   argv=[sys.executable] + sys.argv, cwd=os.getcwd(), interpreter=sys.executable,
                   python=sys.version, dependency_versions=versions, git_head=git_head(), input_sha256=inputs,
                   input_pins=dict(path=PINS, sha256=checked["pins_sha256"], verified_before_import=True),
                   input_bytes_total=checked["input_bytes_total"],
                   sys_path=sys.path, import_roots={r: sum(1 for v in imported.values() if v == r) for r in sorted(set(imported.values()))},
                   preexisting_outside_modules=preexisting, sentinels=dict(COUNTERS),
                   assertions=assertions, phases=phases,
                   limits="Local scoped acceptance only: REVIEW REQUIRED; not full CI, source qualification or semantic acceptance.")
    payload = (json.dumps(receipt, sort_keys=True, indent=1, allow_nan=False) + "\n").encode()
    write_once(output / "receipt.json", payload)
    summary = dict(suite=args.suite, exit=status, receipt=str(output / "receipt.json"),
                   receipt_sha256=hashlib.sha256(payload).hexdigest(),
                   phases={p["name"]: dict(exit=p["exit"], **p["counts"]) for p in phases},
                   failed_assertions=[a["name"] for a in assertions if not a["ok"]])
    print(json.dumps(summary, sort_keys=True, indent=1))
    raise SystemExit(status)


if __name__ == "__main__":
    main()
