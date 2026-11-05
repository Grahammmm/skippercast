import test from 'node:test';
import assert from 'node:assert/strict';

const {logCounts, filterLog, logCountsText, drawLogView, LOG_NO_MATCH} = await import('../dist/account.js');

let n = 0;
const row = (outcome, species = null, count = outcome === 'fish' ? 1 : 0) => ({id: 'e' + ++n, started_at: '2026-11-01T14:00:00Z', outcome, count, species, method: null, note: null, lat: null, lon: null, trip_id: null});
const els = () => ({list: {innerHTML: ''}, counts: {textContent: '', hidden: true}, species: {innerHTML: '', value: ''}});
const items = e => (e.list.innerHTML.match(/<li>/g) || []).length;

test('counts by outcome, fish total and top five species with ties by name; null species ignored', () => {
  const rows = [row('fish', 'lingcod', 3), row('fish', 'vermilion', 2), row('blank'), row('unknown', 'zebra'), row('blank', null), row('blank', '  '),
    row('fish', 'cabezon'), row('fish', 'bass'), row('fish', 'rockfish'), row('fish', 'ayu')];
  const c = logCounts(rows);
  assert.equal(c.entries, 10); assert.equal(c.fish, 6); assert.equal(c.fishTotal, 9); assert.equal(c.blank, 3); assert.equal(c.unknown, 1);
  assert.deepEqual(c.species.map(s => s.name), ['ayu', 'bass', 'cabezon', 'lingcod', 'rockfish']);
  assert.ok(c.species.every(s => s.count === 1));
  assert.equal(logCounts([]).entries, 0);
});

test('species are trimmed and grouped without case, shown with the first-seen spelling', () => {
  const c = logCounts([row('fish', 'Lingcod'), row('fish', ' lingcod '), row('fish', 'LINGCOD'), row('fish', 'cabezon')]);
  assert.deepEqual(c.species, [{name: 'Lingcod', count: 3}, {name: 'cabezon', count: 1}]);
});

test('the line says loaded while older pages remain, and not when none remain', () => {
  const c = logCounts([row('fish', 'lingcod', 4), row('blank'), row('unknown')]);
  const more = logCountsText(c, {more: true}), done = logCountsText(c, {more: false});
  assert.equal(more, 'In the 3 entries loaded: 1 fish trips (4 fish), 1 blanks, 1 not sure. Most logged: lingcod 1. Older entries are not loaded yet.');
  assert.ok(!/loaded/i.test(done)); assert.match(done, /^In the 3 entries: /);
  assert.match(logCountsText(c, {filtered: true, more: true}), /^In the 3 loaded entries that match: /);
  assert.ok(!/%|rate|score|per trip/i.test(more));
});

test('each filter alone and both together narrow rows and counts; species matches without case', () => {
  const rows = [row('fish', 'Lingcod', 2), row('blank', 'lingcod'), row('fish', 'vermilion', 5), row('unknown'), row('fish', ' LINGCOD ', 1)];
  assert.equal(filterLog(rows, {outcome: 'fish'}).length, 3);
  assert.equal(filterLog(rows, {species: 'lingcod'}).length, 3);
  assert.equal(filterLog(rows, {species: '  LingCod'}).length, 3);
  assert.equal(filterLog(rows, {outcome: 'fish', species: 'lingcod'}).length, 2);
  assert.equal(filterLog(rows, {}).length, 5);
  const e = els();
  drawLogView(e, {entries: rows, view: {outcome: 'fish', species: 'lingcod'}});
  assert.equal(items(e), 2);
  assert.match(e.counts.textContent, /^In the 2 entries that match: 2 fish trips \(3 fish\), 0 blanks, 0 not sure\./);
  assert.equal(e.species.value, 'lingcod');
  assert.match(e.species.innerHTML, /<option value="lingcod">Lingcod<\/option>/);
  assert.equal((e.species.innerHTML.match(/<option/g) || []).length, 3);   // Any, lingcod, vermilion
});

test('a filter kept across Show older: new matching rows appear and the counts update', () => {
  const first = [row('fish', 'lingcod', 2), row('blank'), row('fish', 'vermilion', 1)];
  const view = {outcome: 'fish', species: 'lingcod'}, e = els();
  drawLogView(e, {entries: first, view, more: true});
  assert.equal(items(e), 1); assert.match(e.counts.textContent, /^In the 1 loaded entry that match/); assert.match(e.counts.textContent, /Older entries are not loaded yet\./);
  const all = [...first, row('fish', 'Lingcod', 4), row('blank', 'lingcod'), row('fish', 'cabezon')];
  drawLogView(e, {entries: all, view, more: false});
  assert.equal(items(e), 2);
  assert.match(e.counts.textContent, /2 fish trips \(6 fish\)/); assert.ok(!/not loaded/.test(e.counts.textContent));
});

test('an empty result says so; a chosen species that vanished still filters; an empty log shows no counts', () => {
  const e = els(), rows = [row('fish', 'lingcod', 1)];
  drawLogView(e, {entries: rows, view: {outcome: 'blank', species: ''}});
  assert.equal(items(e), 0); assert.equal(e.counts.textContent, LOG_NO_MATCH); assert.equal(e.counts.hidden, false);
  drawLogView(e, {entries: rows, view: {outcome: '', species: 'vermilion'}});
  assert.equal(e.counts.textContent, LOG_NO_MATCH); assert.equal(e.species.value, 'vermilion');
  assert.match(e.species.innerHTML, /<option value="vermilion">vermilion<\/option>/);
  drawLogView(e, {entries: [], view: {outcome: '', species: ''}});
  assert.equal(e.counts.hidden, true); assert.equal(e.counts.textContent, ''); assert.equal(e.list.innerHTML, '');
});

test('species words are escaped in the choices', () => {
  const e = els();
  drawLogView(e, {entries: [row('fish', '<b>x</b>', 1)], view: {outcome: '', species: ''}});
  assert.ok(!e.species.innerHTML.includes('<b>'));
});
