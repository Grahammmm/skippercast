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
