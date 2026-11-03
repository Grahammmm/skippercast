// BF-deep-links: the Share link names the region, the port, the absolute day and the profile;
// opening one shows that port without touching the saved home; a bad ?port= degrades and is cleaned.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {dockTime} from '../web/hour.ts';
import {HOME_PORT_KEY, currentPort, exploreURL, linkedPort, portURL} from '../web/ports.ts';
import {PROFILES, PROFILE_TABLE} from '../web/profile.ts';
import {SHARED_VIEW_KEYS, shareLink, shareOrCopy} from '../web/share-link.ts';
import {configureStore, parsePort, port, readURL, syncFromURL, withParams} from '../web/state.ts';

const PORTS = JSON.parse(readFileSync(new URL('../dist/data/home-ports.json', import.meta.url), 'utf8')).ports;
const byId = id => PORTS.find(p => p.id === id);
const TZ = 'America/Los_Angeles', ORIGIN = 'https://skippercast.com';
const WED = new Date('2026-11-04T20:00:00Z'), THU = new Date('2026-11-05T20:00:00Z');   // noon PST
const SOCAL = 'southern-california';
const link = (query, extra = {}) => shareLink({href: `${ORIGIN}/map?${query}`, origin: ORIGIN, ports: PORTS, region: new URLSearchParams(query).get('region'),
  savedId: null, profile: 'boat', now: WED, tz: TZ, ...extra});
const params = url => Object.fromEntries(new URL(url).searchParams);
const memory = (init = {}) => { const m = new Map(Object.entries(init)); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), map: m}; };

test('the port is carried: the linked port wins over the saved one, and reading the link never saves it', () => {
  const made = link(`region=${SOCAL}&port=san-diego`, {savedId: 'santa-barbara'});
  assert.equal(params(made.url).port, 'san-diego');
  const opened = readURL(made.url);
  assert.equal(currentPort(PORTS, opened.region, 'santa-barbara', parsePort(opened.port)).name, 'San Diego');
  assert.equal(currentPort(PORTS, SOCAL, 'santa-barbara').name, 'Santa Barbara', 'without a link the saved port shows, as before');
  assert.equal(currentPort(PORTS, 'morro-bay', 'port-san-luis', 'morro-bay').id, 'morro-bay');
  for (const [href, saved] of [[made.url, 'santa-barbara'], [link('region=morro-bay&port=morro-bay').url, 'port-san-luis']]) {
    const store = memory({[HOME_PORT_KEY]: saved});
    configureStore({storage: store});
    syncFromURL(href);
    assert.equal(store.map.get(HOME_PORT_KEY), saved, 'the saved home is byte-identical');
    assert.equal(port.value, params(href).port);
  }
  configureStore({storage: null});
  assert.equal(params(portURL(`${ORIGIN}/map?port=ventura&region=x`, byId('san-diego'))).port, 'san-diego', 'a port choice replaces the port key');
});

test('the day is absolute: today is written, a stale day reads as today, a later horizon day round-trips, a far one is left out', () => {
  assert.equal(params(link(`region=${SOCAL}`).url).day, '2026-11-04', 'Wednesday with no ?day= still names Wednesday');
  const wed = link(`region=${SOCAL}`).url;
  const thu = dockTime(readURL(wed).day, null, THU, TZ);
  assert.equal(thu.day, thu.today, 'opened Thursday the dock shows today');
  assert.equal(params(shareLink({href: wed, origin: ORIGIN, ports: PORTS, region: SOCAL, savedId: null, profile: 'boat', now: THU, tz: TZ}).url).day, '2026-11-05', 'the stale day is never passed on');
  const ahead = link(`region=${SOCAL}&day=2026-11-09`).url;
  assert.equal(params(ahead).day, '2026-11-09');
  assert.equal(dockTime(readURL(ahead).day, null, WED, TZ).day, '2026-11-09', 'the recipient sees the same dock day');
  assert.notEqual(params(link(`region=${SOCAL}&day=2026-11-20`).url).day, '2026-11-20', 'beyond the horizon is not emitted');
  assert.notEqual(params(link(`region=${SOCAL}&day=2026-11-01`).url).day, '2026-11-01', 'a past day is not emitted');
});

test('an hour wins and is exact; an hour outside the horizon is kept and no day is invented', () => {
  const within = params(link(`region=${SOCAL}&hour=2026-11-07T15:00Z&day=2026-11-09`).url);
  assert.equal(within.hour, '2026-11-07T15:00Z');
  assert.equal(within.day, '2026-11-07', 'the hour\'s local date');
  const far = params(link(`region=${SOCAL}&hour=2026-12-01T15:00Z`).url);
  assert.equal(far.hour, '2026-12-01T15:00Z');
  assert.equal('day' in far, false);
  assert.equal('hour' in params(link(`region=${SOCAL}&hour=tomorrow`).url), false, 'a malformed hour is dropped');
});

test('an invalid, foreign, repeated or hostile port resolves to saved/first, never throws and is flagged for removal', () => {
  const bad = ['nowhere', 'A..B', 'x'.repeat(200), '<script>', ''];
  for (const value of bad) {
    const href = `${ORIGIN}/map?region=${SOCAL}&port=${encodeURIComponent(value)}`;
    const id = parsePort(readURL(href).port);
    assert.equal(linkedPort(PORTS, SOCAL, id), null, value);
    assert.equal(currentPort(PORTS, SOCAL, 'ventura', id).id, 'ventura', value);
    assert.equal(params(link(new URL(href).search.slice(1), {savedId: 'ventura'}).url).port, 'ventura', value);
  }
  assert.equal(linkedPort(PORTS, 'monterey-point-sur', 'morro-bay'), null, 'a port from another region');
  assert.equal(currentPort(PORTS, 'monterey-point-sur', null, 'morro-bay').id, 'monterey');
  const repeated = `${ORIGIN}/map?region=${SOCAL}&port=san-diego&port=san-diego`;
  configureStore({storage: null});
  syncFromURL(repeated);
  assert.equal(port.value, null, 'a repeated port is unusable');
  assert.equal(params(link(new URL(repeated).search.slice(1)).url).port, 'santa-barbara', 'first in region');
  assert.equal(new URL(withParams(repeated, {port: null})).searchParams.has('port'), false, 'the cleanup removes every copy');
  assert.equal(linkedPort(null, SOCAL, 'san-diego'), null, 'no directory');
});

test('a directory that failed to load still builds a link, without a port', () => {
  for (const ports of [null, []]) {
    const made = link(`region=${SOCAL}&port=san-diego`, {ports});
    assert.equal('port' in params(made.url), false);
    assert.equal(params(made.url).region, SOCAL);
    assert.equal(made.title, 'Wed Nov 4 · Boat');
  }
});

test('Explore the coast round-trips: a region-less link names its coast, so the recipient is not sent to their saved home', () => {
  const explore = new URL(exploreURL(`${ORIGIN}/map?region=${SOCAL}&port=san-diego`)).search.slice(1);
  const made = link(explore, {savedId: 'santa-barbara'});
  assert.deepEqual([...new URL(made.url).searchParams.keys()], ['coast', 'profile', 'day']);
  assert.equal(params(made.url).coast, 'central');
  const opened = readURL(made.url);
  assert.equal(opened.region, null);
  assert.equal(opened.coast, 'central', 'web/app/main.tsx redirects only when region and coast are both missing');
  assert.equal(made.title, 'Wed Nov 4 · Boat');
  for (const query of ['', 'coast=a&coast=b', `coast=${encodeURIComponent('<x>')}`]) {
    assert.equal(params(link(query).url).coast, 'central', `never locationless: ${query}`);
  }
  assert.equal('coast' in params(link(`region=${SOCAL}&coast=central`).url), false, 'a region is the geography when there is one');
});

test('whitelist, not echo: only documented keys, in order, re-encoded', () => {
  const query = `utm_source=x&ui=v2&diagnostics=1&access_token=abc&spot=r1&base=chart&layers=swell,sst&target=halibut&view=conditions&profile=spear&region=${SOCAL}&port=san-diego&place=avila&presentation=3d&current=wcofs&habitat=reef:r1`;
  const made = shareLink({href: `${ORIGIN}/map?${query}#account`, origin: ORIGIN, ports: PORTS, region: SOCAL, savedId: null, profile: 'kayak', now: WED, tz: TZ});
  const url = new URL(made.url);
  assert.equal(url.origin + url.pathname, `${ORIGIN}/map`);
  assert.equal(url.hash, '');
  assert.deepEqual([...url.searchParams.keys()], ['region', 'port', 'profile', 'day', 'target', ...SHARED_VIEW_KEYS]);
  for (const key of ['utm_source', 'ui', 'diagnostics', 'access_token', 'place']) assert.equal(url.searchParams.has(key), false, key);
  assert.equal(url.searchParams.get('profile'), 'kayak', 'the profile shown, not the address\'s');
  assert.equal(url.searchParams.get('layers'), 'swell,sst');
  const hostile = shareLink({href: `${ORIGIN}/map?region=${SOCAL}&spot=${encodeURIComponent('a&ui=v2')}`, origin: ORIGIN, ports: PORTS, region: SOCAL, savedId: null, profile: 'boat', now: WED, tz: TZ});
  assert.equal(new URL(hostile.url).searchParams.get('spot'), 'a&ui=v2');
  assert.equal(new URL(hostile.url).searchParams.has('ui'), false, 'values are encoded, never concatenated');
});

test('duplicate presses with unchanged state give byte-identical links; the title has the documented shape and no condition', () => {
  assert.equal(link(`region=${SOCAL}&port=san-diego`).url, link(`region=${SOCAL}&port=san-diego`).url);
  const forbidden = /\b(Comfortable|Marginal|Rough|Unknown|Go|kn|ft)\b|%|\/10/;
  for (const profile of PROFILES) {
    const made = link('region=morro-bay&port=morro-bay&day=2026-11-07', {profile});
    assert.equal(made.title, `Morro Bay · Sat Nov 7 · ${PROFILE_TABLE[profile].label}`);
    assert.equal(forbidden.test(made.title), false, made.title);
    assert.equal(forbidden.test(decodeURIComponent(made.url)), false, made.url);
  }
});

test('Share: the sheet when present, a dismissed sheet does nothing, other refusals copy, no clipboard shows the link', async () => {
  const made = {url: `${ORIGIN}/map?region=x`, title: 't'};
  const calls = [];
  const clipboard = (ok = true) => ({writeText: async text => { calls.push(['copy', text]); if (!ok) throw Error('denied'); }});
  const sheet = name => async data => { calls.push(['share', data]); if (name) throw Object.assign(Error(name), {name}); };
  assert.equal(await shareOrCopy(made, {share: sheet(null), clipboard: clipboard()}), 'shared');
  assert.deepEqual(calls.splice(0), [['share', {title: 't', url: made.url}]]);
  assert.equal(await shareOrCopy(made, {share: sheet('AbortError'), clipboard: clipboard()}), 'cancelled');
  assert.deepEqual(calls.splice(0).map(c => c[0]), ['share'], 'cancelled: no clipboard write');
  assert.equal(await shareOrCopy(made, {share: sheet('NotAllowedError'), clipboard: clipboard()}), 'copied');
  assert.deepEqual(calls.splice(0).map(c => c[0]), ['share', 'copy']);
  assert.equal(await shareOrCopy(made, {clipboard: clipboard()}), 'copied');
  assert.deepEqual(calls.splice(0), [['copy', made.url]]);
  assert.equal(await shareOrCopy(made, {clipboard: clipboard(false)}), 'manual', 'denied');
  assert.equal(await shareOrCopy(made, {}), 'manual', 'absent');
  assert.equal(await shareOrCopy(made, undefined), 'manual', 'no navigator');
});
