"""validate_input requires exactly one retained producer proof per mapping item.

Boundary scope: only contained_batch._prepare is replaced (by fully shaped
deterministic items). The real canonical descriptors, SQLite registration, proof
comparison, membership checks and byte resolution run. No native source, worker,
queue or scientific import is exercised.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import source_free
from skippercast.coastal.handoff.common import ref, write

MESSAGE = "exactly one retained producer proof per mapping item required"
NOW = 1000.0
HORIZON = 1100.0
DEADLINE = 2000.0


class Fixture:
    def __init__(self, root, monkeypatch, n_items):
        self.root = root
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(source_free.SCHEMA)
        self.store = SimpleNamespace(root=root, db=self.db, managed_outputs=None, policy={})
        self.items = [
            dict(result_ref=dict(path="results/r%d.json" % i, sha256=str(i) * 64, bytes=10, contract="r"),
                 facts=dict(header=dict(window=[i, i + 1])))
            for i in range(n_items)
        ]
        monkeypatch.setattr(source_free.contained_batch, "_prepare",
                            lambda *args, **kwargs: (list(self.items), [{} for _ in self.items]))

    def proof(self, index, *, registered=True, member=True, result=None, window=None):
        item = self.items[index]
        artifact_path = self.root / "retained" / ("a%d.json" % index)
        write(artifact_path, dict(index=index))
        artifact = ref(self.root, artifact_path, "retained-artifact")
        proof = dict(original_result=result or item["result_ref"],
                     window=window or item["facts"]["header"]["window"], retained_inputs=[artifact])
        path = self.root / "metadata" / ("proof%d.json" % index)
        write(path, proof)
        descriptor = ref(self.root, path, source_free.PROOF)
        if registered:
            self.db.execute("INSERT INTO retained_producers VALUES(?,?)",
                            (descriptor["sha256"], json.dumps(proof, sort_keys=True)))
        if member:
            self.db.execute("INSERT INTO retained_artifacts VALUES(?,?,?,?)",
                            (artifact["path"], artifact["sha256"], artifact["bytes"], descriptor["sha256"]))
        return descriptor

    def manifest(self, proofs, **extra):
        document = dict(schema=source_free.INPUT, source_accessed=False, packets=[], side="a",
                        deadline_epoch=DEADLINE, source_volume_allowance_bytes=0,
                        native_requests_allowance=0, imported_artifacts=[])
        document.update(extra)
        if proofs is not source_free:
            document["producer_proofs"] = proofs
        path = self.root / "metadata" / "manifest.json"
        write(path, document)
        descriptor = ref(self.root, path, source_free.INPUT)
        self.db.execute("INSERT INTO sourcefree_imports VALUES(?,?)",
                        (descriptor["sha256"], json.dumps(document, sort_keys=True)))
        self.db.commit()
        return descriptor

    def validate(self, descriptor):
        return source_free.validate_input(self.store, descriptor, now=NOW, horizon=HORIZON)

    def snapshot(self):
        files = sorted((str(p.relative_to(self.root)), p.read_bytes()) for p in self.root.rglob("*") if p.is_file())
        rows = [self.db.execute("SELECT * FROM %s ORDER BY 1,2" % t).fetchall()
                for t in ("sourcefree_imports", "retained_producers", "retained_artifacts")]
        return files, rows


@pytest.fixture
def make(tmp_path, monkeypatch):
    created = []

    def build(n_items=1):
        root = tmp_path / ("case%d" % len(created))
        root.mkdir()
        created.append(root)
        return Fixture(root, monkeypatch, n_items)
    return build


def test_empty_proof_list_cannot_skip_item(make):
    f = make(1)
    descriptor = f.manifest([])
    with pytest.raises(ValueError, match=MESSAGE):
        f.validate(descriptor)


def test_short_proof_tail_is_not_truncated(make):
    f = make(2)
    descriptor = f.manifest([f.proof(0)])
    with pytest.raises(ValueError, match=MESSAGE):
        f.validate(descriptor)


def test_surplus_proof_tail_is_not_ignored(make):
    f = make(1)
    unreadable = dict(path="metadata/missing-proof.json", sha256="f" * 64, bytes=1, contract=source_free.PROOF)
    descriptor = f.manifest([f.proof(0), unreadable])
    with pytest.raises(ValueError, match=MESSAGE):
        f.validate(descriptor)


@pytest.mark.parametrize("value", [None, "proof", {"path": "x"}, 1, True])
def test_proof_container_must_be_a_list(make, value):
    f = make(1)
    descriptor = f.manifest(value)
    with pytest.raises(ValueError, match=MESSAGE):
        f.validate(descriptor)


def test_missing_proof_field_keeps_existing_refusal(make):
    f = make(1)
    descriptor = f.manifest(source_free)
    with pytest.raises(KeyError):
        f.validate(descriptor)


@pytest.mark.parametrize("n_items", [1, 2])
def test_one_to_one_controls_keep_order(make, n_items):
    f = make(n_items)
    proofs = [f.proof(i) for i in range(n_items)]
    document, items = f.validate(f.manifest(proofs))
    assert document["producer_proofs"] == proofs
    assert items == f.items


IDENTITY = "retained producer/input identity changed"
MEMBERSHIP = "retained artifact producer membership missing"
OTHER = dict(path="results/other.json", sha256="e" * 64, bytes=10, contract="r")


def test_equal_length_swapped_proofs_still_refused(make):
    f = make(2)
    first, second = f.proof(0), f.proof(1)
    with pytest.raises(ValueError, match=IDENTITY):
        f.validate(f.manifest([second, first]))


@pytest.mark.parametrize("kwargs,message", [
    (dict(registered=False), IDENTITY),
    (dict(result=OTHER), IDENTITY),
    (dict(window=[9, 9]), IDENTITY),
    (dict(member=False), MEMBERSHIP),
])
def test_equal_length_proof_identity_still_checked(make, kwargs, message):
    f = make(1)
    with pytest.raises(ValueError, match=message):
        f.validate(f.manifest([f.proof(0, **kwargs)]))


def test_equal_length_invalid_proof_bytes_still_refused(make):
    f = make(1)
    descriptor = f.proof(0)
    (f.root / descriptor["path"]).write_bytes(b"{}")
    with pytest.raises(ValueError, match="artifact bytes/hash changed"):
        f.validate(f.manifest([descriptor]))


def test_validation_is_read_only(make):
    f = make(2)
    passing = f.manifest([f.proof(0), f.proof(1)])
    before = f.snapshot()
    f.validate(passing)
    assert f.snapshot() == before

    short = make(2)
    refusing = short.manifest([short.proof(0)])
    before = short.snapshot()
    with pytest.raises(ValueError, match=MESSAGE):
        short.validate(refusing)
    assert short.snapshot() == before
