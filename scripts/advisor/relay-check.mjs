#!/usr/bin/env node
// Relay check for the Text Advisor's Mac relay (docs/operations/runbooks/advisor-relay-setup.md).
// The owner runs it from a laptop after setting up the Mac mini, BlueBubbles and
// the Cloudflare Tunnel. It talks to BlueBubbles exactly as the Worker does
// (password query, Cloudflare Access service-token headers) and:
//   1. pings the server through the tunnel;
//   2. prints the server info (BlueBubbles version, macOS, Private API loaded);
//   3. checks whether --to is reachable on iMessage;
//   4. sends one test iMessage and one test SMS to --to (skip with --no-send);
//   5. prints a pass/fail summary and exits 1 if anything failed.
// No secret is printed: not the password, the Access secret or the relay URL's query.
//
//   BLUEBUBBLES_URL=https://relay.skippercast.com BLUEBUBBLES_PASSWORD=... \
//   CF_ACCESS_CLIENT_ID=... CF_ACCESS_CLIENT_SECRET=... \
//   node scripts/advisor/relay-check.mjs --to +1XXXXXXXXXX
//
// Options: --to <E.164 US number> (required unless --no-send), --no-send, --timeout <ms> (default 15000).
// --twilio is reserved for the port-to-Twilio runbook (TA-C7) and is refused here.

import {pathToFileURL} from 'node:url';

const TIMEOUT_DEFAULT = 15000;

export function parseArgs(argv) {
  const out = {to: null, send: true, timeout: TIMEOUT_DEFAULT, twilio: false, help: false};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--to') out.to = argv[++i] ?? null;
    else if (a.startsWith('--to=')) out.to = a.slice(5);
    else if (a === '--no-send') out.send = false;
    else if (a === '--timeout') out.timeout = Number(argv[++i]);
    else if (a === '--twilio') out.twilio = true;
    else if (a === '--help' || a === '-h') out.help = true;
    else throw Error(`unknown argument ${a}`);
  }
  return out;
}

/** "+1 (805) 555-0100" -> "+18055550100" for a NANP number, else null. */
export function e164(input) {
  if (typeof input !== 'string' || !/^\+?[\d\s().-]+$/.test(input.trim())) return null;
  const digits = input.replace(/\D/g, '');
  const national = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits.length === 10 ? digits : null;
  return national && /^[2-9]\d{2}[2-9]\d{6}$/.test(national) ? '+1' + national : null;
}

/** The number with all but the last four digits hidden, for the printed summary. */
export const masked = number => number ? number.slice(0, 2) + '•'.repeat(Math.max(0, number.length - 6)) + number.slice(-4) : '';

/** Any secret value in `text` replaced, so an error message can be printed safely. */
export function scrub(text, secrets) {
  let out = String(text ?? '');
  for (const s of secrets) if (s && s.length >= 4) out = out.split(s).join('[secret]');
  return out.replace(/password=[^&\s]*/gi, 'password=[secret]').slice(0, 300);
}

export function relayClient({url, password, accessId, accessSecret, timeout = TIMEOUT_DEFAULT, fetcher = fetch}) {
  const base = String(url ?? '').trim().replace(/\/+$/, '');
  const headers = {Accept: 'application/json'};
  if (accessId && accessSecret) { headers['CF-Access-Client-Id'] = accessId; headers['CF-Access-Client-Secret'] = accessSecret; }
  return async function call(path, {method = 'GET', json, query = {}} = {}) {
    const u = new URL(base + '/api/v1/' + path);
    for (const [k, v] of Object.entries(query)) u.searchParams.set(k, v);
    u.searchParams.set('password', password);
    const init = {method, headers: {...headers}, signal: AbortSignal.timeout(timeout)};
    if (json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(json); }
    const response = await fetcher(u.toString(), init);
    let body = null;
    const text = await response.text();
    try { body = JSON.parse(text); } catch { body = null; }
    // Cloudflare Access answers a missing or wrong service token with its HTML login page (302/403).
    const access = !body && /cloudflareaccess|cf-access|Access denied/i.test(text);
    const error = !response.ok ? `HTTP ${response.status}${access ? ' (Cloudflare Access rejected the service token)' : ''}`
      : !body ? 'response is not JSON (is the tunnel pointing at BlueBubbles?)'
      : body.error ? `relay error: ${typeof body.error === 'object' ? body.error.message ?? body.error.type ?? 'error' : body.error}`
      : (typeof body.status === 'number' && body.status >= 300) ? `relay status ${body.status}: ${body.message ?? ''}` : null;
    return {ok: !error, status: response.status, body, error};
  };
}

/** Run every check; `log` prints a line. Returns {passed, results}. */
export async function runChecks({env, args, fetcher = fetch, log = console.log}) {
  const results = [];
  const secrets = [env.BLUEBUBBLES_PASSWORD, env.CF_ACCESS_CLIENT_SECRET, env.CF_ACCESS_CLIENT_ID];
  const record = (name, ok, detail) => { results.push({name, ok, detail}); log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ': ' + scrub(detail, secrets) : ''}`); return ok; };
  const missing = ['BLUEBUBBLES_URL', 'BLUEBUBBLES_PASSWORD', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'].filter(k => !env[k]);
  if (missing.length) { record('environment', false, `missing ${missing.join(', ')}`); return {passed: false, results}; }
  let host = '';
  try { const u = new URL(env.BLUEBUBBLES_URL); host = u.host; if (u.protocol !== 'https:') throw Error('not https'); }
  catch { record('environment', false, 'BLUEBUBBLES_URL must be an https URL, e.g. https://relay.skippercast.com'); return {passed: false, results}; }
  const to = args.to ? e164(args.to) : null;
  if (args.send && !to) { record('environment', false, '--to must be a US number such as +18055550100 (or pass --no-send)'); return {passed: false, results}; }
  record('environment', true, `relay ${host}${to ? `, test number ${masked(to)}` : ''}`);

  const call = relayClient({url: env.BLUEBUBBLES_URL, password: env.BLUEBUBBLES_PASSWORD, accessId: env.CF_ACCESS_CLIENT_ID, accessSecret: env.CF_ACCESS_CLIENT_SECRET, timeout: args.timeout, fetcher});
  const attempt = async (name, fn) => { try { return await fn(); } catch (error) { record(name, false, error?.name === 'TimeoutError' ? 'timed out' : error?.message); return null; } };

  const ping = await attempt('ping', () => call('ping'));
  if (ping) record('ping', ping.ok, ping.ok ? `${ping.body?.message ?? 'ok'}` : ping.error);
  if (!ping?.ok) return {passed: false, results};

  const info = await attempt('server info', () => call('server/info'));
  if (info) {
    const d = info.body?.data ?? {};
    record('server info', info.ok, info.ok ? `BlueBubbles ${d.server_version ?? '?'}, macOS ${d.os_version ?? '?'}, Private API ${d.private_api ? 'loaded' : 'not loaded'}${typeof d.helper_connected === 'boolean' ? `, helper ${d.helper_connected ? 'connected' : 'not connected'}` : ''}` : info.error);
    if (info.ok && !d.private_api) log('      (typing indicators and read receipts stay off; leave BLUEBUBBLES_PRIVATE_API unset)');
  }

  if (to) {
    const avail = await attempt('iMessage availability', () => call('handle/availability/imessage', {query: {address: to}}));
    if (avail) record('iMessage availability', avail.ok, avail.ok ? `${masked(to)} ${avail.body?.data?.available ? 'is' : 'is not'} reachable on iMessage` : avail.error);
  }

  if (args.send && to) {
    const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    for (const [name, chatGuid] of [['send iMessage', `iMessage;-;${to}`], ['send SMS', `SMS;-;${to}`]]) {
      const kind = name.endsWith('SMS') ? 'SMS' : 'iMessage';
      const sent = await attempt(name, () => call('message/text', {method: 'POST', json: {chatGuid, tempGuid: `relay-check-${kind}-${Date.now()}`, message: `SkipperCast relay check (${kind}) ${stamp} UTC`, method: 'apple-script'}}));
      if (sent) record(name, sent.ok, sent.ok ? `accepted${sent.body?.data?.guid ? ' (message guid received)' : ''}; confirm it arrived on the phone` : sent.error);
    }
  } else log('SKIP  sends (--no-send)');

  const passed = results.every(r => r.ok);
  log('');
  log(`${passed ? 'PASS' : 'FAIL'}: ${results.filter(r => r.ok).length}/${results.length} checks passed.`);
  if (passed && args.send) log('Check the phone: one blue (iMessage) and one green (SMS) text should have arrived.');
  return {passed, results};
}

async function main() {
  let args;
  try { args = parseArgs(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exit(2); }
  if (args.help) { console.log('Usage: node scripts/advisor/relay-check.mjs --to +1XXXXXXXXXX [--no-send] [--timeout ms]\nReads BLUEBUBBLES_URL, BLUEBUBBLES_PASSWORD, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET from the environment.'); return; }
  if (args.twilio) { console.error('--twilio is not available yet (the Twilio adapter lands in TA-C2; see the port-to-Twilio runbook).'); process.exit(2); }
  const {passed} = await runChecks({env: process.env, args});
  process.exit(passed ? 0 : 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
