"""The central rollout planner names a malformed private run receipt instead of crashing on it.

Contract: `rollout.private_progress` reads every private run.json before the planner picks the next
reaches. A receipt that is not an object, or whose `inputs` is not an object, is refused with one
named ValueError (as the scoped twin does); an otherwise valid receipt whose `outputs` or
`ledger_summary` is not an object is simply not complete and never credited as progress.
"""
import json
from pathlib import Path
import tempfile
import unittest

from skippercast.seafloor import rollout
from skippercast.seafloor.io import sha256

LEDGER = {'reference_cells_sha256': 'ref-sha'}
SOURCE = {'id': 's1', 'kind': 'bathymetry'}
MANIFEST = {'surveys': [SOURCE]}
MALFORMED = 'Private progress receipt is malformed'


def _write(root, reach, receipt, *, output=b'{}'):
    folder = Path(root)/'var/seafloor/private-reaches'/reach
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'cells.json').write_bytes(output)
    if isinstance(receipt, dict) and receipt.get('outputs') == 'CHECKSUM':
        receipt['outputs'] = {'cells.json': sha256(folder/'cells.json')}
    (folder/'run.json').write_text(json.dumps(receipt))


def _receipt(**changes):
    body = {'publication_prohibited': True,
            'inputs': {'reference_cells_sha256': 'ref-sha', 'sources': [SOURCE]},
            'outputs': 'CHECKSUM',
            'ledger_summary': {'processing_incomplete': False}}
    body.update(changes)
    return body


class PrivateProgressReceiptShapeTests(unittest.TestCase):
    def progress(self, receipt):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, 'r1', receipt)
            return rollout.private_progress(tmp, LEDGER, MANIFEST)

    def test_healthy_receipt_is_credited_unchanged(self):
        # Guards against the shape checks rejecting or dropping a well-formed complete receipt.
        self.assertEqual(self.progress(_receipt()), {'r1': {'processing_incomplete': False}})

    def test_incomplete_summary_value_is_still_not_credited(self):
        # Guards against crediting a reach whose summary says processing is incomplete.
        self.assertEqual(self.progress(_receipt(ledger_summary={'processing_incomplete': True})), {})

    def test_non_object_receipt_or_inputs_is_named_not_a_crash(self):
        # Guards against a bare AttributeError ('list' has no attribute 'get') that stops the plan.
        for label, receipt in (('list', []), ('string', 'done'), ('null', None),
                               ('inputs list', _receipt(inputs=[])), ('inputs null', _receipt(inputs=None)),
                               ('inputs string', _receipt(inputs='x'))):
            with self.subTest(label), self.assertRaises(ValueError) as caught:
                self.progress(receipt)
            self.assertEqual(str(caught.exception), MALFORMED)

    def test_missing_or_non_object_ledger_summary_leaves_the_reach_out(self):
        # Guards against KeyError on a missing summary and AttributeError on a string summary,
        # and against crediting a reach whose checksum-valid outputs lack a real summary.
        no_summary = _receipt()
        del no_summary['ledger_summary']
        for label, receipt in (('absent', no_summary), ('string', _receipt(ledger_summary='done')),
                               ('list', _receipt(ledger_summary=[])), ('null', _receipt(ledger_summary=None))):
            with self.subTest(label):
                self.assertEqual(self.progress(receipt), {})

    def test_non_object_outputs_leave_the_reach_out(self):
        # Guards against AttributeError on `.items()` and against crediting a reach with no output proof.
        for label, outputs in (('list', ['cells.json']), ('string', 'cells.json'), ('null', None)):
            with self.subTest(label):
                self.assertEqual(self.progress(_receipt(outputs=outputs)), {})

    def test_checksum_mismatch_still_raises(self):
        # Guards against the new leniency swallowing the unchanged output-integrity error.
        receipt = _receipt(outputs={'cells.json': 'deadbeef'})
        with self.assertRaisesRegex(ValueError, 'Private progress output checksum mismatch'):
            self.progress(receipt)

    def test_one_malformed_receipt_is_named_even_beside_a_healthy_one(self):
        # Guards against a silent skip: the planner must name the odd file rather than plan around it.
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, 'r1', _receipt())
            _write(tmp, 'r2', [])
            with self.assertRaisesRegex(ValueError, MALFORMED):
                rollout.private_progress(tmp, LEDGER, MANIFEST)


if __name__ == '__main__':
    unittest.main()
