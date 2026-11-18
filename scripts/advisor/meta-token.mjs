#!/usr/bin/env node
// The owner's Meta token step (docs/plans/text-advisor/09-social.md § Setup,
// step 4; TA-O4). The Facebook-Login route: the Instagram professional account
// is linked to the SkipperCast Page, and the Page token from /me/accounts
// (minted from a long-lived user token) does not expire and serves both the
// Page and the Instagram account, so there is no refresh job.
//
//   node scripts/advisor/meta-token.mjs --token-file <new-private-file> [--page <page-id>] [--redirect-uri <url>]
//
// 1. Prints the Facebook Login dialog URL with the scopes below; open it signed
//    in as the owner and approve.
// 2. Paste the address the browser lands on (or just its `code`).
// 3. The code becomes a short-lived user token, then a long-lived one
//    (fb_exchange_token); GET /me/accounts lists the Pages with their tokens.
// 4. Prints the Page id and the linked Instagram user id, checks
//    the account can publish (content_publishing_limit) and, when Meta exposes it,
//    that its account_type is BUSINESS (Stories publishing needs Business,
//    not Creator), and says whether the Page token expires (debug_token).
//
// The Page token goes only to the new owner-only file (0600). Choose a path
// in private local storage outside the checkout. Import it into META_PAGE_TOKEN
// without displaying it, then remove the temporary file. The app id and secret
// are read from the environment, never from argv (shell history). Every Graph
// call carries appsecret_proof (server/advisor/social/meta.ts graph()).
import {createInterface} from 'node:readline/promises';
import {randomBytes} from 'node:crypto';
import {open, lstat, unlink} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const root = new URL('../../', import.meta.url);
const meta = await import(new URL('server/advisor/social/meta.ts', root).href);

export const SCOPES = ['pages_show_list', 'pages_read_engagement', 'pages_manage_posts', 'pages_manage_metadata', 'pages_messaging',
  'instagram_basic', 'instagram_content_publish', 'instagram_manage_comments', 'instagram_manage_messages', 'instagram_manage_insights', 'business_management'];
/** Meta's own landing page for login flows without a web server ("Manually build a login flow"). Add it to the app's Valid OAuth Redirect URIs. */
export const DEFAULT_REDIRECT = 'https://www.facebook.com/connect/login_success.html';
const USAGE = 'usage: node scripts/advisor/meta-token.mjs --token-file <new-file-in-private-local-storage> [--page <page-id>] [--redirect-uri <https url>]';
const ID = /^\d{1,32}$/;

/** argv -> {page, redirectUri, tokenFile}; requires an explicit file destination. */
export function parseArgs(argv) {
  const out = {page: null, redirectUri: DEFAULT_REDIRECT, tokenFile: null};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], v = argv[i + 1];
    if (a === '--page' && v && ID.test(v)) { out.page = v; i++; }
    else if (a === '--redirect-uri' && v && /^https:\/\/[^\s]+$/.test(v)) { out.redirectUri = v; i++; }
    else if (a === '--token-file' && !out.tokenFile && v && !v.startsWith('-')) { out.tokenFile = v; i++; }
    else throw Error(`unexpected or invalid argument\n${USAGE}`);
  }
  if (!out.tokenFile) throw Error(`--token-file is required\n${USAGE}`);
  return out;
}

/** The Facebook Login dialog URL (response_type=code, the state checked on return). */
export function dialogUrl(appId, redirectUri, state) {
  const q = new URLSearchParams({client_id: appId, redirect_uri: redirectUri, state, response_type: 'code', scope: SCOPES.join(',')});
  return `https://www.facebook.com/${meta.GRAPH_VERSION}/dialog/oauth?${q}`;
}

/** The authorization code from the pasted landing address (state must match) or a bare code. */
export function parseCode(input, state) {
  const text = String(input ?? '').trim();
  if (/^https:\/\//.test(text)) {
    const url = new URL(text), params = new URLSearchParams(url.search || url.hash.slice(1));
    if (params.get('error')) throw Error(`login was not approved: ${params.get('error_reason') || params.get('error')}`);
    if (params.get('state') !== state) throw Error('the state in that address does not match this run; start again');
    const code = params.get('code');
    if (!code) throw Error('no code in that address');
    return code;
  }
  if (!/^[\w.#-]{20,2000}$/.test(text)) throw Error('that does not look like a code or the landing address');
  return text.replace(/#_=_$/, '');
}

async function getJson(fetcher, url) {
  const r = await fetcher(url, {method: 'GET', signal: AbortSignal.timeout(meta.TIMEOUT_MS)});
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = body?.error ?? {};
    throw Error(`Meta answered HTTP ${r.status} (code ${e.code ?? '?'}${e.error_subcode ? `, subcode ${e.error_subcode}` : ''}${e.fbtrace_id ? `, fbtrace_id ${e.fbtrace_id}` : ''})`);
  }
  return body;
}

/** The code -> a short-lived user token -> a long-lived user token. The app secret goes as client_secret (the token endpoint takes no proof). */
export async function longLivedUserToken({appId, appSecret, redirectUri, code, fetcher = fetch}) {
  const short = await getJson(fetcher, `${meta.GRAPH_BASE}/oauth/access_token?${new URLSearchParams({client_id: appId, redirect_uri: redirectUri, client_secret: appSecret, code})}`);
  if (typeof short.access_token !== 'string') throw Error('no user token in the code exchange');
  const long = await getJson(fetcher, `${meta.GRAPH_BASE}/oauth/access_token?${new URLSearchParams({grant_type: 'fb_exchange_token', client_id: appId, client_secret: appSecret, fb_exchange_token: short.access_token})}`);
  if (typeof long.access_token !== 'string') throw Error('no long-lived user token in the exchange');
  return long.access_token;
}

/** GET /me/accounts with the user token: each Page's id, name, token and linked Instagram account. */
export async function pagesOf(cfg) {
  const r = await meta.graph(cfg, 'GET', '/me/accounts', {fields: 'id,name,access_token,instagram_business_account{id,username}', limit: 100});
  return (Array.isArray(r.data) ? r.data : []).filter(p => ID.test(String(p?.id)) && typeof p.access_token === 'string').map(p => ({
    id: p.id, name: typeof p.name === 'string' ? p.name : '', token: p.access_token,
    instagram: p.instagram_business_account?.id && ID.test(p.instagram_business_account.id) ? {id: p.instagram_business_account.id, username: p.instagram_business_account.username ?? null} : null,
  }));
}

/**
 * The linked Instagram account's checks with the Page token: whether it is
 * BUSINESS (account_type, when Meta returns that field on this route), and
 * whether content_publishing_limit answers (instagram_content_publish granted).
 */
export async function checkInstagram(cfg, igUserId) {
  const out = {username: null, account_type: null, business: null, quota: null};
  try {
    const r = await meta.graph({...cfg, attempts: 1}, 'GET', `/${igUserId}`, {fields: 'id,username,account_type'});
    out.username = r.username ?? null;
    out.account_type = typeof r.account_type === 'string' ? r.account_type : null;
  } catch {
    const r = await meta.graph(cfg, 'GET', `/${igUserId}`, {fields: 'id,username'});
    out.username = r.username ?? null;
  }
  if (out.account_type) out.business = out.account_type.toUpperCase() === 'BUSINESS';
  out.quota = await meta.igPublishingLimit(cfg, igUserId);
  return out;
}

/** debug_token with the app access token: the Page token's expiry (0 = never). */
export async function tokenExpiry({appId, appSecret, token, fetcher = fetch}) {
  const r = await getJson(fetcher, `${meta.GRAPH_BASE}/debug_token?${new URLSearchParams({input_token: token, access_token: `${appId}|${appSecret}`})}`);
  return typeof r?.data?.expires_at === 'number' ? r.data.expires_at : null;
}

export async function savePageToken(path, token) {
  let file;
  try {
    // Exclusive creation refuses existing files, devices, pipes and symlinks. A refusal means the
    // file at `path` is not ours: it is never touched, and nothing below runs.
    file = await open(path, 'wx', 0o600);
  } catch {
    throw Error('Could not save the Page token. --token-file must name a new owner-only file in private local storage. The file there, if any, was not created by this run and was left untouched.');
  }
  try {
    const info = await file.stat();
    if (!info.isFile() || (info.mode & 0o777) !== 0o600 || info.uid !== process.geteuid()) throw Error();
    await file.writeFile(token);
  } catch {
    // Ownership is established by the open descriptor: remove the path only while it is still that very file.
    try {
      const mine = await file.stat(), now = await lstat(path);
      if (now.dev === mine.dev && now.ino === mine.ino) await unlink(path);
    } catch { /* leave it for manual inspection */ }
    throw Error('Could not save the Page token. This run created the file and removed it; start again with a new --token-file name.');
  } finally { await file.close(); }
}

export async function main(argv, {env = process.env, fetcher = fetch, ask, log = console.log} = {}) {
  const args = parseArgs(argv);
  if (typeof process.geteuid !== 'function') throw Error('A POSIX filesystem with owner-only file permissions is required.');
  const appId = String(env.META_APP_ID ?? '').trim(), appSecret = String(env.META_APP_SECRET ?? '').trim();
  if (!ID.test(appId) || !appSecret) throw Error(`set META_APP_ID and META_APP_SECRET in the environment\n${USAGE}`);
  const state = randomBytes(12).toString('hex');
  log('1. Open this address signed in as the owner, and approve every permission:');
  log(`   ${dialogUrl(appId, args.redirectUri, state)}`);
  log(`2. The browser lands on ${new URL(args.redirectUri).origin}${new URL(args.redirectUri).pathname}?code=...`);
  const prompt = ask ?? (async q => { const rl = createInterface({input: process.stdin, output: process.stdout}); try { return await rl.question(q); } finally { rl.close(); } });
  const code = parseCode(await prompt('   Paste that whole address here: '), state);
  const userToken = await longLivedUserToken({appId, appSecret, redirectUri: args.redirectUri, code, fetcher});
  const pages = await pagesOf({token: userToken, appSecret, fetcher});
  if (!pages.length) throw Error('no Pages came back: was the Page selected in the login dialog?');
  const page = args.page ? pages.find(p => p.id === args.page) : pages.length === 1 ? pages[0] : null;
  if (!page) {
    log('More than one Page (or not the one asked for). Run again with --page <id>:');
    for (const p of pages) log(`   ${p.id}  ${p.name}${p.instagram ? `  (Instagram @${p.instagram.username ?? p.instagram.id})` : ''}`);
    return 1;
  }
  if (!page.instagram) throw Error(`the Page "${page.name}" has no linked Instagram professional account (Page settings > Linked accounts)`);
  const cfg = {token: page.token, appSecret, fetcher};
  const ig = await checkInstagram(cfg, page.instagram.id);
  const expires = await tokenExpiry({appId, appSecret, token: page.token, fetcher}).catch(() => null);
  log('');
  log(`Page token: ${expires === 0 ? 'does not expire' : expires ? `expires ${new Date(expires * 1000).toISOString()} (expected never: was the user token long-lived?)` : 'expiry unknown'}`);
  log(`Publishing quota: ${ig.quota.quota_usage} of ${ig.quota.quota_total ?? '?'} posts used in the last 24 hours.`);
  if (ig.business === true) log('Instagram account type: BUSINESS.');
  else if (ig.business === false) { log(`Instagram account type is ${ig.account_type}, not BUSINESS: Stories publishing needs a Business account (Instagram app > Settings > Account type).`); return 1; }
  else log('Instagram account type: Meta did not return it on this route. Confirm in the Instagram app (Settings > Account type and tools) that it is Business, not Creator.');
  await savePageToken(args.tokenFile, page.token);
  log('');
  log('3. Put these in the repository secrets (Settings > Secrets and variables > Actions):');
  log(`   META_PAGE_ID      ${page.id}   (${page.name})`);
  log('   META_PAGE_TOKEN   Import from the file given to --token-file without displaying it, then remove the file.');
  log(`   META_IG_USER_ID   ${page.instagram.id}   (@${ig.username ?? page.instagram.username ?? '?'})`);
  log('   META_APP_ID and META_APP_SECRET as used here, and META_VERIFY_TOKEN: any long random string (the webhook handshake, TA-S6).');
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  try { process.exitCode = await main(process.argv.slice(2)); }
  catch (e) { console.error(String(e?.message ?? e)); process.exitCode = 1; }
}
