// RF2000-8: whitespace between a configured selector and its brace must not change theme maps or contrast results.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {themes, check} from '../scripts/check_contrast.mjs';

const LIGHT = ':root[data-theme="light"]';
const SEPS = {space: ' ', none: '', tab: '\t', lf: '\n', crlf: '\r\n', many: '   '};
const css = (d, l, body = {dark: '--text:#ffffff;--bg:#000000;--muted:#ffffff;', light: '--text:#000000;--bg:#ffffff;'}) =>
  `/* c */\n:root${d}{${body.dark}}\n${LIGHT}${l}{${body.light}}\n`;
const spec = pairs => ({pairs, base: 'dark', overlay: 'light', selectors: {dark: ':root', light: LIGHT}});

test('token_selector_whitespace_is_semantically_equivalent', () => {
  const control = themes(css(' ', ' '), spec([]));
  assert.equal(control.light.muted, '#ffffff');
  for (const [name, sep] of Object.entries(SEPS)) {
    assert.ok(isDeepStrictEqual(themes(css(sep, sep), spec([])), control), `separator ${name}`);
  }
});

test('dark_and_light_headers_vary_independently', () => {
  const control = themes(css(' ', ' '), spec([]));
  assert.ok(isDeepStrictEqual(themes(css('', ' '), spec([])), control));
  assert.ok(isDeepStrictEqual(themes(css(' ', '\n'), spec([])), control));
});

test('contrast_outcomes_do_not_depend_on_header_formatting', () => {
  const s = spec([['text', 'bg', 'readable'], ['muted', 'bg', 'equal colours']]);
  const control = check(css(' ', ' '), s);
  for (const [name, sep] of Object.entries(SEPS)) {
    assert.ok(isDeepStrictEqual(check(css(sep, sep), s), control), `separator ${name}`);
  }
});

test('missing_and_longer_selector_controls', () => {
  assert.throws(() => themes(`${LIGHT}{--text:#000000;}`, spec([])), /missing :root/);
  assert.throws(() => themes(`:root{--text:#ffffff;}`, spec([])), /missing :root\[data-theme="light"\]/);
  assert.throws(() => themes(`:root:hover{--text:#ffffff;}\n${LIGHT}{--text:#000000;}`, spec([])), /missing :root/);
  assert.throws(() => themes(`a:root{--text:#ffffff;}\n${LIGHT}{--text:#000000;}`, spec([])), /missing :root/);
});
