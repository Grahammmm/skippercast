import assert from 'node:assert/strict';
import test from 'node:test';
import {lookupBoat, parseResponse} from '../server/boat-lookup.ts';

// Synthetic Messages API payloads only; no network.
const spec = '{"name":"Parker 2320 SL","loa_ft":23.3,"hull":"deep-v","confidence":"high","estimated":["displacement_lb"],"notes":"Cuddy."}';
const u = i => `https://site${i}.example/p`;
const src = i => ({url: u(i), title: `T${i}`});
const urls = r => r.sources.map(s => s.url);
const junk = [null, false, 0, 7, 'https://string.example/x', ['https://array.example/x'], undefined, true];
const payload = ({citations, results, blocks = []} = {}) => ({
  content: [
    {type: 'server_tool_use', id: 's1', name: 'web_search', input: {query: 'q'}},
    ...(results === undefined ? [] : [{type: 'web_search_tool_result', tool_use_id: 's1', content: results}]),
    ...blocks,
    {type: 'text', text: spec, ...(citations === undefined ? {} : {citations})},
  ],
  stop_reason: 'end_turn',
});
const answerOf = r => ({boat: r.boat, confidence: r.confidence, estimated: r.estimated, notes: r.notes});

test('citation_null_rows_preserve_neighbors', () => {
  const control = parseResponse(payload({citations: [src(1), src(2), src(3)]}));
  const mixed = parseResponse(payload({citations: [junk[0], src(1), junk[1], junk[2], src(2), junk[3], junk[4], junk[5], junk[6], junk[7], src(3), null]}));
  assert.deepEqual(mixed.sources, control.sources);
  assert.deepEqual(urls(mixed), [u(1), u(2), u(3)]);
  assert.ok(util_equal(answerOf(mixed), answerOf(control)), 'answer fields match the control');
  assert.equal(mixed.boat.loa_ft, 23.3);
  assert.equal(mixed.confidence, 'high');
  assert.deepEqual(mixed.estimated, ['displacement_lb']);
  assert.equal(mixed.notes, 'Cuddy.');
});

function util_equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

test('nonarray_citations_are_empty_not_fatal', () => {
  const containers = [{url: 'https://object.example/x', title: 'o'}, 'https://string.example/x', 5, true, false, null, undefined, {}];
  for (const bad of containers) {
    const r = parseResponse(payload({citations: bad, results: [src(1)]}));
    assert.deepEqual(urls(r), [u(1)], `container ${JSON.stringify(bad)}`);
    assert.equal(r.boat.loa_ft, 23.3);
  }
  // A malformed container on an earlier block does not hide a valid one on a later block.
  const early = {type: 'text', text: 'narration', citations: {url: u(9), title: 'x'}};
  assert.deepEqual(urls(parseResponse(payload({citations: [src(2)], blocks: [early]}))), [u(2)]);
  for (const empty of [[], null, undefined]) assert.deepEqual(parseResponse(payload({citations: empty})).sources, []);
});

test('six valid later sources still get six slots and a seventh is capped', () => {
  const rows = [...junk, ...[1, 2, 3, 4, 5, 6, 7].map(src)];
  assert.deepEqual(urls(parseResponse(payload({citations: rows}))), [1, 2, 3, 4, 5, 6].map(u));
  assert.deepEqual(urls(parseResponse(payload({results: rows}))), [1, 2, 3, 4, 5, 6].map(u));
});

test('search_result_null_rows_preserve_neighbors', () => {
  const results = [null, src(1), 'x', [src(9)], src(2), false, 3, src(1)];
  const citations = [src(2), undefined, src(3), {url: u(1), title: 'dup'}];
  const r = parseResponse(payload({results, citations}));
  // Results come first in block order; exact duplicates keep their first title.
  assert.deepEqual(r.sources, [src(1), src(2), src(3)]);
  assert.equal(r.boat.loa_ft, 23.3);
  assert.equal(r.notes, 'Cuddy.');
  // A malformed row never changes which text is the final answer.
  const narration = {type: 'text', text: '{"name":"Wrong","loa_ft":99}'};
  const withNarration = {content: [narration, ...payload({results, citations}).content], stop_reason: 'end_turn'};
  assert.equal(parseResponse(withNarration).boat.loa_ft, 23.3);
});

test('injected_lookup_survives_source_shapes', async () => {
  const body = payload({citations: [null, 'x', src(1), [src(2)]], results: [false, src(3), 4]});
  body.usage = {input_tokens: 111, output_tokens: 22, server_tool_use: {web_search_requests: 3}};
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw Error('global fetch must not be used'); };
  try {
    const usage = {};
    const fetcher = async () => new Response(JSON.stringify(body), {status: 200});
    const r = await lookupBoat('Parker 2320 SL', {apiKey: 'test-key', fetcher, usage});
    assert.equal(r.boat.loa_ft, 23.3);
    assert.deepEqual(urls(r), [u(3), u(1)]);
    assert.equal(usage.turns, 1);
    assert.equal(usage.input_tokens, 111);
    assert.equal(usage.output_tokens, 22);
    assert.equal(usage.web_search_requests, 3);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('required_answer_errors_still_fail', () => {
  const text = t => ({content: [{type: 'text', text: t, citations: [null, src(1)]}], stop_reason: 'end_turn'});
  assert.throws(() => parseResponse(text('no json here')), /no specification/);
  assert.throws(() => parseResponse(text('{not json}')), /unreadable specification/);
  assert.throws(() => parseResponse(text('{"name":"X","hull":"deep-v"}')), /could not find this boat/);
  assert.throws(() => parseResponse(text('{"name":"X","loa_ft":"big"}')), /could not find this boat/);
});
