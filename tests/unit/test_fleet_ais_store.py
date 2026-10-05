"""skippercast.fleet.ais: the raw day-file store, its retention, the AisSource interface,
the aisstream normaliser and subscription message, and the Datalastic stub (CF-40).

Fixtures under tests/fixtures/fleet/ais/aisstream/ follow aisstream's published
message models with synthetic MMSIs (999xxxxxx) and made-up names.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from skippercast.fleet.ais import store as store_module
from skippercast.fleet.ais.sources import SOURCES, get_source
from skippercast.fleet.ais.sources import aisstream
from skippercast.fleet.ais.sources.aisstream import (AisstreamError, AisstreamSource, MalformedMessage, normalise,
                                                     parse_time_utc, subscription_message)
from skippercast.fleet.ais.sources.base import (AisPosition, AisSource, AisStatic, NotConfigured, Unsupported,
                                                bbox_contains, bbox_of)
from skippercast.fleet.ais.sources.datalastic import DatalasticSource
from skippercast.fleet.ais.store import AisStore, RetentionLimits, fleet_var, retention_limits
from tests._support import FIXTURES, ROOT

AIS_FIXTURES = FIXTURES / 'fleet' / 'ais' / 'aisstream'
BBOX = ((34.0, -122.0), (36.0, -119.0))


def ms(*parts):
    """Epoch milliseconds of a UTC datetime given as (year, month, day, hour, minute, second, micro)."""
    return int(datetime(*parts, tzinfo=timezone.utc).timestamp() * 1000)


def fixture(name):
    return json.loads((AIS_FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


def position(mmsi=999000101, ts=None, source='aisstream', lat=35.36, lon=-120.9):
    ts = ms(2026, 7, 4, 18, 22, 30) if ts is None else ts
    return AisPosition(mmsi=mmsi, ts=ts, lat=lat, lon=lon, sog=1.4, cog=212.5, heading=210, nav_status=7,
                       msg_type='PositionReport', source=source, received_at=ts + 318)


def static(mmsi=999000101, ts=None, name='EXAMPLE ONE'):
    ts = ms(2026, 7, 4, 18, 25) if ts is None else ts
    return AisStatic(mmsi=mmsi, ts=ts, name=name, call_sign='ZZ0001', imo=None, ship_type=30, dim_bow=12,
                     dim_stern=6, dim_port=3, dim_starboard=3, ais_class='A', source='aisstream')


class NormaliseTest(unittest.TestCase):
    def test_position_report(self):
        [record] = normalise(json.dumps(fixture('position-report')))
        self.assertEqual(record, AisPosition(
            mmsi=999000101, ts=ms(2026, 7, 4, 18, 22, 30), lat=35.36, lon=-120.9, sog=1.4, cog=212.5, heading=210,
            nav_status=7, msg_type='PositionReport', source='aisstream', received_at=ms(2026, 7, 4, 18, 22, 32, 318000)))

    def test_standard_class_b_position_report(self):
        [record] = normalise(fixture('standard-class-b-position-report'))
        # Fix second 58 is later than receipt (18:23:05) by more than the slack, so it belongs to 18:22.
        self.assertEqual(record.ts, ms(2026, 7, 4, 18, 22, 58))
        self.assertEqual(record.received_at, ms(2026, 7, 4, 18, 23, 5, 4000))
        self.assertEqual((record.mmsi, record.sog, record.cog, record.heading, record.nav_status, record.msg_type),
                         (999000202, 6.2, None, None, None, 'StandardClassBPositionReport'))

    def test_extended_class_b_yields_position_and_static(self):
        record, info = normalise(fixture('extended-class-b-position-report'))
        received = ms(2026, 7, 4, 18, 24, 10, 500000)
        self.assertIsInstance(record, AisPosition)
        self.assertEqual((record.ts, record.sog, record.cog, record.heading), (received, None, 95.0, 96))
        self.assertEqual(info, AisStatic(mmsi=999000303, ts=received, name='EXAMPLE THREE', call_sign=None, imo=None,
                                         ship_type=37, dim_bow=8, dim_stern=4, dim_port=2, dim_starboard=2,
                                         ais_class='B', source='aisstream'))

    def test_ship_static_data(self):
        [info] = normalise(fixture('ship-static-data'))
        self.assertEqual(info, AisStatic(mmsi=999000101, ts=ms(2026, 7, 4, 18, 25, 0, 250000), name='EXAMPLE ONE',
                                         call_sign='ZZ0001', imo=None, ship_type=30, dim_bow=12, dim_stern=6,
                                         dim_port=3, dim_starboard=3, ais_class='A', source='aisstream'))

    def test_static_data_report_parts(self):
        [part_a] = normalise(fixture('static-data-report-a'))
        [part_b] = normalise(fixture('static-data-report-b'))
        self.assertEqual((part_a.name, part_a.call_sign, part_a.ship_type, part_a.dim_bow, part_a.ais_class),
                         ('EXAMPLE TWO', None, None, None, 'B'))
        self.assertEqual((part_b.name, part_b.call_sign, part_b.ship_type, part_b.dim_bow, part_b.dim_starboard),
                         (None, 'ZZ0002', 37, 7, 1))

    def test_every_listed_message_type_has_a_fixture_that_normalises(self):
        seen = set()
        for path in sorted(AIS_FIXTURES.glob('*.json')):
            document = json.loads(path.read_text(encoding='utf-8'))
            if document.get('MessageType') in aisstream.MESSAGE_TYPES:
                records = normalise(document)
                self.assertTrue(records, path.name)
                seen.add(document['MessageType'])
                for record in records:
                    self.assertTrue(999_000_000 <= record.mmsi <= 999_999_999, f'{path.name}: synthetic MMSIs only')
        self.assertEqual(seen, set(aisstream.MESSAGE_TYPES))

    def test_region_message_types_are_all_supported(self):
        for path in sorted((ROOT / 'regions').glob('*/fleet.json')):
            types = json.loads(path.read_text(encoding='utf-8'))['ais']['message_types']
            self.assertLessEqual(set(types), set(aisstream.MESSAGE_TYPES), path)
            AisstreamSource(message_types=types)

    def test_frames_without_records(self):
        self.assertEqual(normalise(fixture('subscription-confirmation')), [])
        self.assertEqual(normalise({'MessageType': 'BaseStationReport', 'Message': {}, 'MetaData': {}}), [])
        invalid = fixture('position-report')
        invalid['Message']['PositionReport']['Valid'] = False
        self.assertEqual(normalise(invalid), [])
        no_fix = fixture('position-report')
        no_fix['Message']['PositionReport'].update(Latitude=91, Longitude=181)
        self.assertEqual(normalise(no_fix), [])
        undefined_status = fixture('position-report')
        undefined_status['Message']['PositionReport']['NavigationalStatus'] = 15
        self.assertIsNone(normalise(undefined_status)[0].nav_status)
        bad_mmsi = fixture('position-report')
        bad_mmsi['Message']['PositionReport']['UserID'] = 0
        self.assertEqual(normalise(bad_mmsi), [])

    def test_error_and_malformed_frames_raise(self):
        with self.assertRaises(AisstreamError):
            normalise((AIS_FIXTURES / 'error.json').read_bytes())
        for raw in ('not json', '[]', json.dumps({'MessageType': 'PositionReport', 'MetaData': {}, 'Message': {}})):
            with self.assertRaises(MalformedMessage):
                normalise(raw)
        broken_time = fixture('position-report')
        broken_time['MetaData']['time_utc'] = 'yesterday'
        with self.assertRaises(MalformedMessage):
            normalise(broken_time)

    def test_missing_time_uses_received_at_then_clock(self):
        document = fixture('ship-static-data')
        del document['MetaData']['time_utc']
        self.assertEqual(normalise(document, received_at=ms(2026, 7, 5, 1, 0))[0].ts, ms(2026, 7, 5, 1, 0))
        clock = lambda: datetime(2026, 7, 6, 2, 0, tzinfo=timezone.utc)   # noqa: E731
        self.assertEqual(normalise(document, clock=clock)[0].ts, ms(2026, 7, 6, 2, 0))

    def test_same_report_heard_twice_gets_one_key(self):
        first = fixture('position-report')
        second = fixture('position-report')
        second['MetaData']['time_utc'] = '2026-07-04 18:22:33.9 +0000 UTC'
        self.assertEqual(normalise(first)[0].ts, normalise(second)[0].ts)

    def test_parse_time_utc_variants(self):
        self.assertEqual(parse_time_utc('2026-07-04 18:22:32.318353912 +0000 UTC'), ms(2026, 7, 4, 18, 22, 32, 318000))
        self.assertEqual(parse_time_utc('2026-07-04T18:22:32.318Z'), ms(2026, 7, 4, 18, 22, 32, 318000))
        self.assertEqual(parse_time_utc('2026-07-04 11:22:32 -0700'), ms(2026, 7, 4, 18, 22, 32))

    def test_source_tag(self):
        self.assertEqual({r.source for r in AisstreamSource().normalise(fixture('extended-class-b-position-report'))},
                         {'aisstream'})


class SubscriptionTest(unittest.TestCase):
    def test_shape(self):
        message = subscription_message('k', BBOX, {999000202, 999000101}, ['PositionReport', 'ShipStaticData'])
        self.assertEqual(message, {'APIKey': 'k', 'BoundingBoxes': [[[34.0, -122.0], [36.0, -119.0]]],
                                   'FiltersShipMMSI': ['999000101', '999000202'],
                                   'FilterMessageTypes': ['PositionReport', 'ShipStaticData']})
        self.assertEqual(set(subscription_message('k', BBOX)), {'APIKey', 'BoundingBoxes'})
        self.assertEqual(subscription_message('k', BBOX, {100_000_000})['FiltersShipMMSI'], ['100000000'])

    def test_limits(self):
        with self.assertRaises(ValueError):
            subscription_message('k', BBOX, range(999000000, 999000201))
        subscription_message('k', BBOX, range(999000000, 999000200))
        for bad in ({'mmsis': set()}, {'mmsis': {0}}, {'mmsis': {99_999_999}}, {'mmsis': {True}},
                    {'message_types': ['SafetyBroadcastMessage']},
                    {'message_types': []}):
            with self.assertRaises(ValueError, msg=bad):
                subscription_message('k', BBOX, **bad)
        for bbox in (((36.0, -122.0), (34.0, -119.0)), ((34.0, -119.0), (36.0, -122.0)), 'box'):
            with self.assertRaises(ValueError):
                subscription_message('k', bbox)
        with self.assertRaises(ValueError):
            subscription_message('', BBOX)

    def test_source_needs_a_key_and_never_shows_it(self):
        with self.assertRaises(NotConfigured):
            AisstreamSource().subscription(BBOX)
        source = AisstreamSource(api_key='secret-value', message_types=['PositionReport'])
        self.assertEqual(source.subscription(BBOX)['FilterMessageTypes'], ['PositionReport'])
        self.assertNotIn('secret-value', repr(source))
        with self.assertRaises(ValueError):
            AisstreamSource(message_types=['NotAType'])


class SourceInterfaceTest(unittest.TestCase):
    def test_registry_and_protocol(self):
        self.assertEqual(set(SOURCES), {'aisstream', 'datalastic'})
        for ident in SOURCES:
            source = get_source(ident)
            self.assertIsInstance(source, AisSource)
            self.assertEqual(source.id, ident)
        with self.assertRaises(KeyError):
            get_source('marinecadastre')

    def test_aisstream_has_no_history(self):
        with self.assertRaises(Unsupported):
            AisstreamSource().history(date(2026, 7, 4), BBOX, None)

    def test_datalastic_is_a_stub(self):
        source = DatalasticSource()
        with self.assertRaises(NotConfigured):
            source.history(date(2026, 7, 4), BBOX, None)

        async def first():
            async for record in source.stream(BBOX, None):
                return record
        with self.assertRaises(NotConfigured):
            asyncio.run(first())

    def test_bbox_helpers(self):
        ais = SimpleNamespace(south=34.0, west=-122.0, north=36.0, east=-119.0)
        self.assertEqual(bbox_of(ais), BBOX)
        self.assertTrue(bbox_contains(BBOX, 35.0, -120.0))
        self.assertFalse(bbox_contains(BBOX, 37.0, -120.0))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.var = Path(self.tmp.name)
        self.store = AisStore.for_region('ZZ', self.var)

    def tearDown(self):
        self.tmp.cleanup()

    def test_layout_and_fleet_var(self):
        self.assertEqual(self.store.raw_dir, self.var / 'ZZ' / 'ais' / 'raw')
        self.assertEqual(fleet_var({'SKIPPERCAST_FLEET_VAR': str(self.var)}), self.var)
        self.assertEqual(fleet_var({}), store_module.repo_root() / 'var' / 'fleet')
        with self.assertRaises(ValueError):
            AisStore.for_region('../x', self.var)

    def test_duplicate_mmsi_ts_source_is_ignored(self):
        record = position()
        counts = self.store.write(positions=[record, record])
        self.assertEqual(counts.positions, 1)
        again = self.store.write(positions=[record, position(source='marinecadastre')])
        self.assertEqual(again.positions, 1)
        changed = AisPosition(**{**record.__dict__, 'lat': 35.0, 'received_at': record.received_at + 900})
        self.assertEqual(self.store.write(positions=[changed]).positions, 0)
        rows = list(self.store.read_positions(0, ms(2027, 1, 1, 0, 0)))
        self.assertEqual([(r.mmsi, r.ts, r.source, r.lat) for r in rows],
                         [(999000101, record.ts, 'aisstream', 35.36), (999000101, record.ts, 'marinecadastre', 35.36)])
        self.assertEqual(self.store.write(statics=[static(), static()]).statics, 1)
        self.assertEqual(self.store.write(discovery=[record, record]).discovery, 1)

    def test_earliest_receipt_wins_in_either_order(self):
        early = position()
        late = AisPosition(**{**early.__dict__, 'lat': 35.0, 'received_at': early.received_at + 70_000})
        for order, table in (([early, late], 'positions'), ([late, early], 'positions'),
                             ([early, late], 'discovery'), ([late, early], 'discovery')):
            with self.subTest(order=[r.received_at for r in order], table=table):
                store = AisStore(self.var / f'{table}-{order[0].received_at}')
                for record in order:
                    store.write(**{table: [record]})
                self.assertEqual(list(store.read_positions(0, ms(2027, 1, 1, 0, 0), table=table)), [early])
        store = AisStore(self.var / 'one-batch')
        self.assertEqual(store.write(positions=[late, early, late]).positions, 2)   # insert, then one replacement
        self.assertEqual(list(store.read_positions(0, ms(2027, 1, 1, 0, 0))), [early])

    def test_records_go_to_their_utc_day_and_read_back_in_order(self):
        late = position(mmsi=999000202, ts=ms(2026, 7, 4, 23, 59, 59))
        early = position(mmsi=999000202, ts=ms(2026, 7, 5, 0, 0, 1))
        other = position(mmsi=999000101, ts=ms(2026, 7, 5, 0, 0, 0))
        counts = self.store.write(positions=[early, late, other], discovery=[position(mmsi=999000909)],
                                  statics=[static(ts=ms(2026, 7, 5, 6, 0))])
        self.assertEqual((counts.positions, counts.discovery, counts.statics, counts.total), (3, 1, 1, 5))
        self.assertEqual(self.store.days(), [date(2026, 7, 4), date(2026, 7, 5)])
        window = list(self.store.read_positions(ms(2026, 7, 4, 23, 0), ms(2026, 7, 5, 1, 0)))
        self.assertEqual(window, [other, late, early])
        self.assertEqual(list(self.store.read_positions(ms(2026, 7, 4, 0, 0), ms(2026, 7, 6, 0, 0), {999000202})),
                         [late, early])
        self.assertEqual(list(self.store.read_positions(0, ms(2027, 1, 1, 0, 0), set())), [])
        self.assertEqual([p.mmsi for p in self.store.read_positions(0, ms(2027, 1, 1, 0, 0), table='discovery')],
                         [999000909])
        self.assertEqual(list(self.store.read_statics(0, ms(2027, 1, 1, 0, 0))), [static(ts=ms(2026, 7, 5, 6, 0))])
        with self.assertRaises(ValueError):
            list(self.store.read_positions(0, 1, table='statics'))

    def test_day_file_schema(self):
        self.store.write(positions=[position()])
        with sqlite3.connect(self.store.day_path(date(2026, 7, 4))) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], store_module.SCHEMA_VERSION)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {'positions', 'discovery', 'statics'})

    def test_write_rejects_wrong_records(self):
        with self.assertRaises(TypeError):
            self.store.write(positions=[static()])
        with self.assertRaises(ValueError):
            self.store.write(positions=[position(mmsi=0)])

    def test_normalised_records_round_trip(self):
        records = [r for name in ('position-report', 'extended-class-b-position-report', 'ship-static-data')
                   for r in normalise(fixture(name))]
        positions = [r for r in records if isinstance(r, AisPosition)]
        statics = [r for r in records if isinstance(r, AisStatic)]
        self.store.write(positions=positions, statics=statics)
        by_mmsi = lambda records: sorted(records, key=lambda r: r.mmsi)   # noqa: E731
        self.assertEqual(list(self.store.read_positions(0, ms(2027, 1, 1, 0, 0))), by_mmsi(positions))
        self.assertEqual(list(self.store.read_statics(0, ms(2027, 1, 1, 0, 0))), by_mmsi(statics))


class RetentionTest(unittest.TestCase):
    TODAY = date(2026, 10, 4)
    LIMITS = RetentionLimits(raw_days=30, discovery_days=7, static_days=90)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AisStore(Path(self.tmp.name) / 'ZZ' / 'ais')

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, age):
        day = self.TODAY - timedelta(days=age)
        noon = ms(day.year, day.month, day.day, 12, 0)
        self.store.write(positions=[position(ts=noon)], discovery=[position(mmsi=999000909, ts=noon)],
                         statics=[static(ts=noon)])
        return self.store.day_path(day)

    def counts(self, path):
        with sqlite3.connect(path) as conn:
            return tuple(conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                         for t in ('positions', 'discovery', 'statics'))

    def test_deletes_only_day_files_past_the_limit_and_never_validation(self):
        paths = {age: self.fill(age) for age in (0, 7, 8, 30, 31, 90, 91, 400)}
        validation = self.store.validation_dir
        (validation / 'trip-1').mkdir(parents=True)
        kept = {
            validation / '2025-01-01.sqlite': b'labelled trip positions',
            validation / 'trip-1' / '2025-01-02.sqlite': b'labelled trip positions',
            self.store.raw_dir / 'notes.txt': b'not a day file',
            self.store.raw_dir / '2026-13-01.sqlite': b'not a real day',
        }
        for path, data in kept.items():
            path.write_bytes(data)
        os.utime(validation / '2025-01-01.sqlite', (1_700_000_000, 1_700_000_000))
        link = self.store.raw_dir / '2024-01-01.sqlite'
        link.symlink_to(validation / '2025-01-01.sqlite')

        result = self.store.apply_retention(self.LIMITS, today=self.TODAY)

        self.assertEqual(sorted(result.deleted_files), sorted(p.name for a, p in paths.items() if a > 90))
        for age in (91, 400):
            self.assertFalse(paths[age].exists())
            self.assertFalse(paths[age].with_name(paths[age].name + '-wal').exists())
        self.assertEqual(self.counts(paths[0]), (1, 1, 1))
        self.assertEqual(self.counts(paths[7]), (1, 1, 1))
        self.assertEqual(self.counts(paths[8]), (1, 0, 1))
        self.assertEqual(self.counts(paths[30]), (1, 0, 1))
        self.assertEqual(self.counts(paths[31]), (0, 0, 1))
        self.assertEqual(self.counts(paths[90]), (0, 0, 1))
        self.assertEqual(result.emptied[paths[8].name], ['discovery'])
        self.assertEqual(result.emptied[paths[31].name], ['positions', 'discovery'])
        for path, data in kept.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(os.stat(validation / '2025-01-01.sqlite').st_mtime, 1_700_000_000)
        self.assertTrue(link.is_symlink())

        again = self.store.apply_retention(self.LIMITS, today=self.TODAY)
        self.assertEqual((again.deleted_files, again.emptied), ([], {}))

    def test_clock_and_missing_store(self):
        self.assertEqual(self.store.apply_retention(self.LIMITS, today=self.TODAY).deleted_files, [])
        old = self.fill(100)
        clock = lambda: datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc)   # noqa: E731
        self.assertEqual(self.store.apply_retention(self.LIMITS, clock=clock).deleted_files, [old.name])

    def test_raw_symlink_is_skipped(self):
        trap = AisStore(Path(self.tmp.name) / 'trap')
        (trap.validation_dir).mkdir(parents=True)
        trap.raw_dir.symlink_to(trap.validation_dir)
        self.assertEqual(trap.apply_retention(self.LIMITS, today=self.TODAY).deleted_files, [])

    def test_validation_resolving_around_raw_is_refused(self):
        old = self.fill(100)
        self.store.validation_dir.symlink_to(self.store.root)   # validation/ now contains raw/
        with self.assertRaises(RuntimeError):
            self.store.apply_retention(self.LIMITS, today=self.TODAY)
        self.assertTrue(old.exists())

    def test_hard_linked_day_file_is_not_emptied(self):
        path = self.fill(31)
        self.store.validation_dir.mkdir(parents=True)
        shared = self.store.validation_dir / path.name
        os.link(path, shared)
        result = self.store.apply_retention(self.LIMITS, today=self.TODAY)
        self.assertEqual((result.skipped, result.emptied), ([path.name], {}))
        self.assertEqual(self.counts(shared), (1, 1, 1))
        expired = self.store.apply_retention(self.LIMITS, today=self.TODAY + timedelta(days=60))
        self.assertEqual(expired.deleted_files, [path.name])
        self.assertFalse(path.exists())
        self.assertEqual(self.counts(shared), (1, 1, 1))

    def test_limits_from_region_thresholds(self):
        region = SimpleNamespace(thresholds={'retention': {'raw_days': 30, 'discovery_days': 7, 'static_days': 90}})
        self.assertEqual(retention_limits(region), self.LIMITS)
        ca = json.loads((ROOT / 'regions' / 'CA' / 'fleet.json').read_text(encoding='utf-8'))
        retention_limits(SimpleNamespace(thresholds=ca['thresholds']))
        for bad in ({'raw_days': 0}, {'static_days': True}):
            with self.assertRaises(ValueError):
                RetentionLimits(**{'raw_days': 30, 'discovery_days': 7, 'static_days': 90, **bad})


if __name__ == '__main__':
    unittest.main()
