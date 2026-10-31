import assert from 'node:assert/strict';
import test from 'node:test';
import {lookupBoat, parseResponse} from '../server/boat-lookup.ts';

// Synthetic Messages API payloads only; no network.
const spec = '{"name":"Parker 2320 SL","loa_ft":23.3,"hull":"deep-v","confidence":"high","estimated":["displacement_lb"],"notes":"Cuddy."}';
const good = {url: 'https://www.parkerboats.net/2320sl', title: 'Parker 2320 SL'};
const withSources = (citations, results = []) => ({
  content: [
    {type: 'server_tool_use', id: 's1', name: 'web_search', input: {query: 'Parker 2320 SL'}},
    {type: 'web_search_tool_result', tool_use_id: 's1', content: results.map(r => ({type: 'web_search_result', ...r}))},
    {type: 'text', text: spec, citations: citations.map(c => ({type: 'web_search_result_location', ...c}))},
  ],
  stop_reason: 'end_turn',
});
const urls = r => r.sources.map(s => s.url);

test('the existing answer shape still yields the same single source', () => {
  const r = parseResponse(withSources([good], [good]));
  assert.deepEqual(r.sources, [good]);
  assert.equal(r.boat.loa_ft, 23.3);
  assert.equal(r.confidence, 'high');
  assert.deepEqual(r.estimated, ['displacement_lb']);
  assert.equal(r.notes, 'Cuddy.');
});

test('a bare https:// citation is skipped, not fatal', () => {
  const r = parseResponse(withSources([{url: 'https://', title: ''}, good]));
  assert.deepEqual(r.sources, [good]);
  assert.equal(r.boat.loa_ft, 23.3);
});

test('a space in the host is skipped with or without a title', () => {
  for (const title of ['', 'Has a title']) {
    const r = parseResponse(withSources([{url: 'https://exa mple.com/x', title}], [{url: 'https://exa mple.com/y', title}, good]));
    assert.deepEqual(urls(r), [good.url], `title ${JSON.stringify(title)}`);
  }
});

test('non-https and uppercase-scheme URLs stay rejected', () => {
  const bad = ['http://example.com', 'javascript:alert(1)', 'HTTPS://Example.com/a', 'ftp://example.com/x', 'https:example.com'];
  const r = parseResponse(withSources(bad.map(url => ({url, title: 't'})), [...bad.map(url => ({url, title: ''})), good]));
  assert.deepEqual(urls(r), [good.url]);
});

test('non-string URLs are ignored', () => {
  const r = parseResponse(withSources([{url: null, title: 'x'}, {url: 42, title: 'x'}, {title: 'x'}], [good]));
  assert.deepEqual(urls(r), [good.url]);
});

test('at most six unique sources in first-seen order, duplicates dropped', () => {
  const u = i => `https://site${i}.example/p`;
  const list = [u(1), u(2), u(1), u(3), u(4), u(2), u(5), u(6), u(7), u(8)].map(url => ({url, title: 'T'}));
  const r = parseResponse(withSources(list));
  assert.deepEqual(urls(r), [u(1), u(2), u(3), u(4), u(5), u(6)]);
});

test('malformed entries do not use up the six-source cap', () => {
  const u = i => `https://site${i}.example/p`;
  const list = [{url: 'https://', title: ''}, ...[1, 2, 3, 4, 5, 6].map(i => ({url: u(i), title: ''}))];
  assert.deepEqual(urls(parseResponse(withSources(list))), [1, 2, 3, 4, 5, 6].map(u));
});

test('an empty title falls back to the hostname', () => {
  const r = parseResponse(withSources([{url: 'https://www.parkerboats.net/a?b=1', title: ''}, {url: 'https://x.example:8443/p'}]));
  assert.deepEqual(r.sources, [{url: 'https://www.parkerboats.net/a?b=1', title: 'www.parkerboats.net'}, {url: 'https://x.example:8443/p', title: 'x.example'}]);
});

test('lookupBoat resolves the boat despite a malformed citation', async () => {
  const fetcher = async () => new Response(JSON.stringify(withSources([{url: 'https://', title: ''}, {url: 'https://exa mple.com/x'}, good])), {status: 200});
  const usage = {};
  const r = await lookupBoat('Parker 2320 SL', {apiKey: 'test', fetcher, usage});
  assert.equal(r.boat.loa_ft, 23.3);
  assert.deepEqual(r.sources, [good]);
  assert.equal(usage.turns, 1);
});

test('a payload whose only sources are malformed still parses with no sources', () => {
  const r = parseResponse(withSources([{url: 'https://', title: ''}], [{url: 'https://exa mple.com/x', title: ''}]));
  assert.deepEqual(r.sources, []);
  assert.equal(r.boat.name, 'Parker 2320 SL');
});
