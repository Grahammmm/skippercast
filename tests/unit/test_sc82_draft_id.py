"""SC82 direct API regressions; all product calls use inert ingestion and synthetic roots.

The previous Luna test is preserved outside the repository as evidence. Its
expected-failure wrapper and unguarded writer are deliberately not reused.
Importing this module does not import product modules or activate audit hooks.
"""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from tests._support import FIXTURES as SUPPORT_FIXTURES, ROOT

FIXTURES = SUPPORT_FIXTURES / "sc82-draft-id"
URL = "https://example.invalid/survey.tif"
BOUNDS = [0, 0, 1, 1]
INVALID = {
    "traversal": "../escape", "absolute": "/absolute-survey", "slash": "bad/id",
    "backslash": "bad\\id", "empty": "", "null": None, "true": True, "false": False,
    "list": ["survey-valid"], "mapping": {"id": "survey-valid"}, "empty-list": [],
    "empty-mapping": {}, "integer": 42, "zero": 0, "float": 1.5,
    "uppercase": "Survey-valid", "one-char": "a", "too-long": "a" * 65,
    "newline": "survey-valid\n", "unicode": "survey-é", "nul": "bad\x00id",
}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DraftIDCases(unittest.TestCase):
    external_root = None
    external_guard = None
    assertion_class = "compatibility"

    def setUp(self):
        self.preservation = {}
        self.owned_temp = None
        self.guard = self.external_guard
        self.old_bytecode = sys.dont_write_bytecode
        self.old_tempdir = tempfile.tempdir
        sys.dont_write_bytecode = True
        self.addCleanup(setattr, sys, "dont_write_bytecode", self.old_bytecode)
        self.addCleanup(setattr, tempfile, "tempdir", self.old_tempdir)
        if self.external_root is None:
            # Ordinary discovery gets scoped guards, not permanent ambient changes.
            self.owned_temp = tempfile.TemporaryDirectory(prefix="sc82-")
            self.addCleanup(self.owned_temp.cleanup)
            self.tree = Path(self.owned_temp.name)
            from tools.run_sc82_draft_id import IsolationGuard
            self.guard = IsolationGuard(self.tree)
            self.guard.start()
            self.addCleanup(self.guard.stop)
        else:
            self.tree = self.external_root / uuid.uuid4().hex
            self.tree.mkdir()
        # The fresh runner already redirects pre-import defaults. Ordinary CI
        # uses explicit API roots without changing cached product defaults for
        # unrelated peer suites in the same interpreter.
        self.draft = importlib.import_module("skippercast.seafloor.draft")
        expected = ROOT / "src/skippercast/seafloor/draft.py"
        self.assertEqual(Path(self.draft.__file__).resolve(), expected)
        if self.external_root is not None:
            self.assertEqual(self.draft.REPO, self.external_root)
            self.assertEqual(self.draft.add_survey.__kwdefaults__["root"], self.external_root)
        shape = json.loads((FIXTURES / "source-shape.json").read_text())
        self.row = shape["row"]
        self.saved = shape["adapter_review"]
        self.root = self.tree / "product-root"
        self.root.mkdir()
        (self.root / "catalog").mkdir()
        (self.root / "var/seafloor/drafts").mkdir(parents=True)
        self.catalog = self.root / "catalog/surveys.json"
        self.sentinel = self.tree / "outside-root-sentinel.json"
        self.sentinel.write_bytes(b"outside product root, inside synthetic tree\n")
        self.existing = self.root / "var/seafloor/drafts/existing.json"
        self.existing.write_bytes(b"retained existing draft\n")
        self.escape = self.root / "var/seafloor/escape.json"
        self.escape.write_bytes(b"retained traversal target\n")
        self.calls = []
        self.writes = []
        self.real_read = self.draft.read_json
        self.real_writer = self.draft.atomic_json
        self.read_rows = []
        self.forbid_ingest = False
        self.forbid_writer = False
        self.patches = [patch.object(self.draft, "ingest", self.inert_ingest),
                        patch.object(self.draft, "atomic_json", self.writer),
                        patch.object(self.draft, "read_json", self.reader)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.check_guard)

    def check_guard(self):
        self.assertEqual(self.guard.unexpected, [])

    def reader(self, path):
        self.assertEqual(path, self.catalog)
        value = self.real_read(path)
        self.read_rows.append(value)
        return value

    def writer(self, path, value, **kwargs):
        self.writes.append(path)
        if self.forbid_writer:
            raise AssertionError("atomic writer must not be called")
        self.assertTrue(path.is_relative_to(self.root / "var/seafloor/drafts"))
        return self.real_writer(path, value, **kwargs)

    def inert_ingest(self, row, bounds, **kwargs):
        self.calls.append((deepcopy(row), deepcopy(bounds), kwargs.copy()))
        if self.forbid_ingest:
            raise AssertionError("ingest must not be called")
        self.assertEqual(kwargs["root"], self.root)
        return deepcopy(self.saved), False, True

    def catalog_rows(self, rows):
        self.catalog.write_text(json.dumps({"schema_version": 1, "surveys": rows}) + "\n")
        self.original_document = {"schema_version": 1, "surveys": deepcopy(rows)}
        self.before = {str(path.relative_to(self.tree)): file_hash(path)
                       for path in (self.catalog, self.sentinel, self.existing, self.escape)}
        self.preservation["before"] = self.before

    def unchanged(self):
        after = {name: file_hash(self.tree / name) for name in self.before}
        self.preservation["after"] = after
        self.assertEqual(after, self.before)
        self.assertEqual(self.read_rows, [self.original_document] * len(self.read_rows))

    def reject(self, ident, *, matched):
        self.row["id"] = ident
        self.catalog_rows([self.row] if matched else [])
        self.forbid_ingest = self.forbid_writer = True
        try:
            with self.assertRaisesRegex(ValueError, "^Invalid survey ID$"):
                self.draft.add_survey(URL, BOUNDS, root=self.root,
                                      **({} if matched else {"ident": ident}))
            self.assertEqual(self.calls, [])
            self.assertEqual(self.writes, [])
            self.assertEqual(sorted(p.name for p in (self.root / "var/seafloor/drafts").iterdir()),
                             ["existing.json"])
        finally:
            self.unchanged()

    def positive(self, ident="survey-valid", *, matched=True, member="unknown", **kwargs):
        self.row["id"] = ident
        self.catalog_rows([self.row] if matched else [])
        requested = {} if matched else {"ident": ident}
        requested.update(kwargs)
        dest = self.draft.add_survey(URL, BOUNDS, root=self.root, member=member, **requested)
        expected_id = ident or "survey-" + hashlib.sha256(URL.encode()).hexdigest()[:16]
        self.assertEqual(dest, self.root / "var/seafloor/drafts" / (expected_id + ".json"))
        self.assertEqual(self.writes, [dest])
        self.assertEqual(len(self.calls), 1)
        ingested, bounds, options = self.calls[0]
        self.assertEqual(ingested["id"], expected_id)
        self.assertEqual(bounds, BOUNDS)
        self.assertEqual(options, {"root": self.root, "fetch": kwargs.get("fetch", False),
                                   "local": kwargs.get("local")})
        actual = json.loads(dest.read_text())
        self.assertEqual(actual["adapter_review"], self.saved)
        self.assertIs(actual["downloaded"], False)
        self.assertIs(actual["normalization_reused"], True)
        expected_row = deepcopy(ingested)
        expected_row.update(status="candidate", sha256=self.saved["source_sha256"],
                            bytes=self.saved["source_bytes"], resolution_m=3.0,
                            horizontal_crs="EPSG:4326", vertical_datum="unknown", hold_reason="unknown")
        self.assertEqual(actual["row"], expected_row)
        self.assertEqual(ingested["url"], URL)
        self.assertEqual(ingested["kind"], "bathymetry")
        if matched:
            source = deepcopy(self.row)
            if member != "unknown":
                source["archive_member"] = member
            self.assertEqual(ingested, source)
        else:
            self.assertEqual(ingested["status"], "candidate")
            self.assertEqual(ingested["format"], kwargs.get("format_name") or "usgs-geotiff")
            self.assertEqual(ingested["archive_member"], member)
            self.assertEqual(ingested["title"], "survey.tif")
            self.assertEqual(ingested["publisher"], "unknown")
            self.assertEqual(ingested["license"], "unknown")
            self.assertEqual(ingested["evidence"], [])
            self.assertEqual(ingested["field_evidence"], {})
        self.unchanged()
        return dest

    def test_positive_matched(self):
        self.positive(fetch=True, local=self.tree / "inert-local.tif")

    def test_positive_new(self):
        self.positive("explicit-new", matched=False, format_name="bag", member="member.bag")

    def test_positive_generated(self):
        self.positive(None, matched=False)

    def test_member_override_and_copy_nonmutation(self):
        self.positive(member="override.tif")
        self.assertEqual(self.read_rows[0]["surveys"][0]["archive_member"], "original.tif")

    def test_multi_product_refusal(self):
        row2 = deepcopy(self.row)
        row2["id"] = "survey-second"
        self.catalog_rows([self.row, row2])
        self.forbid_ingest = self.forbid_writer = True
        with self.assertRaisesRegex(ValueError, "Select --id for a URL with multiple products"):
            self.draft.add_survey(URL, BOUNDS, root=self.root)
        self.assertEqual((self.calls, self.writes), ([], []))
        self.unchanged()

    def test_explicit_catalog_selection(self):
        row2 = deepcopy(self.row)
        row2["id"] = "survey-second"
        self.catalog_rows([self.row, row2])
        dest = self.draft.add_survey(URL, BOUNDS, ident="survey-second", root=self.root)
        self.assertEqual(dest.name, "survey-second.json")
        self.assertEqual(self.calls[0][0], row2)
        self.unchanged()

    def test_generated_deterministic(self):
        dest = self.positive(None, matched=False)
        original = dest.read_bytes()
        self.calls.clear()
        self.writes.clear()
        repeat = self.draft.add_survey(URL, BOUNDS, root=self.root)
        self.assertEqual(repeat, dest)
        self.assertEqual(repeat.read_bytes(), original)
        self.unchanged()

    def test_valid_grammar_edges(self):
        for ident in ("ab", "a0", "a-", "a" * 64):
            self.calls.clear()
            self.writes.clear()
            self.read_rows.clear()
            self.positive(ident)

    def test_isolation_allowed_and_denied_synthetic_control(self):
        allowed = self.tree / "allowed-control.txt"
        self.guard.authorize(allowed, write=True)
        allowed.write_text("inert synthetic control\n")
        self.assertEqual(allowed.read_text(), "inert synthetic control\n")
        # Exercise the same policy method without performing a forbidden open.
        denied = self.guard.synthetic.parent / "inert-denied-sentinel"
        with self.assertRaisesRegex(PermissionError, "SC82 synthetic file boundary"):
            self.guard.authorize(denied, write=True, control=True)
        self.assertEqual(self.guard.events[-1]["control"], True)
        self.assertEqual(self.guard.unexpected, [])

    def test_negative_control_shared_check_only(self):
        self.assertTrue(callable(self.draft._validate_survey_id))
        original = self.draft._validate_survey_id
        with patch.object(self.draft, "_validate_survey_id", lambda ident: None):
            with self.assertRaisesRegex(AssertionError, "^ingest must not be called$"):
                self.reject("../escape", matched=True)
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.calls[0][0]["id"], "../escape")
            self.assertEqual(self.writes, [])
            self.preservation["mutant_detected"] = True
            self.forbid_ingest = self.forbid_writer = False
            self.calls.clear()
            self.read_rows.clear()
            self.positive()
            self.preservation["positive_passed"] = True
        self.assertIs(self.draft._validate_survey_id, original)
        self.calls.clear()
        self.writes.clear()
        self.read_rows.clear()
        self.positive()
        self.preservation["restored_positive_passed"] = True


def invalid_case(ident, matched):
    def test(self):
        self.reject(deepcopy(ident), matched=matched)
    test.assertion_class = "invalid-effective-id/no-ingest/no-write/preservation"
    return test


def fallback_case(ident):
    def test(self):
        self.positive(deepcopy(ident), matched=False)
    test.assertion_class = "compatibility/documented-falsy-fallback"
    return test


for label, value in INVALID.items():
    setattr(DraftIDCases, "test_reject_matched_" + label.replace("-", "_"), invalid_case(value, True))
    if value:
        setattr(DraftIDCases, "test_reject_new_" + label.replace("-", "_"), invalid_case(value, False))
    else:
        setattr(DraftIDCases, "test_fallback_new_" + label.replace("-", "_"), fallback_case(value))

# Each receipt records the method's assertion class, not a guessed test count.
for name in unittest.defaultTestLoader.getTestCaseNames(DraftIDCases):
    method = getattr(DraftIDCases, name)
    if not hasattr(method, "assertion_class"):
        method.assertion_class = "negative-control" if "negative_control" in name else "compatibility/isolation"


def load_suite(suite):
    names = unittest.defaultTestLoader.getTestCaseNames(DraftIDCases)
    if suite == "compatibility":
        names = [n for n in names if not n.startswith("test_reject_") and "negative_control" not in n]
    elif suite == "regression":
        names = [n for n in names if "negative_control" not in n]
    elif suite == "negative-control":
        names = ["test_negative_control_shared_check_only", "test_positive_matched",
                 "test_isolation_allowed_and_denied_synthetic_control"]
    elif suite == "baseline-regression":
        names = ["test_reject_matched_traversal", "test_positive_matched"]
    else:
        raise ValueError("Unknown suite")
    return unittest.TestSuite(DraftIDCases(name) for name in names)
