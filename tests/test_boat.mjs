import assert from 'node:assert/strict';
import test from 'node:test';
import {REFERENCE, boatFactors, describeFactors, normalizeBoat} from '../dist/boat-handling.js';
import {hourScores} from '../dist/morning-outlook.js';
import {buildRequest, lookupBoat, parseResponse, validQuery} from '../server/boat-lookup.js';

const rough = {wind: 12, gust: 16, sea: {height: 6}, chop: {height: 3, period: 5}, swell: {from: 300}, secondary: {height: 0, from: 200}};
const other = {wind: 12, gust: 16, sea: {height: 6}};

test('no boat and the reference boat keep the tuned thresholds exactly', () => {
  assert.deepEqual(boatFactors(null), {sea: 1, wind: 1, chopPeriod: 6, custom: false});
  const ref = boatFactors(REFERENCE);
  assert.equal(ref.sea, 1); assert.equal(ref.wind, 1); assert.equal(ref.chopPeriod, 6);
  assert.deepEqual(hourScores(rough, other, 'reef', 16, ref), hourScores(rough, other, 'reef', 16));
  assert.deepEqual(describeFactors(boatFactors(null)), {seas: 1.5, chop: 0.4, wind: 4, gust: 7, chopPeriod: 6});
});

test('bigger, heavier and softer-riding hulls tolerate more; small flat hulls less', () => {
  const big = boatFactors({loa_ft: 32, displacement_lb: 11000, deadrise_deg: 22, hull: 'deep-v', layout: 'pilothouse'});
  const skiff = boatFactors({loa_ft: 16, displacement_lb: 1200, deadrise_deg: 8, layout: 'skiff'});
  const cat = boatFactors({loa_ft: 23, displacement_lb: 4500, hull: 'catamaran', layout: 'walkaround'});
  assert.ok(big.sea > 1.3 && big.wind > 1.2);
  assert.ok(skiff.sea < 0.6 && skiff.wind < 0.8);
  assert.ok(cat.sea > 1);
  const score = f => hourScores(rough, other, 'reef', 16, f).conditions;
  assert.ok(score(big) > score(boatFactors(null)));
  assert.ok(score(skiff) < score(boatFactors(null)));
});

test('profiles are validated like any input', () => {
  const b = normalizeBoat({name: 'x'.repeat(200), loa_ft: 23, beam_ft: 40, dry_weight_lb: 4000, deadrise_deg: 21, hull: 'spaceship', cruise_kn: 999});
  assert.equal(b.name.length, 80);
  assert.equal(b.beam_ft, null);           // wider than it is long: rejected
  assert.equal(b.displacement_lb, 5200);  // 1.3 x dry weight
  assert.equal(b.hull, 'deep-v');          // inferred from deadrise
  assert.equal(b.cruise_kn, null);
  assert.equal(normalizeBoat({loa_ft: '24.5'}).loa_ft, 24.5);
});

const answer = {
  content: [
    {type: 'text', text: 'I will search for {the} spec sheet.'},
    {type: 'server_tool_use', id: 's1', name: 'web_search', input: {query: 'Parker 2320 SL specs'}},
    {type: 'web_search_tool_result', tool_use_id: 's1', content: [{type: 'web_search_result', url: 'https://www.parkerboats.net/2320sl', title: 'Parker 2320 SL'}]},
    {type: 'text', text: '{"name":"Parker 2320 SL (2016-2020)","loa_ft":23.3,"beam_ft":8.5,"dry_weight_lb":3800,"displacement_lb":null,"deadrise_deg":20,',
      citations: [{type: 'web_search_result_location', url: 'https://www.parkerboats.net/2320sl', title: 'Parker 2320 SL'}]},
    {type: 'text', text: '"hull":"deep-v","layout":"walkaround","cruise_kn":28,"max_hp":250,"fuel_gal":125,"confidence":"high","estimated":["displacement_lb"],"notes":"Walkaround cuddy."}'},
  ],
  stop_reason: 'end_turn',
};

test('AI answers are parsed from the text after the last search and validated', () => {
  const r = parseResponse(answer);
  assert.equal(r.boat.loa_ft, 23.3);
  assert.equal(r.boat.displacement_lb, 4940);
  assert.equal(r.confidence, 'high');
  assert.deepEqual(r.estimated, ['displacement_lb']);
  assert.deepEqual(r.sources, [{url: 'https://www.parkerboats.net/2320sl', title: 'Parker 2320 SL'}]);
  assert.throws(() => parseResponse({content: [{type: 'text', text: 'Sorry, no idea.'}]}), /no specification/);
  assert.throws(() => parseResponse({content: [{type: 'text', text: '{"name":"x","loa_ft":500}'}]}), /could not find/);
});

test('lookup requests web search and continues paused turns', async () => {
  assert.equal(buildRequest('Parker').tools[0].type, 'web_search_20250305');
  assert.equal(validQuery('  2019   Parker 2320 '), '2019 Parker 2320');
  assert.equal(validQuery('x'), null);
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push(JSON.parse(init.body));
    const first = calls.length === 1;
    return new Response(JSON.stringify(first ? {content: answer.content.slice(0, 3), stop_reason: 'pause_turn'}
      : {content: answer.content.slice(3), stop_reason: 'end_turn'}), {status: 200});
  };
  const r = await lookupBoat('Parker 2320 SL', {apiKey: 'k', fetcher});
  assert.equal(calls.length, 2);
  assert.equal(calls[1].messages.at(-1).role, 'assistant');
  assert.equal(r.boat.hull, 'deep-v');
  await assert.rejects(lookupBoat('x', {apiKey: 'k', fetcher: async () => new Response('no', {status: 500})}), /HTTP 500/);
});

test('lookup usage adds billed tokens and searches across paused turns', async () => {
  let n = 0;
  const fetcher = async () => {
    n++;
    return new Response(JSON.stringify(n === 1
      ? {content: answer.content.slice(0, 3), stop_reason: 'pause_turn', usage: {input_tokens: 1000, output_tokens: 50, server_tool_use: {web_search_requests: 2}}}
      : {content: answer.content.slice(3), stop_reason: 'end_turn', usage: {input_tokens: 3000, output_tokens: 400, cache_read_input_tokens: 500, server_tool_use: {web_search_requests: 1}}}), {status: 200});
  };
  const usage = {};
  await lookupBoat('Parker 2320 SL', {apiKey: 'k', model: 'm-1', fetcher, usage});
  assert.deepEqual(usage, {model: 'm-1', turns: 2, input_tokens: 4500, output_tokens: 450, web_search_requests: 3});
  const failed = {};
  await assert.rejects(lookupBoat('x', {apiKey: 'k', fetcher: async () => new Response('no', {status: 500}), usage: failed}));
  assert.equal(failed.turns, 1);
});

test('trip alert defaults start from the saved boat; the reference boat keeps 8 / 12 kt and 3 ft', async () => {
  const { tripDefaults, tripBoat } = await import('../dist/trip-alerts.js');
  const { boatFactors } = await import('../dist/boat-handling.js');
  assert.deepEqual(tripDefaults(boatFactors(null)), { wind: 8, gust: 12, sea: 3 });
  const skiff = boatFactors({ loa_ft: 16, hull: 'flat', layout: 'skiff' });
  const d = tripDefaults(skiff);
  assert.ok(d.sea < 3 && d.wind <= 8 && d.gust >= d.wind);
  assert.equal(tripBoat(boatFactors(null), null), null, 'no saved boat sends nothing');
  const sent = tripBoat(skiff, { name: 'Skiff' });
  assert.deepEqual(Object.keys(sent).sort(), ['chop_period', 'name', 'sea', 'wind']);
  assert.ok(sent.sea >= 0.45 && sent.sea <= 2.6 && sent.wind >= 0.6 && sent.wind <= 1.8);
});
