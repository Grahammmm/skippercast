// RF0910-2: a shared link carries `target` and each view key only when the address has it once, in plain form:
// target must be an id (`^[a-z][a-z0-9-]{0,63}$`, fishLink's species shape); a view value 1-200 characters with no
// whitespace, control character or `#`. Anything else is left out of the link, never rewritten.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {PLAIN, single, shareLink, TARGET_ID} from '../web/share-link.ts';

const PORTS = JSON.parse(readFileSync(new URL('../dist/data/home-ports.json', import.meta.url), 'utf8')).ports;
const ORIGIN = 'https://skippercast.com', TZ = 'America/Los_Angeles', WED = new Date('2026-11-04T20:00:00Z');
const BASE = 'region=southern-california&port=san-diego';
const MAIN_URL = `${ORIGIN}/map?region=southern-california&port=san-diego&profile=boat&day=2026-11-04`;
const MAIN_TITLE = 'San Diego · Wed Nov 4 · Boat';
const link = query => shareLink({href: `${ORIGIN}/map?${query}`, origin: ORIGIN, ports: PORTS,
  region: new URLSearchParams(query).get('region'), savedId: null, profile: 'boat', now: WED, tz: TZ});
const param = (made, key) => new URL(made.url).searchParams.getAll(key);

test('a single id-shaped target is kept; capitals, a leading digit, a space or an empty value are dropped', () => {
  assert.deepEqual(param(link(`${BASE}&target=lingcod`), 'target'), ['lingcod']);
  assert.equal(link(`${BASE}&target=lingcod`).url, `${MAIN_URL}&target=lingcod`);
  for (const bad of ['Lingcod', '1abc', 'a%20b', '', '-rock', 'rock_fish', 'a'.repeat(65)]) {
    const made = link(`${BASE}&target=${bad}`);
    assert.deepEqual(param(made, 'target'), [], bad);
    assert.equal(made.url, MAIN_URL, `${bad}: the link is the no-target link`);
    assert.equal(made.title, MAIN_TITLE, `${bad}: the title does not change`);
  }
  assert.deepEqual(param(link(`${BASE}&target=${'a'.repeat(64)}`), 'target'), ['a'.repeat(64)]);
});

test('a repeated target or view key is dropped, even when the copies agree; a single value is byte-identical', () => {
  for (const q of ['target=a&target=b', 'target=lingcod&target=lingcod', 'layers=x&layers=y', 'layers=reefs&layers=reefs', 'view=list&view=']) {
    const made = link(`${BASE}&${q}`);
    assert.equal(made.url, MAIN_URL, q);
    assert.equal(made.title, MAIN_TITLE, q);
  }
  assert.equal(link(`${BASE}&layers=reefs,shore`).url, `${MAIN_URL}&layers=reefs%2Cshore`);
  assert.deepEqual(param(link(`${BASE}&layers=reefs,shore`), 'layers'), ['reefs,shore']);
  // One bad key does not take the others with it.
  assert.equal(link(`${BASE}&view=list&layers=x&layers=y&base=sat`).url, `${MAIN_URL}&view=list&base=sat`);
});

test('a 200-character view value is kept; 201 characters, a control character, a space or # is dropped', () => {
  const v200 = 'v'.repeat(200);
  assert.deepEqual(param(link(`${BASE}&view=${v200}`), 'view'), [v200]);
  for (const bad of ['v'.repeat(201), 'a%0Ab', 'a%09b', 'a%7Fb', 'a%23b', 'a%00b', 'a%20b', 'a+b', '']) {
    const made = link(`${BASE}&view=${bad}`);
    assert.deepEqual(param(made, 'view'), [], bad);
    assert.equal(made.url, MAIN_URL, bad);
    assert.equal(made.title, MAIN_TITLE, bad);
  }
});

test('a non-ASCII plain value is kept and re-encoded as main encodes it', () => {
  const made = link(`${BASE}&spot=Morro-Roca-%C3%A9`);
  assert.deepEqual(param(made, 'spot'), ['Morro-Roca-é']);
  assert.equal(made.url, `${MAIN_URL}&spot=Morro-Roca-%C3%A9`);
  assert.equal(link(`${BASE}&spot=Morro-Roca-é`).url, made.url, 'a raw é encodes the same way');
});

test('no view keys: the link and title are main\'s; dropped values never change the title', () => {
  const plain = link(BASE);
  assert.equal(plain.url, MAIN_URL);
  assert.equal(plain.title, MAIN_TITLE);
  const junk = link(`${BASE}&target=A&view=${'x'.repeat(300)}&spot=a%0Ab&habitat=r&habitat=s&utm_source=x`);
  assert.equal(junk.url, MAIN_URL);
  assert.equal(junk.title, MAIN_TITLE);
});

test('single() needs exactly one matching value; the shapes are fixed', () => {
  const p = new URLSearchParams('a=x&b=1&b=2&c=Bad');
  assert.equal(single(p, 'a', PLAIN), 'x');
  assert.equal(single(p, 'b', PLAIN), null, 'repeated');
  assert.equal(single(p, 'missing', PLAIN), null, 'absent');
  assert.equal(single(p, 'c', TARGET_ID), null, 'wrong shape');
  assert.equal(single(p, 'c', PLAIN), 'Bad');
  assert.equal(single(p, 'a', TARGET_ID), 'x', 'calling twice gives the same answer (no sticky regex state)');
});

// RF1100-13: the legacy Fish `species` alias is read from the original query, so a repeated alias is as ambiguous as a
// repeated `target`. An explicit `target` (present, even empty or bad) always blocks the alias fallback.
const blockFetch = fn => {
  const real = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('fetch is not allowed'); };
  try { return fn(); } finally { globalThis.fetch = real; }
};
const expectNoTarget = (query, base = MAIN_URL, title = MAIN_TITLE) => {
  const made = blockFetch(() => link(query));
  assert.deepEqual(param(made, 'target'), [], query);
  assert.deepEqual(param(made, 'species'), [], `${query}: no species key leaks out`);
  assert.equal(made.url, base, query);
  assert.equal(made.title, title, query);
};

test('share_species_alias_refuses_duplicates_before_rewrite', () => {
  for (const q of ['species=lingcod&species=rockfish', 'species=rockfish&species=lingcod', 'species=lingcod&species=lingcod',
    'species=lingcod&species=', 'species=&species=lingcod', 'species=lingcod&species=Lingcod']) {
    expectNoTarget(`${BASE}&${q}`);
  }
});

test('share_species_alias_keeps_only_one_valid_id', () => {
  for (const ok of ['lingcod', 'ling%63od', 'a'.repeat(64)]) {
    const made = blockFetch(() => link(`${BASE}&species=${ok}`));
    assert.deepEqual(param(made, 'target'), [decodeURIComponent(ok)], ok);
    assert.deepEqual(param(made, 'species'), [], `${ok}: no species key leaks out`);
    assert.equal(made.url, `${MAIN_URL}&target=${decodeURIComponent(ok)}`, ok);
    assert.equal(made.title, MAIN_TITLE, ok);
  }
  for (const bad of ['', 'Lingcod', '1abc', 'a%20b', 'a%0Ab', 'a%23b', 'a'.repeat(65)]) expectNoTarget(`${BASE}&species=${bad}`);
});

test('share_explicit_target_presence_blocks_alias_fallback', () => {
  assert.equal(blockFetch(() => link(`${BASE}&target=rockfish&species=lingcod&species=cabezon`)).url, `${MAIN_URL}&target=rockfish`);
  assert.equal(blockFetch(() => link(`${BASE}&species=lingcod&species=cabezon&target=rockfish`)).url, `${MAIN_URL}&target=rockfish`);
  assert.equal(blockFetch(() => link(`${BASE}&target=rockfish&species=Bad`)).url, `${MAIN_URL}&target=rockfish`);
  assert.equal(blockFetch(() => link(`${BASE}&species=lingcod&target=rockfish`)).url, `${MAIN_URL}&target=rockfish`);
  for (const q of ['target=&species=lingcod', 'species=lingcod&target=', 'target=Bad&species=lingcod', 'target=a&target=b&species=lingcod',
    'species=lingcod&target=a&target=b', 'target=rockfish&target=rockfish&species=lingcod', 'species=lingcod&target=rockfish&target=rockfish']) {
    expectNoTarget(`${BASE}&${q}`);
  }
});

test('share_alias_refusal_preserves_other_state', () => {
  const dup = 'species=lingcod&species=rockfish';
  const coastBase = 'coast=central&layers=terrain&base=sat&spot=a1&habitat=reef&grade=ab';
  const coastUrl = `${ORIGIN}/map?coast=central&profile=boat&day=2026-11-04&layers=terrain&base=sat&habitat=reef&spot=a1&grade=ab`;
  expectNoTarget(coastBase, coastUrl, 'Wed Nov 4 · Boat');
  expectNoTarget(`${dup}&${coastBase}&utm_source=x#frag`, coastUrl, 'Wed Nov 4 · Boat');
  expectNoTarget(`${coastBase}&${dup}`, coastUrl, 'Wed Nov 4 · Boat');
  const hourBase = 'region=morro-bay&port=morro-bay&hour=2026-11-05T15:00Z&current=on';
  const hourUrl = `${ORIGIN}/map?region=morro-bay&port=morro-bay&profile=boat&day=2026-11-05&hour=2026-11-05T15%3A00Z&current=on`;
  expectNoTarget(hourBase, hourUrl, 'Morro Bay · Thu Nov 5 · Boat');
  expectNoTarget(`${hourBase}&${dup}&token=secret`, hourUrl, 'Morro Bay · Thu Nov 5 · Boat');
  // A single legacy species still rewrites exactly as before, with mode/place/grade.
  const made = blockFetch(() => link('mode=boat&species=rockfish&place=coast&grade=ab'));
  assert.equal(made.url, `${ORIGIN}/map?coast=central&profile=boat&day=2026-11-04&target=rockfish&grade=ab`);
  assert.equal(made.title, 'Wed Nov 4 · Boat');
});
