"""SC-CACHE-CLOCK: cached metadata evidence times are explicit and host-timezone independent.

Synthetic metadata only. Test names carry their acceptance row (a1/a2/a3) so the
named runner (scripts/accept_sc_cache_clock.py) can select each suite; the same
tests also run under ordinary pytest discovery. ``naive_regression`` tests decide
the awareness gate, ``aware_positive`` tests are its positive control and
``completeness_gate`` tests decide the separate complete date-time gate.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from skippercast.coastal import cached_inventory as ci
from tests._support import FIXTURES

VECTORS = json.loads((FIXTURES / "sc_cache_clock" / "vectors.json").read_text(encoding="utf-8"))
GROUPS = VECTORS["equivalent_instants"]
INVALID = [(kind, text) for kind in ("naive", "date_only", "incomplete", "out_of_range",
                                     "invalid_offset", "malformed") for text in VECTORS[kind]]
AWARE_STRINGS = [text for group in GROUPS for text in group["strings"]]
RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "accept_sc_cache_clock.py"


def base_parse(text):
    """The base (59fca09b) string branch of epoch, used only as a compatibility oracle."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
CLOCK_ERROR = "explicit-offset complete date-time required"
N = 1767225600  # 2026-01-01T00:00:00Z
H = N + 3600
# Local offsets for the standard-library fake of host timezone; never the host's own.
FAKE_OFFSETS = (-12, -8, -7, 0, 5.5, 14)


def fake_local_datetime(offset_hours):
    """A datetime whose naive ``timestamp()`` behaves as in a host at ``offset_hours``."""
    zone = timezone(timedelta(hours=offset_hours))

    class FakeLocal(datetime):
        def timestamp(self):
            if self.tzinfo is None:
                return datetime.timestamp(self.replace(tzinfo=zone))
            return datetime.timestamp(self)
    return FakeLocal


def reference(path, contract):
    data = path.read_bytes()
    return dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contract=contract)


def legacy_plan(tmp_path, rights_times, scope_times):
    """A v2 metadata-only plan whose rights and scope pass every check except time."""
    source = dict(sha256="a" * 64, bytes=4, url="https://example.org/source.bag")
    (tmp_path / "source.bag").write_bytes(b"data")  # stat-only stand-in; never opened
    (tmp_path / "source.json").write_bytes(ci.encoded(source))
    identity = dict(sha256=source["sha256"], bytes=source["bytes"])
    rights = dict(schema="synthetic-rights-v1", independent=True, private_use=True,
                  accepted_source_rights_for_declared_private_purpose=True, holds_added=[],
                  source=identity, **rights_times)
    scope = dict(schema="synthetic-scope-v1", status="accepted_scope_only", independent=True, holds=[],
                 source=identity, window_set=[[0, 0, 4, 4]], product_region="synthetic",
                 native_quality_accepted=False, global_affine=None, grid_shape=None, **scope_times)
    (tmp_path / "rights.json").write_bytes(ci.encoded(rights))
    (tmp_path / "scope.json").write_bytes(ci.encoded(scope))
    candidate = dict(source_manifest=reference(tmp_path / "source.json", "cached-source-json-v1"),
                     rights=reference(tmp_path / "rights.json", "synthetic-rights-v1"),
                     scope=reference(tmp_path / "scope.json", "synthetic-scope-v1"),
                     cache_path="source.bag", window_set=[[0, 0, 4, 4]])
    return dict(schema=ci.PLAN, region="synthetic", candidates=[candidate],
                metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT,
                network_bytes=0, source_read_bytes=0, output_root=str(tmp_path / "output"))


def traced_inventory(tmp_path, value, now=N, horizon=H):
    """Run inventory, recording every bounded metadata read by name."""
    names = []
    original = ci.bounded_metadata_read

    def record(root, name, expected):
        names.append(name)
        return original(root, name, expected)
    with patch.object(ci, "bounded_metadata_read", side_effect=record):
        result = ci.inventory(tmp_path, value, now=now, horizon=horizon)
    return result, names


def times(checked_at, valid_until):
    return dict(checked_at=checked_at, valid_until=valid_until)


# A1 focused ---------------------------------------------------------------

@pytest.mark.parametrize("group", GROUPS, ids=lambda g: str(g["epoch"]))
def test_a1_aware_positive_equivalent_offsets_equal_numeric(group):
    values = [ci.epoch(text) for text in group["strings"]]
    assert values == [ci.epoch(group["epoch"])] * len(values)


@pytest.mark.parametrize("text", VECTORS["naive"])
def test_a1_naive_regression_rejected(text):
    with pytest.raises(ValueError, match=CLOCK_ERROR):
        ci.epoch(text)


@pytest.mark.parametrize("text", VECTORS["date_only"])
def test_a1_completeness_gate_date_only_rejected(text):
    with pytest.raises(ValueError, match=CLOCK_ERROR):
        ci.epoch(text)


@pytest.mark.parametrize("now_text,horizon_text", [
    ("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"),
    ("2025-12-31T16:00:00-08:00", "2026-01-01T06:30:00+05:30"),
    (N, "2026-01-01T01:00:00+00:00"),
    (N, H),
])
def test_a1_aware_positive_inclusive_endpoints_retained(now_text, horizon_text):
    assert ci.freshness(times(now_text, horizon_text), N, H) is True


@pytest.mark.parametrize("doc", [
    times("2026-01-01T00:00:00.000001Z", "2026-01-01T01:00:00Z"),
    times("2025-12-31T16:00:00.000001-08:00", H),
    times(N, "2026-01-01T00:59:59.999999Z"),
    times(N, "2026-01-01T06:29:59.999999+05:30"),
])
def test_a1_future_checked_or_expired_valid_fails(doc):
    assert ci.freshness(doc, N, H) is False


BAD_CLOCKS = [
    (N, N), (N, N - 1), (N, N + 3601),
    ("2026-01-01T01:00:00Z", "2026-01-01T00:30:00Z"),
    ("2026-01-01T00:00:00Z", "2026-01-01T05:30:00+05:30"),           # same instant
    ("2026-01-01T00:00:00Z", "2026-01-01T06:30:00.000001+05:30"),    # 1 h + 1 us
    ("2026-01-01T00:00:00", H), (N, "2026-01-01T00:30:00"),
    ("2026-01-01", H), (N, "2026-01-01"),
    (True, H), (N, math.nan), (N, math.inf), (None, H),
]


@pytest.mark.parametrize("now,horizon", BAD_CLOCKS)
def test_a1_invalid_clock_arguments_rejected_before_reads(tmp_path, now, horizon):
    value = legacy_plan(tmp_path, times(N, H), times(N, H))
    output = tmp_path / "output"
    refuse = AssertionError("no read before clock validation")
    with patch.object(ci, "read_metadata", side_effect=refuse), \
            patch.object(ci, "bounded_metadata_read", side_effect=refuse), \
            patch.object(ci, "owned", side_effect=refuse):
        with pytest.raises(ValueError):
            ci.inventory(tmp_path, value, now=now, horizon=horizon)
        with pytest.raises(ValueError):
            ci.produce(tmp_path, value, output, now=now, horizon=horizon)
    assert not output.exists()


def write_cli_plan(tmp_path, value):
    plan_dir = tmp_path / "cli"
    plan_dir.mkdir(exist_ok=True)
    plan_file = plan_dir / "plan.json"
    payload = ci.encoded(value)
    plan_file.write_bytes(payload)
    return plan_file, payload


def run_cli(tmp_path, plan_file, payload, now, horizon):
    argv = ["cached_inventory", "--root", str(tmp_path), "--plan", str(plan_file),
            "--out", str(tmp_path / "output"), "--now=" + now, "--horizon=" + horizon,
            "--plan-sha256", hashlib.sha256(payload).hexdigest(), "--plan-bytes", str(len(payload))]
    stdout = io.StringIO()
    with patch.object(sys, "argv", argv), patch.object(sys, "stdout", stdout):
        ci.main()
    return json.loads(stdout.getvalue())


CLI_BAD_CLOCKS = [("nan", "3600"), ("0", "nan"), ("inf", "3600"), ("-inf", "3600"), ("0", "inf"),
                  ("200", "100"), ("100", "100"), ("100", "3701"), (str(N), str(N + 3601))]


@pytest.mark.parametrize("now,horizon", CLI_BAD_CLOCKS)
def test_a1_cli_invalid_clock_rejected_before_any_read_or_write(tmp_path, now, horizon):
    value = legacy_plan(tmp_path, times(N, H), times(N, H))
    plan_file, payload = write_cli_plan(tmp_path, value)
    before = sorted(p.name for p in tmp_path.iterdir())
    refuse = AssertionError("no read or write before CLI clock validation")
    with patch.object(ci, "read_metadata", side_effect=refuse), \
            patch.object(ci, "bounded_metadata_read", side_effect=refuse), \
            patch.object(ci, "owned", side_effect=refuse), \
            patch.object(ci, "sync_directory", side_effect=refuse), \
            patch.object(ci, "output_tree_bytes", side_effect=refuse):
        with pytest.raises(ValueError, match="finite clock required|prospective discovery horizon"):
            run_cli(tmp_path, plan_file, payload, now, horizon)
    assert not (tmp_path / "output").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert plan_file.read_bytes() == payload


def test_a1_aware_positive_cli_ordinary_run_unchanged(tmp_path):
    value = legacy_plan(tmp_path, times(N, H), times(N, H))
    plan_file, payload = write_cli_plan(tmp_path, value)
    result = run_cli(tmp_path, plan_file, payload, str(N), str(H))
    assert result["status"] == "completed"
    assert result["control_plan_bytes_read_this_call"] == len(payload)
    assert result["result"]["now"] == N and result["result"]["prospective_horizon"] == H
    assert result["result"]["sources"][0]["holds"] == FRESH_HOLDS
    assert sorted(p.name for p in (tmp_path / "output").iterdir()) == sorted(
        ["checkpoint.json", "cli-plan-admission.json", "inventory.lock", "metadata-admission.json",
         "result-intent.json", "usable-inputs.json"])
    again = run_cli(tmp_path, plan_file, payload, str(N), str(H))
    assert again["status"] == "completed_reused" and again["control_plan_bytes_read_this_call"] == 0


def test_a1_aware_positive_string_clock_arguments_match_numeric(tmp_path):
    value = legacy_plan(tmp_path, times(N, H), times(N, H))
    numeric, _ = traced_inventory(tmp_path, value, now=N, horizon=H)
    text, _ = traced_inventory(tmp_path, value, now="2025-12-31T16:00:00-08:00",
                               horizon="2026-01-01T06:30:00+05:30")
    assert text == numeric
    assert numeric["now"] == N and numeric["prospective_horizon"] == H


# A2 producer contract ------------------------------------------------------

FRESH_HOLDS = ["header_metadata_missing", "prepared_acquisition_metadata_missing"]
METADATA_READS = ["rights.json", "scope.json", "source.json"]


@pytest.mark.parametrize("rights,scope", [
    (times("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"),
     times("2025-12-31T16:00:00-08:00", "2026-01-01T06:30:00+05:30")),
    (times(N, "2026-01-01T15:00:00+14:00"), times("2026-01-01T00:00:00.000000+00:00", H + 1)),
])
def test_a2_aware_positive_inventory_accepts_explicit_offsets(tmp_path, rights, scope):
    result, names = traced_inventory(tmp_path, legacy_plan(tmp_path, rights, scope))
    entry = result["sources"][0]
    assert entry["holds"] == FRESH_HOLDS
    assert sorted(names) == METADATA_READS
    usage = result["usage"]
    assert (usage["source_read_bytes"], usage["source_hashes"], usage["network_requests"],
            usage["network_bytes"], usage["source_stat_checks"]) == (0, 0, 0, 0, 1)


@pytest.mark.parametrize("field,value,hold", [
    ("checked_at", "2026-01-01T00:00:00", "private_source_rights_unreviewed"),
    ("valid_until", "2026-01-01T01:00:00", "private_source_rights_unreviewed"),
    ("checked_at", "2026-01-01", "private_source_rights_unreviewed"),
    ("checked_at", "2026-01-01T00:00:00.000001Z", "private_source_rights_unreviewed"),
    ("valid_until", "2026-01-01T06:29:59.999999+05:30", "private_source_rights_unreviewed"),
    ("valid_until", None, "private_source_rights_unreviewed"),
])
def test_a2_bad_evidence_time_holds_without_extra_read(tmp_path, field, value, hold):
    rights = times(N, H); rights[field] = value
    result, names = traced_inventory(tmp_path, legacy_plan(tmp_path, rights, times(N, H)))
    assert result["sources"][0]["holds"] == sorted(FRESH_HOLDS + [hold])
    assert not result["usable_source_ids"]
    assert sorted(names) == METADATA_READS
    assert result["usage"]["source_read_bytes"] == result["usage"]["source_hashes"] == 0


def test_a2_bad_scope_time_holds_scope(tmp_path):
    result, names = traced_inventory(tmp_path, legacy_plan(tmp_path, times(N, H),
                                                           times("2026-01-01T00:00:00", H)))
    assert result["sources"][0]["holds"] == sorted(FRESH_HOLDS + ["prospective_geographic_scope_unreviewed"])
    assert sorted(names) == METADATA_READS


@pytest.mark.parametrize("rights,scope", [
    (times("20260101T000000Z", "2026-01-01 06:30:00+0530"),
     times("2026-01-01t00:00:00Z", "20260101T010000.0000009+00")),
    (times("2026-W01-4T00:00:00-00:00", "2026-01-01T06:30:00+05:30:00"),
     times("2025-12-31 16:00:00,000-0800", "2026W014T010000Z")),
])
def test_a2_aware_positive_base_complete_forms_through_inventory(tmp_path, rights, scope):
    """Complete explicitly offset forms the base parser accepted stay fresh through inventory."""
    for text in list(rights.values()) + list(scope.values()):
        assert base_parse(text).utcoffset() is not None
    assert ci.freshness(rights, N, H) is True and ci.freshness(scope, N, H) is True
    result, names = traced_inventory(tmp_path, legacy_plan(tmp_path, rights, scope))
    assert result["sources"][0]["holds"] == FRESH_HOLDS
    assert sorted(names) == METADATA_READS


@pytest.mark.parametrize("offset", FAKE_OFFSETS)
def test_a2_fake_host_offset_is_real(offset):
    """The test-local fake genuinely changes naive interpretation (so A2 is not vacuous)."""
    fake = fake_local_datetime(offset)
    parsed = fake.fromisoformat("2026-01-01T00:00:00")
    assert type(parsed) is fake
    assert parsed.timestamp() == N - offset * 3600


@pytest.mark.parametrize("offset", FAKE_OFFSETS)
def test_a2_aware_positive_results_identical_under_fake_host_offsets(tmp_path, offset):
    rights = times("2025-12-31T16:00:00-08:00", "2026-01-01T06:30:00+05:30")
    scope = times("2026-01-01T00:00:00Z", "2026-01-01T01:00:00+00:00")
    baseline, _ = traced_inventory(tmp_path, legacy_plan(tmp_path, rights, scope))
    with patch.object(ci, "datetime", fake_local_datetime(offset)):
        faked, names = traced_inventory(tmp_path, legacy_plan(tmp_path, rights, scope),
                                        now="2026-01-01T00:00:00Z", horizon="2026-01-01T01:00:00Z")
        values = [ci.epoch(text) for group in GROUPS for text in group["strings"]]
    assert faked == baseline
    assert values == [group["epoch"] for group in GROUPS for _ in group["strings"]]
    assert faked["sources"][0]["holds"] == FRESH_HOLDS
    assert sorted(names) == METADATA_READS


@pytest.mark.parametrize("offset", FAKE_OFFSETS)
def test_a2_naive_regression_refused_under_fake_host_offsets(offset):
    with patch.object(ci, "datetime", fake_local_datetime(offset)):
        for text in VECTORS["naive"]:
            with pytest.raises(ValueError, match=CLOCK_ERROR):
                ci.epoch(text)
        assert ci.freshness(times("2026-01-01T00:00:00", H), N, H) is False


# A3 negative and preservation ----------------------------------------------

@pytest.mark.parametrize("value", [True, False, math.nan, -math.nan, math.inf, -math.inf,
                                   10 ** 400, None, [], {}, b"2026-01-01T00:00:00Z"])
def test_a3_non_finite_or_non_clock_values_rejected(value):
    with pytest.raises(ValueError, match="finite clock required"):
        ci.epoch(value)


@pytest.mark.parametrize("value", [0, -1, 1.5, -1.5, N, H + 0.25, 10 ** 18, 2 ** 63 - 1])
def test_a3_aware_positive_numeric_domain_preserved(value):
    result = ci.epoch(value)
    assert result == value and type(result) is type(value)


@pytest.mark.parametrize("kind,text", INVALID, ids=[f"{k}-{i}" for i, (k, _) in enumerate(INVALID)])
def test_a3_invalid_strings_rejected_with_stable_error(kind, text):
    with pytest.raises(ValueError, match=CLOCK_ERROR):
        ci.epoch(text)


@pytest.mark.parametrize("text", VECTORS["naive"])
def test_a3_naive_regression_freshness_false(text):
    assert ci.freshness(times(text, H), N, H) is False
    with pytest.raises(ValueError, match=CLOCK_ERROR):
        ci.epoch(text)


@pytest.mark.parametrize("text", VECTORS["date_only"] + VECTORS["incomplete"])
def test_a3_completeness_gate_rejects_partial(text):
    with pytest.raises(ValueError, match=CLOCK_ERROR):
        ci.epoch(text)


BAD_EVIDENCE = [text for _, text in INVALID] + [None, True, False, math.nan, math.inf, [], {}]


@pytest.mark.parametrize("field", ["checked_at", "valid_until"])
def test_a3_freshness_false_for_malformed_or_missing_evidence_time(field):
    for value in BAD_EVIDENCE:
        doc = times(N, H); doc[field] = value
        assert ci.freshness(doc, N, H) is False, (field, value)
    doc = times(N, H); del doc[field]
    assert ci.freshness(doc, N, H) is False
    assert ci.freshness({}, N, H) is False


@pytest.mark.parametrize("checked,valid,expected", [
    ("2026-01-01T14:00:00+14:00", "2025-12-31T13:00:00-12:00", True),
    ("2026-01-01T14:00:00.000001+14:00", H, False),
    (N, "2025-12-31T12:59:59.999999-12:00", False),
    ("2025-12-31T23:59:59.999999-00:01", H, False),  # valid offset, but 1 min after now
])
def test_a3_aware_positive_equivalent_instant_boundaries(checked, valid, expected):
    assert ci.freshness(times(checked, valid), N, H) is expected


def test_a3_freshness_does_not_treat_missing_time_as_now():
    assert ci.freshness(dict(valid_until=H), N, H) is False
    assert ci.freshness(dict(checked_at=N), N, H) is False
    assert ci.freshness(times(None, None), N, H) is False


# A3 base-compatibility oracle ----------------------------------------------

@pytest.mark.parametrize("text", AWARE_STRINGS)
def test_a3_aware_positive_base_value_preserved(text):
    """Every complete explicit-offset vector keeps exactly the base parser's value."""
    parsed = base_parse(text)
    assert parsed.utcoffset() is not None
    assert ci.epoch(text) == parsed.timestamp()


def test_a3_newly_refused_aware_forms_are_only_incomplete_or_bad_offset_fields():
    """No complete, validly offset form the base accepted is narrowed away."""
    newly_refused = []
    for _, text in INVALID:
        try:
            parsed = base_parse(text)
        except ValueError:
            continue
        if parsed.utcoffset() is None:
            continue  # naive or date-only: refused by design
        newly_refused.append(text)
    assert sorted(newly_refused) == sorted(VECTORS["base_accepted_now_refused"]["strings"])
    assert set(newly_refused) <= set(VECTORS["incomplete"]) | set(VECTORS["invalid_offset"])


# A3 runner input contract (synthetic trees only) ---------------------------

@pytest.fixture()
def runner():
    """Load the acceptance runner as a plain module; main() only ever runs to a preflight refusal here."""
    flag = sys.dont_write_bytecode
    spec = importlib.util.spec_from_file_location("sc_cache_clock_runner_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = flag
    return module


INPUT_FILES = {"a.txt": b"alpha\n", "sub/b.json": b"{\"b\": 1}\n"}
PINS_NAME = "pins/input-pins.json"


def synthetic_repo(tmp_path, runner, files=INPUT_FILES):
    repo = tmp_path / "repo"
    for name, data in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
    pins = dict(schema=runner.PINS_SCHEMA, inputs={
        name: dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)) for name, data in files.items()})
    (repo / PINS_NAME).parent.mkdir(parents=True, exist_ok=True)
    (repo / PINS_NAME).write_bytes(json.dumps(pins, sort_keys=True).encode())
    return repo


def tree_state(root):
    """Names, link/type flags and regular-file bytes; never follows a symlink."""
    state = []
    for folder, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(folder) / name
            info = path.lstat()
            regular = path.is_file() and not path.is_symlink()
            state.append((str(path.relative_to(root)), info.st_mode >> 12, path.read_bytes() if regular else None))
    return sorted(state)


def test_a3_runner_input_matching_regular_tree_accepted(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    before = tree_state(tmp_path)
    checked = runner.preflight(repo, tuple(INPUT_FILES), PINS_NAME)
    assert checked["data"] == INPUT_FILES
    assert checked["sha256"] == {n: hashlib.sha256(d).hexdigest() for n, d in INPUT_FILES.items()}
    assert checked["pins_sha256"] == hashlib.sha256((repo / PINS_NAME).read_bytes()).hexdigest()
    assert tree_state(tmp_path) == before


def assert_refused(tmp_path, runner, repo, match, inputs=tuple(INPUT_FILES)):
    before = tree_state(tmp_path)
    with pytest.raises(ValueError, match=match):
        runner.preflight(repo, inputs, PINS_NAME)
    assert tree_state(tmp_path) == before  # inputs and prior outputs untouched, nothing created


def test_a3_runner_input_hash_mismatch_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "a.txt").write_bytes(b"alphA\n")  # same size, different bytes
    assert_refused(tmp_path, runner, repo, "does not match its frozen pin")


def test_a3_runner_input_size_mismatch_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "sub/b.json").write_bytes(b"{\"b\": 12}\n")
    assert_refused(tmp_path, runner, repo, "does not match its frozen pin")


def test_a3_runner_input_unpinned_or_extra_pin_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    assert_refused(tmp_path, runner, repo, "pins must cover exactly", inputs=("a.txt",))
    assert_refused(tmp_path, runner, repo, "pins must cover exactly", inputs=("a.txt", "sub/b.json", "c.txt"))


def test_a3_runner_input_symlink_root_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    assert_refused(tmp_path, runner, alias, "symlink or non-directory ancestry")


def test_a3_runner_input_symlink_root_ancestor_refused(tmp_path, runner):
    synthetic_repo(tmp_path, runner)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert_refused(tmp_path, runner, alias / "repo", "symlink or non-directory ancestry")


def test_a3_runner_input_symlink_intermediate_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "sub").rename(tmp_path / "real-sub")
    (repo / "sub").symlink_to(tmp_path / "real-sub", target_is_directory=True)
    assert_refused(tmp_path, runner, repo, "symlink or non-directory ancestry")


def test_a3_runner_input_symlink_leaf_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "a.txt").rename(tmp_path / "real-a.txt")
    (repo / "a.txt").symlink_to(tmp_path / "real-a.txt")
    assert_refused(tmp_path, runner, repo, "symlink or special input refused")


def test_a3_runner_input_symlink_pins_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / PINS_NAME).rename(tmp_path / "real-pins.json")
    (repo / PINS_NAME).symlink_to(tmp_path / "real-pins.json")
    assert_refused(tmp_path, runner, repo, "symlink or special input refused")


def test_a3_runner_input_special_file_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "a.txt").rename(tmp_path / "real-a.txt")
    os.mkfifo(repo / "a.txt")
    assert_refused(tmp_path, runner, repo, "regular input file required")


def test_a3_runner_input_directory_as_leaf_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "a.txt").rename(tmp_path / "real-a.txt")
    (repo / "a.txt").mkdir()
    assert_refused(tmp_path, runner, repo, "regular input file required")


def test_a3_runner_input_oversize_refused_before_read(tmp_path, runner):
    big = b"x" * (runner.FILE_CAP + 1)
    repo = synthetic_repo(tmp_path, runner, files={"a.txt": big, "sub/b.json": b"{}\n"})
    original = runner.read_chunk

    def refuse_oversize(fd, size):
        assert os.fstat(fd).st_size <= runner.FILE_CAP, "no read of an oversize input"
        return original(fd, size)
    with patch.object(runner, "read_chunk", side_effect=refuse_oversize):
        assert_refused(tmp_path, runner, repo, "per-file input cap")


def test_a3_runner_input_aggregate_cap_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    room = (repo / PINS_NAME).stat().st_size + len(INPUT_FILES["a.txt"]) + 3  # b.json does not fit
    with patch.object(runner, "TOTAL_CAP", room):
        assert_refused(tmp_path, runner, repo, "aggregate input cap exceeded: sub/b.json")


def test_a3_runner_input_growth_during_read_refused(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    original = runner.read_chunk
    target = (repo / "a.txt").stat().st_ino
    grown = []

    def grow_then_read(fd, size):
        if not grown and os.fstat(fd).st_ino == target:
            with open(repo / "a.txt", "ab") as stream:
                stream.write(b"more")
            grown.append(True)
        return original(fd, size)
    with patch.object(runner, "read_chunk", side_effect=grow_then_read):
        with pytest.raises(ValueError, match="changed during bounded read"):
            runner.preflight(repo, tuple(INPUT_FILES), PINS_NAME)
    assert grown


def test_a3_runner_input_preflight_failure_writes_no_output(tmp_path, runner):
    repo = synthetic_repo(tmp_path, runner)
    (repo / "a.txt").write_bytes(b"alphA\n")
    out_root = tmp_path / "out"
    out_root.mkdir()
    (out_root / "prior-run").mkdir()
    (out_root / "prior-run" / "receipt.json").write_bytes(b"{}\n")
    before = tree_state(tmp_path)
    argv = ["accept_sc_cache_clock.py", "--suite", "focused", "--output", str(out_root / "new-run")]
    stdout = io.StringIO()
    with patch.object(runner, "REPO", repo), patch.object(runner, "OUT_ROOT", out_root), \
            patch.object(runner, "INPUTS", tuple(INPUT_FILES)), patch.object(runner, "PINS", PINS_NAME), \
            patch.object(runner, "install_guards", side_effect=AssertionError("no guard install")), \
            patch.object(sys, "argv", argv), patch.object(sys, "stdout", stdout):
        with pytest.raises(SystemExit) as stopped:
            runner.main()
    assert stopped.value.code == 3
    assert json.loads(stdout.getvalue())["status"] == "REFUSED"
    assert tree_state(tmp_path) == before
    assert not (out_root / "new-run").exists()
