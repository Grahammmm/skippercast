"""SC-SCHEMA-CLOSURE: static offline dependency closure of explicitly listed JSON Schemas.

Three groups, selected by class name in scripts/accept_sc_schema_closure.py:
    TestFocusedClosure      A1 focused behaviour on tiny synthetic schemas and the real family
    TestContractRealFamily  A2 producer contract against the pinned real families and the
                            independent oracle expectations frozen in the fixtures
    TestNegativeClosure     A3 unsafe/malformed input, refusals and preservation

Paths derive from this file; nothing reads a box-specific location. Temporary trees are
created with tempfile.mkdtemp and never removed by the tests (no deletion).
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "sc_schema_closure"
MODULE_PATH = REPO / "scripts" / "coast_diagnostics" / "schema_closure.py"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def load_module():
    spec = importlib.util.spec_from_file_location("sc_schema_closure_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sc = load_module()


RUNNER_PATH = REPO / "scripts" / "accept_sc_schema_closure.py"


def fresh_dir():
    # Physical (symlink-free) path: platforms alias their temporary directory through a
    # symlink, and the tool refuses every symlinked ancestor.
    return Path(os.path.realpath(tempfile.mkdtemp(prefix="sc-schema-closure-")))


def load_runner():
    spec = importlib.util.spec_from_file_location("accept_sc_schema_closure_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(report):
    return {r["pointer"]: r["classification"] for r in report["references"]}


def targets(report):
    return {r["pointer"]: (r["resolution_target"] or {}).get("pointer") for r in report["references"]}


def stop_io(*args, **kwargs):
    raise AssertionError("I/O reached through an unsafe path")


def stage(documents, root=None):
    """Write {logical path: JSON value or raw bytes} under a fresh root; return (manifest, root)."""
    root = fresh_dir() if root is None else root
    files = []
    for path, value in documents.items():
        data = value if isinstance(value, bytes) else json.dumps(value, indent=1).encode()
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    return {"schema": "sc-schema-closure-input-v1", "files": files}, root


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def codes(report, severity=None):
    return sorted(f["code"] for f in report["findings"] if severity is None or f["severity"] == severity)


def finding(report, code):
    rows = [f for f in report["findings"] if f["code"] == code]
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one {code} finding, got {rows}")
    return rows[0]


def edge_key(row):
    return (row["source_path"], row["pointer"], row["keyword"], row["reference"],
            row["target_path"], row["target_pointer"])


def missing_edges(report, expected_rows):
    """Closure-completeness assertion: every expected resolved reference has exactly its edge."""
    have = {edge_key(e) for e in report["edges"]}
    want = {edge_key(r) for r in expected_rows if r["outcome"] == "resolved"}
    return sorted(want - have)


def assert_closure_complete(report, expected_rows):
    missing = missing_edges(report, expected_rows)
    if missing:
        raise AssertionError(f"closure incomplete: {len(missing)} expected edge(s) missing: {missing}")


A = "https://example.test/s/a.schema.json"
B = "https://example.test/s/b.schema.json"


def doc(ident=None, **body):
    value = {"$schema": DIALECT}
    if ident is not None:
        value["$id"] = ident
    value.update(body)
    return value


class TestFocusedClosure(unittest.TestCase):
    """A1: closed chains resolve; duplicates, missing fragments and cycles are exact and visible."""

    def test_closed_two_document_chain_and_fragments_resolve(self):
        manifest = load_json(FIXTURES / "closed-manifest.json")
        report = sc.inspect_closure(manifest, FIXTURES)
        self.assertEqual(report["schema"], "sc-schema-closure-v1")
        self.assertIs(report["execution_allowed"], False)
        self.assertEqual((report["status"], report["exit_code"]), ("closed", 0))
        self.assertEqual(codes(report, "error") + codes(report, "unverified"), [])
        targets = {(e["source_path"], e["pointer"]): (e["target_path"], e["target_pointer"], e["status"])
                   for e in report["edges"]}
        self.assertEqual(targets, {
            ("closed/a.schema.json", "/properties/slug/$ref"): ("closed/b.schema.json", "/$defs/slug", "resolved"),
            ("closed/a.schema.json", "/properties/named/$ref"): ("closed/b.schema.json", "/$defs/slug", "resolved"),
            ("closed/a.schema.json", "/properties/local/$ref"): ("closed/a.schema.json", "/$defs/local", "resolved"),
        })
        self.assertTrue(all(r["classification"] == "resolved" for r in report["references"]))
        self.assertEqual(report["input"]["files"], [
            {"path": row["path"], "sha256": row["sha256"],
             "bytes": (FIXTURES / row["path"]).stat().st_size} for row in manifest["files"]])
        self.assertEqual(report["document_edges"],
                         [{"source_path": "closed/a.schema.json", "target_path": "closed/b.schema.json", "count": 2}])
        # a.schema.json has no referrer in the manifest: visible, informational, not a failure
        self.assertEqual(finding(report, "unused_schema")["source_path"], "closed/a.schema.json")
        self.assertEqual(finding(report, "unused_schema")["severity"], "info")

    def test_real_family_every_occurrence_classified(self):
        manifest = load_json(FIXTURES / "real" / "pinned-manifest.json")
        report = sc.inspect_closure(manifest, REPO)
        scanned = []

        def scan(value, pointer, path):
            if isinstance(value, dict):
                for key, child in value.items():
                    token = key.replace("~", "~0").replace("/", "~1")
                    if key in ("$ref", "$dynamicRef"):
                        scanned.append((path, pointer + "/" + token))
                    scan(child, pointer + "/" + token, path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    scan(child, f"{pointer}/{index}", path)

        for row in manifest["files"]:
            scan(load_json(REPO / row["path"]), "", row["path"])
        listed = [(r["source_path"], r["pointer"]) for r in report["references"]]
        self.assertEqual(sorted(listed), sorted(scanned))
        self.assertGreater(len(listed), 0)
        allowed = {"resolved", "unverified_dynamic", "outside_schema_location"} | set(sc.ERROR_CODES)
        self.assertTrue(all(r["classification"] in allowed for r in report["references"]))
        self.assertEqual(report["exit_code"], 0 if report["status"] == "closed" else 1)
        self.assertEqual({d["dialect"] for d in report["dialects"]}, {DIALECT})
        meta = [e for e in report["edges"] if "json-schema.org" in e["target_path"]]
        self.assertEqual(meta, [])

    def test_duplicate_ids_give_exact_file_and_pointer(self):
        manifest, root = stage({
            "one.json": doc(A, type="object"),
            "nested/two.json": doc("https://example.test/other.json", **{"$defs": {"x": {"$id": A}}}),
        })
        report = sc.inspect_closure(manifest, root)
        rows = sorted((f["source_path"], f["pointer"]) for f in report["findings"] if f["code"] == "duplicate_id")
        self.assertEqual(rows, [("nested/two.json", "/$defs/x/$id"), ("one.json", "/$id")])
        self.assertEqual((report["status"], report["exit_code"]), ("open", 1))

    def test_missing_pointer_and_anchor_give_exact_findings(self):
        manifest, root = stage({
            "a.json": doc(A, properties={"p": {"$ref": "b.schema.json#/$defs/nope"},
                                         "q": {"$ref": "b.schema.json#nope"}}),
            "b.json": doc(B, **{"$defs": {"yes": {"type": "string"}}}),
        })
        report = sc.inspect_closure(manifest, root)
        missing = finding(report, "missing_pointer_target")
        self.assertEqual((missing["source_path"], missing["pointer"], missing["reference"]),
                         ("a.json", "/properties/p/$ref", "b.schema.json#/$defs/nope"))
        self.assertEqual(missing["resolution_target"], {"path": "b.json", "pointer": "/$defs/nope"})
        anchor = finding(report, "missing_anchor")
        self.assertEqual((anchor["source_path"], anchor["pointer"]), ("a.json", "/properties/q/$ref"))
        self.assertEqual(report["exit_code"], 1)

    def test_cycles_are_bounded_visible_and_informational(self):
        documents = {}
        size = 100
        for index in range(size):
            nxt = (index + 1) % size
            documents[f"ring/{index:03d}.json"] = doc(f"https://example.test/ring/{index:03d}.json",
                                                      properties={"next": {"$ref": f"{nxt:03d}.json"}})
        documents["self.json"] = doc("https://example.test/self.json", items={"$ref": "#"})
        manifest, root = stage(documents)
        report = sc.inspect_closure(manifest, root)
        self.assertEqual((report["status"], report["exit_code"]), ("closed", 0))
        self.assertEqual(len(report["cycles"]), 2)
        ring = [c for c in report["cycles"] if len(c["documents"]) == size][0]
        self.assertEqual(len(ring["edges"]), size)
        selfloop = [c for c in report["cycles"] if c["documents"] == ["self.json"]][0]
        self.assertEqual(selfloop["edges"], [{"source_path": "self.json", "pointer": "/items/$ref",
                                              "target_path": "self.json", "target_pointer": ""}])
        self.assertEqual([f["severity"] for f in report["findings"] if f["code"] == "cycle"], ["info", "info"])

    def test_schema_dialect_is_reported_not_fetched(self):
        manifest, root = stage({"a.json": doc(A, **{"$defs": {"x": {"$schema": "https://meta.test/custom"}}})})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(report["references"], [])
        self.assertEqual(report["dialects"], [
            {"source_path": "a.json", "pointer": "/$defs/x/$schema", "dialect": "https://meta.test/custom"},
            {"source_path": "a.json", "pointer": "/$schema", "dialect": DIALECT}])
        self.assertEqual(report["exit_code"], 0)

    def test_dynamic_anchor_resolution_is_unverified(self):
        manifest, root = stage({
            "a.json": doc(A, **{"$dynamicAnchor": "node", "items": {"$dynamicRef": "#node"},
                                "$defs": {"plain": {"$dynamicRef": "#/$defs/leaf"}, "leaf": {"type": "string"}}}),
        })
        report = sc.inspect_closure(manifest, root)
        unverified = finding(report, "dynamic_resolution_unverified")
        self.assertEqual((unverified["severity"], unverified["pointer"]), ("unverified", "/items/$dynamicRef"))
        self.assertEqual(unverified["resolution_target"], {"path": "a.json", "pointer": ""})
        by_pointer = {r["pointer"]: r["classification"] for r in report["references"]}
        self.assertEqual(by_pointer, {"/items/$dynamicRef": "unverified_dynamic",
                                      "/$defs/plain/$dynamicRef": "resolved"})
        self.assertEqual((report["status"], report["exit_code"]), ("open", 1))

    def test_reference_keys_outside_schema_locations_are_not_edges(self):
        manifest, root = stage({
            "a.json": doc(A, const={"$ref": "#/nowhere"}, enum=[{"$ref": "x"}],
                          properties={"$ref": {"type": "string"}}),
        })
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(report["edges"], [])
        outside = sorted(f["pointer"] for f in report["findings"] if f["code"] == "reference_outside_schema_location")
        self.assertEqual(outside, ["/const/$ref", "/enum/0/$ref"])
        self.assertEqual(report["exit_code"], 0)

    def test_embedded_resource_and_repeated_occurrences(self):
        manifest, root = stage({
            "a.json": doc(A, **{"$defs": {"inner": {"$id": "inner/x.json", "$defs": {"v": {"type": "integer"}}}}}),
            "b.json": doc(B, properties={"one": {"$ref": "inner/x.json#/$defs/v"},
                                         "two": {"$ref": "inner/x.json#/$defs/v"}}),
        })
        report = sc.inspect_closure(manifest, root)
        rows = [(e["pointer"], e["target_path"], e["target_pointer"]) for e in report["edges"]]
        self.assertEqual(rows, [("/properties/one/$ref", "a.json", "/$defs/inner/$defs/v"),
                                ("/properties/two/$ref", "a.json", "/$defs/inner/$defs/v")])
        self.assertIn({"path": "a.json", "pointer": "/$defs/inner", "id": "https://example.test/s/inner/x.json",
                       "kind": "embedded"}, report["nodes"])
        self.assertEqual(report["exit_code"], 0)

    def test_anchor_conflicts_and_dual_keyword_anchor(self):
        manifest, root = stage({
            "a.json": doc(A, items={"$ref": "#same"}, contains={"$ref": "#twice"},
                          **{"$defs": {"s": {"$anchor": "same", "$dynamicAnchor": "same"},
                                       "t1": {"$anchor": "twice"}, "t2": {"$anchor": "twice"}}}),
        })
        report = sc.inspect_closure(manifest, root)
        by_pointer = {r["pointer"]: r["classification"] for r in report["references"]}
        self.assertEqual(by_pointer, {"/items/$ref": "resolved", "/contains/$ref": "ambiguous_resource"})
        self.assertEqual(sorted(f["pointer"] for f in report["findings"] if f["code"] == "duplicate_anchor"),
                         ["/$defs/t1/$anchor", "/$defs/t2/$anchor"])
        self.assertEqual(report["exit_code"], 1)

    def test_boolean_schema_document_is_accepted(self):
        manifest, root = stage({"t.json": True, "a.json": doc(A, items={"$ref": "#/$defs/t"}, **{"$defs": {"t": False}})})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(report["edges"][0]["target_pointer"], "/$defs/t")
        self.assertEqual(report["exit_code"], 0)

    def test_pointer_reached_object_dependency_is_not_ignored(self):
        # Review round 1 item 2: a reference into a non-keyword location makes that object a
        # schema; its own unresolved dependency must keep the closure open.
        manifest, root = stage({"a.json": doc("https://example.test/p.json", **{
            "$ref": "#/custom", "custom": {"$ref": "https://missing.test/not-staged.json"}})})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(classify(report), {"/$ref": "resolved", "/custom/$ref": "unresolved_resource"})
        self.assertNotIn("reference_outside_schema_location", codes(report))
        self.assertEqual((report["status"], report["exit_code"]), ("open", 1))

    def test_pointer_reached_chains_repeats_and_cycles_are_analysed(self):
        manifest, root = stage({
            "a.json": doc(A, **{"allOf": [{"$ref": "#/x"}, {"$ref": "#/x"}],
                                "x": {"$ref": "#/y", "properties": {"p": {"$ref": "b.schema.json"}}},
                                "y": {"$ref": "#/x"},
                                "const": {"$ref": "#/nowhere"}}),
            "b.json": doc(B, type="string"),
        })
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(classify(report), {
            "/allOf/0/$ref": "resolved", "/allOf/1/$ref": "resolved", "/x/$ref": "resolved",
            "/x/properties/p/$ref": "resolved", "/y/$ref": "resolved",
            "/const/$ref": "outside_schema_location"})
        self.assertEqual(targets(report)["/x/properties/p/$ref"], "")
        self.assertEqual(targets(report)["/y/$ref"], "/x")
        self.assertEqual([f["pointer"] for f in report["findings"] if f["code"] == "reference_outside_schema_location"],
                         ["/const/$ref"])
        self.assertEqual(len(report["cycles"]), 1)
        self.assertEqual({(e["pointer"], e["target_pointer"]) for e in report["cycles"][0]["edges"]},
                         {("/x/$ref", "/y"), ("/y/$ref", "/x")})
        self.assertEqual(report["document_edges"],
                         [{"source_path": "a.json", "target_path": "b.json", "count": 1}])
        self.assertEqual((report["status"], report["exit_code"]), ("closed", 0))

    def test_percent_encoded_fragments_resolve_after_one_decode(self):
        manifest, root = stage({"a.json": doc(A, **{
            "$defs": {"leaf": {"$anchor": "leaf", "type": "string"}, "a/b": {}, "caf\u00e9": {}},
            "properties": {"enc_ptr": {"$ref": "#%2F$defs%2Fleaf"}, "enc_anchor": {"$ref": "#%6Ceaf"},
                           "enc_token": {"$ref": "#/$defs/a%7E1b"}, "utf8": {"$ref": "#/$defs/caf%C3%A9"},
                           "raw_utf8": {"$ref": "#/$defs/caf\u00e9"}, "plain": {"$ref": "#/$defs/leaf"}}})})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(set(classify(report).values()), {"resolved"})
        self.assertEqual(targets(report), {
            "/properties/enc_ptr/$ref": "/$defs/leaf", "/properties/enc_anchor/$ref": "/$defs/leaf",
            "/properties/enc_token/$ref": "/$defs/a~1b", "/properties/utf8/$ref": "/$defs/caf\u00e9",
            "/properties/raw_utf8/$ref": "/$defs/caf\u00e9", "/properties/plain/$ref": "/$defs/leaf"})
        raw = {r["pointer"]: r["reference"] for r in report["references"]}
        self.assertEqual(raw["/properties/enc_ptr/$ref"], "#%2F$defs%2Fleaf")
        self.assertEqual(raw["/properties/enc_anchor/$ref"], "#%6Ceaf")
        self.assertEqual((report["status"], report["exit_code"]), ("closed", 0))


class TestContractRealFamily(unittest.TestCase):
    """A2: the pinned recipe/shared families, the real CLI, relocation and order determinism."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = load_json(FIXTURES / "real" / "pinned-manifest.json")
        cls.provenance = load_json(FIXTURES / "real" / "pinned-provenance.json")
        cls.oracle = load_json(FIXTURES / "real" / "oracle-expected-refs.json")
        cls.ids = load_json(FIXTURES / "real" / "oracle-expected-ids.json")

    def run_cli(self, manifest, root):
        work = fresh_dir()
        manifest_path = work / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        out = work / "report.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(root), "--out", str(out)])
        return status, out.read_bytes()

    def test_pinned_manifest_matches_staged_family_bytes(self):
        families = self.provenance["families"]
        self.assertEqual(families, ["schemas", "skills/coast-campaign-shared/schemas"])
        staged = sorted(f"{family}/{p.name}" for family in families
                        for p in (REPO / family).glob("*.schema.json"))
        self.assertEqual(sorted(r["path"] for r in self.manifest["files"]), staged,
                         "schema family listing changed since the pinned base; refresh the pinned fixtures")
        for row in self.manifest["files"]:
            data = (REPO / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"], row["path"])
        self.assertEqual(self.provenance["count"], len(self.manifest["files"]))
        manifest_bytes = (FIXTURES / "real" / "pinned-manifest.json").read_bytes()
        self.assertEqual(self.oracle["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
        self.assertEqual(self.ids["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())

    def test_real_cli_matches_independent_oracle(self):
        status, data = self.run_cli(self.manifest, REPO)
        report = json.loads(data)
        oracle_rows = self.oracle["references"]
        # Source-derived expectation: the pinned shared family declares the same $id in several
        # oneOf branches, so the real closure is NOT closed. That nonzero status is expected
        # evidence, frozen here; it is not an exemption.
        expected_open = any(r["outcome"] != "resolved" for r in oracle_rows) or bool(self.ids["duplicate_ids"])
        self.assertTrue(expected_open)
        self.assertEqual(status, 1 if expected_open else 0)
        self.assertEqual(report["exit_code"], status)
        self.assertEqual(report["status"], "open")
        duplicates = sorted((f["source_path"], f["pointer"], f["reference"]) for f in report["findings"]
                            if f["code"] in ("duplicate_id", "aliasing_id"))
        self.assertEqual(duplicates, [(r["source_path"], r["pointer"], r["id"]) for r in self.ids["duplicate_ids"]])
        self.assertEqual(sorted((n["path"], n["pointer"] + "/$id", n["id"]) for n in report["nodes"]),
                         [(r["source_path"], r["pointer"], r["id"]) for r in self.ids["ids"]])
        self.assertEqual(report["dialects"], self.ids["dialects"])
        blocking = sorted({f["code"] for f in report["findings"] if f["severity"] != "info"})
        self.assertEqual(blocking, ["duplicate_id"])
        ours = sorted((r["source_path"], r["pointer"], r["keyword"], r["reference"],
                       (r["resolution_target"] or {}).get("path"), (r["resolution_target"] or {}).get("pointer"))
                      for r in report["references"] if r["classification"] != "outside_schema_location")
        theirs = sorted((r["source_path"], r["pointer"], r["keyword"], r["reference"],
                         r.get("target_path"), r.get("target_pointer")) for r in oracle_rows)
        self.assertEqual(ours, theirs)
        assert_closure_complete(report, oracle_rows)
        self.assertEqual(len(report["edges"]), len(oracle_rows))
        outside = [(f["source_path"], f["pointer"]) for f in report["findings"]
                   if f["code"] == "reference_outside_schema_location"]
        self.assertEqual(outside, [(r["source_path"], r["pointer"])
                                   for r in self.oracle["reference_keys_outside_schema_locations"]])
        self.assertIs(report["execution_allowed"], False)
        self.assertEqual([(r["path"], r["sha256"]) for r in report["input"]["files"]],
                         [(r["path"], r["sha256"]) for r in self.manifest["files"]])

    def test_relocated_copy_and_input_order_are_byte_identical(self):
        status, baseline = self.run_cli(self.manifest, REPO)
        copy = fresh_dir() / "relocated"
        for row in self.manifest["files"]:
            target = copy / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / row["path"]).read_bytes())
        relocated_status, relocated = self.run_cli(self.manifest, copy)
        self.assertEqual((relocated_status, relocated), (status, baseline))
        files = list(self.manifest["files"])
        for permutation in (files[::-1], files[1::2] + files[0::2]):
            varied = {"files": permutation, "schema": self.manifest["schema"]}
            self.assertEqual(self.run_cli(varied, REPO), (status, baseline))

    def test_module_is_stdlib_only_and_never_executes_schemas(self):
        import ast
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertTrue(imported <= {"__future__", "argparse", "hashlib", "json", "os", "re", "stat", "sys"},
                        imported)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"eval", "exec", "compile", "__import__"})


class TestNegativeClosure(unittest.TestCase):
    """A3: unsafe or malformed input exits 2 before analysis; unbound references never leave the manifest."""

    def refused(self, manifest, root, code):
        with self.assertRaises(sc.ClosureInputError) as caught:
            sc.inspect_closure(manifest, root)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_duplicate_json_keys_refused(self):
        manifest, root = stage({"a.json": b'{"$id": "https://example.test/a.json", "$id": "https://example.test/b.json"}'})
        self.refused(manifest, root, "json_duplicate_key")

    def test_nonfinite_and_deep_and_non_schema_documents_refused(self):
        manifest, root = stage({"a.json": b'{"minimum": NaN}'})
        self.refused(manifest, root, "json_nonfinite")
        manifest, root = stage({"a.json": ('{"not":' * 300 + "true" + "}" * 300).encode()})
        self.refused(manifest, root, "json_too_deep")
        manifest, root = stage({"a.json": b'[1, 2]'})
        self.refused(manifest, root, "not_a_schema")
        manifest, root = stage({"a.json": b'\xff\xfe{}'})
        self.refused(manifest, root, "json_malformed")

    def test_aliasing_ids_conflict(self):
        manifest, root = stage({
            "a.json": doc("https://Example.TEST/s/./x.json"),
            "b.json": doc("https://example.test/s/%78.json"),
        })
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(codes(report, "error"), ["aliasing_id", "aliasing_id"])
        self.assertEqual(report["exit_code"], 1)

    def test_unbound_urls_and_file_references_never_leave_the_manifest(self):
        manifest, root = stage({
            "a.json": doc(A, properties={"url": {"$ref": "https://remote.test/x.json"},
                                         "file": {"$ref": "file:///etc/hostname"},
                                         "rel": {"$ref": "../../outside.json"},
                                         "name": {"$ref": "b.json"}}),
            "b.json": doc(None, items={"$ref": "a.json"}),
        })
        opened = []
        real_open = os.open

        def recording_open(path, *args, **kwargs):
            opened.append(os.fspath(path))
            return real_open(path, *args, **kwargs)

        def no_network(*args, **kwargs):
            raise AssertionError("network attempted")

        with mock.patch.object(socket, "socket", no_network), \
                mock.patch.object(socket, "getaddrinfo", no_network), \
                mock.patch.object(socket, "create_connection", no_network), \
                mock.patch("os.open", recording_open):
            report = sc.inspect_closure(manifest, root)
        by_pointer = {(r["source_path"], r["pointer"]): r["classification"] for r in report["references"]}
        self.assertEqual(by_pointer, {
            ("a.json", "/properties/url/$ref"): "unresolved_resource",
            ("a.json", "/properties/file/$ref"): "unbound_file_reference",
            ("a.json", "/properties/rel/$ref"): "unresolved_resource",
            ("a.json", "/properties/name/$ref"): "unresolved_resource",
            ("b.json", "/items/$ref"): "unbound_relative_reference",
        })
        self.assertEqual(sorted(opened), sorted(str(root / r["path"]) for r in manifest["files"]))
        self.assertEqual(report["edges"], [])
        self.assertEqual(report["exit_code"], 1)

    def test_traversal_and_unnormalized_logical_paths_refused(self):
        _, root = stage({"a.json": doc(A)})
        good = hashlib.sha256((root / "a.json").read_bytes()).hexdigest()
        for path in ("../a.json", "/a.json", "./a.json", "x/../a.json", "x//a.json", "x\\a.json", "",
                     "a.json/", "a.txt", "x/\u0000.json"):
            with self.subTest(path=path):
                self.refused({"schema": "sc-schema-closure-input-v1", "files": [{"path": path, "sha256": good}]},
                             root, "path_unsafe")
        self.refused({"schema": "sc-schema-closure-input-v1",
                      "files": [{"path": "a.json", "sha256": good}, {"path": "A.json", "sha256": good}]},
                     root, "path_duplicate")
        for manifest in ({"schema": "other", "files": []}, {"schema": "sc-schema-closure-input-v1"},
                         {"schema": "sc-schema-closure-input-v1", "files": [], "extra": 1},
                         {"schema": "sc-schema-closure-input-v1", "files": []},
                         {"schema": "sc-schema-closure-input-v1", "files": [{"path": "a.json", "sha256": "AB"}]},
                         {"schema": "sc-schema-closure-input-v1",
                          "files": [{"path": "a.json", "sha256": good, "x": 1}]}):
            with self.subTest(manifest=manifest):
                self.refused(manifest, root, "manifest_malformed")

    def test_invalid_percent_escapes_and_fragments(self):
        manifest, root = stage({
            "a.json": doc(A, properties={"pct": {"$ref": "#/$defs/%ZZ"}, "pctid": {"$ref": "b%G1.json"},
                                         "tilde": {"$ref": "#/$defs/a~2b"}, "name": {"$ref": "#bad!name"},
                                         "space": {"$ref": "b.json x"}},
                          **{"$defs": {"a~b": {}}}),
        })
        report = sc.inspect_closure(manifest, root)
        by_pointer = {r["pointer"]: r["classification"] for r in report["references"]}
        self.assertEqual(by_pointer, {
            "/properties/pct/$ref": "invalid_percent_escape",
            "/properties/pctid/$ref": "invalid_percent_escape",
            "/properties/tilde/$ref": "invalid_fragment",
            "/properties/name/$ref": "invalid_fragment",
            "/properties/space/$ref": "invalid_reference",
        })

    def test_malformed_dynamic_anchors_and_ids(self):
        manifest, root = stage({
            "a.json": doc(A, **{"$defs": {"n": {"$dynamicAnchor": "1bad"}, "t": {"$dynamicAnchor": 5},
                                          "i": {"$id": "x.json#frag"}, "j": {"$anchor": "a b"},
                                          "k": {"$ref": 7}}}),
        })
        report = sc.inspect_closure(manifest, root)
        rows = sorted((f["code"], f["pointer"]) for f in report["findings"] if f["severity"] == "error")
        self.assertEqual(rows, [("malformed_anchor", "/$defs/j/$anchor"),
                                ("malformed_dynamic_anchor", "/$defs/n/$dynamicAnchor"),
                                ("malformed_dynamic_anchor", "/$defs/t/$dynamicAnchor"),
                                ("malformed_id", "/$defs/i/$id"),
                                ("malformed_reference", "/$defs/k/$ref")])
        self.assertEqual(report["exit_code"], 1)

    def test_oversized_documents_and_aggregate_refused_before_reading(self):
        manifest, root = stage({"big.json": b" " * (sc.MAX_FILE_BYTES + 1) + b"{}"})
        with mock.patch.object(sc.hashlib, "sha256", side_effect=AssertionError("read before size check")):
            self.refused(manifest, root, "file_too_large")
        chunk = b"{}" + b" " * (sc.MAX_FILE_BYTES - 2)
        manifest, root = stage({f"f{i}.json": chunk for i in range(sc.MAX_TOTAL_BYTES // sc.MAX_FILE_BYTES + 1)})
        with mock.patch.object(sc.hashlib, "sha256", side_effect=AssertionError("read before size check")):
            self.refused(manifest, root, "aggregate_too_large")

    def test_more_than_128_entries_refused_before_any_file_access(self):
        rows = [{"path": f"f{i}.json", "sha256": "0" * 64} for i in range(sc.MAX_FILES + 1)]
        root = fresh_dir()
        with mock.patch("os.lstat", side_effect=AssertionError("file access before count check")):
            self.refused({"schema": "sc-schema-closure-input-v1", "files": rows}, root, "manifest_too_many_files")

    def test_row_cap_refused(self):
        props = {f"p{i}": {"$ref": "#/$defs/x"} for i in range(sc.MAX_ROWS + 1)}
        manifest, root = stage({"a.json": doc(A, properties=props, **{"$defs": {"x": {}}})})
        self.refused(manifest, root, "row_cap_exceeded")

    def test_symlink_ancestry_special_files_and_hash_mismatch(self):
        manifest, root = stage({"dir/a.json": doc(A)})
        link_root = fresh_dir() / "link-root"
        os.symlink(root, link_root)
        self.refused(manifest, link_root, "input_root_unsafe")
        other = fresh_dir()
        os.symlink(root / "dir", other / "dir")
        self.refused(manifest, other, "symlink_in_path")
        leaf = fresh_dir()
        (leaf / "dir").mkdir()
        os.symlink(root / "dir" / "a.json", leaf / "dir" / "a.json")
        self.refused(manifest, leaf, "symlink_in_path")
        fifo = fresh_dir()
        (fifo / "dir").mkdir()
        os.mkfifo(fifo / "dir" / "a.json")
        self.refused(manifest, fifo, "not_regular_file")
        self.refused(manifest, fresh_dir(), "missing_file")
        tampered = dict(manifest, files=[dict(manifest["files"][0], sha256="0" * 64)])
        self.refused(tampered, root, "hash_mismatch")

    def test_cli_refuses_preexisting_output_and_unsafe_output_parent(self):
        manifest, root = stage({"a.json": doc(A)})
        work = fresh_dir()
        manifest_path = work / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        existing = work / "report.json"
        existing.write_bytes(b"keep me\n")
        before = {p.name: p.read_bytes() for p in (manifest_path, existing, root / "a.json")}
        stderr = io.StringIO()
        with mock.patch.object(sys, "stderr", stderr), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(root), "--out", str(existing)])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "output_exists")
        self.assertEqual({p.name: p.read_bytes() for p in (manifest_path, existing, root / "a.json")}, before)
        linked = fresh_dir()
        os.symlink(work, linked / "via")
        with mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(root),
                              "--out", str(linked / "via" / "new.json")])
        self.assertEqual(status, 2)
        self.assertFalse((work / "new.json").exists())
        broken = work / "broken.json"
        broken.write_bytes(json.dumps(dict(manifest, files=[dict(manifest["files"][0], sha256="1" * 64)])).encode())
        out = work / "never.json"
        with mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(broken), "--input-root", str(root), "--out", str(out)])
        self.assertEqual(status, 2)
        self.assertFalse(out.exists())

    def test_cli_manifest_must_be_a_regular_non_symlink_file(self):
        manifest, root = stage({"a.json": doc(A)})
        work = fresh_dir()
        real = work / "manifest.json"
        real.write_text(json.dumps(manifest), encoding="utf-8")
        os.symlink(real, work / "alias.json")
        with mock.patch.object(sys, "stderr", io.StringIO()) as err, mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(work / "alias.json"), "--input-root", str(root),
                              "--out", str(work / "r.json")])
        self.assertEqual((status, json.loads(err.getvalue())["code"]), (2, "symlink_in_path"))
        self.assertFalse((work / "r.json").exists())

    def test_higher_symlink_ancestors_refused_before_io(self):
        # Review round 1 item 1: every ancestor, not only the root or immediate parent.
        base = fresh_dir()
        real = base / "real"
        manifest, nested = stage({"dir/a.json": doc(A)}, root=real / "nested")
        manifest_path = nested / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        os.symlink(real, base / "link")
        via = base / "link" / "nested"
        with mock.patch.object(sc, "_read_checked", stop_io):
            self.refused(manifest, via, "input_root_unsafe")
        for argv, code, never in (
                ([str(via / "manifest.json"), str(nested), str(base / "out1.json")], "symlink_in_path",
                 base / "out1.json"),
                ([str(manifest_path), str(via), str(base / "out2.json")], "input_root_unsafe", base / "out2.json"),
                ([str(manifest_path), str(nested), str(via / "out3.json")], "output_unsafe", nested / "out3.json"),
                ([str(manifest_path), str(nested), str(via / "deeper" / "out4.json")], "output_unsafe",
                 nested / "deeper")):
            with self.subTest(code=code, argv=argv):
                stderr = io.StringIO()
                with mock.patch.object(sc, "_read_checked", stop_io) if code != "input_root_unsafe" else \
                        mock.patch.object(sc, "_write_new", stop_io), \
                        mock.patch.object(sys, "stderr", stderr), mock.patch.object(sys, "stdout", io.StringIO()):
                    status = sc.main(["--manifest", argv[0], "--input-root", argv[1], "--out", argv[2]])
                self.assertEqual((status, json.loads(stderr.getvalue())["code"]), (2, code))
                self.assertFalse(never.exists())
        # Real-directory positives on the same physical tree.
        self.assertEqual(sc.inspect_closure(manifest, nested)["exit_code"], 0)
        with mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(nested),
                              "--out", str(nested / "ok.json")])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads((nested / "ok.json").read_text(encoding="utf-8"))["exit_code"], 0)

    def test_runner_output_refuses_symlinked_higher_ancestor(self):
        runner = load_runner()
        base = fresh_dir()
        (base / "real" / "nested").mkdir(parents=True)
        os.symlink(base / "real", base / "link")
        with mock.patch("os.mkdir", side_effect=AssertionError("mkdir reached through a symlink")):
            error = runner.prepare_output(str(base / "link" / "nested" / "run"))
        self.assertIsNotNone(error)
        self.assertFalse((base / "real" / "nested" / "run").exists())
        self.assertIsNone(runner.prepare_output(str(base / "real" / "nested" / "run")))
        self.assertTrue((base / "real" / "nested" / "run").is_dir())
        self.assertIsNotNone(runner.prepare_output(str(base / "real" / "nested" / "run")))  # write-once

    def test_row_cap_applies_to_every_emitted_collection(self):
        # Review round 1 item 4: on-boundary passes, one over is refused before resolution.
        cap = sc.MAX_ROWS

        def ids(n):
            return {"a.json": doc(A, **{"$defs": {f"d{i}": {"$id": f"https://example.test/ids/{i}.json"}
                                                  for i in range(n)}})}

        def anchors(n):
            return {"a.json": doc(A, **{"$defs": {f"d{i}": {"$anchor": f"a{i}"} for i in range(n)}})}

        def dialects(n):
            return {"a.json": doc(A, **{"$defs": {f"d{i}": {"$schema": DIALECT} for i in range(n)}})}

        def refs(n):
            return {"a.json": doc(A, properties={f"p{i}": {"$ref": "#/$defs/x"} for i in range(n)},
                                  **{"$defs": {"x": {}}})}

        def bad_anchors(n):
            return {"a.json": doc(A, **{"$defs": {f"d{i}": {"$anchor": "1bad"} for i in range(n)}})}

        cases = (("nodes", ids, cap - 1, True), ("anchors", anchors, cap, True),
                 ("dialects", dialects, cap - 1, True), ("references", refs, cap, False),
                 ("findings", bad_anchors, cap - 1, False))
        for name, build, boundary, before_resolution in cases:
            with self.subTest(collection=name):
                manifest, root = stage(build(boundary))
                report = sc.inspect_closure(manifest, root)
                self.assertEqual(len(report[name]), cap)
                manifest, root = stage(build(boundary + 1))
                if before_resolution:
                    with mock.patch.object(sc, "_resolve_reference", stop_io):
                        self.refused(manifest, root, "row_cap_exceeded")
                else:
                    self.refused(manifest, root, "row_cap_exceeded")

    def test_promoted_scope_identifiers_are_unverified_not_registered(self):
        manifest, root = stage({"a.json": doc(A, **{
            "$ref": "#/c", "c": {"$id": "https://example.test/c.json", "$anchor": "k",
                                 "$dynamicAnchor": "d", "$defs": {"q": {}}}})})
        report = sc.inspect_closure(manifest, root)
        rows = sorted((f["pointer"], f["severity"]) for f in report["findings"] if f["code"] == "promoted_scope_unverified")
        self.assertEqual(rows, [("/c/$anchor", "unverified"), ("/c/$dynamicAnchor", "unverified"),
                                ("/c/$id", "unverified")])
        self.assertNotIn("https://example.test/c.json", [n["id"] for n in report["nodes"]])
        self.assertEqual(report["anchors"], [])
        self.assertEqual((report["status"], report["exit_code"]), ("open", 1))

    def test_malformed_and_double_encoded_fragments(self):
        manifest, root = stage({"a.json": doc(A, **{
            "$dynamicAnchor": "node", "prefixItems": [{}],
            "$defs": {"leaf": {"$anchor": "leaf"}},
            "properties": {"bad_utf8": {"$ref": "#%FF"}, "double": {"$ref": "#%252F$defs%252Fleaf"},
                           "double_anchor": {"$ref": "#%256Ceaf"}, "missing": {"$ref": "#%2F$defs%2Fnope"},
                           "index_nl": {"$ref": "#/prefixItems/0%0A"}, "anchor_nl": {"$ref": "#leaf%0A"},
                           "dyn": {"$dynamicRef": "#%6Eode"}}})})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(classify(report), {
            "/properties/bad_utf8/$ref": "invalid_fragment", "/properties/double/$ref": "invalid_fragment",
            "/properties/double_anchor/$ref": "invalid_fragment",
            "/properties/missing/$ref": "missing_pointer_target",
            "/properties/index_nl/$ref": "missing_pointer_target", "/properties/anchor_nl/$ref": "invalid_fragment",
            "/properties/dyn/$dynamicRef": "unverified_dynamic"})
        self.assertEqual(report["exit_code"], 1)

    def test_long_numeric_pointer_indices_are_findings_not_crashes(self):
        # Round-2 return: _locate converted unbounded decimal tokens with int(), which raised
        # ValueError past the interpreter's integer-string digit limit. Long indices must be
        # ordinary missing_pointer_target findings (exit 1) with the safeguard left untouched.
        limit_before = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else None
        lengths = (4300, 4301, 5000, 20000)
        props = {f"long_{n}": {"$ref": "#/prefixItems/" + "1" * n} for n in lengths}
        props.update({
            "valid_0": {"$ref": "#/prefixItems/0"}, "missing_1": {"$ref": "#/prefixItems/1"},
            "missing_100": {"$ref": "#/prefixItems/100"},
            "leading_zero_long": {"$ref": "#/prefixItems/" + "0" * 5000},
            "long_object_key": {"$ref": "#/$defs/" + "7" * 5000},
        })
        manifest, root = stage({"a.json": doc(A, **{"prefixItems": [{}],
                                                     "$defs": {"7" * 5000: {"type": "string"}},
                                                     "properties": props})})
        before = (root / "a.json").read_bytes()
        report = sc.inspect_closure(manifest, root)
        expected = {f"/properties/long_{n}/$ref": "missing_pointer_target" for n in lengths}
        expected.update({"/properties/valid_0/$ref": "resolved", "/properties/missing_1/$ref": "missing_pointer_target",
                         "/properties/missing_100/$ref": "missing_pointer_target",
                         "/properties/leading_zero_long/$ref": "missing_pointer_target",
                         "/properties/long_object_key/$ref": "resolved"})
        self.assertEqual(classify(report), expected)
        missing = [f for f in report["findings"] if f["code"] == "missing_pointer_target"]
        self.assertEqual(len(missing), len(lengths) + 3)
        for row in missing:
            self.assertEqual(row["source_path"], "a.json")
            self.assertEqual(row["resolution_target"]["path"], "a.json")
        self.assertEqual(report["exit_code"], 1)
        # Actual CLI: report written, exit 1, inputs unchanged, safeguard unchanged, no overwrite.
        work = fresh_dir()
        manifest_path = work / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        out = work / "report.json"
        with mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(root), "--out", str(out)])
        self.assertEqual(status, 1)
        self.assertEqual(classify(load_json(out)), expected)
        written = out.read_bytes()
        self.assertEqual((root / "a.json").read_bytes(), before)
        stderr = io.StringIO()
        with mock.patch.object(sys, "stderr", stderr), mock.patch.object(sys, "stdout", io.StringIO()):
            status = sc.main(["--manifest", str(manifest_path), "--input-root", str(root), "--out", str(out)])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stderr.getvalue())["code"], "output_exists")
        self.assertEqual(out.read_bytes(), written)
        self.assertEqual((root / "a.json").read_bytes(), before)
        if limit_before is not None:
            self.assertEqual(sys.get_int_max_str_digits(), limit_before)

    def test_malformed_anchor_suffixes_and_lone_surrogates(self):
        # Review round 1 item 5: whole-string grammar; malformed Unicode is typed exit 2, no crash.
        manifest, root = stage({"a.json": doc(A, **{"$defs": {
            "n": {"$dynamicAnchor": "node\n"}, "m": {"$anchor": "ok\n"}, "c": {"$anchor": "ok\u0001"},
            "fine": {"$anchor": "fine"}}})})
        report = sc.inspect_closure(manifest, root)
        rows = sorted((f["code"], f["pointer"]) for f in report["findings"] if f["severity"] == "error")
        self.assertEqual(rows, [("malformed_anchor", "/$defs/c/$anchor"), ("malformed_anchor", "/$defs/m/$anchor"),
                                ("malformed_dynamic_anchor", "/$defs/n/$dynamicAnchor")])
        self.assertEqual([a["name"] for a in report["anchors"]], ["fine"])
        self.assertEqual(report["exit_code"], 1)
        for raw in (b'{"$ref": "#/\\ud800"}', b'{"$ref": "#/\\udc00"}', b'{"\\ud800": {}}',
                    b'{"$defs": {"x": {"$anchor": "a\\udfff"}}}'):
            with self.subTest(raw=raw):
                manifest, root = stage({"a.json": raw})
                self.refused(manifest, root, "json_invalid_unicode")
                work = fresh_dir()
                (work / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
                stderr = io.StringIO()
                with mock.patch.object(sys, "stderr", stderr), mock.patch.object(sys, "stdout", io.StringIO()):
                    status = sc.main(["--manifest", str(work / "m.json"), "--input-root", str(root),
                                      "--out", str(work / "r.json")])
                self.assertEqual((status, json.loads(stderr.getvalue())["code"]), (2, "json_invalid_unicode"))
                self.assertFalse((work / "r.json").exists())
                self.assertEqual((root / "a.json").read_bytes(), raw)
        manifest, root = stage({"a.json": b'{"$defs": {"\\ud83d\\ude00": {}}, "$ref": "#/$defs/\\ud83d\\ude00"}'})
        report = sc.inspect_closure(manifest, root)
        self.assertEqual(classify(report), {"/$ref": "resolved"})
        self.assertEqual(report["exit_code"], 0)

    def test_whole_string_grammar_for_manifest_hashes(self):
        manifest, root = stage({"a.json": doc(A)})
        row = manifest["files"][0]
        self.refused(dict(manifest, files=[dict(row, sha256=row["sha256"] + "\n")]), root, "manifest_malformed")

    def test_removing_one_real_edge_fails_closure_completeness(self):
        manifest = load_json(FIXTURES / "real" / "pinned-manifest.json")
        oracle = load_json(FIXTURES / "real" / "oracle-expected-refs.json")["references"]
        report = sc.inspect_closure(manifest, REPO)
        assert_closure_complete(report, oracle)            # positive control
        victim = sorted(report["edges"], key=edge_key)[0]
        mutated = dict(report, edges=[e for e in report["edges"] if e is not victim])
        with self.assertRaises(AssertionError) as caught:
            assert_closure_complete(mutated, oracle)
        self.assertIn(repr(edge_key(victim)), str(caught.exception))
        self.assertEqual(missing_edges(mutated, oracle), [edge_key(victim)])


if __name__ == "__main__":
    unittest.main()
