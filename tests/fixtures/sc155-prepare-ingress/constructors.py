"""SC155 portable synthetic constructors for prepare_round --inputs (no host paths, no I/O).

The object uses the review-context/inputs vocabulary of tests/coast_contract_factory.py
(header + plan identity + context fields) with deterministic synthetic values built
at runtime. It is only decoded by the ingress under test; prepare is never run.
"""
import json


def _ref(path):
    return dict(root_id="queue:synthetic", path=path, sha256="a" * 64, bytes=1)


def prepare_inputs():
    leaf = _ref("provenance/leaf.txt")
    return dict(
        schema="coast-review-context-v1",
        created_utc="2026-10-21T00:00:00Z", author_profile="fixture", author_model="synthetic-author",
        card_id="t_366d24e2", code_commit="1" * 40, skill_commit="2" * 40,
        campaign_segment_id="synthetic", coordinator_segment_id="seg:3310:-5000:0:5000",
        plan_id="plan01", plan_sha256="b" * 64,
        review_round=1, attempt=1,
        identity_provenance=leaf, run_author_model="synthetic-author", run_author_provenance=leaf,
        run_card_id="t_366d24e2", root_ids=["queue:synthetic"], posted_hashes=_ref("provenance/posted-01.txt"),
        routing=_ref("provenance/routing.json"), thresholds=leaf, prompts=[leaf],
        supersedes=None, correction_verdict=None, ledger_snapshot=None,
        mode="normal", admission=_ref("plans/plan01/admission.json"), run=_ref("plans/plan01/runs/run.json"),
        bridge=leaf, enqueue=_ref("plans/plan01/enqueue.json"), observations=[])


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def padded(value, size):
    """Valid JSON of exactly ``size`` bytes: compact object plus trailing whitespace."""
    body = encode(value)
    if size < len(body) + 1:
        raise ValueError("requested size is smaller than the encoded object")
    return body + b" " * (size - len(body) - 1) + b"\n"
