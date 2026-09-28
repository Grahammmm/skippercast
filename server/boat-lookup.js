// AI boat-spec lookup: a Claude model with web search finds the builder's
// specifications for a named boat and returns them as JSON for the person to
// confirm. Values are validated with the same rules as manual entry.
import {HULLS, LAYOUTS, normalizeBoat} from '../dist/boat-handling.js';

export const DEFAULT_MODEL = 'claude-sonnet-5';
const API = 'https://api.anthropic.com/v1/messages';

export const SYSTEM = `You identify recreational fishing and power boats and report their specifications.
Use web search to find the builder's specification sheet or a reputable boat test for the exact make, model and year given.
Reply with ONLY one JSON object, no prose, with these keys:
{"name": string (builder, model, and model years it applies to),
 "loa_ft": number (length overall, feet), "beam_ft": number, "dry_weight_lb": number, "displacement_lb": number or null (loaded, only if published),
 "deadrise_deg": number (at transom), "hull": one of ${JSON.stringify(Object.keys(HULLS))},
 "layout": one of ${JSON.stringify(Object.keys(LAYOUTS))},
 "cruise_kn": number (typical cruise speed with common power), "max_hp": number, "fuel_gal": number,
 "confidence": "high" | "medium" | "low", "estimated": [keys you inferred rather than found published],
 "notes": string (under 200 characters: which variant or years the numbers apply to, and any doubt)}
Convert units to feet, pounds, degrees, knots and US gallons. Use null for anything you cannot find or reasonably infer. Never invent a boat that does not exist; if the model is unclear, give your best match and set confidence to "low".`;

export function buildRequest(query, model = DEFAULT_MODEL) {
  return {model, max_tokens: 1500, system: SYSTEM,
    tools: [{type: 'web_search_20250305', name: 'web_search', max_uses: 4}],
    messages: [{role: 'user', content: `Boat: ${query}`}]};
}

export function validQuery(query) {
  if (typeof query !== 'string') return null;
  const q = query.replace(/\s+/g, ' ').trim();
  return q.length >= 3 && q.length <= 120 ? q : null;
}

/** Messages API response -> {boat, confidence, estimated, notes, sources}. */
export function parseResponse(data) {
  const blocks = Array.isArray(data?.content) ? data.content : [];
  // The answer is the text after the last search; earlier text is narration.
  let last = -1;
  blocks.forEach((b, i) => { if (b.type !== 'text') last = i; });
  const text = blocks.slice(last + 1).filter(b => b.type === 'text').map(b => b.text).join('');
  const start = text.indexOf('{'), end = text.lastIndexOf('}');
  if (start < 0 || end <= start) throw Error('lookup returned no specification');
  let raw;
  try { raw = JSON.parse(text.slice(start, end + 1)); } catch { throw Error('lookup returned unreadable specification'); }
  const boat = normalizeBoat(raw);
  if (!boat.loa_ft) throw Error('lookup could not find this boat');
  const sources = [];
  const add = (url, title) => {
    if (typeof url !== 'string' || !/^https:\/\//.test(url) || sources.some(s => s.url === url) || sources.length >= 6) return;
    sources.push({url: url.slice(0, 500), title: String(title || new URL(url).hostname).slice(0, 140)});
  };
  for (const b of blocks) {
    for (const c of b.citations || []) add(c.url, c.title);
    if (b.type === 'web_search_tool_result' && Array.isArray(b.content)) for (const r of b.content) add(r.url, r.title);
  }
  const estimated = Array.isArray(raw.estimated) ? raw.estimated.filter(k => typeof k === 'string' && k in boat).slice(0, 12) : [];
  return {boat, confidence: ['high', 'medium', 'low'].includes(raw.confidence) ? raw.confidence : 'low',
    estimated, notes: typeof raw.notes === 'string' ? raw.notes.slice(0, 300) : '', sources};
}

/** Call the Messages API. `fetcher` is injectable for tests. */
export async function lookupBoat(query, {apiKey, model, fetcher = fetch}) {
  const request = buildRequest(query, model || DEFAULT_MODEL);
  const all = [];
  for (let turn = 0; turn < 3; turn++) {
    const response = await fetcher(API, {method: 'POST', signal: AbortSignal.timeout(60000),
      headers: {'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
      body: JSON.stringify(request)});
    if (!response.ok) throw Error(`lookup service HTTP ${response.status}`);
    const data = await response.json();
    all.push(...(data.content || []));
    // A long search turn can pause; send the partial assistant turn back to continue.
    if (data.stop_reason !== 'pause_turn') return parseResponse({content: all});
    request.messages = [...request.messages, {role: 'assistant', content: data.content}];
  }
  throw Error('lookup did not finish');
}
