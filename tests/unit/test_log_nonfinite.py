"""JSON log records with NaN/inf values are written with the value as text, never lost (stdlib only, offline)."""
from contextlib import redirect_stderr
from decimal import Decimal
import io
import json
import logging
import unittest

from skippercast import log

NAN, INF = float('nan'), float('inf')


def strict(line):
    def refuse(token):
        raise ValueError(f'non-strict JSON token {token}')
    return json.loads(line, parse_constant=refuse)


class Ratio(float):
    pass


class NonFiniteJsonRecords(unittest.TestCase):
    def tearDown(self):
        root = logging.getLogger('skippercast')
        for handler in list(root.handlers):
            root.removeHandler(handler)

    def emit(self, call, mode='json'):
        """Run call(logger); return (stream text, anything logging printed to stderr)."""
        stream, errors = io.StringIO(), io.StringIO()
        logger = log.configure('daily', stream=stream, environ={'GITHUB_RUN_ID': '987', 'SKIPPERCAST_LOG': mode})
        with redirect_stderr(errors):
            call(logger)
        return stream.getvalue(), errors.getvalue()

    def one(self, call):
        text, errors = self.emit(call)
        self.assertEqual(errors, '')
        self.assertNotIn('Logging error', text)
        lines = text.splitlines()
        self.assertEqual(len(lines), 1, text)
        return strict(lines[0])

    def test_nan_duration_is_written_as_text_and_the_record_kept(self):
        record = self.one(lambda logger: logger.info('x', extra={'duration_ms': NAN}))
        self.assertEqual((record['msg'], record['duration_ms'], record['run_id']), ('x', 'NaN', '987'))

    def test_infinities_in_any_field(self):
        record = self.one(lambda logger: logger.info('x', extra={'http_status': INF, 'duration_ms': -INF}))
        self.assertEqual((record['http_status'], record['duration_ms']), ('Infinity', '-Infinity'))

    def test_nested_values_converted_and_other_items_unchanged(self):
        record = self.one(lambda logger: logger.info('x', extra={
            'region': {'a': [1.0, INF], 'b': (NAN, 2, 'z'), 'c': {'d': -INF, 'e': None}}, 'source_id': [True, 3.5]}))
        self.assertEqual(record['region'], {'a': [1.0, 'Infinity'], 'b': ['NaN', 2, 'z'], 'c': {'d': '-Infinity', 'e': None}})
        self.assertEqual(record['source_id'], [True, 3.5])

    def test_only_floats_are_converted(self):
        record = self.one(lambda logger: logger.info('x', extra={
            'duration_ms': Ratio('nan'), 'http_status': 1200, 'region': Decimal('NaN'), 'source_id': [True, 1.5]}))
        self.assertEqual((record['duration_ms'], record['http_status'], record['region'], record['source_id']),
                         ('NaN', 1200, 'NaN', [True, 1.5]))
        self.assertIsInstance(record['http_status'], int)

    def test_finite_values_give_the_same_json_with_or_without_a_nan_beside_them(self):
        fields = {'duration_ms': 1200, 'http_status': 1.5, 'region': True}
        plain_text, _ = self.emit(lambda logger: logger.info('x', extra=fields))
        plain = strict(plain_text)
        self.assertIn('"region": true, "duration_ms": 1200, "http_status": 1.5}', plain_text)
        mixed = self.one(lambda logger: logger.info('x', extra={**fields, 'source_id': NAN}))
        self.assertEqual(mixed.pop('source_id'), 'NaN')
        mixed.pop('ts'), plain.pop('ts')
        self.assertEqual(list(mixed.items()), list(plain.items()))

    def test_exception_with_a_nan_field_keeps_class_and_traceback(self):
        def call(logger):
            try:
                raise TimeoutError('NDBC did not answer')
            except TimeoutError:
                logger.exception('buoy failed', extra={'duration_ms': NAN})
        record = self.one(call)
        self.assertEqual((record['error_class'], record['duration_ms']), ('TimeoutError', 'NaN'))
        self.assertIn('NDBC did not answer', record['exc'])

    def test_nan_message_argument_is_already_text(self):
        record = self.one(lambda logger: logger.info('v=%s', NAN))
        self.assertEqual(record['msg'], 'v=nan')

    def test_text_mode_is_unchanged(self):
        text, errors = self.emit(lambda logger: logger.info('built', extra={'source_id': 'gfs', 'duration_ms': NAN}), 'text')
        self.assertEqual(errors, '')
        self.assertRegex(text.strip(), r'^\d{2}:\d{2}:\d{2}Z INFO    daily gfs: built \(duration_ms=nan\)$')


if __name__ == '__main__':
    unittest.main()
