// RF0910-1: Share keeps the terrain grade filter (web/grade.ts: "written as `?grade=` so a shared link keeps it").
// The value is normalised through parseGrade/gradeParam: `a` and `ab` are carried, anything else adds nothing.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parseGrade} from '../web/grade.ts';
import {shareLink} from '../web/share-link.ts';

const PORTS = JSON.parse(readFileSync(new URL('../dist/data/home-ports.json', import.meta.url), 'utf8')).ports;
const ORIGIN = 'https://skippercast.com', TZ = 'America/Los_Angeles', WED = new Date('2026-11-04T20:00:00Z');
const SOCAL = 'southern-california';
const link = query => shareLink({href: `${ORIGIN}/map?${query}`, origin: ORIGIN, ports: PORTS,
  region: new URLSearchParams(query).get('region'), savedId: null, profile: 'boat', now: WED, tz: TZ});
const grades = url => new URL(url).searchParams.getAll('grade');

test('?grade=a and ?grade=ab are carried; an upper-case value is normalised', () => {
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=a`).url), ['a']);
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=ab`).url), ['ab']);
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=A`).url), ['a']);
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=AB`).url), ['ab']);
});

test('all, empty, junk, b or no key adds no grade key', () => {
  for (const q of ['grade=all', 'grade=', 'grade=abc', 'grade=b', 'grade=%20a', 'grade=c', '']) {
    const url = link(`region=${SOCAL}&${q}`).url;
    assert.equal(new URL(url).searchParams.has('grade'), false, q);
    assert.equal(url, link(`region=${SOCAL}`).url, `${q}: the link is the no-grade link`);
  }
});

test('a repeated key reads the first value only, as the view keys do', () => {
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=a&grade=ab`).url), ['a']);
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=ab&grade=a`).url), ['ab']);
  assert.deepEqual(grades(link(`region=${SOCAL}&grade=junk&grade=a`).url), [], 'a bad first value is all grades');
});

// Main's links for three inputs without a grade: these must stay byte-identical, and adding a grade only appends it.
const MAIN = [
  [`region=${SOCAL}&port=san-diego&view=list&utm_source=x`,
    `${ORIGIN}/map?region=southern-california&port=san-diego&profile=boat&day=2026-11-04&view=list`, 'San Diego · Wed Nov 4 · Boat'],
  ['coast=central&layers=terrain&base=sat&spot=a1&habitat=reef',
    `${ORIGIN}/map?coast=central&profile=boat&day=2026-11-04&layers=terrain&base=sat&habitat=reef&spot=a1`, 'Wed Nov 4 · Boat'],
  ['region=morro-bay&port=morro-bay&target=rockfish&hour=2026-11-05T15:00Z&current=on&presentation=x',
    `${ORIGIN}/map?region=morro-bay&port=morro-bay&profile=boat&day=2026-11-05&hour=2026-11-05T15%3A00Z&target=rockfish&presentation=x&current=on`,
    'Morro Bay · Thu Nov 5 · Boat'],
];

test('without a grade the link and title are main\'s; with one, grade follows the last view key and nothing else moves', () => {
  for (const [query, url, title] of MAIN) {
    const plain = link(query);
    assert.equal(plain.url, url, query);
    assert.equal(plain.title, title, query);
    for (const g of ['a', 'ab']) {
      const graded = link(`grade=${g}&${query}`);
      assert.equal(graded.url, `${url}&grade=${g}`, `${query} grade=${g}`);
      assert.equal(graded.title, title, 'the title never names the filter');
    }
  }
});

test('a fish-link address keeps the grade after fishLink rewriting, and the recipient reads it back', () => {
  const made = link('mode=boat&species=rockfish&place=coast&grade=ab');
  const p = new URL(made.url).searchParams;
  assert.equal(p.get('target'), 'rockfish');
  assert.equal(p.get('coast'), 'central');
  assert.deepEqual(grades(made.url), ['ab']);
  assert.equal([...p.keys()].at(-1), 'grade');
  assert.equal(parseGrade(p.get('grade')), 'ab', 'the page reads the same filter back');
});
