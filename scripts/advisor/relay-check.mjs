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
//
// TA-C2: --twilio checks the Twilio account instead (port-to-Twilio runbook, step 5):
//   TWILIO_ACCOUNT_SID=AC... TWILIO_AUTH_TOKEN=... TWILIO_FROM=+1XXXXXXXXXX \
//   node scripts/advisor/relay-check.mjs --twilio --to +1XXXXXXXXXX
// It fetches the account (GET /2010-04-01/Accounts/<sid>.json), sends one SMS from
// TWILIO_FROM to --to (skip with --no-send) and prints the message sid. Never the token.

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

// ---- TA-C2: --twilio ---------------------------------------------------------------

const TWILIO_API = 'https://api.twilio.com/2010-04-01';

/** The Twilio account check and one test SMS; `log` prints a line. Returns {passed, results, sid}. */
export async function runTwilioChecks({env, args, fetcher = fetch, log = console.log}) {
  const results = [];
  const secrets = [env.TWILIO_AUTH_TOKEN];
  const record = (name, ok, detail) => { results.push({name, ok, detail}); log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ': ' + scrub(detail, secrets) : ''}`); return ok; };
  const need = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', ...(args.send ? ['TWILIO_FROM'] : [])];
  const missing = need.filter(k => !env[k]);
  if (missing.length) { record('environment', false, `missing ${missing.join(', ')}`); return {passed: false, results, sid: null}; }
  const sid = String(env.TWILIO_ACCOUNT_SID).trim();
  if (!/^AC[0-9a-f]{32}$/.test(sid)) { record('environment', false, 'TWILIO_ACCOUNT_SID must look like AC followed by 32 hex characters'); return {passed: false, results, sid: null}; }
  const from = args.send ? e164(env.TWILIO_FROM) : null, to = args.to ? e164(args.to) : null;
  if (args.send && !from) { record('environment', false, 'TWILIO_FROM must be a US number such as +18055550100'); return {passed: false, results, sid: null}; }
  if (args.send && !to) { record('environment', false, '--to must be a US number such as +18055550100 (or pass --no-send)'); return {passed: false, results, sid: null}; }
  record('environment', true, `account ${sid.slice(0, 6)}…${from ? `, from ${masked(from)}, to ${masked(to)}` : ''}`);

  const headers = {Authorization: 'Basic ' + Buffer.from(`${sid}:${String(env.TWILIO_AUTH_TOKEN).trim()}`).toString('base64'), Accept: 'application/json'};
  const call = async (path, form) => {
    const init = {method: form ? 'POST' : 'GET', headers: {...headers}, signal: AbortSignal.timeout(args.timeout)};
    if (form) { init.headers['Content-Type'] = 'application/x-www-form-urlencoded'; init.body = form.toString(); }
    const response = await fetcher(`${TWILIO_API}/Accounts/${sid}${path}`, init);
    let body = null;
    try { body = JSON.parse(await response.text()); } catch { body = null; }
    const code = body?.code ?? body?.error_code ?? null;
    const error = response.ok ? null : `HTTP ${response.status}${code ? ` (Twilio error ${code}${response.status === 401 ? ': check the sid and auth token' : ''})` : ''}`;
    return {ok: !error, status: response.status, body, error};
  };
  const attempt = async (name, fn) => { try { return await fn(); } catch (error) { record(name, false, error?.name === 'TimeoutError' ? 'timed out' : error?.message); return null; } };

  const account = await attempt('account', () => call('.json'));
  if (account) record('account', account.ok, account.ok ? `status ${account.body?.status ?? 'unknown'}${account.body?.type ? `, ${account.body.type}` : ''}` : account.error);
  if (!account?.ok) return {passed: false, results, sid: null};

  let messageSid = null;
  if (args.send) {
    const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    const sent = await attempt('send SMS', () => call('/Messages.json', new URLSearchParams({To: to, From: from, Body: `SkipperCast relay check (Twilio SMS) ${stamp} UTC`})));
    if (sent) {
      messageSid = typeof sent.body?.sid === 'string' ? sent.body.sid : null;
      record('send SMS', sent.ok && Boolean(messageSid), sent.ok ? (messageSid ? `accepted, sid ${messageSid}, status ${sent.body?.status ?? 'unknown'}; confirm it arrived on the phone` : 'no message sid in the response') : sent.error);
    }
  } else log('SKIP  send (--no-send)');

  const passed = results.every(r => r.ok);
  log('');
  log(`${passed ? 'PASS' : 'FAIL'}: ${results.filter(r => r.ok).length}/${results.length} checks passed.`);
  if (passed && args.send) log('Check the phone: one SMS from the advisor number should have arrived.');
  return {passed, results, sid: messageSid};
}

async function main() {
  let args;
  try { args = parseArgs(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exit(2); }
  if (args.help) { console.log('Usage: node scripts/advisor/relay-check.mjs [--twilio] --to +1XXXXXXXXXX [--no-send] [--timeout ms]\nReads BLUEBUBBLES_URL, BLUEBUBBLES_PASSWORD, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET from the environment;\nwith --twilio, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM instead.'); return; }
  const {passed} = await (args.twilio ? runTwilioChecks : runChecks)({env: process.env, args});
  process.exit(passed ? 0 : 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
