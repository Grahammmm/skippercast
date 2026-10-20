"""The four128 harness reads cumulative source/scratch accounting from one signed
budget amendment that carries the failed 2026-10-11 charges.

The failed attempt's two conservative source reservations (73,515,136 B) and its
full scratch reservation (536,870,912 B) stay charged; nothing is refunded, and
the extra allowance must equal the shortfall exactly.
"""
import copy
import importlib
import os
import sys
import unittest
from unittest import mock

from tests._support import ROOT

SCRIPTS = ROOT / "research" / "scripts"
MODULES = ("coastal_four128_runtime", "coastal_four128_resources")


def _load(name, env):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    with mock.patch.dict(os.environ, env):
        for module in MODULES:
            sys.modules.pop(module, None)
        return importlib.import_module(name)


def amendment():
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


class BudgetAmendment(unittest.TestCase):
    def setUp(self):
        self.resources = _load("coastal_four128_resources", {})

    def tearDown(self):
        for module in MODULES:
            sys.modules.pop(module, None)

    def test_exact_reconciled_amendment_is_admitted(self):
        limits = self.resources.budget_limits(amendment())
        self.assertEqual(limits, dict(source_prior_bytes=895006524, source_limit_bytes=1189067068,
                                      scratch_prior_bytes=1616905649, scratch_limit_bytes=2153776561))
        self.assertEqual(limits["source_prior_bytes"] + 294060544, limits["source_limit_bytes"])
        self.assertEqual(limits["scratch_prior_bytes"] + 536870912, limits["scratch_limit_bytes"])

    def refused(self, mutate):
        doc = amendment()
        mutate(doc)
        with self.assertRaises(ValueError):
            self.resources.budget_limits(doc)

    def test_omitting_failed_source_charges_is_refused(self):
        def omit(doc):
            doc["source"].update(failed_trial_charged_bytes=0, prior_effective_bytes=821491388,
                                 additional_bytes=0, cumulative_limit_bytes=1115551932)
        self.refused(omit)

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
        self.refused(lambda d: d["source"].update(prior_effective_bytes=float(895006524)))

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
        for literal in ("821491388", "1115551932", "2147483648"):
            self.assertNotIn(literal, text)
        prepare = (SCRIPTS / "coastal_four128_prepare.py").read_text()
        for literal in ("821491388", "1115551932"):
            self.assertNotIn(literal, prepare)

    def test_grant_must_match_signed_amendment(self):
        runtime = self.runtime()
        ref = dict(path="metadata/four128-budget-amendment.json", contract="coastal-four128-budget-amendment-v1",
                   bytes=1, sha256="0" * 64)
        grant = dict(approved_budget_amendment=ref, prior_effective_bytes=895006524,
                     prior_effective_source_bytes=895006524, cumulative_limit_bytes=1189067068,
                     source_volume_cap_bytes=294060544)
        with mock.patch.object(runtime, "metadata_document", return_value=amendment()) as read:
            limits = runtime.limits_for(grant)
            read.assert_called_once_with(runtime.R, ref, "coastal-four128-budget-amendment-v1")
            self.assertEqual(limits["source_limit_bytes"], 1189067068)
            for key, value in (("prior_effective_bytes", 821491388),
                               ("prior_effective_source_bytes", 821491388),
                               ("cumulative_limit_bytes", 1115551932),
                               ("source_volume_cap_bytes", 220545408)):
                stale = copy.deepcopy(grant)
                stale[key] = value
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "signed budget amendment"):
                    runtime.limits_for(stale)


if __name__ == "__main__":
    unittest.main()
