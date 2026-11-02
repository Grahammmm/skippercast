"""RF2330-2: collect needs a new packet folder; apply names malformed input and exits 1."""
from contextlib import redirect_stderr
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from skippercast.platform.contracts import REPO, atomic_json
from skippercast.pipeline import regulation_review as rr
from skippercast.pipeline import regulations as rules

NOW = datetime(2026, 9, 22, 18, tzinfo=timezone.utc)
JURISDICTION_FILES = rr.jurisdiction_files


class FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class OfflineClient:
    calls = []

    def __init__(self, now, session=None, cache=None):
        self.now, self.requests = now, []

    def get(self, url, as_json=False, as_pdf=False, as_binary=False):
        OfflineClient.calls.append(url)
        raise ConnectionError('offline fixture')


class Inputs(TestCase):
    def setUp(self):
        # Same builder as tests/contract/test_pipeline_regulation_review.py (copied, not imported).
        self.j = json.loads((REPO/'jurisdictions/california-southern.json').read_text())
        self.r = json.loads((REPO/'dist'/self.j['regulations_asset']).read_text())
        self.packet = {'jurisdiction_id': self.j['id'], 'sources': {}}
        self.decision = {'jurisdiction_id': self.j['id'], 'revision': 'fixture',
            'reviewed_at': NOW.isoformat(), 'reviewed_species': list(self.r['species']),
            'rules_content_sha256': rules.content_hash(self.r), 'sources': {}}
        for ident, spec in self.r['sources'].items():
            self.packet['sources'][ident] = {'url': spec['url'], 'status': 'ok',
                'checked_at': NOW.isoformat(), 'data_retrieved_at': (NOW-timedelta(minutes=1)).isoformat(),
                'data': {'content_sha256': 'a'*64, 'normalization': spec['normalization']}}
            self.decision['sources'][ident] = {'decision': 'approve', 'content_sha256': 'a'*64,
                'note': 'Fixture review: checked the specific source and its legal scope.'}
        holder = tempfile.TemporaryDirectory(); self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.root = self.tmp/'root'
        (self.root/'jurisdictions').mkdir(parents=True)
        (self.root/'jurisdictions/california-southern.json').write_text(json.dumps(self.j))
        self.registry = self.root/'dist'/self.j['regulations_asset']
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes((REPO/'dist'/self.j['regulations_asset']).read_bytes())
        self.before = self.registry.read_bytes()

    def main(self, *argv):
        files = lambda ident, root=None: JURISDICTION_FILES(ident, self.root)
        err = io.StringIO()
        with patch.object(rr, 'datetime', FixedNow), redirect_stderr(err), \
                patch.object(rr, 'jurisdiction_files', files), patch('sys.argv', ['regulation_review', *argv]):
            code = rr.main()
        return code, err.getvalue()

    def apply(self, packet=None, decision=None):
        pp, dp = self.tmp/'packet.json', self.tmp/'decision.json'
        pp.write_text(json.dumps(self.packet if packet is None else packet))
        dp.write_text(json.dumps(self.decision if decision is None else decision))
        return self.main('apply', '--jurisdiction', self.j['id'], '--packet', str(pp), '--decision', str(dp))

    def refused(self, result, message):
        code, err = result
        self.assertEqual(code, 1)
        self.assertEqual(err, f'regulation review refused: {message}\n')
        self.assertNotIn('Traceback', err)
        self.assertEqual(self.registry.read_bytes(), self.before)

    def collect(self, output):
        OfflineClient.calls = []
        # The eCFR adapter spaces requests 3 s apart; the offline fixture needs no spacing.
        with patch.object(rr, 'Client', OfflineClient), \
                patch.object(rules, 'ecfr_section', lambda client, spec: client.get('ecfr', as_json=True)):
            return rr.collect_packet(self.j['id'], output, root=self.root, now=NOW)

    def test_collect_accepts_only_a_missing_or_empty_folder(self):
        for output in (self.tmp/'new'/'packet', self.tmp/'empty'):
            if output.name == 'empty':
                output.mkdir()
            self.collect(output)
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['coverage.json', 'packet.json'])
            self.assertTrue(OfflineClient.calls)
        stale = self.tmp/'stale'; stale.mkdir(); (stale/'x.html').write_text('old copy')
        with self.assertRaisesRegex(ValueError, r'^Use a new packet directory; preserve previous evidence$'):
            self.collect(stale)
        self.assertEqual([p.name for p in stale.iterdir()], ['x.html'])
        self.assertEqual((stale/'x.html').read_text(), 'old copy')
        self.assertEqual(OfflineClient.calls, [])
        afile = self.tmp/'afile'; afile.write_text('not a folder')
        with self.assertRaisesRegex(ValueError, r'^Packet output is not a folder$'):
            self.collect(afile)
        self.assertEqual((afile.read_text(), OfflineClient.calls), ('not a folder', []))

    def test_collect_refusal_from_the_command_line_exits_1(self):
        stale = self.tmp/'stale'; stale.mkdir(); (stale/'x.html').write_text('old copy')
        code, err = self.main('collect', '--jurisdiction', self.j['id'], '--output', str(stale))
        self.assertEqual((code, err), (1, 'regulation review refused: Use a new packet directory; preserve previous evidence\n'))
        self.assertEqual([p.name for p in stale.iterdir()], ['x.html'])

    def test_malformed_decision_fields_are_named(self):
        ident = next(iter(self.r['sources']))
        for change, message in (
            (lambda d: d.pop('reviewed_at'), 'decision.reviewed_at must be an ISO time string'),
            (lambda d: d.update(reviewed_at=5), 'decision.reviewed_at must be an ISO time string'),
            (lambda d: d.update(reviewed_at='yesterday'), 'decision.reviewed_at must be an ISO time string'),
            (lambda d: d.update(sources=[]), 'decision.sources must be an object'),
            (lambda d: d['sources'].update({ident: 'approve'}), f'decision.sources.{ident} must be an object'),
        ):
            decision = json.loads(json.dumps(self.decision)); change(decision)
            self.refused(self.apply(decision=decision), message)
        self.refused(self.apply(decision=[]), 'packet and decision must be objects')

    def test_malformed_packet_fields_are_named(self):
        ident = next(iter(self.r['sources']))
        packet = dict(self.packet, sources=[])
        self.refused(self.apply(packet=packet), 'packet.sources must be an object')
        packet = json.loads(json.dumps(self.packet)); packet['sources'][ident]['data_retrieved_at'] = 7
        self.refused(self.apply(packet=packet), f'packet.sources.{ident}.data_retrieved_at must be an ISO time string')
        packet = json.loads(json.dumps(self.packet)); packet['sources'][ident] = 'ok'
        self.refused(self.apply(packet=packet), f'packet.sources.{ident} must be an object')

    def test_unreadable_packet_is_refused_without_traceback(self):
        dp = self.tmp/'decision.json'; dp.write_text(json.dumps(self.decision))
        truncated = self.tmp/'truncated.json'; truncated.write_text(json.dumps(self.packet)[:40])
        for path, fragment in ((truncated, 'line 1 column'), (self.tmp/'missing.json', 'No such file')):
            code, err = self.main('apply', '--jurisdiction', self.j['id'], '--packet', str(path), '--decision', str(dp))
            self.assertEqual(code, 1)
            self.assertTrue(err.startswith('regulation review refused: ') and fragment in err, err)
            self.assertNotIn('Traceback', err)
            self.assertEqual(self.registry.read_bytes(), self.before)

    def test_existing_rules_keep_their_exact_messages(self):
        ident = next(iter(self.r['sources']))
        wrong_hash = json.loads(json.dumps(self.decision)); wrong_hash['rules_content_sha256'] = 'b'*64
        self.refused(self.apply(decision=wrong_hash), 'Legal content changed since the review decision')
        short = json.loads(json.dumps(self.decision)); short['sources'][ident]['note'] = 'ok'
        self.refused(self.apply(decision=short), f'Review must name the inspected hash and conclusion: {ident}')
        stale = json.loads(json.dumps(self.decision)); stale['reviewed_at'] = (NOW-timedelta(days=3)).isoformat()
        self.refused(self.apply(decision=stale), 'Review time must be recent and timezone-aware')

    def test_valid_approval_writes_the_registry_exactly_as_before(self):
        expected = self.tmp/'expected.json'
        atomic_json(expected, rr.approved_registry(json.loads(self.before), self.j, self.packet, self.decision, NOW), indent=2)
        code, err = self.apply()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.registry.read_bytes(), expected.read_bytes())
        self.assertNotEqual(self.registry.read_bytes(), self.before)
