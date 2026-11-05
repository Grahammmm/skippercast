import test from 'node:test';
import assert from 'node:assert/strict';
import {readGpxWaypoints} from '../web/gpx-waypoints.ts';

const wrap = body => `<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;
const one = inner => wrap(`<wpt lat="35" lon="-120"><name>N</name>${inner}</wpt>`);

test('gpx_waypoints_xml_name_characters_that_are_js_whitespace_are_legal', () => {
  for (const ch of ['\u1680', '\ufeff']) {
    const r = readGpxWaypoints(one(`<x:e${ch}f xmlns:x="urn:x" x:a${ch}b="1"/>`));
    assert.equal(r.ok, true, `U+${ch.codePointAt(0).toString(16)} in names`);
    assert.equal(r.waypoints.length, 1);
    const c = readGpxWaypoints(one(`<e${ch}><i/></e${ch}>`));
    assert.equal(c.ok, true);
  }
});

test('gpx_waypoints_xml_whitespace_still_separates_names', () => {
  assert.equal(readGpxWaypoints(one('<e\ta="1"\n/>')).ok, true);
  assert.equal(readGpxWaypoints(one('<e\u00a0a="1"/>')).ok, false);
});

test('gpx_waypoints_literal_cr_and_crlf_normalize_to_lf', () => {
  const r = readGpxWaypoints(one('<desc>A\rB\r\nC</desc>'));
  assert.equal(r.ok, true);
  assert.equal(r.waypoints[0].note, 'A\nB\nC');
  const cd = readGpxWaypoints(one('<desc><![CDATA[A\rB\r\nC]]></desc>'));
  assert.equal(cd.waypoints[0].note, 'A\nB\nC');
});

test('gpx_waypoints_character_reference_cr_is_preserved', () => {
  const r = readGpxWaypoints(one('<desc>A&#13;B&#xD;&#10;C</desc>'));
  assert.equal(r.waypoints[0].note, 'A\rB\r\nC');
});

test('gpx_waypoints_note_truncation_counts_normalized_text', () => {
  const r = readGpxWaypoints(one(`<desc>${'a\r\n'.repeat(600)}</desc>`));
  assert.equal(r.waypoints[0].note.length, 1000);
  assert.ok(!r.waypoints[0].note.includes('\r'));
});
