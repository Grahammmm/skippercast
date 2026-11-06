// FE-61 part 3: current coast source must have no fallback theme.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {checkFallbackFreeCoast, sourceFiles} from '../scripts/check_tokens.mjs';

const root = new URL('../', import.meta.url).pathname;
const read = file => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
const sources = Object.fromEntries(sourceFiles(root, 'packages/coast').map(file => [file, read(file)]));
const tokens = read('web/tokens.css');
const bridge = 'packages/coast/tokens-bridge.css';

test('every coast role is fallback-free and resolves through the bridge into web tokens', () => {
  assert.equal(checkFallbackFreeCoast(sources, tokens).length, 0);
});

test('missing roles, underlying tokens and any second argument fail closed', () => {
  const file = 'packages/coast/example.css';
  const bindings = {[bridge]: '[data-coast-theme="tokens"], :host([data-coast-theme="tokens"]) {--coast-text:var(--text);}'};
  for (const fallback of ['#fff', 'rgb(1 2 3)', 'var(--other)', '']) {
    const failures = checkFallbackFreeCoast({...bindings, [file]: `.a{color:var(--coast-text,${fallback})}`}, ':root {--text:#fff;}');
    assert.ok(failures.some(f => f.rule === 'coast-fallback'), `second argument: ${fallback}`);
  }
  const good = {...bindings, [file]: '.a{color:var(--coast-text)}'};
  assert.equal(checkFallbackFreeCoast(good, ':root {--text:#fff;}').length, 0);
  assert.ok(checkFallbackFreeCoast({...good, [bridge]: ''}, tokens).some(f => f.rule === 'coast-role-undeclared'));
  for (const broken of ['', ':root {--text:var(--missing);}', ':root {--text:var(--text);}'])
    assert.ok(checkFallbackFreeCoast(good, broken).some(f => f.rule === 'coast-token-undefined'));
});

test('all six legend ramps retain every original stop in order, including seven-stop bathy', () => {
  const ramps = {
    bathy: ['#82e6d6', '#38bcb5', '#287db8', '#394aae', '#6d41b6', '#a64b99', '#e9828c'],
    current: ['#245893', '#228fab', '#4bcbbb', '#d2e59a', '#f6c876', '#ec8e68'],
    reef: ['#3c7381', '#3e9fa2', '#5ac8b4', '#d8df92', '#f6d47e'],
    'reef-fit': ['#549ca1', '#b2dca2'],
    shore: ['#83aec4', '#e9cc72', '#6deabd'],
    wave: ['#336d93', '#69b9ee', '#b8b6fc'],
  };
  for (const [ramp, stops] of Object.entries(ramps)) {
    const roles = [...sources['packages/coast/panel.css'].matchAll(new RegExp(`var\\(--coast-${ramp}-(\\d)\\)`, 'g'))].map(m => Number(m[1]));
    assert.equal(roles.join(','), stops.map((_, i) => i).join(','), ramp);
    for (const [i, hex] of stops.entries()) {
      assert.ok(tokens.includes(`--${ramp}-${i}: ${hex};`), `${ramp} stop ${i}`);
      assert.ok(sources[bridge].includes(`--coast-${ramp}-${i}: var(--${ramp}-${i});`));
    }
  }
});
