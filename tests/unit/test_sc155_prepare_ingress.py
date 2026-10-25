"""SC155: bound prepare_round --inputs before allocating or decoding its bytes.

Ordinary discovery is inert at import: no product import, global patch, audit hook
or filesystem write happens until a test runs. Every product module is loaded in
setUp under reversible, test-scoped sys.path/sys.modules patches and restored in
teardown. Only prepare_round's own ``os`` binding is replaced, by a pass-through
recording view (the named stat/read seam); coast_refs/review_common keep the real os.
"""
from contextlib import redirect_stderr
import functools
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock
import uuid

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills/coast-sign-off/scripts"
PRODUCT = SCRIPTS / "prepare_round.py"
COMMON = SCRIPTS / "review_common.py"
CONSTRUCTORS = REPO / "tests/fixtures/sc155-prepare-ingress/constructors.py"
SCRIPT_MODULES = ("prepare_round", "review_common", "coast_refs", "coast_sample", "coast_native", "coast_raw",
                  "coast_receipt_versions", "validate_coast_receipt", "coast_ledger", "tests.coast_contract_factory")
REQUIRED = ("test_positive_contract", "test_rejects_malformed", "test_baseline_compatibility",
            "test_isolation_and_discovery", "test_deciding_negative_control")
POSITIVE_CASES = ("tiny", "limit_minus_one", "limit_exact", "ancestor_churn")
MALFORMED_CASES = ("limit_plus_one", "oversize_modeled", "directory", "symlink_component_0", "symlink_component_1",
                   "symlink_component_2", "fifo_modeled", "char_device_modeled", "block_device_modeled",
                   "socket_modeled", "growth_metadata", "growth_read", "shrink_read", "replacement_real",
                   "missing_leaf", "missing_intermediate", "ancestor_dir_replaced_top", "ancestor_dir_replaced_mid",
                   "ancestor_symlink_replaced_top", "ancestor_symlink_replaced_mid")
COMPATIBILITY_CASES = ("limit_and_decoder_identity", "factory_vocabulary_and_schema", "exact_bytes",
                       "unavailable_file_oserror_and_finish", "roots_policy_runs_first_unchanged",
                       "argument_policy_unchanged")
# A3 deciding mutants: (disabled seam, refusal case fed through the same check_refusal assertion).
MUTANT_PLAN = (("unbounded_reader", "oversize_modeled"), ("identity_disabled", "growth_metadata"),
               ("identity_disabled", "replacement_real"), ("ancestry_disabled", "ancestor_dir_replaced_mid"),
               ("ancestry_disabled", "ancestor_symlink_replaced_top"))
PRODUCT_MODULES = ("prepare_round", "review_common", "coast_refs")
EXPECTED_LIMIT = 32 * 1024 * 1024
UNBOUNDED = 1 << 62
LARGE = 1024 * 1024
ROOT_ID = "queue:synthetic"
RUN_ROOT = None  # set by tools/run_sc155_prepare_ingress.py to its exclusive invocation root
RECORDS = []
ORIGINS = []  # actual product module origins, captured while the fixture-scoped real modules are loaded
_MISSING = object()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_file(name, path, register=True):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def case_parent():
    """Runner root; else the candidate's sibling out/ when staged; else the inherited temp root (CI)."""
    if RUN_ROOT is not None:
        return Path(RUN_ROOT).resolve()
    staged = REPO.parent / "out"
    if staged.is_dir():
        parent = staged / "discovery"
        parent.mkdir(exist_ok=True)
        return parent.resolve()
    return Path(tempfile.gettempdir()).resolve()


def _restore_modules(saved):
    for name, module in saved.items():
        if module is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def modeled(result, **changes):
    """Inert metadata model of an fstat/stat result (no special file is ever created)."""
    fields = {key: getattr(result, key) for key in ("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid",
                                                     "st_size", "st_atime_ns", "st_mtime_ns", "st_ctime_ns")}
    fields.update(changes)
    return types.SimpleNamespace(**fields)


def fd_is_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


def moved(before, old, new, extra):
    """Expected snapshot after a case's own rename of ``old`` to ``new`` plus its replacement entries."""
    after = {}
    for key, value in before.items():
        after[new + key[len(old):] if key == old or key.startswith(old + "/") else key] = value
    after.update(extra)
    return after


class PrepareReached(Exception):
    """Inert prepare sentinel: main stops here; no context, artifact or ledger is created."""


class OsView:
    """Pass-through view of ``os`` bound only as prepare_round.os.

    Records every open/close and every read request size (allocation spy) and
    optionally models leaf metadata/read results. Reads are forwarded in chunks
    of at most 1 MiB, so even an unbounded request never allocates its size.
    """

    def __init__(self, leaf_name):
        self.leaf_name = leaf_name
        self.opened, self.closed, self.requests = [], [], []
        self.leaf_fds = set()
        self.fstat_calls = 0
        self.fstat_hook = self.read_hook = self.stat_hook = None

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        fd = os.open(path, flags, mode, dir_fd=dir_fd)
        self.opened.append(fd)
        if os.fsdecode(path).rsplit("/", 1)[-1] == self.leaf_name and not flags & os.O_DIRECTORY:
            self.leaf_fds.add(fd)
        return fd

    def close(self, fd):
        self.closed.append(fd)
        return os.close(fd)

    def read(self, fd, size):
        self.requests.append(size)
        if self.read_hook is not None and fd in self.leaf_fds:
            return self.read_hook(fd, size)
        return os.read(fd, min(size, LARGE))

    def fstat(self, fd):
        result = os.fstat(fd)
        if fd in self.leaf_fds:
            self.fstat_calls += 1
            if self.fstat_hook is not None:
                return self.fstat_hook(result, self.fstat_calls)
        return result

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        result = os.stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if self.stat_hook is not None and os.fsdecode(path).rsplit("/", 1)[-1] == self.leaf_name:
            return self.stat_hook(result)
        return result


def unbounded_reader(product, path):
    """A3 test-local mutant adapter: unchecked open and unbounded read requests (old read_bytes shape)."""
    fd = product.os.open(str(path), os.O_RDONLY)
    try:
        chunks = []
        while True:
            chunk = product.os.read(fd, UNBOUNDED)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        product.os.close(fd)


def snapshot(root):
    """Every entry below root: type plus content hash or link target (no link is followed)."""
    entries = {}
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names + files:
            path = Path(directory) / name
            info = os.lstat(path)
            key = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                entries[key] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                entries[key] = ("dir",)
            else:
                entries[key] = ("file", digest(path.read_bytes()))
    return entries


class PrepareIngressTests(unittest.TestCase):
    def setUp(self):
        parent = case_parent()
        self.root = Path(tempfile.mkdtemp(prefix="sc155-", dir=parent)).resolve()
        saved = {name: sys.modules.get(name, _MISSING) for name in SCRIPT_MODULES}
        self.addCleanup(_restore_modules, saved)
        self.enterContext(mock.patch.object(sys, "path", [str(REPO), str(SCRIPTS)] + list(sys.path)))
        self.enterContext(mock.patch.object(sys, "dont_write_bytecode", True))
        for name in SCRIPT_MODULES:
            sys.modules.pop(name, None)
        self.common = load_file("review_common", COMMON)
        self.product = load_file("prepare_round", PRODUCT)
        self.refs = sys.modules["coast_refs"]
        self.fx = load_file("sc155_constructors", CONSTRUCTORS, register=False)
        self.limit = self.common.LIMIT
        origins = {}
        for name in PRODUCT_MODULES:
            origin = Path(sys.modules[name].__file__).resolve()
            self.assertTrue(origin.is_relative_to(REPO.resolve()), "product module outside staged checkout: " + name)
            origins[name] = dict(file=str(origin), sha256=digest(origin.read_bytes()))
        self.assertEqual(origins["prepare_round"]["file"], str(PRODUCT.resolve()))
        ORIGINS.append(dict(test=self.id(), modules=origins))

    # ----- fixture construction -------------------------------------------------
    def new_case(self, name):
        case = self.root / (name + "-" + uuid.uuid4().hex[:8])
        (case / "queue").mkdir(parents=True)
        roots = case / "roots.json"
        roots.write_bytes(self.refs.canonical({ROOT_ID: str(case / "queue")}))
        (case / "unrelated.txt").write_bytes(b"UNRELATED SENTINEL: must be preserved\n")
        out = case / "queue/plans/plan01/review/r01/a01/context.json"
        return types.SimpleNamespace(dir=case, roots=roots, out=out, name=name)

    def put(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        if len(raw) > LARGE:
            # Fixture-owned bulk payload: its hash is recorded before this cleanup runs.
            self.addCleanup(path.unlink, missing_ok=True)
        return path

    def argv(self, case, inputs, roots=None, root_id=ROOT_ID):
        return ["prepare_round.py", "--roots", str(roots or case.roots), "--allowed-root-id", root_id,
                "--inputs", str(inputs), "--round", "1", "--attempt", "1", "--out", str(case.out)]

    def run_main(self, case, inputs, view, argv=None):
        calls = []

        def sentinel(resolver, inputs_value, review_round, attempt, out):
            calls.append(dict(inputs=inputs_value, review_round=review_round, attempt=attempt, out=out,
                              bindings={k: str(v) for k, v in resolver.bindings.items()}))
            raise PrepareReached()

        outcome, error = "returned", None
        with mock.patch.object(sys, "argv", argv or self.argv(case, inputs)), \
                mock.patch.object(self.product, "prepare", sentinel), \
                mock.patch.object(self.product, "os", view, create=True):
            try:
                self.product.main()
            except PrepareReached:
                outcome = "prepare"
            except Exception as caught:  # recorded and asserted precisely by the caller
                outcome, error = "raised", caught
        still_open = [fd for fd in view.opened if fd_is_open(fd)]
        return outcome, error, calls, still_open

    def build_positive(self, name):
        case = self.new_case(name)
        value = self.fx.prepare_inputs()
        raw = {"tiny": lambda: self.fx.encode(value),
               "ancestor_churn": lambda: self.fx.encode(value),
               "limit_minus_one": lambda: self.fx.padded(value, self.limit - 1),
               "limit_exact": lambda: self.fx.padded(value, self.limit)}[name]()
        inputs = self.put(case.dir / "top/mid/inputs.json", raw)
        return case, inputs, raw, value

    def build_refusal(self, name):
        """Return (case, inputs path, view, expectation). Unrelated prerequisites stay valid."""
        case = self.new_case(name)
        value = self.fx.prepare_inputs()
        tiny = self.fx.encode(value)
        inputs = case.dir / "top/mid/inputs.json"
        view = OsView("inputs.json")
        expect = dict(kind="value", reason="changed", pre_read=False)
        transform = None
        if name == "limit_plus_one":
            self.put(inputs, self.fx.padded(value, self.limit + 1))
            expect = dict(kind="value", reason="exceeds", pre_read=True)
        elif name == "oversize_modeled":
            self.put(inputs, tiny)
            view.fstat_hook = lambda result, n: modeled(result, st_size=self.limit + 1)
            expect = dict(kind="value", reason="exceeds", pre_read=True)
        elif name == "directory":
            inputs.mkdir(parents=True)
            expect = dict(kind="value", reason="regular file", pre_read=True)
        elif name.startswith("symlink_component_"):
            # A genuine sibling target tree, reachable only through a link at this
            # component position (0 = first component below the case root).
            position = int(name.rsplit("_", 1)[1])
            parts = ["top", "mid", "inputs.json"]
            real = case.dir.joinpath(*parts[:position], "real-" + parts[position])
            self.put(real.joinpath(*parts[position + 1:]), tiny)
            os.symlink(real.name, case.dir.joinpath(*parts[:position + 1]))
            expect = dict(kind="value", reason="symlink", pre_read=True)
        elif name in ("fifo_modeled", "char_device_modeled", "block_device_modeled", "socket_modeled"):
            kind = {"fifo_modeled": stat.S_IFIFO, "char_device_modeled": stat.S_IFCHR,
                    "block_device_modeled": stat.S_IFBLK, "socket_modeled": stat.S_IFSOCK}[name]
            self.put(inputs, tiny)
            view.fstat_hook = lambda result, n: modeled(result, st_mode=kind | 0o600)
            expect = dict(kind="value", reason="regular file", pre_read=True)
        elif name == "growth_metadata":
            self.put(inputs, tiny)
            view.fstat_hook = lambda result, n: result if n == 1 else modeled(
                result, st_size=result.st_size + 1, st_mtime_ns=result.st_mtime_ns + 1)
        elif name == "growth_read":
            self.put(inputs, tiny)
            state = {"first": True}

            def grow(fd, size):
                if state["first"]:
                    state["first"] = False
                    return (os.read(fd, min(size, LARGE)) + b" ")[:size]
                return b""
            view.read_hook = grow
        elif name == "shrink_read":
            self.put(inputs, tiny)
            state = {"first": True}

            def shrink(fd, size):
                if state["first"]:
                    state["first"] = False
                    return os.read(fd, min(size, LARGE))[:-1]
                return b""
            view.read_hook = shrink
        elif name == "replacement_real":
            self.put(inputs, tiny)
            os.link(inputs, inputs.parent / "original.link")
            replacement = self.put(inputs.parent / "replacement.tmp", self.fx.encode(dict(value, plan_id="other")))
            state = {"first": True}

            def replace(fd, size):
                if state["first"]:
                    state["first"] = False
                    os.rename(replacement, inputs)  # real named-file replacement mid-read
                return os.read(fd, min(size, LARGE))
            view.read_hook = replace

            def transform(before):
                after = dict(before)
                after["top/mid/inputs.json"] = before["top/mid/replacement.tmp"]
                del after["top/mid/replacement.tmp"]
                return after
        elif name == "missing_leaf":
            (case.dir / "top/mid").mkdir(parents=True)
            expect = dict(kind="oserror", reason=None, pre_read=True)
        elif name == "missing_intermediate":
            (case.dir / "top").mkdir(parents=True)
            expect = dict(kind="oserror", reason=None, pre_read=True)
        elif name.startswith("ancestor_"):
            # A real ancestor directory (top or top/mid) is renamed away mid-read and its old
            # name replaced by an ordinary directory holding identical bytes, or by a symlink to
            # the moved original. The held descriptors still see the original file unchanged.
            self.put(inputs, tiny)
            old = "top" if name.endswith("_top") else "top/mid"
            new = old + "-moved"
            symlink = "_symlink_" in name
            state = {"first": True}

            def swap(fd, size):
                if state["first"]:
                    state["first"] = False
                    os.rename(case.dir / old, case.dir / new)
                    if symlink:
                        os.symlink(Path(new).name, case.dir / old)
                    else:
                        (case.dir / old).mkdir()
                        if old == "top":
                            (case.dir / "top/mid").mkdir()
                        (case.dir / "top/mid/inputs.json").write_bytes(tiny)
                return os.read(fd, min(size, LARGE))
            view.read_hook = swap
            expect = dict(kind="value", reason="parent directory was replaced", pre_read=False)

            def transform(before):
                if symlink:
                    extra = {old: ("link", Path(new).name)}
                else:
                    extra = {"top/mid": ("dir",), "top/mid/inputs.json": before["top/mid/inputs.json"]}
                    if old == "top":
                        extra["top"] = ("dir",)
                return moved(before, old, new, extra)
        else:
            raise KeyError(name)
        return case, inputs, view, expect, transform

    # ----- deciding assertions ----------------------------------------------------
    def check_refusal(self, name, label="real"):
        case, inputs, view, expect, transform = self.build_refusal(name)
        before = snapshot(case.dir)
        outcome, error, calls, still_open = self.run_main(case, inputs, view)
        after = snapshot(case.dir)
        RECORDS.append(dict(test=self.id(), case=name, label=label, outcome=outcome,
                            error_type=type(error).__name__ if error else None, error=str(error) if error else None,
                            requests=view.requests[:8], request_total=sum(view.requests), opened=len(view.opened),
                            closed=len(view.closed), still_open=still_open, inputs_sha256=before.get("top/mid/inputs.json"),
                            preserved=after == (transform(before) if transform else before)))
        # 1. Allocation/request spy (decisive for the unbounded-reader mutant).
        if expect["pre_read"]:
            self.assertEqual(view.requests, [], "payload read requested before metadata refusal")
        self.assertLessEqual(sum(view.requests), self.limit + 1, "requested read bytes exceed LIMIT + 1")
        # 2. Refused before prepare (decisive for the disabled-identity mutant).
        self.assertNotEqual(outcome, "prepare", "refused input reached prepare")
        self.assertEqual(calls, [])
        self.assertEqual(outcome, "raised")
        if expect["kind"] == "value":
            self.assertIsInstance(error, ValueError)
            self.assertNotIsInstance(error, OSError)
            self.assertIn(expect["reason"], str(error))
        else:
            self.assertIsInstance(error, FileNotFoundError, "unavailable-file OSError behavior retained")
        # 3. Every descriptor the reader opened is closed.
        self.assertEqual(still_open, [])
        self.assertEqual(sorted(view.opened), sorted(view.closed))
        # 4. Inputs, unrelated sentinels and the whole case tree are unchanged; nothing written.
        self.assertEqual(after, transform(before) if transform else before)
        self.assertFalse(case.out.exists())
        self.assertEqual(after["unrelated.txt"], ("file", digest(b"UNRELATED SENTINEL: must be preserved\n")))
        if name == "replacement_real":
            self.assertEqual(after["top/mid/original.link"], before["top/mid/inputs.json"])

    def check_accept(self, name, label="real"):
        case, inputs, raw, value = self.build_positive(name)
        view = OsView("inputs.json")
        transform = None
        state = {"first": True}
        if name == "ancestor_churn":
            # Healthy control for the ancestry predicate: unrelated entries appear in every held
            # ancestor mid-read (their mtimes change, their identities do not); input must pass.

            def churn(fd, size):
                if state["first"]:
                    state["first"] = False
                    (case.dir / "churn-dir").mkdir()
                    (case.dir / "top/churn-dir").mkdir()
                    (case.dir / "top/mid/churn.txt").write_bytes(b"churn\n")
                return os.read(fd, min(size, LARGE))
            view.read_hook = churn

            def transform(before):
                if state["first"]:  # the churn hook only fires on a descriptor-bound os.read path
                    return before
                return dict(before, **{"churn-dir": ("dir",), "top/churn-dir": ("dir",),
                                       "top/mid/churn.txt": ("file", digest(b"churn\n"))})
        before = snapshot(case.dir)
        outcome, error, calls, still_open = self.run_main(case, inputs, view)
        after = snapshot(case.dir)
        churned = name == "ancestor_churn" and not state["first"]
        RECORDS.append(dict(test=self.id(), case=name, label=label, outcome=outcome, bytes=len(raw),
                            inputs_sha256=digest(raw), error=str(error) if error else None, churned=churned,
                            requests=view.requests[:8], request_total=sum(view.requests), still_open=still_open))
        if name == "ancestor_churn" and hasattr(self.product, "_intact"):
            self.assertTrue(churned, "ancestor churn control did not run during the bounded read")
        self.assertEqual(outcome, "prepare", repr(error))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["inputs"], value, "decoded object changed")
        self.assertEqual(calls[0]["inputs"], self.refs.loads(raw))
        self.assertEqual((calls[0]["review_round"], calls[0]["attempt"], calls[0]["out"]), (1, 1, case.out))
        self.assertEqual(calls[0]["bindings"], {ROOT_ID: str(case.dir / "queue")})
        self.assertLessEqual(sum(view.requests), len(raw) + 1)
        self.assertLessEqual(sum(view.requests), self.limit + 1)
        self.assertEqual(still_open, [])
        self.assertEqual(sorted(view.opened), sorted(view.closed))
        self.assertEqual(after, transform(before) if transform else before, "acceptance created or changed files")
        self.assertFalse(case.out.exists())
        self.assertEqual(len(raw), {"tiny": len(self.fx.encode(value)), "limit_minus_one": self.limit - 1,
                                    "limit_exact": self.limit, "ancestor_churn": len(self.fx.encode(value))}[name])

    # ----- A1 ------------------------------------------------------------------
    def test_positive_contract(self):
        for name in POSITIVE_CASES:
            with self.subTest(case=name):
                self.check_accept(name)

    def test_rejects_malformed(self):
        for name in MALFORMED_CASES:
            with self.subTest(case=name):
                self.check_refusal(name)

    # ----- A2 ------------------------------------------------------------------
    def test_baseline_compatibility(self):
        with self.subTest(case="limit_and_decoder_identity"):
            self.assertEqual(self.common.LIMIT, EXPECTED_LIMIT)
            self.assertIs(self.product.loads, self.refs.loads)
            self.assertIs(self.common.loads, self.refs.loads)
            self.assertIs(getattr(self.product, "LIMIT", self.common.LIMIT), self.common.LIMIT)
        with self.subTest(case="factory_vocabulary_and_schema"):
            case, inputs, raw, value = self.build_positive("tiny")
            decoded = self.refs.loads(self.product._read_inputs(inputs))
            self.assertEqual(decoded, value)
            factory = load_file("tests.coast_contract_factory", REPO / "tests/coast_contract_factory.py")
            branches = factory.schemas()["review-context"]["oneOf"]
            for branch in branches:
                self.assertEqual(set(branch["properties"]), set(decoded))
            # Same wrapper prepare applies first; actual shared validator, no prepare run.
            context = dict(decoded, schema="coast-review-context-v1", review_round=1, attempt=1)
            self.assertIs(self.common.validate_schema(context), context)
        with self.subTest(case="exact_bytes"):
            case, inputs, raw, value = self.build_positive("tiny")
            self.assertEqual(self.product._read_inputs(inputs), raw)
        with self.subTest(case="unavailable_file_oserror_and_finish"):
            case = self.new_case("finish")
            missing = case.dir / "absent.json"
            with self.assertRaises(FileNotFoundError):
                self.product._read_inputs(missing)
            for path, text in ((missing, "No such file"), (self.put(case.dir / "dir/x.json", b"{}").parent, "regular file")):
                stderr = io.StringIO()
                with mock.patch.object(sys, "argv", self.argv(case, path)), \
                        mock.patch.object(self.product, "prepare", side_effect=AssertionError("prepare reached")), \
                        redirect_stderr(stderr):
                    status = self.common.finish(self.product.main)
                self.assertEqual(status, 3)
                self.assertIn(text, stderr.getvalue())
        with self.subTest(case="roots_policy_runs_first_unchanged"):
            case, inputs, raw, value = self.build_positive("tiny")
            view = OsView("inputs.json")
            outcome, error, calls, still_open = self.run_main(
                case, inputs, view, argv=self.argv(case, inputs, root_id="queue:other"))
            self.assertEqual(outcome, "raised")
            self.assertIsInstance(error, ValueError)
            self.assertIn("root binding", str(error))
            self.assertEqual((view.opened, view.requests, calls), ([], [], []))
        with self.subTest(case="argument_policy_unchanged"):
            case, inputs, raw, value = self.build_positive("tiny")
            for bad in ("relative/inputs.json", str(case.dir) + "/top/../top/mid/inputs.json"):
                with mock.patch.object(sys, "argv", self.argv(case, bad)), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as stop:
                        self.product.main()
                self.assertEqual(stop.exception.code, 2)

    def test_isolation_and_discovery(self):
        names = unittest.TestLoader().getTestCaseNames(PrepareIngressTests)
        self.assertEqual(sorted(names), sorted(REQUIRED))
        module = sys.modules.get(__name__)
        if module is not None:
            for name in ("prepare_round", "review_common", "coast_refs"):
                self.assertNotIsInstance(getattr(module, name, None), types.ModuleType)
        self.assertTrue(self.root.is_relative_to(case_parent()))

        def state():
            return dict(path=list(sys.path), modules={n: id(sys.modules.get(n)) for n in SCRIPT_MODULES},
                        environ=dict(os.environ), tempdir=tempfile.tempdir, bytecode=sys.dont_write_bytecode,
                        argv=list(sys.argv), product_os=self.product.__dict__.get("os"),
                        peer=digest((REPO / "pyproject.toml").read_bytes()))

        class Peer(unittest.TestCase):
            seen = []

            def test_harmless(self):
                Peer.seen.append(json.dumps(sorted(os.listdir(REPO / "tests/fixtures"))[:3]))

        def run_peer():
            result = unittest.TestResult()
            Peer("test_harmless").run(result)
            return result.wasSuccessful()

        first = state()
        self.assertTrue(run_peer())
        inner = unittest.TestResult()
        PrepareIngressTests("test_baseline_compatibility").run(inner)
        self.assertTrue(inner.wasSuccessful(), inner.failures + inner.errors)
        self.assertTrue(run_peer())
        self.assertEqual(state(), first, "inner test teardown leaked patched state")
        self.assertEqual(Peer.seen[0], Peer.seen[1])
        self.assertIs(sys.modules["prepare_round"], self.product)

    # ----- A3 ------------------------------------------------------------------
    def test_deciding_negative_control(self):
        detected = {}
        seams = {"unbounded_reader": ("_read_inputs", functools.partial(unbounded_reader, self.product),
                                      "payload read requested before metadata refusal"),
                 "identity_disabled": ("_stable", lambda before, after, named: True, "refused input reached prepare"),
                 "ancestry_disabled": ("_intact", lambda chain, names: True, "refused input reached prepare")}
        for seam, name in MUTANT_PLAN:
            attribute, broken, expected = seams[seam]
            # Only this one seam is broken; every unrelated prerequisite of the case stays valid.
            with mock.patch.object(self.product, attribute, broken):
                with self.assertRaises(AssertionError) as caught:
                    self.check_refusal(name, label="mutant-" + seam.replace("_", "-"))
            message = str(caught.exception)
            self.assertIn(expected, message)
            if seam == "unbounded_reader":
                self.assertEqual(RECORDS[-1]["requests"][:1], [UNBOUNDED])
            else:
                self.assertEqual(RECORDS[-1]["outcome"], "prepare")
                self.assertLessEqual(RECORDS[-1]["request_total"], self.limit + 1)
            detected[seam + ":" + name] = message
            # Real path restored: the same deciding assertion now passes on a fresh case.
            self.check_refusal(name, label="restored")
        # Healthy finite positives with the real reader restored.
        self.check_accept("tiny", label="restored-positive")
        self.check_accept("ancestor_churn", label="restored-positive")
        RECORDS.append(dict(test=self.id(), case="negative-control-summary", detected=detected))


# ----- A4 ordinary-discovery execution evidence ---------------------------------
def required_subtests():
    return ({("test_positive_contract", case) for case in POSITIVE_CASES} |
            {("test_rejects_malformed", case) for case in MALFORMED_CASES} |
            {("test_baseline_compatibility", case) for case in COMPATIBILITY_CASES})


def execution_problems(executed, subtests, skips, failures, errors, origins):
    """Fail-closed completeness check over what one invocation actually executed."""
    problems = []
    names = [test_id.rsplit(".", 1)[-1] for test_id in executed]
    if sorted(names) != sorted(REQUIRED):
        problems.append("executed methods differ from required: " + repr(sorted(names)))
    if skips:
        problems.append("required tests skipped: " + repr(skips))
    if failures or errors:
        problems.append("failures/errors: " + repr(failures + errors))
    seen = {}
    for item in subtests:
        seen.setdefault((item["method"], item["params"].get("case")), []).append(item["outcome"])
    for key in sorted(required_subtests()):
        if seen.get(key) != ["pass"]:
            problems.append("required subtest missing or not passed once: %s/%s %r" % (key[0], key[1], seen.get(key)))
    for name in REQUIRED:
        loaded = [o for o in origins if o["test"].rsplit(".", 1)[-1] == name]
        if not loaded or any(set(o["modules"]) != set(PRODUCT_MODULES) for o in loaded):
            problems.append("product origins not captured for " + name)
    return problems


def git_head():
    """Read the checkout HEAD from repository files (no child process)."""
    git = REPO / ".git"
    try:
        if git.is_file():
            text = git.read_text().strip()
            git = (REPO / text.split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head[4:].strip()
        if (git / ref).is_file():
            return (git / ref).read_text().strip()
        for line in (git / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except (OSError, IndexError):
        return None
    return None


class EvidenceSuite(unittest.TestSuite):
    """Ordinary-discovery wrapper (load_tests protocol): records this invocation's executed IDs,
    subtest outcomes, skips/failures/errors and product origins on the live result object through
    instance attributes that are removed again after the run, then writes one receipt."""

    HOOKS = ("startTest", "addSubTest", "addSkip", "addFailure", "addError", "addUnexpectedSuccess")

    def run(self, result, debug=False):
        executed, subtests, skips, failures, errors = [], [], [], [], []
        first_origin, first_record = len(ORIGINS), len(RECORDS)
        saved = {name: result.__dict__.get(name, _MISSING) for name in self.HOOKS}
        original = {name: getattr(result, name) for name in self.HOOKS}

        def start(test):
            executed.append(test.id())
            original["startTest"](test)

        def sub(test, subtest, err):
            outcome = "pass" if err is None else ("fail" if issubclass(err[0], test.failureException) else "error")
            subtests.append(dict(id=subtest.id(), method=test._testMethodName, params=dict(subtest.params),
                                 outcome=outcome))
            original["addSubTest"](test, subtest, err)

        def note(bucket, name):
            def hook(test, *args):
                bucket.append(dict(id=test.id(), detail=str(args[0])[:2000] if args else None))
                original[name](test, *args)
            return hook

        hooks = dict(startTest=start, addSubTest=sub, addSkip=note(skips, "addSkip"),
                     addFailure=note(failures, "addFailure"), addError=note(errors, "addError"),
                     addUnexpectedSuccess=note(failures, "addUnexpectedSuccess"))
        for name, hook in hooks.items():
            setattr(result, name, hook)
        try:
            super().run(result, debug)
        finally:
            for name, value in saved.items():
                if value is _MISSING:
                    result.__dict__.pop(name, None)
                else:
                    result.__dict__[name] = value
        origins, records = ORIGINS[first_origin:], RECORDS[first_record:]
        problems = execution_problems(executed, subtests, skips, failures, errors, origins)
        spec = REPO.parent / "ACCEPTANCE-SPEC.json"
        sources = (PRODUCT, COMMON, CONSTRUCTORS, Path(__file__).resolve(), REPO / "tools/run_sc155_prepare_ingress.py")
        receipt = dict(
            schema="sc155-discovery-receipt/v1", argv=list(sys.argv), orig_argv=list(getattr(sys, "orig_argv", [])),
            cwd=os.getcwd(), interpreter=sys.executable, prefix=sys.prefix, python=sys.version, head=git_head(),
            spec_sha256=digest(spec.read_bytes()) if spec.is_file() else None,
            source_hashes={p.relative_to(REPO).as_posix(): digest(p.read_bytes()) for p in sources if p.is_file()},
            executed_ids=executed, count=len(executed), subtests=subtests, subtest_count=len(subtests),
            required_subtest_count=len(required_subtests()), skips=skips, failures=failures, errors=errors,
            product_origins=origins, cases=records, problems=problems, complete=not problems)
        directory = Path(tempfile.mkdtemp(prefix="discovery-receipt-", dir=case_parent()))
        raw = json.dumps(receipt, indent=2, default=str).encode() + b"\n"
        (directory / "receipt.json").write_bytes(raw)
        sys.stderr.write("\nSC155-DISCOVERY-RECEIPT %s %s\n" % (directory / "receipt.json", digest(raw)))
        if problems:
            error = ValueError("SC155 discovery evidence incomplete: " + "; ".join(problems))
            result.addError(unittest.suite._ErrorHolder("sc155-discovery-evidence"), (ValueError, error, None))
        return result


def _method_names(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _method_names(item)
        else:
            yield getattr(item, "_testMethodName", None)


def load_tests(loader, standard_tests, pattern):
    """Unfiltered ordinary discovery of this module gets the evidence wrapper; a filtered
    selection (for example -k) runs unwrapped and makes no completeness claim."""
    if set(REQUIRED) <= set(_method_names(standard_tests)):
        return EvidenceSuite([standard_tests])
    return standard_tests
