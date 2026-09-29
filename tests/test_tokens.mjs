import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {check, contrast, themes} from '../scripts/check_contrast.mjs';

const dist = new URL('../dist/', import.meta.url);
const read = name => readFileSync(new URL(name, dist), 'utf8');
const tokens = read('tokens.css');

test('documented token text pairs reach 4.5:1 in light and dark themes', () => {
  assert.deepEqual(check(tokens).failures, []);
  assert.equal(contrast('#000000', '#ffffff').toFixed(2), '21.00');
  const broken = tokens.replace('--caution: #a46200;', '--caution: #b26b00;');
  assert.match(check(broken).failures.join('\n'), /light: --caution #b26b00 on --surface/);
});

test('tokens.css loads before every other stylesheet and dark mode stays off', () => {
  for (const page of readdirSync(dist).filter(n => n.endsWith('.html'))) {
    const sheets = [...read(page).matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map(m => m[1]);
    if (!sheets.includes('styles.css')) continue;
    assert.equal(sheets[0], 'tokens.css', page);
    assert.doesNotMatch(read(page), /<html[^>]*data-theme/, page);
  }
});

test('legacy styles.css variables resolve to their pre-token values', () => {
  const {light} = themes(tokens);
  const root = read('styles.css').match(/^:root \{([\s\S]*?)\}/)[1];
  const legacy = Object.fromEntries([...root.matchAll(/--([a-z]+): var\(--([a-z0-9-]+)\);/g)].map(m => [m[1], light[m[2]]]));
  assert.deepEqual(legacy, {
    ink: '#102f3b', muted: '#526773', navy: '#082e3b', teal: '#007f73', mint: '#54dacb',
    line: '#dbe4e7', paper: '#f3f7f8', white: '#ffffff', amber: '#946008', blue: '#315f98',
  });
});
