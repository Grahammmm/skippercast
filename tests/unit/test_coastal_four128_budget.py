"""The four128 harness reads cumulative source/scratch accounting from one signed
budget amendment that carries every failed attempt's charges.

The failed 2026-10-11 attempt's two conservative source reservations (73,515,136 B)
and its full scratch reservation (536,870,912 B) stay charged, and so do the
uncertain source reservation of attempt 2 of the 2026-10-19 trial (36,757,568 B,
amendment revision 2), the three reservations of attempt 4 (110,272,704 B) and the
two window pre-scan opens of the cached BAG (73,515,136 B, both revision 3) and the
seven reservations of attempt 5 (257,302,976 B, revision 4: six settled A/B/C
acquire+qualify, one uncertain D-acquire), the eight settled admissions of the
completed attempt 6 (294,060,544 B) and the two read-only BAG hash passes of its
independent validation (73,515,136 B, both revision 5).
Nothing is refunded, the extra allowance must equal the shortfall exactly, and a
revision-1, -2, -3 or -4 amendment, or the unused revision-5 draft that omits the
validation reads, is refused.
"""
import copy
import hashlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests._support import ROOT

SCRIPTS = ROOT / "research" / "scripts"
MODULES = ("coastal_four128_runtime", "coastal_four128_resources")

# The signed documents live on the maintainer machine only. When present they are
# checked byte-for-byte against the pinned digests and the in-code copies below;
# CI exercises the same accounting blocks through those copies.
SIGNED = Path.home() / "agent-work" / "t08a" / "budget"
SIGNED_V1 = (SIGNED / "four128-budget-amendment.json",
             "62df4400d9448fe4ed36284d9985f6a76290855e5036db0521f5a1d7045d2f63")
SIGNED_V2 = (SIGNED / "four128-budget-amendment-v2.json",
             "c0f8ffad8e6b28ca5dd6bc0f3058539d9b1e27b6d4a5c28faf1a9026ba1323cd")
SIGNED_V3 = (SIGNED / "four128-budget-amendment-v3.json",
             "448f16fcc136168f79676d393eb2e14ae25eb98cda79d32d13c7d2c0e434f693")
SIGNED_V4 = (SIGNED / "four128-budget-amendment-v4.json",
             "0d970656a2ec3e5adfd0093033b49b942df377784fcd85bd9516da8237e320d6")
SIGNED_V5 = (SIGNED / "four128-budget-amendment-v5.json",
             "150f78452dd1aeb1952c372ec4415edbe54a530780db500492d444e9b8bca9d9")
# The first revision-5 signature omitted the validation hash reads; renamed aside, never used.
SIGNED_V5_DRAFT = (SIGNED / "four128-budget-amendment-v5-superseded-unused-omits-validation-hash-reads.json",
                   "d822d56b951e733c709cb28f2e2bf291da48c595a364883a68333cf8fb0a078b")


def _load(name, env):
    # Load by file location (no sys.path edits, tests/contract/test_test_layout.py);
    # the runtime module adds its own directory to find coastal_four128_resources.
    with mock.patch.dict(os.environ, env):
        for module in MODULES:
            sys.modules.pop(module, None)
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


def amendment_v1():
    """Revision 1 (2026-10-19 18:05 PDT): carries the 2026-10-11 charges only."""
    return dict(
        schema="coastal-four128-budget-amendment-v1",
        status="SIGNED_DELEGATED_BUDGET_AUTHORITY",
        signer=dict(profile="fable-2nd-look", model="claude-fable-5-1", reviewer_id="fable-test"),
        author_under_review="opus-coder",
        source=dict(pre_failure_prior_bytes=821491388, failed_trial_charged_bytes=73515136,
                    prior_effective_bytes=895006524, previous_cumulative_limit_bytes=1115551932,
                    additional_bytes=73515136, cumulative_limit_bytes=1189067068,
                    fresh_allowance_bytes=294060544, refunds=False, downloads=0),
        scratch=dict(charged_prior_bytes=1616905649, previous_cumulative_maximum_bytes=2147483648,
                     additional_bytes=6292913, cumulative_maximum_bytes=2153776561,
                     trial_reservation_bytes=536870912, refunds=False),
    )


def amendment_v2():
    """Revision 2 (signed 2026-10-20T02:50Z): adds the attempt-2 uncertain reservation."""
    doc = amendment_v1()
    doc["amendment_revision"] = 2
    doc["source"].update(failed_trial_2_charged_bytes=36757568, prior_effective_bytes=931764092,
                         additional_bytes=110272704, cumulative_limit_bytes=1225824636)
    return doc


def amendment_v3():
    """Revision 3 (signed 2026-10-20T04:06Z): adds attempt 4 and the two pre-scan opens."""
    doc = amendment_v2()
    doc["amendment_revision"] = 3
    doc["source"].update(failed_trial_4_charged_bytes=110272704, window_prescan_charged_bytes=73515136,
                         prior_effective_bytes=1115551932, additional_bytes=294060544,
                         cumulative_limit_bytes=1409612476)
    return doc


def amendment_v4():
    """Revision 4 (signed 2026-10-20T06:15Z): adds the seven attempt-5 reservations."""
    doc = amendment_v3()
    doc["amendment_revision"] = 4
    doc["source"].update(failed_trial_5_charged_bytes=257302976, prior_effective_bytes=1372854908,
                         additional_bytes=551363520, cumulative_limit_bytes=1666915452)
    return doc


def amendment_v5_draft():
    """Unused revision-5 draft (signed 2026-10-20T06:51Z, superseded): attempt 6 without the validation reads."""
    doc = amendment_v4()
    doc["amendment_revision"] = 5
    doc["source"].update(trial_6_charged_bytes=294060544, prior_effective_bytes=1666915452,
                         additional_bytes=845424064, cumulative_limit_bytes=1960975996)
    return doc


def amendment():
    """Revision 5 (re-signed 2026-10-20): attempt 6 and the two validation hash reads."""
    doc = amendment_v5_draft()
    doc["source"].update(validation_hash_reads_charged_bytes=73515136, prior_effective_bytes=1740430588,
                         additional_bytes=918939200, cumulative_limit_bytes=2034491132)
    return doc


def assert_self_consistent(doc):
    """A mutated document still balances, so its refusal is about the omitted charge."""
    s = doc["source"]
    charges = ("pre_failure_prior_bytes", "failed_trial_charged_bytes", "failed_trial_2_charged_bytes",
               "failed_trial_4_charged_bytes", "window_prescan_charged_bytes", "failed_trial_5_charged_bytes",
               "trial_6_charged_bytes", "validation_hash_reads_charged_bytes")
    assert s["prior_effective_bytes"] == sum(s.get(k, 0) for k in charges), "unbalanced prior"
    assert s["additional_bytes"] == s["prior_effective_bytes"] + 294060544 - 1115551932, "unbalanced additional"
    assert s["cumulative_limit_bytes"] == 1115551932 + s["additional_bytes"], "unbalanced cap"


SOURCE_KEYS = ("pre_failure_prior_bytes", "failed_trial_charged_bytes", "failed_trial_2_charged_bytes",
               "failed_trial_4_charged_bytes", "window_prescan_charged_bytes", "failed_trial_5_charged_bytes",
               "trial_6_charged_bytes", "validation_hash_reads_charged_bytes", "prior_effective_bytes",
               "previous_cumulative_limit_bytes", "additional_bytes", "cumulative_limit_bytes",
               "fresh_allowance_bytes", "refunds", "downloads")
SCRATCH_KEYS = ("charged_prior_bytes", "previous_cumulative_maximum_bytes", "additional_bytes",
                "cumulative_maximum_bytes", "trial_reservation_bytes", "refunds")


def signed(entry):
    path, sha256 = entry
    if not path.is_file():
        return None
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256, f"signed amendment changed: {path}"
    return json.loads(data)


class BudgetAmendment(unittest.TestCase):
    def setUp(self):
        self.resources = _load("coastal_four128_resources", {})

    def tearDown(self):
        for module in MODULES:
            sys.modules.pop(module, None)

    def test_constants_carry_every_failed_attempt_and_the_prescan(self):
        r = self.resources
        self.assertEqual(r.FAILED_TRIAL2_SOURCE_CHARGED, 36757568)
        self.assertEqual(r.FAILED_TRIAL4_SOURCE_CHARGED, 110272704)
        self.assertEqual(r.FAILED_TRIAL4_SOURCE_CHARGED, 3 * 36757568)  # A-acquire, A-qualify, B-acquire
        self.assertEqual(r.PRESCAN_SOURCE_CHARGED, 73515136)
        self.assertEqual(r.PRESCAN_SOURCE_CHARGED, 2 * 36757568)  # scan run + reviewer verification
        self.assertEqual(r.FAILED_TRIAL5_SOURCE_CHARGED, 257302976)
        self.assertEqual(r.FAILED_TRIAL5_SOURCE_CHARGED, 7 * 36757568)  # A/B/C acquire+qualify, D-acquire
        self.assertEqual(r.TRIAL6_SOURCE_CHARGED, 294060544)
        self.assertEqual(r.TRIAL6_SOURCE_CHARGED, 8 * 36757568)  # A-D acquire+qualify, all settled
        self.assertEqual(r.VALIDATION_HASH_SOURCE_CHARGED, 73515136)
        self.assertEqual(r.VALIDATION_HASH_SOURCE_CHARGED, 2 * 36757568)  # two read-only hash passes
        self.assertEqual(r.SOURCE_PRIOR_FLOOR, 1740430588)
        self.assertEqual(r.SOURCE_PRIOR_FLOOR, r.PRE_FAILURE_SOURCE_PRIOR + r.FAILED_TRIAL_SOURCE_CHARGED
                         + r.FAILED_TRIAL2_SOURCE_CHARGED + r.FAILED_TRIAL4_SOURCE_CHARGED
                         + r.PRESCAN_SOURCE_CHARGED + r.FAILED_TRIAL5_SOURCE_CHARGED
                         + r.TRIAL6_SOURCE_CHARGED + r.VALIDATION_HASH_SOURCE_CHARGED)
        self.assertEqual(r.RECORDED_SOURCE_LIMIT, 1115551932)
        self.assertEqual(r.FRESH_SOURCE, 294060544)
        self.assertEqual(r.SOURCE_PRIOR_FLOOR + r.FRESH_SOURCE - r.RECORDED_SOURCE_LIMIT, 918939200)

    def test_exact_reconciled_amendment_is_admitted(self):
        assert_self_consistent(amendment())
        limits = self.resources.budget_limits(amendment())
        self.assertEqual(limits, dict(source_prior_bytes=1740430588, source_limit_bytes=2034491132,
                                      scratch_prior_bytes=1616905649, scratch_limit_bytes=2153776561))
        self.assertEqual(limits["source_prior_bytes"] + 294060544, limits["source_limit_bytes"])
        self.assertEqual((limits["source_limit_bytes"] - limits["source_prior_bytes"]) // 36757568, 8)
        self.assertEqual(limits["scratch_prior_bytes"] + 536870912, limits["scratch_limit_bytes"])

    def test_revision_1_to_4_and_the_v5_draft_are_now_refused(self):
        for label, old in (("v1", amendment_v1()), ("v2", amendment_v2()), ("v3", amendment_v3()),
                           ("v4", amendment_v4()), ("v5-draft", amendment_v5_draft())):
            with self.subTest(revision=label), \
                    self.assertRaisesRegex(ValueError, "exact integer source accounting"):
                self.resources.budget_limits(old)
        # Naming the keys without carrying the charges is refused as well.
        doc = amendment_v2()
        doc["source"].update(failed_trial_4_charged_bytes=0, window_prescan_charged_bytes=0)
        with self.assertRaises(ValueError):
            self.resources.budget_limits(doc)
        doc = amendment_v3()
        doc["source"].update(failed_trial_5_charged_bytes=0, trial_6_charged_bytes=0,
                             validation_hash_reads_charged_bytes=0)
        assert_self_consistent(doc)
        with self.assertRaisesRegex(ValueError, "carry the failed charges"):
            self.resources.budget_limits(doc)
        doc = amendment_v4()
        doc["source"].update(trial_6_charged_bytes=0, validation_hash_reads_charged_bytes=0)
        assert_self_consistent(doc)
        with self.assertRaisesRegex(ValueError, "carry the failed charges"):
            self.resources.budget_limits(doc)
        doc = amendment_v5_draft()
        doc["source"].update(validation_hash_reads_charged_bytes=0)
        assert_self_consistent(doc)
        with self.assertRaisesRegex(ValueError, "carry the failed charges"):
            self.resources.budget_limits(doc)

    def test_signed_documents_on_this_machine(self):
        """The real re-signed revision 5 is admitted with the ruled numbers; revisions 1-4 and the
        superseded revision-5 draft are refused.

        Off the maintainer machine (CI) the files are absent and the in-code copies
        above carry the same accounting blocks."""
        v5 = signed(SIGNED_V5)
        if v5 is not None:
            self.assertEqual(self.resources.budget_limits(v5), self.resources.budget_limits(amendment()))
            self.assertEqual(self.resources.budget_limits(v5),
                             dict(source_prior_bytes=1740430588, source_limit_bytes=2034491132,
                                  scratch_prior_bytes=1616905649, scratch_limit_bytes=2153776561))
            self.assertEqual({k: v5["source"][k] for k in SOURCE_KEYS},
                             {k: amendment()["source"][k] for k in SOURCE_KEYS})
            self.assertEqual({k: v5["scratch"][k] for k in SCRATCH_KEYS},
                             {k: amendment()["scratch"][k] for k in SCRATCH_KEYS})
            self.assertEqual(v5["amendment_revision"], 5)
            self.assertEqual(v5["supersedes"]["sha256"], SIGNED_V4[1])
            self.assertEqual(v5["retained_output"]["prior_retained_bytes"], 68088433)
        draft = signed(SIGNED_V5_DRAFT)
        if draft is not None:
            # The unused draft keeps its signed accounting but omits the validation hash reads.
            missing = "validation_hash_reads_charged_bytes"
            self.assertEqual({k: draft["source"][k] for k in SOURCE_KEYS if k != missing},
                             {k: amendment_v5_draft()["source"][k] for k in SOURCE_KEYS if k != missing})
            self.assertNotIn(missing, draft["source"])
        v4 = signed(SIGNED_V4)
        if v4 is not None:
            # Revision 4 keeps its signed accounting but is now refused: it omits attempt 6.
            later = ("trial_6_charged_bytes", "validation_hash_reads_charged_bytes")
            self.assertEqual({k: v4["source"][k] for k in SOURCE_KEYS if k not in later},
                             {k: amendment_v4()["source"][k] for k in SOURCE_KEYS if k not in later})
            self.assertNotIn("trial_6_charged_bytes", v4["source"])
            self.assertEqual(v4["supersedes"]["sha256"], SIGNED_V3[1])
            self.assertEqual(v4["retained_output"]["prior_retained_bytes"], 58079477)
        v3 = signed(SIGNED_V3)
        if v3 is not None:
            # Revision 3 keeps its signed accounting but is refused: it omits attempts 5 and 6.
            later = ("failed_trial_5_charged_bytes", "trial_6_charged_bytes", "validation_hash_reads_charged_bytes")
            self.assertEqual({k: v3["source"][k] for k in SOURCE_KEYS if k not in later},
                             {k: amendment_v3()["source"][k] for k in SOURCE_KEYS if k not in later})
            self.assertNotIn("failed_trial_5_charged_bytes", v3["source"])
        for entry in (SIGNED_V5_DRAFT, SIGNED_V4, SIGNED_V3, SIGNED_V2, SIGNED_V1):
            old = signed(entry)
            if old is not None:
                with self.subTest(path=entry[0].name), \
                        self.assertRaisesRegex(ValueError, "exact integer source accounting"):
                    self.resources.budget_limits(old)

    def refused(self, mutate, *, balanced=False):
        doc = amendment()
        mutate(doc)
        if balanced:
            assert_self_consistent(doc)
        with self.assertRaises(ValueError):
            self.resources.budget_limits(doc)

    def test_omitting_failed_source_charges_is_refused(self):
        # Each document below still balances internally; only the omitted charge is wrong.
        def omit_20261011(doc):
            doc["source"].update(failed_trial_charged_bytes=0, prior_effective_bytes=1666915452,
                                 additional_bytes=845424064, cumulative_limit_bytes=1960975996)
        self.refused(omit_20261011, balanced=True)

        def omit_attempt2(doc):
            doc["source"].update(failed_trial_2_charged_bytes=0, prior_effective_bytes=1703673020,
                                 additional_bytes=882181632, cumulative_limit_bytes=1997733564)
        self.refused(omit_attempt2, balanced=True)

        def omit_attempt4(doc):
            doc["source"].update(failed_trial_4_charged_bytes=0, prior_effective_bytes=1630157884,
                                 additional_bytes=808666496, cumulative_limit_bytes=1924218428)
        self.refused(omit_attempt4, balanced=True)

        def omit_prescan(doc):
            doc["source"].update(window_prescan_charged_bytes=0, prior_effective_bytes=1666915452,
                                 additional_bytes=845424064, cumulative_limit_bytes=1960975996)
        self.refused(omit_prescan, balanced=True)

        def one_prescan_open(doc):
            doc["source"].update(window_prescan_charged_bytes=36757568, prior_effective_bytes=1703673020,
                                 additional_bytes=882181632, cumulative_limit_bytes=1997733564)
        self.refused(one_prescan_open, balanced=True)

        def omit_attempt5(doc):
            doc["source"].update(failed_trial_5_charged_bytes=0, prior_effective_bytes=1483127612,
                                 additional_bytes=661636224, cumulative_limit_bytes=1777188156)
        self.refused(omit_attempt5, balanced=True)

        def settled_attempt5_only(doc):  # refunding the uncertain D-acquire reservation
            doc["source"].update(failed_trial_5_charged_bytes=220545408, prior_effective_bytes=1703673020,
                                 additional_bytes=882181632, cumulative_limit_bytes=1997733564)
        self.refused(settled_attempt5_only, balanced=True)

        def omit_attempt6(doc):
            doc["source"].update(trial_6_charged_bytes=0, prior_effective_bytes=1446370044,
                                 additional_bytes=624878656, cumulative_limit_bytes=1740430588)
        self.refused(omit_attempt6, balanced=True)

        def seven_attempt6_admissions(doc):  # refunding one settled attempt-6 admission
            doc["source"].update(trial_6_charged_bytes=257302976, prior_effective_bytes=1703673020,
                                 additional_bytes=882181632, cumulative_limit_bytes=1997733564)
        self.refused(seven_attempt6_admissions, balanced=True)

        def omit_validation_reads(doc):  # the superseded draft's numbers under the new key
            doc["source"].update(validation_hash_reads_charged_bytes=0, prior_effective_bytes=1666915452,
                                 additional_bytes=845424064, cumulative_limit_bytes=1960975996)
        self.refused(omit_validation_reads, balanced=True)

        def one_validation_read(doc):
            doc["source"].update(validation_hash_reads_charged_bytes=36757568, prior_effective_bytes=1703673020,
                                 additional_bytes=882181632, cumulative_limit_bytes=1997733564)
        self.refused(one_validation_read, balanced=True)

        for key in ("failed_trial_2_charged_bytes", "failed_trial_4_charged_bytes", "window_prescan_charged_bytes",
                    "failed_trial_5_charged_bytes", "trial_6_charged_bytes", "validation_hash_reads_charged_bytes"):
            def drop_key(doc, key=key):
                del doc["source"][key]
            with self.subTest(drop=key):
                self.refused(drop_key)

        # prior omits attempt 4, the pre-scan, both, attempt 5, attempt 6 or the validation reads
        for prior in (931764092, 1005279228, 1042036796, 1115551932, 1372854908, 1446370044,
                      1666915452, 1703673020):
            with self.subTest(prior=prior):
                self.refused(lambda d, prior=prior: d["source"].update(prior_effective_bytes=prior))

    def test_unsigned_or_self_signed_amendment_is_refused(self):
        self.refused(lambda d: d.update(status="PROPOSED_PENDING_SIGNOFF"))
        self.refused(lambda d: d["signer"].update(profile="opus-coder"))
        self.refused(lambda d: d["signer"].update(model="claude-opus-5-5"))
        self.refused(lambda d: d["signer"].update(profile="luna-worker"))
        self.refused(lambda d: d.update(author_under_review="sol-reviewer"))

    def test_margin_refund_or_download_is_refused(self):
        def margin(doc):
            doc["source"]["additional_bytes"] += 1
            doc["source"]["cumulative_limit_bytes"] += 1
        self.refused(margin)
        self.refused(lambda d: d["source"].update(refunds=True))
        self.refused(lambda d: d["source"].update(downloads=1))
        self.refused(lambda d: d["source"].update(fresh_allowance_bytes=220545408))
        self.refused(lambda d: d["source"].update(prior_effective_bytes=float(931764092)))
        self.refused(lambda d: d["source"].update(failed_trial_2_charged_bytes=float(36757568)))

    def test_scratch_refund_or_margin_is_refused(self):
        def refund(doc):
            doc["scratch"].update(charged_prior_bytes=1080034737, additional_bytes=0,
                                  cumulative_maximum_bytes=2147483648)
        self.refused(refund)
        def margin(doc):
            doc["scratch"]["additional_bytes"] += 1
            doc["scratch"]["cumulative_maximum_bytes"] += 1
        self.refused(margin)
        self.refused(lambda d: d["scratch"].update(refunds=True))


# Retained-output carry for the next attempt (coastal_four128_prepare.py
# --prior-retained-bytes). Counted per preserved managed-output.json ledger as
# complete entries' actual_bytes plus reserved entries still open (T08-FIX rule).
MISSIONS = Path.home() / "skippercast-data/2026-10-07-pge-south/outputs/t08-four128-20261019"
PRIOR_RETAINED_BASE = 40773417
RETAINED_CAP = 167772160
TRIAL_OUTPUT_TOTAL = 33554432
ATTEMPT_LEDGERS = {  # ledger sha256, complete actual bytes, open reserved bytes, plan prior bytes
    "mission-attempt1-failed-init-slice":
        ("01bf091aaffb17db9f70cdcc2030d51a136aad28680d938e5ba5aa2d42f6074f", 183752, 36864, PRIOR_RETAINED_BASE),
    "mission-attempt2-failed-native-bootstrap-missing":
        ("15b3d9c14a9188cb98e9e7b6404c15787c811e1dde625a600ad6c281a9bd115a", 254423, 4194304, PRIOR_RETAINED_BASE),
    # Attempt 3 ran under the carry after attempts 1-2 (45,442,760 B).
    "mission-attempt3-failed-driver-envelope-deadline":
        ("0ee13e07c4724edfff37c1609f940d149ccfa179b983f718039c11af0bb16bc5", 195467, 65536, 45442760),
}
NEW_PRIOR_RETAINED = 45703763


def charged(ledger):
    files = ledger["files"].values()
    if any(e["state"] not in ("complete", "reserved") for e in files):
        raise ValueError("unknown managed entry state")
    complete = sum(e["actual_bytes"] for e in files if e["state"] == "complete")
    reserved = sum(e["bytes"] for e in files if e["state"] == "reserved")
    return complete, reserved


class RetainedOutputCarry(unittest.TestCase):
    def test_new_prior_carries_every_failed_attempt(self):
        total = sum(complete + reserved for _, complete, reserved, _ in ATTEMPT_LEDGERS.values())
        self.assertEqual(total, 220616 + 4448727 + 261003)
        self.assertEqual(NEW_PRIOR_RETAINED, PRIOR_RETAINED_BASE + total)
        self.assertLessEqual(NEW_PRIOR_RETAINED + TRIAL_OUTPUT_TOTAL, RETAINED_CAP)
        # Attempt 3's ledger planned under the carry of attempts 1-2 (the previous pin).
        first_two = sum(c + r for name, (_, c, r, _) in ATTEMPT_LEDGERS.items() if "attempt3" not in name)
        self.assertEqual(ATTEMPT_LEDGERS["mission-attempt3-failed-driver-envelope-deadline"][3],
                         PRIOR_RETAINED_BASE + first_two)

    def test_attempt_ledgers_on_this_machine(self):
        """Recompute from the preserved ledgers when present (read-only; CI uses the pins)."""
        for name, (sha256, complete, reserved, plan_prior) in ATTEMPT_LEDGERS.items():
            path = MISSIONS / name / "managed-output.json"
            if not path.is_file():
                continue
            data = path.read_bytes()
            with self.subTest(attempt=name):
                self.assertEqual(hashlib.sha256(data).hexdigest(), sha256)
                ledger = json.loads(data)
                self.assertEqual(charged(ledger), (complete, reserved))
                self.assertEqual(ledger["plan"]["prior_retained_bytes"], plan_prior)
                self.assertEqual(ledger["plan"]["cumulative_cap_bytes"], RETAINED_CAP)


class RuntimeBindsAmendment(unittest.TestCase):
    def tearDown(self):
        for module in MODULES:
            sys.modules.pop(module, None)

    def runtime(self):
        return _load("coastal_four128_runtime", {
            "SKIPPERCAST_FOUR128_RUN_TAG": "20261019t08",
            "SKIPPERCAST_FOUR128_MISSION_ROOT": "/nonexistent/outputs/t08-four128-20261019",
            "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT),
        })

    def test_no_hard_coded_cumulative_constants(self):
        runtime = self.runtime()
        self.assertFalse(hasattr(runtime, "PRIOR_SOURCE"))
        self.assertFalse(hasattr(runtime, "SOURCE_LIMIT"))
        text = (SCRIPTS / "coastal_four128_runtime.py").read_text()
        for literal in ("821491388", "1115551932", "2147483648", "931764092", "1225824636", "1409612476",
                        "1372854908", "1666915452", "1960975996", "1740430588", "2034491132"):
            self.assertNotIn(literal, text)
        prepare = (SCRIPTS / "coastal_four128_prepare.py").read_text()
        for literal in ("821491388", "1115551932", "931764092", "1225824636", "1409612476",
                        "1372854908", "1666915452", "1960975996", "1740430588", "2034491132"):
            self.assertNotIn(literal, prepare)

    def test_grant_must_match_signed_amendment(self):
        runtime = self.runtime()
        ref = dict(path="metadata/four128-budget-amendment-v5.json", contract="coastal-four128-budget-amendment-v1",
                   bytes=1, sha256="0" * 64)
        grant = dict(approved_budget_amendment=ref, prior_effective_bytes=1740430588,
                     prior_effective_source_bytes=1740430588, cumulative_limit_bytes=2034491132,
                     source_volume_cap_bytes=294060544)
        with mock.patch.object(runtime, "metadata_document", return_value=amendment()) as read:
            limits = runtime.limits_for(grant)
            read.assert_called_once_with(runtime.R, ref, "coastal-four128-budget-amendment-v1")
            self.assertEqual(limits["source_limit_bytes"], 2034491132)
            # Revision-2/3/4 or v5-draft numbers, or a prior that omits a later charge, are stale.
            for key, value in (("prior_effective_bytes", 931764092),
                               ("prior_effective_bytes", 1042036796),
                               ("prior_effective_bytes", 1115551932),
                               ("prior_effective_bytes", 1372854908),
                               ("prior_effective_bytes", 1666915452),
                               ("prior_effective_source_bytes", 1042036796),
                               ("prior_effective_source_bytes", 1115551932),
                               ("prior_effective_source_bytes", 1372854908),
                               ("prior_effective_source_bytes", 1666915452),
                               ("cumulative_limit_bytes", 1225824636),
                               ("cumulative_limit_bytes", 1409612476),
                               ("cumulative_limit_bytes", 1666915452),
                               ("cumulative_limit_bytes", 1960975996),
                               ("source_volume_cap_bytes", 220545408)):
                stale = copy.deepcopy(grant)
                stale[key] = value
                with self.subTest(key=key, value=value), \
                        self.assertRaisesRegex(ValueError, "signed budget amendment"):
                    runtime.limits_for(stale)
        # A grant still bound to a revision-1, -2, -3 or -4 amendment, or the v5 draft, is refused outright.
        for old in (amendment_v1(), amendment_v2(), amendment_v3(), amendment_v4(), amendment_v5_draft()):
            with mock.patch.object(runtime, "metadata_document", return_value=old):
                with self.assertRaises(ValueError):
                    runtime.limits_for(grant)


if __name__ == "__main__":
    unittest.main()
