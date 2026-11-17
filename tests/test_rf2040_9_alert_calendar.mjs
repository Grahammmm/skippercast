// RF2040-9: alertInstant checks February against the literal Gregorian year, not Date.UTC's 0-99 -> 1900s remap.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'alert-calendar-')), 'bundle.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `export {alertInstant} from './web/alert-time.ts';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', plugins: preparedRendererPlugins,
});
const {alertInstant} = await import(pathToFileURL(out).href);
const iso = value => alertInstant(value)?.toISOString() ?? null;

test('alert_calendar_accepts_year_zero_leap_day', () => {
  assert.equal(iso('0000-02-29T10:00:00Z'), '0000-02-29T10:00:00.000Z');
  assert.equal(iso('0000-02-29T10:00:00+00:00'), '0000-02-29T10:00:00.000Z');
  assert.equal(iso('0000-02-29T10:00:00-02:00'), '0000-02-29T12:00:00.000Z');
});

test('alert_calendar_century_boundaries', () => {
  assert.equal(iso('0100-02-29T10:00:00Z'), null);
  assert.equal(iso('1900-02-29T10:00:00Z'), null);
  assert.equal(iso('0400-02-29T10:00:00Z'), '0400-02-29T10:00:00.000Z');
  assert.equal(iso('2000-02-29T10:00:00Z'), '2000-02-29T10:00:00.000Z');
  for (const y of ['0000', '0004', '0100', '0400', '1900', '2000']) assert.equal(iso(`${y}-02-30T10:00:00Z`), null, y);
  assert.equal(iso('0099-02-28T10:00:00Z'), '0099-02-28T10:00:00.000Z');
  assert.equal(iso('0099-02-29T10:00:00Z'), null);
});

test('alert_calendar_month_edges', () => {
  for (const bad of ['2026-00-10T10:00:00Z', '2026-13-10T10:00:00Z', '2026-05-00T10:00:00Z', '2026-04-31T10:00:00Z', '2026-02-29T10:00:00Z']) {
    assert.equal(iso(bad), null, bad);
  }
  assert.equal(iso('2026-01-31T10:00:00Z'), '2026-01-31T10:00:00.000Z');
  assert.equal(iso('2026-04-30T10:00:00Z'), '2026-04-30T10:00:00.000Z');
});

test('alert_calendar_modern_control_unchanged', () => {
  assert.equal(iso('2026-10-08T20:00:00Z'), '2026-10-08T20:00:00.000Z');
  assert.equal(iso('2024-02-29T10:00:00Z'), '2024-02-29T10:00:00.000Z');
  assert.equal(iso('0000-02-28T10:00:00Z'), '0000-02-28T10:00:00.000Z');
  for (const bad of [null, undefined, '', 'not a date', '2026-10-08', '2026-10-08T20:00:00']) assert.equal(iso(bad), null, String(bad));
});
