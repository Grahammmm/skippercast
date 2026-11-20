"""The operations report requires both analytics opt-in and read bindings."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import BytesIO, StringIO
import unittest
from unittest.mock import Mock

from scripts import ops_report


class OpsReportOptInTests(unittest.TestCase):
    def test_queries_only_when_enabled_and_configured(self):
        # Retained read bindings must not authorize queries once analytics is off.
        bindings = {'CF_ANALYTICS_TOKEN': 'synthetic-token', 'CLOUDFLARE_ACCOUNT_ID': 'synthetic-account'}
        for flag in (None, 'false', 'true'):
            for configured in (False, True):
                with self.subTest(flag=flag, configured=configured):
                    env = dict(bindings) if configured else {}
                    if flag is not None:
                        env['ENABLE_ANALYTICS'] = flag
                    opener = Mock(side_effect=lambda *args, **kwargs: BytesIO(b'{"data": []}'))
                    github_opener = Mock(side_effect=AssertionError('unexpected GitHub request'))
                    with redirect_stdout(StringIO()) as output:
                        status = ops_report.main([], env, opener=opener, github_opener=github_opener,
                                                 now=datetime(2026, 1, 1, tzinfo=timezone.utc))
                    self.assertEqual(status, 0)
                    if flag == 'true' and configured:
                        self.assertGreater(opener.call_count, 0)
                        self.assertNotIn('Operations report skipped:', output.getvalue())
                    else:
                        opener.assert_not_called()
                        reason = 'set the CF_ANALYTICS_TOKEN secret' if flag == 'true' else 'ENABLE_ANALYTICS is not true'
                        self.assertIn(f'Operations report skipped: {reason}', output.getvalue())
                    github_opener.assert_not_called()
