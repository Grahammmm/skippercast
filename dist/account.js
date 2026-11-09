// Account sheet: create a SkipperCast account or sign in with a passkey, add or
// remove passkeys, sign out, delete the account. Opens from the Guide entry or
// any #account link. Passkey ceremonies use the vendored @simplewebauthn/browser
// (globalThis.SimpleWebAuthnBrowser), which loadPasskeyLibrary() adds once, with SRI,
// when a ceremony starts: app.html does not load it for map page views.
const RETURN_KEY = 'skippercast-account-return';
import {coordinateFormat, formatCoordinate, formatCoordinates, parseCoordinate} from './coordinates.js';
import catalog from '../catalog/app/strings.json' with {type: 'json'};

// SC0922-14: this module is imported on demand and cannot call web/i18n.ts t(), so openAccount({lang, strings}) receives the
// resolved language and the finished `account.*` catalogue values (web/account-copy.ts). Without them every string is the English
// value in the same catalogue, so there is one English table.
const DEFAULTS = catalog.strings;
const holes = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]))].sort().join(',');
/**
 * One dialog's copy reader: `t(id, vars)` fills `{name}` variables (plain text; callers escape at HTML sinks). An injected value is used
 * only for a known id, as a nonempty string with the same placeholders as the English; anything else reads the English. An unknown
 * id throws. An unknown `lang` reads English. Nothing is shared between readers, so a deferred handler keeps its own dialog's language.
 */
export function createCopy(options) {
  const lang = options?.lang === 'es' ? 'es' : 'en';
  const given = options?.strings && typeof options.strings === 'object' ? options.strings : {};
  const t = (id, vars = {}) => {
    if (!Object.hasOwn(DEFAULTS, id)) throw Error('unknown account string ' + id);
    const base = DEFAULTS[id].en, own = Object.hasOwn(given, id) ? given[id] : undefined;
    const text = typeof own === 'string' && own !== '' && holes(own) === holes(base) ? own : base;
    return text.replace(/\{(\w+)\}/g, (whole, name) => Object.hasOwn(vars, name) ? String(vars[name]) : whole);
  };
  t.lang = lang;
  return t;
}
const DEFAULT_COPY = createCopy();
/** A reader as given to an exported helper: a reader itself, options to make one from, or nothing (English). */
const asCopy = copy => typeof copy === 'function' ? copy : copy ? createCopy(copy) : DEFAULT_COPY;

// The position format chosen in the account menu, read at each draw; blocked or unreadable storage means decimal degrees.
function chosenFormat() {
  try { return coordinateFormat(globalThis.localStorage?.getItem('skippercast-coordinates-v1')); } catch { return 'dd'; }
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const day = (iso, lang = 'en') => iso ? new Date(iso).toLocaleDateString(lang === 'es' ? 'es' : undefined, {year: 'numeric', month: 'short', day: 'numeric'}) : '';

async function api(path, {method = 'GET', body, includeResponse = false} = {}) {
  const response = await fetch('/api/' + path, {method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20000)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = Error(data.error || DEFAULTS['account.err.apiFallback'].en); error.status = response.status; if (!data.error) error.apiFallback = true; throw error; }
  return includeResponse ? {data, response} : data;
}

/**
 * One page of the owner's catch log (SC0922-03): the newest page when `cursor` is null, else the page after that cursor.
 * The body stays {entries}; the server says whether older rows exist, and where they start, in two response headers.
 * An answer without a usable entries list or without the has-more header is refused, never read as a finished list.
 */
export async function readLogPage(cursor = null) {
  const {data, response} = await api(cursor ? 'catch-log?cursor=' + encodeURIComponent(cursor) : 'catch-log', {includeResponse: true});
  const more = response.headers.get('X-SC-Catch-Log-Has-More'), next = response.headers.get('X-SC-Catch-Log-Next-Cursor');
  if (!Array.isArray(data?.entries) || (more !== 'true' && more !== 'false') || (more === 'true') !== Boolean(next)) throw Error('The catch log answer was incomplete');
  return {entries: data.entries, nextCursor: more === 'true' ? next : null, hasMore: more === 'true'};
}

/**
 * The link for the server's `signIn` path. "/#account" becomes "#account" so
 * following it is an in-page hash change: a full load of "/" would drop the
 * current region and view. Anything not same-site is refused ('').
 */
export function signInHref(signIn) {
  if (typeof signIn !== 'string' || !signIn.startsWith('/') || signIn.startsWith('//')) return '';
  return signIn.startsWith('/#') ? signIn.slice(1) : signIn;
}

/** Plain-language message for a failed passkey ceremony. */
export function passkeyMessage(error, copy) {
  const t = asCopy(copy), name = error?.name, code = error?.code;
  if (code === 'PASSKEY_LIBRARY_UNAVAILABLE') return t('account.err.library');
  if (code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED' || name === 'InvalidStateError') return t('account.err.registered');
  if (name === 'NotAllowedError' || name === 'AbortError') return t('account.err.cancelled');
  if (name === 'SecurityError') return t('account.err.insecure');
  if (error?.status === 429) return t('account.err.rate');
  // Spanish: this module's own fallback is translated; any other message comes from the server or the browser and is shown as given.
  if (t.lang !== 'en' && error?.apiFallback) return t('account.err.apiFallback');
  if (!error?.message) return t('account.err.generic');
  return t.lang === 'en' ? error.message.charAt(0).toUpperCase() + error.message.slice(1) + '.' : t('account.err.detail', {detail: error.message});
}

/**
 * An in-page confirmation under `anchor` (not window.confirm, which blocks the
 * page and automation). Resolves true for the confirm button, false for Cancel
 * or Escape. Only one is shown per anchor.
 */
export function confirmInPage(anchor, message, confirmLabel, copy) {
  const t = asCopy(copy);
  anchor.parentElement.querySelector(':scope > .account-confirm')?.remove();
  const box = document.createElement('div');
  box.className = 'account-confirm';
  box.setAttribute('role', 'alertdialog');
  box.innerHTML = `<p>${esc(message)}</p><div class="home-port-actions"><button type="button" data-confirm="no">${esc(t('account.cancel'))}</button><button type="button" data-confirm="yes" class="account-destructive">${esc(confirmLabel)}</button></div>`;
  const id = 'account-confirm-' + Math.random().toString(36).slice(2);
  box.querySelector('p').id = id; box.setAttribute('aria-labelledby', id);
  anchor.after(box);
  anchor.disabled = true;
  box.querySelector('[data-confirm="no"]').focus();
  return new Promise(resolve => {
    const done = answer => { box.remove(); anchor.disabled = false; if (!answer) anchor.focus(); resolve(answer); };
    box.addEventListener('click', event => { const b = event.target.closest('[data-confirm]'); if (b) done(b.dataset.confirm === 'yes'); });
    box.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); done(false); } });
  });
}

const webauthn = () => globalThis.SimpleWebAuthnBrowser;

/** The vendored passkey library: same-origin absolute path (so /map and hash links resolve it alike), pinned by SRI to the bytes in scripts/web-vendor-sha256.json. */
export const PASSKEY_LIBRARY = {src: '/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js', integrity: 'sha256-KbsGmbRbw5o1DZkqE7/BpNQNiVMTkFgeH1fxFCxuIh0='};
export const PASSKEY_UNAVAILABLE = DEFAULTS['account.err.library'].en;
const PASSKEY_LOAD_MS = 20000;
const isComplete = lib => ['browserSupportsWebAuthn', 'startAuthentication', 'startRegistration'].every(name => typeof lib?.[name] === 'function');

let passkeyLoad = null;   // the one shared attempt: pending, or resolved once the library has loaded
/**
 * Resolves with the passkey library, adding its script the first time a ceremony needs it. Callers that overlap share one
 * attempt; a loaded library is reused for the page's life. A script error (an SRI mismatch included), a missing or incomplete
 * global, a refused insert or no answer in 20 s rejects with PASSKEY_UNAVAILABLE and clears only that attempt, so the next
 * deliberate try loads afresh and a late event from the old attempt cannot settle it. The script has no crossorigin attribute:
 * a same-origin request, never with credentials mode changed or another origin.
 */
export function loadPasskeyLibrary() {
  if (isComplete(webauthn())) return Promise.resolve(webauthn());
  if (passkeyLoad) return passkeyLoad.promise;
  const attempt = {promise: null};
  attempt.promise = new Promise((resolve, reject) => {
    passkeyLoad = attempt;
    let script = null, timer = null, settled = false;
    const settle = ok => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      script?.removeEventListener('load', onLoad); script?.removeEventListener('error', onError);
      if (ok) { resolve(webauthn()); return; }
      try { script?.remove(); } catch { /* already gone */ }
      if (passkeyLoad === attempt) passkeyLoad = null;
      reject(Object.assign(Error(PASSKEY_UNAVAILABLE), {code: 'PASSKEY_LIBRARY_UNAVAILABLE'}));
    };
    const onLoad = () => settle(isComplete(webauthn()));
    const onError = () => settle(false);
    try {
      script = document.createElement('script');
      script.src = PASSKEY_LIBRARY.src; script.integrity = PASSKEY_LIBRARY.integrity;
      script.addEventListener('load', onLoad); script.addEventListener('error', onError);
      timer = setTimeout(() => settle(false), PASSKEY_LOAD_MS);
      document.head.append(script);
    } catch { settle(false); }
  });
  return attempt.promise;
}

function finish() {
  // Reload so trip alerts, feedback and AI lookup pick up the new session,
  // returning to the screen that sent the person here.
  let back = '#guide';
  try { back = sessionStorage.getItem(RETURN_KEY) || back; sessionStorage.removeItem(RETURN_KEY); } catch { /* storage blocked */ }
  history.replaceState(null, '', location.pathname + location.search + back);
  location.reload();
}

const OUTCOME_WORDS = {fish: 'account.outcome.fish', blank: 'account.outcome.blank', unknown: 'account.outcome.unknown'};
/**
 * One catch-log entry as list HTML. Every stored string is escaped, so markup in a note shows as plain text.
 * `trips` are the person's saved trips: an entry whose trip_id is exactly one of them also shows that trip's saved date
 * (a stored calendar date, never parsed as an instant); a null, orphan or deleted association adds nothing.
 */
export function logItemHTML(row, trips = [], format = chosenFormat(), copy) {
  const t = asCopy(copy);
  const trip = row.trip_id ? (Array.isArray(trips) ? trips : []).find(x => x?.id === row.trip_id) : null;
  const outcome = Object.hasOwn(OUTCOME_WORDS, row.outcome) ? t(OUTCOME_WORDS[row.outcome]) : row.outcome;   // an unknown stored outcome shows as stored
  const fish = row.outcome === 'fish' ? (Number(row.count) === 1 ? t('account.log.fish.one', {n: row.count}) : t('account.log.fish.other', {n: row.count})) : '';
  const bits = [day(row.started_at, t.lang), outcome, fish, row.species, row.method,
    row.lat != null && row.lon != null ? formatCoordinates(row.lat, row.lon, format) : '', trip?.date ? t('account.log.tripDate', {date: trip.date}) : ''].filter(Boolean);
  return `<li><span>${bits.map(esc).join(' · ')}</span>${row.note ? `<p class="account-hint">${esc(row.note)}</p>` : ''}
    <button type="button" data-edit-log="${esc(row.id)}">${esc(t('account.log.edit'))}</button>
    <button type="button" data-remove-log="${esc(row.id)}">${esc(t('account.remove'))}</button></li>`;
}

// SC2037-10: the person's own counts over the entries loaded so far. Never a rate, a score or a comparison; nothing is sent.
const speciesKey = value => typeof value === 'string' ? value.trim().toLocaleLowerCase('en') : '';
/** Counts of the given rows by outcome, the fish total, and the five species logged most often (trimmed, grouped without case, first-seen spelling). */
export function logCounts(rows) {
  const out = {entries: 0, fish: 0, fishTotal: 0, blank: 0, unknown: 0, species: []}, seen = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    out.entries++;
    if (row.outcome === 'fish') { out.fish++; out.fishTotal += Number(row.count) || 0; } else if (row.outcome === 'blank') out.blank++; else if (row.outcome === 'unknown') out.unknown++;
    const key = speciesKey(row.species);
    if (!key) continue;
    const found = seen.get(key); if (found) found.count++; else seen.set(key, {name: row.species.trim(), count: 1, key});
  }
  out.species = [...seen.values()].sort((a, b) => b.count - a.count || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)).slice(0, 5).map(({name, count}) => ({name, count}));
  return out;
}
/** Rows whose outcome equals `outcome` and whose trimmed, case-folded species equals the folded `species`; an empty filter is any. */
export function filterLog(rows, {outcome = '', species = ''} = {}) {
  const want = speciesKey(species);
  return (Array.isArray(rows) ? rows : []).filter(row => (!outcome || row.outcome === outcome) && (!want || speciesKey(row.species) === want));
}
/** The one-line summary of `counts`; `filtered` and `more` (older pages still unread) change only the opening words. */
export function logCountsText(counts, {filtered = false, more = false} = {}, copy) {
  const t = asCopy(copy), n = counts.entries, one = n === 1;
  const head = filtered
    ? (more ? (one ? t('account.counts.loadedMatch.one', {n}) : t('account.counts.loadedMatch.other', {n})) : (one ? t('account.counts.match.one', {n}) : t('account.counts.match.other', {n})))
    : (more ? (one ? t('account.counts.loaded.one', {n}) : t('account.counts.loaded.other', {n})) : (one ? t('account.counts.plain.one', {n}) : t('account.counts.plain.other', {n})));
  const top = counts.species.length ? t('account.counts.top', {list: counts.species.map(s => `${s.name} ${s.count}`).join(', ')}) : '';
  return t('account.counts.body', {head, fish: counts.fish, fishTotal: counts.fishTotal, blank: counts.blank, unknown: counts.unknown, top, more: more ? t('account.counts.more') : ''});
}
export const LOG_NO_MATCH = DEFAULTS['account.log.noMatch'].en;
/**
 * Draw the list, the counts line and the species choices for the loaded `entries` under `view` ({outcome, species}).
 * `els` are {list, counts, species}. The counts are over the filtered rows. A chosen species that no longer appears still filters.
 */
export function drawLogView(els, {entries, trips = [], view, more = false, copy}) {
  const t = asCopy(copy), all = Array.isArray(entries) ? entries : [], shown = filterLog(all, view);
  const options = new Map();
  for (const row of all) { const key = speciesKey(row.species); if (key && !options.has(key)) options.set(key, row.species.trim()); }
  const chosen = speciesKey(view.species);
  if (chosen && !options.has(chosen)) options.set(chosen, view.species.trim());
  els.species.innerHTML = `<option value="">${esc(t('account.any'))}</option>` + [...options].map(([key, name]) => `<option value="${esc(key)}">${esc(name)}</option>`).join('');
  els.species.value = chosen;
  els.list.innerHTML = shown.map(row => logItemHTML(row, trips, undefined, t)).join('');
  const filtered = Boolean(view.outcome || chosen);
  els.counts.hidden = !all.length;
  els.counts.textContent = !all.length ? '' : shown.length ? logCountsText(logCounts(shown), {filtered, more}, t) : t('account.log.noMatch');
}

/** A typed position the form refused: a plain Error carrying `.field` ('lat' or 'lon') and the parser's reason. */
function fieldError(field, message) { const error = Error(message); error.field = field; return error; }
/** Reads one typed latitude or longitude box into decimal degrees; a refusal names its box and carries the parser's reason. */
function readPosition(text, field) {
  const r = parseCoordinate(String(text ?? ''), field === 'lat' ? 'latitude' : 'longitude');
  if (r.error !== undefined) throw fieldError(field, r.error);
  return r.value;
}
const blankText = v => String(v ?? '').trim() === '';

/** One latitude or longitude box: a text input with an example in the chosen format as its hint and an empty error line beside it. */
export function positionFieldHTML(prefix, field, label, note = '', format = chosenFormat(), copy) {
  const t = asCopy(copy), latitude = field === 'lat', id = `${prefix}-${field}`;
  const example = latitude ? formatCoordinate(35.3576, 'latitude', format) : formatCoordinate(-120.8578, 'longitude', format);
  return `<label for="${id}">${label}${note ? ` <span class="account-hint">${note}</span>` : ''}</label><input id="${id}" type="text" inputmode="text" autocomplete="off" aria-describedby="${id}-hint ${id}-error" /><span class="account-hint" id="${id}-hint">${esc(t('account.pos.example', {example}))}</span><p class="account-hint" role="alert" id="${id}-error" hidden></p>`;
}

/**
 * Runs a position form's submit: clears each box's error, builds the body, and when a box was refused shows the reason beside
 * that box, marks it invalid, focuses it and sends nothing. `$` finds an element by selector; `send` posts the built body.
 */
export async function submitPositionForm($, prefix, build, send) {
  for (const f of ['lat', 'lon']) {
    const err = $(`#${prefix}-${f}-error`), box = $(`#${prefix}-${f}`);
    if (err) { err.textContent = ''; err.hidden = true; }
    box?.removeAttribute?.('aria-invalid');
  }
  let body;
  try { body = build(); } catch (error) {
    if (error?.field !== 'lat' && error?.field !== 'lon') throw error;
    const err = $(`#${prefix}-${error.field}-error`), box = $(`#${prefix}-${error.field}`);
    if (err) { err.textContent = error.message; err.hidden = false; }
    box?.setAttribute?.('aria-invalid', 'true');
    box?.focus?.();
    return false;
  }
  await send(body);
  return true;
}

// SC1607-05: "Use my position". One fresh fix is asked for only when the button is pressed; it fills the two boxes and nothing is saved.
export const POSITION_OPTIONS = Object.freeze({enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
/** A device fix as the two box values (six decimals, no negative zero) and the accuracy in whole metres rounded up; null when anything is unusable or rounds onto a pole or the antimeridian. */
export function positionFromFix(fix) {
  const c = fix?.coords, num = v => typeof v === 'number' && Number.isFinite(v);
  if (!c || !num(c.latitude) || !num(c.longitude) || !num(c.accuracy) || c.accuracy < 0) return null;
  const lat = Number(c.latitude.toFixed(6)), lon = Number(c.longitude.toFixed(6));
  if (!(lat > -90 && lat < 90 && lon > -180 && lon < 180)) return null;
  const text = n => (n === 0 ? '0.000000' : n.toFixed(6));
  return {lat: text(lat), lon: text(lon), accuracy: Math.ceil(c.accuracy)};
}
/** The words for a refused or failed request: code 1 or a SecurityError is permission, code 3 a time-out, anything else the device. */
export function positionFailure(error) { return error?.code === 1 || error?.name === 'SecurityError' ? 'denied' : error?.code === 3 ? 'timeout' : 'unavailable'; }
const FAILURE_WORDS = {denied: 'account.position.denied', timeout: 'account.position.timeout', unavailable: 'account.position.unavailable'};
/** The button, hint and status line under a form's two position boxes. */
export function positionControlsHTML(prefix, copy) {
  const t = asCopy(copy);
  return `<div class="home-port-actions"><button type="button" id="${prefix}-use-position" aria-describedby="${prefix}-position-hint ${prefix}-position-status">${esc(t('account.position.use'))}</button></div><p class="account-hint" id="${prefix}-position-hint">${esc(t('account.position.hint'))}</p><p class="account-hint" role="status" aria-live="polite" id="${prefix}-position-status"></p>`;
}
/**
 * Wires one form's "Use my position" button. `$` finds an element; `alive()` says the dialog and render are still current;
 * `blocked()` (optional) refuses a request; `after()` (optional) runs when controls are given back. One attempt at a time: while it
 * is pending the button, both boxes and Save are disabled (their earlier state returns afterwards). `invalidate()` drops a pending
 * attempt, so a late answer changes nothing. Returns {invalidate, pending}.
 */
export function createPositionControl({$, prefix, copy, alive = () => true, blocked = () => false, after = () => {}, geolocation = () => globalThis.navigator?.geolocation}) {
  const t = asCopy(copy), button = $(`#${prefix}-use-position`), say = text => { const el = $(`#${prefix}-position-status`); if (el) el.textContent = text; };
  let attempt = null;
  for (const f of ['lat', 'lon']) { const box = $(`#${prefix}-${f}`); box?.setAttribute('aria-describedby', `${box.getAttribute('aria-describedby') ?? ''} ${prefix}-position-status`.trim()); }
  const parts = () => [button, $(`#${prefix}-lat`), $(`#${prefix}-lon`), $(`#${prefix}-save`)];
  const release = a => { for (const [el, was] of a.saved) if (el) el.disabled = was; after(); };
  const invalidate = () => { const a = attempt; attempt = null; if (a) release(a); say(''); };
  const fill = pos => {
    for (const [f, value] of [['lat', pos.lat], ['lon', pos.lon]]) {
      const box = $(`#${prefix}-${f}`), err = $(`#${prefix}-${f}-error`);
      box.value = value; box.removeAttribute('aria-invalid'); if (err) { err.textContent = ''; err.hidden = true; }
      box.dispatchEvent(new Event('input', {bubbles: true}));
    }
  };
  button.addEventListener('click', () => {
    if (attempt || blocked() || !alive()) return;
    const geo = geolocation();
    if (!geo || typeof geo.getCurrentPosition !== 'function') { say(t('account.position.unsupported')); return; }
    const a = {saved: parts().map(el => [el, el?.disabled])};
    const settle = (words, apply) => {
      if (attempt !== a) return;
      attempt = null;
      if (!alive() || !button.isConnected) return;
      release(a);
      apply?.(); say(words());
    };
    attempt = a; for (const el of parts()) if (el) el.disabled = true; say(t('account.position.finding'));
    try {
      geo.getCurrentPosition(fix => {
        const pos = positionFromFix(fix);
        if (pos) settle(() => t('account.position.filled', {accuracy: pos.accuracy}), () => fill(pos));
        else settle(() => t('account.position.unavailable'));
      }, error => settle(() => t(FAILURE_WORDS[positionFailure(error)])), POSITION_OPTIONS);
    } catch (error) { settle(() => t(FAILURE_WORDS[positionFailure(error)])); }
  });
  return {invalidate, get pending() { return attempt !== null; }};
}

/** The form's fields as the log route's body: a blank sends no count, a position is sent only when both boxes are filled; typed positions are read in decimal degrees, degrees and decimal minutes, or degrees minutes seconds. */
export function logBody(f, copy) {
  const num = v => (String(v ?? '').trim() === '' ? null : Number(v));
  const hasLat = !blankText(f.lat), hasLon = !blankText(f.lon);
  if (hasLat !== hasLon) throw fieldError(hasLat ? 'lon' : 'lat', asCopy(copy)('account.log.both'));
  const lat = hasLat ? readPosition(f.lat, 'lat') : null, lon = hasLon ? readPosition(f.lon, 'lon') : null;
  const started = f.started ? new Date(f.started) : new Date();
  const out = {started_at: started.toISOString(), outcome: f.outcome, method: f.method || null, species: f.species || null, note: f.note || null, lat, lon};
  if (f.ended) { const ended = new Date(f.ended); if (Number.isNaN(ended.getTime())) throw localError(asCopy(copy)('account.log.invalidTime')); out.ended_at = ended.toISOString(); }
  if (f.outcome === 'fish') out.count = num(f.count);
  if (f.trip_id !== undefined && f.trip_id !== null && f.trip_id !== '') out.trip_id = f.trip_id;   // the chosen id exactly; the route checks it is the caller's own
  return out;
}

/** A refusal made in the page before anything is sent: its message is already the person's own-language words. */
function localError(message) { const error = Error(message); error.local = true; return error; }
const pad = (n, width = 2) => String(n).padStart(width, '0');
/** An instant as a datetime-local value in the browser's own time, with seconds and milliseconds when present (so no precision is lost). */
export function localInputValue(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '';
  const ms = d.getMilliseconds();
  return `${pad(d.getFullYear(), 4)}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${ms ? '.' + pad(ms, 3) : ''}`;
}
/**
 * SC1137-11: the whole edit form as the PATCH body. Every mutable field is sent, so a cleared box really clears: a blank or unknown
 * outcome sends count 0, no trip sends trip_id null, an empty end sends ended_at null, empty boxes send lat and lon null, blank text sends null.
 * `original` is {started_at, ended_at, startedShown, endedShown, lat, lon, latShown, lonShown}: a box still showing the value it was
 * filled with sends the stored value itself (exact instant, subsecond precision, repeated-hour side, exact coordinate), never a re-parse.
 * A half-entered position is sent as the number and null it is, so the server names the refusal.
 */
export function logEditBody(f, original = {}, copy) {
  const t = asCopy(copy), num = v => (String(v ?? '').trim() === '' ? null : Number(v));
  const instant = (value, stored, shown, required) => {
    if (blankText(value)) { if (required) throw localError(t('account.log.invalidTime')); return null; }
    if (stored && value === shown) return stored;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) throw localError(t('account.log.invalidTime'));
    return d.toISOString();
  };
  const position = (value, field) => blankText(value) ? null : (original[field] != null && value === original[field + 'Shown'] ? original[field] : readPosition(value, field));
  const started_at = instant(f.started, original.started_at, original.startedShown, true), ended_at = instant(f.ended, original.ended_at, original.endedShown, false);
  return {started_at, ended_at, outcome: f.outcome, count: f.outcome === 'fish' ? num(f.count) : 0, species: f.species || null, method: f.method || null,
    trip_id: f.trip || null, lat: position(f.lat, 'lat'), lon: position(f.lon, 'lon'), note: f.note || null};
}
/** The stored entries in the log's own order: newest start first, ties by id. */
export const sortLogEntries = rows => rows.sort((a, b) => (a.started_at < b.started_at ? 1 : a.started_at > b.started_at ? -1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
// Older-page rows join the loaded ones (ids already loaded or removed are skipped) and the whole set is put back in the log's order,
// so a row edited to start before the cursor still sorts among the older dates that arrive after it.
export const mergeOlderLogEntries = (rows, page, gone = new Set()) => {
  const seen = new Set(rows.map(row => row.id));
  for (const row of page || []) if (!seen.has(row?.id) && !gone.has(row?.id)) { seen.add(row?.id); rows.push(row); }
  return sortLogEntries(rows);
};

/** A saved trip's choice label: its stored date as written, then the area (the active region's point name when known, else "region / point"). */
export function logTripLabel(trip, region) {
  const known = region && region.id === trip?.region ? region.forecast_points?.find(p => p.id === trip.point)?.name : '';
  return `${trip?.date} · ${known || `${trip?.region} / ${trip?.point}`}`;
}

/** The Trip choices after "No trip": one option per saved trip, in the order given, value the exact id, label escaped. */
export function logTripOptionsHTML(trips, region) {
  return (Array.isArray(trips) ? trips : []).map(trip => `<option value="${esc(trip.id)}">${esc(logTripLabel(trip, region))}</option>`).join('');
}
const noTrip = t => `<option value="">${esc(t('account.log.noTrip'))}</option>`;

const logFormHTML = t => `<h2 class="account-subhead">${esc(t('account.log.head'))}</h2>
    <p class="home-port-fine">${esc(t('account.log.fine'))}</p>
    <form id="log-form" autocomplete="off">
      <p class="account-hint" id="log-editing" role="status" hidden>${esc(t('account.log.editing'))}</p>
      <label for="log-started">${esc(t('account.log.when'))}</label><input id="log-started" type="datetime-local" step="any" />
      <label for="log-ended">${esc(t('account.log.ended'))}</label><input id="log-ended" type="datetime-local" step="any" />
      <label for="log-outcome">${esc(t('account.log.what'))}</label><select id="log-outcome"><option value="blank">${esc(t('account.outcome.blank'))}</option><option value="fish">${esc(t('account.outcome.fish'))}</option><option value="unknown">${esc(t('account.outcome.unknown'))}</option></select>
      <label for="log-count">${esc(t('account.log.count'))}</label><input id="log-count" type="number" min="1" max="9999" step="1" />
      <label for="log-species">${esc(t('account.log.species'))}</label><input id="log-species" type="text" maxlength="60" />
      <label for="log-method">${esc(t('account.log.method'))}</label><input id="log-method" type="text" maxlength="40" />
      <label for="log-trip">${esc(t('account.log.trip'))} <span class="account-hint">${esc(t('account.optional'))}</span></label><select id="log-trip">${noTrip(t)}</select>
      ${positionFieldHTML('log', 'lat', esc(t('account.log.lat')), esc(t('account.optional.private')), chosenFormat(), t)}
      ${positionFieldHTML('log', 'lon', esc(t('account.log.lon')), esc(t('account.optional.private')), chosenFormat(), t)}
      ${positionControlsHTML('log', t)}
      <label for="log-note">${esc(t('account.log.note'))}</label><input id="log-note" type="text" maxlength="1000" />
      <div class="home-port-actions"><button type="submit" id="log-save">${esc(t('account.log.save'))}</button><button type="button" id="log-cancel" hidden>${esc(t('account.cancel'))}</button></div>
    </form>
    <div class="home-port-actions"><label for="log-filter-outcome">${esc(t('account.log.filter'))}</label><select id="log-filter-outcome"><option value="">${esc(t('account.any'))}</option><option value="fish">${esc(t('account.outcome.fish'))}</option><option value="blank">${esc(t('account.outcome.blank'))}</option><option value="unknown">${esc(t('account.outcome.unknown'))}</option></select>
      <label for="log-filter-species">${esc(t('account.log.filterSpecies'))}</label><select id="log-filter-species"><option value="">${esc(t('account.any'))}</option></select></div>
    <p class="account-hint" id="log-counts" role="status" hidden></p>
    <ul class="account-passkeys" id="log-list"></ul>
    <p class="account-hint" id="log-status" role="status"></p>
    <div class="home-port-actions"><button type="button" id="log-retry" hidden>${esc(t('account.log.retry'))}</button><button type="button" id="log-older" hidden>${esc(t('account.log.older'))}</button></div>`;

/** One saved spot as list HTML. Name, note and verdict are escaped, so markup in them shows as plain text. */
export function spotItemHTML(spot, verdict, format = chosenFormat(), copy) {
  const t = asCopy(copy);
  const name = String(spot.name ?? '').replace(/[\u0000-\u001f\ufffe\uffff]/g, '').trim() || t('account.spots.unnamed');
  return `<li data-spot-row="${esc(spot.id)}"><span>${esc(name)} · ${esc(formatCoordinates(spot.lat, spot.lon, format))}</span>${verdict?.text ? `<p class="account-hint">${esc(verdict.text)}</p>` : ''}${spot.note ? `<p class="account-hint">${esc(spot.note)}</p>` : ''}
    <button type="button" data-edit-spot="${esc(spot.id)}">${esc(t('account.spotEdit.edit'))}</button> <button type="button" data-remove-spot="${esc(spot.id)}">${esc(t('account.remove'))}</button></li>`;
}

/**
 * SC1137-09: the edit form that replaces one spot's row. The position is shown as plain text (a different position is a new
 * spot) and the current protected-area reading stays. The name and note are filled by `fillSpotEdit` with .value, so their
 * bytes are exact; nothing here is submitted but those two.
 */
export function spotEditHTML(spot, verdict, format = chosenFormat(), copy) {
  const t = asCopy(copy), id = esc(spot.id);
  return `<li data-spot-row="${id}" data-spot-editing><form class="spot-edit" autocomplete="off" aria-label="${esc(t('account.spotEdit.title'))}">
    <label for="spot-edit-name">${esc(t('account.name'))}</label><input id="spot-edit-name" name="name" type="text" maxlength="80" />
    <p class="account-hint">${esc(t('account.log.lat'))} / ${esc(t('account.log.lon'))}: ${esc(formatCoordinates(spot.lat, spot.lon, format))}</p>${verdict?.text ? `<p class="account-hint">${esc(verdict.text)}</p>` : ''}
    <p class="home-port-fine">${esc(t('account.spotEdit.positionHelp'))}</p>
    <label for="spot-edit-note">${esc(t('account.spots.note'))}</label><textarea id="spot-edit-note" name="note"></textarea>
    <p class="home-port-feedback" data-edit-status role="status"></p>
    <div class="home-port-actions"><button type="submit" data-edit-save>${esc(t('account.spotEdit.save'))}</button><button type="button" data-edit-cancel>${esc(t('account.cancel'))}</button></div></form></li>`;
}

/** The stored name and note into the edit form exactly as saved (not the cleaned display name). */
export function fillSpotEdit(form, spot) {
  form.elements.name.value = spot.name ?? '';
  form.elements.note.value = spot.note ?? '';
}

/** The edit request's body: only the two editable fields, never trimmed here and never a position (the route refuses one). */
export function spotEditBody(f) {
  return {name: f.name ?? '', note: f.note ?? null};
}

/** The form's fields as the spots route's body. A position is always required; a blank or unreadable box is refused here with the parser's reason. */
export function spotBody(f) {
  return {name: f.name ?? '', lat: readPosition(f.lat, 'lat'), lon: readPosition(f.lon, 'lon'), note: f.note || null};
}

// SC0022-04: the reading for a spot the protected-area screen could not check.

/** Each spot's reading from the shared screen (dist/geo-screen.js `screenPlace`, BF-closures-everywhere): excluded (boundary named), unavailable (not checked), or clear (no text). */
export async function spotVerdicts(spots, screen, copy) {
  const t = asCopy(copy), {screenPlace, placeRefused} = await import('./geo-screen.js'), {protectedHitReading} = await import('./trip-export.js');
  return spots.map(s => {
    const v = screenPlace(screen, {latitude: s.lat, longitude: s.lon});
    if (!v.screened) return {status: 'unavailable', text: t('account.spots.unchecked')};
    if (!placeRefused(v)) return {status: 'clear', text: ''};
    // Spanish picks its sentence from the structured `inside`, never by matching the English reading.
    const reading = t.lang === 'es' ? t(v.inside ? 'account.spots.inside' : 'account.spots.margin') : protectedHitReading({inside: v.inside, reef: false});
    return {status: 'excluded', text: t('account.spots.excluded', {reading, name: v.name ? v.name + '.' : ''}).replace(/\s+/g, ' ')};
  });
}

/**
 * The saved spots as one GPX file through the planner's own export path (dist/trip-export.js `buildExport`, so gpx.js
 * names are cleaned and made unique by its one serialiser). A spot inside or near a protected area is left out and named;
 * with the screen stale or missing nothing is exported. The file must pass the same GPX check, with the screen, that the planner runs.
 */
export async function exportSpots(spots, screen, region, now = new Date(), copy) {
  const t = asCopy(copy), {buildExport} = await import('./trip-export.js'), {checkGpx} = await import('../web/gpx-check.ts');
  if (!spots.length) throw Error(t('account.exp.none'));
  const verdicts = await spotVerdicts(spots, screen, t);
  if (verdicts.some(v => v.status === 'unavailable')) throw Error(t('account.exp.unavailable'));
  const held = spots.filter((s, i) => verdicts[i].status !== 'clear'), clear = spots.filter((s, i) => verdicts[i].status === 'clear');
  if (!clear.length) throw Error(t('account.exp.allHeld'));
  const points = clear.map(s => ({id: 'user:' + s.id, name: s.name.trim() ? s.name : 'Waypoint', category: 'other', latitude: s.lat, longitude: s.lon}));
  const out = buildExport({atlas: {targets: [], areas: [], drifts: []}, screen, ids: points.map(p => p.id), region, title: 'SkipperCast saved spots', now, userWaypoints: points});
  const check = checkGpx(out.gpx, {waypoints: clear.length}, screen);
  if (!check.ok) throw Error(t('account.exp.failed', {problem: check.problems[0]}));
  return {gpx: out.gpx, exported: clear.length, withheld: held.length};
}

// The Spanish text adds one paragraph that the English does not carry: private notes never reach the GPX (the English sentence above already says so).
const spotFormHTML = t => `<h2 class="account-subhead">${esc(t('account.spots.head'))}</h2>
    <p class="home-port-fine">${esc(t('account.spots.fine'))}</p>${t.lang === 'es' ? `<p class="home-port-fine">${esc(t('account.spots.notesGpx'))}</p>` : ''}
    <form id="spot-form" autocomplete="off">
      <label for="spot-name">${esc(t('account.name'))}</label><input id="spot-name" type="text" maxlength="80" />
      ${positionFieldHTML('spot', 'lat', esc(t('account.log.lat')), '', chosenFormat(), t)}
      ${positionFieldHTML('spot', 'lon', esc(t('account.log.lon')), '', chosenFormat(), t)}
      ${positionControlsHTML('spot', t)}
      <label for="spot-note">${esc(t('account.spots.note'))}</label><input id="spot-note" type="text" maxlength="1000" />
      <div class="home-port-actions"><button type="submit" id="spot-save">${esc(t('account.spots.save'))}</button><button type="button" id="spot-export">${esc(t('account.spots.export'))}</button></div>
    </form>
    <ul class="account-passkeys" id="spot-list"></ul>`;

function signedOutHTML(t) {
  return `<h1 id="account-title">${esc(t('account.out.title'))}</h1>
    <p class="home-port-intro">${esc(t('account.out.intro'))}</p>
    <label for="account-name">${esc(t('account.name'))} <span class="account-hint">${esc(t('account.name.optional'))}</span></label>
    <input id="account-name" type="text" maxlength="60" autocomplete="username webauthn" placeholder="${esc(t('account.name.placeholder'))}" />
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-create" class="account-primary">${esc(t('account.create'))}</button><button type="button" id="account-signin">${esc(t('account.signin'))}</button></div>
    <p class="home-port-fine">${esc(t('account.out.fine'))}</p>`;
}

function signedInHTML(session, passkeys, t) {
  const name = session.user?.display_name;
  return `<h1 id="account-title">${esc(name ? t('account.in.titleNamed', {name}) : t('account.in.title'))}</h1>
    <p class="home-port-intro">${esc(t('account.in.intro'))}</p>
    <h2 class="account-subhead">${esc(t('account.passkeys.head'))}</h2>
    <ul class="account-passkeys">${passkeys.map(p => `<li><span>${esc(t('account.passkeys.added', {date: day(p.created_at, t.lang)}))}${p.last_used_at ? esc(t('account.passkeys.lastUsed', {date: day(p.last_used_at, t.lang)})) : ''}</span>
      <button type="button" data-remove-passkey="${esc(p.id)}"${passkeys.length < 2 ? ` disabled title="${esc(t('account.passkeys.removeTitle'))}"` : ''}>${esc(t('account.remove'))}</button></li>`).join('')}</ul>
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-add">${esc(t('account.add'))}</button><button type="button" id="account-signout">${esc(t('account.signout'))}</button></div>
    ${logFormHTML(t)}
    ${spotFormHTML(t)}
    <details class="account-danger"><summary>${esc(t('account.del.head'))}</summary>
      <p>${esc(t('account.del.body'))}</p>
      <button type="button" id="account-delete">${esc(t('account.del.button'))}</button></details>`;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
/** The enabled, visible focusable elements inside `root`, in DOM order; a closed <details> hides all but its summary. */
export function dialogFocusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(el => {
    if (el.disabled) return false;
    for (let node = el; node && node !== root; node = node.parentElement) {
      if (node.hasAttribute?.('hidden')) return false;
      const parent = node.parentElement;
      if (parent && parent.tagName === 'DETAILS' && !parent.open && node.tagName !== 'SUMMARY') return false;
    }
    return true;
  });
}
/** Keeps Tab and Shift+Tab inside `root`: wraps at either end, or pulls focus back in from outside. True when it moved focus. */
export function keepFocusIn(root, event, active) {
  if (event.key !== 'Tab') return false;
  const items = dialogFocusables(root);
  if (!items.length) {
    event.preventDefault();
    const title = root.querySelector('#account-title');
    title?.focus?.();
    return true;
  }
  const first = items[0], last = items[items.length - 1], inside = items.includes(active);
  if (event.shiftKey && (active === first || !inside)) { event.preventDefault(); last.focus(); return true; }
  if (!event.shiftKey && (active === last || !inside)) { event.preventDefault(); first.focus(); return true; }
  return false;
}

let open = null;
/** Opens the dialog. `options` is {lang, strings} from web/account-copy.ts, read once here: this dialog keeps them for its life. */
export async function openAccount(options = {}) {
  if (open) return;
  const t = createCopy(options);
  const previous = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim account-scrim';
  scrim.innerHTML = `<section class="home-port-card account-card" role="dialog" aria-modal="true" aria-labelledby="account-title">
    <div class="home-port-kicker">${esc(t('account.kicker'))}</div><div id="account-body"><h1 id="account-title">${esc(t('account.title'))}</h1><p role="status">${esc(t('account.checking'))}</p></div>
    <button type="button" class="home-port-close" aria-label="${esc(t('account.close'))}">×</button></section>`;
  document.body.append(scrim);
  document.body.classList.add('choosing-home-port');
  const $ = sel => scrim.querySelector(sel), body = $('#account-body');
  // F-23: focus moves into the card now, onto its title, and again after a repaint replaces the title, unless focus
  // is on a field inside the card (the person may be typing).
  const focusTitle = () => { const title = $('#account-title'); if (title) { title.tabIndex = -1; title.focus(); } };
  const paint = html => {
    const active = document.activeElement;
    const inField = active && active !== body && active !== document.body && body.contains(active);
    body.innerHTML = html;
    if (!inField) focusTitle();
  };
  focusTitle();
  const status = message => { const el = $('#account-status'); if (el) el.textContent = message; };
  const self = open = {close};   // this dialog; a close or a newer dialog replaces it

  function close() {
    try { webauthn()?.WebAuthnAbortService?.cancelCeremony(); } catch { /* nothing pending */ }
    scrim.remove(); document.body.classList.remove('choosing-home-port'); open = null;
    if (location.hash === '#account') {
      let back = '#guide';
      try { back = sessionStorage.getItem(RETURN_KEY) || back; sessionStorage.removeItem(RETURN_KEY); } catch { /* storage blocked */ }
      history.replaceState(null, '', location.pathname + location.search + back);
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    }
    previous?.focus?.();
  }
  $('.home-port-close').addEventListener('click', close);
  scrim.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    else keepFocusIn($('.account-card'), event, document.activeElement);
  });
  scrim.addEventListener('click', event => { if (event.target === scrim) close(); });

  let session;
  try { session = await api('session'); }
  catch { paint(`<h1 id="account-title">${esc(t('account.title'))}</h1><p class="home-port-intro">${esc(t('account.offline'))}</p>`); return; }
  if (!session.signIn) { paint(`<h1 id="account-title">${esc(t('account.title'))}</h1><p class="home-port-intro">${esc(t('account.disabled'))}</p>`); return; }

  if (!session.signedIn) {
    paint(signedOutHTML(t));
    const buttons = [$('#account-create'), $('#account-signin')];
    const busy = on => buttons.forEach(b => { b.disabled = on; });
    // Without the native API there is nothing to load: say so now. Otherwise the library loads when a ceremony starts
    // (a tap on Create or Sign in, or the optional autofill below), never because the dialog is merely open signed in.
    if (typeof globalThis.PublicKeyCredential !== 'function') { busy(true); status(t('account.status.unsupported')); return; }
    // #597: once the person taps Create or Sign in, or this dialog is closed or replaced, a passkey-autofill request
    // still waiting for the library, its support check or its options must not start: its ceremony would abort theirs
    // through the shared abort service.
    let manual = false;
    const stale = autofill => open !== self || (autofill && manual);
    const signIn = async (lib, autofill = false) => {
      const options = await api('auth/login/options', {method: 'POST', body: {}});
      if (stale(autofill)) return;
      const response = await lib.startAuthentication({optionsJSON: options, useBrowserAutofill: autofill});
      if (open !== self) return;
      await api('auth/login/verify', {method: 'POST', body: {response}});
      status(t('account.status.signedIn')); finish();
    };
    // The library, once it has loaded and this browser supports passkeys; null when the dialog was closed or replaced meanwhile
    // (nothing is painted into it) or when the browser lacks passkeys (said, and the buttons stay off).
    const ready = async () => {
      const lib = await loadPasskeyLibrary();
      if (open !== self) return null;
      if (!lib.browserSupportsWebAuthn()) { status(t('account.status.unsupported')); return null; }
      return lib;
    };
    $('#account-create').addEventListener('click', async () => {
      manual = true; busy(true); status(t('account.status.createPrompt'));
      try {
        const lib = await ready(); if (!lib) return;
        const name = $('#account-name').value.trim();
        const options = await api('auth/register/options', {method: 'POST', body: {display_name: name}});
        if (open !== self) return;
        const response = await lib.startRegistration({optionsJSON: options});
        if (open !== self) return;
        await api('auth/register/verify', {method: 'POST', body: {response, display_name: name}});
        status(t('account.status.created')); finish();
      } catch (error) { if (open === self) { status(passkeyMessage(error, t)); busy(false); } }
    });
    $('#account-signin').addEventListener('click', async () => {
      manual = true; busy(true); status(t('account.status.signinPrompt'));
      try { const lib = await ready(); if (lib) await signIn(lib, false); } catch (error) { if (open === self) { status(passkeyMessage(error, t)); busy(false); } }
    });
    // Passkey autofill: suggestions appear in the name field where supported. Optional, so a library that will not
    // load stays silent here; only the server's answer is shown, because the browser ends a pending autofill request
    // (AbortError/NotAllowedError) whenever a button starts another.
    (async () => {
      try {
        const lib = await loadPasskeyLibrary();
        if (stale(true)) return;
        if (!await lib.browserSupportsWebAuthnAutofill()) return;
        if (stale(true)) return;
        await signIn(lib, true);
      } catch (error) { if (open === self && error?.status) status(passkeyMessage(error, t)); }
    })();
    $('#account-name').focus();
    return;
  }

  const render = async () => {
    let passkeys = [];
    try { passkeys = (await api('auth/passkeys')).passkeys; } catch (error) { status(passkeyMessage(error, t)); }
    paint(signedInHTML(session, passkeys, t));
    const list = $('#log-list'), tripSelect = $('#log-trip'), older = $('#log-older'), retry = $('#log-retry'), logStatus = $('#log-status');
    // Saved trips (one read per render, independent of the log, passkeys and spots): they label the Trip choice and date the entries.
    // SC0922-03: the log is read a page at a time. `entries` holds every page shown so far in server order, `nextCursor` where the
    // next older page starts (null: none), and `generation` counts first-page reads so an older-page read that a refresh or a newly
    // saved entry has overtaken is dropped. `gone` holds ids removed here, so a page read before a removal cannot bring one back.
    let view = {outcome: '', species: ''}, trips = [], entries = null, nextCursor = null, busy = false, generation = 0, loadFailed = false, gone = new Set();
    // SC1137-11: `editing` is {id, original, draft, pending} while the log form holds a correction (draft: the create form as it was).
    let editing = null, tripRegion = null, logPos = null;   // logPos: the position control, wired below
    const live = () => open === self && list.isConnected;
    const FORM_FIELDS = ['started', 'ended', 'outcome', 'count', 'species', 'method', 'trip', 'lat', 'lon', 'note'];
    const readForm = () => Object.fromEntries(FORM_FIELDS.map(n => [n, $('#log-' + n).value]));
    const writeForm = values => { for (const n of FORM_FIELDS) $('#log-' + n).value = values[n] ?? ''; };
    const clearPositionErrors = () => { for (const f of ['lat', 'lon']) { const err = $(`#log-${f}-error`); err.textContent = ''; err.hidden = true; $('#log-' + f).removeAttribute('aria-invalid'); } };
    const drawLog = () => {
      if (entries) drawLogView({list, counts: $('#log-counts'), species: $('#log-filter-species')}, {entries, trips, view, more: Boolean(nextCursor), copy: t});
      const keepFocus = document.activeElement === older && !(entries && nextCursor);
      older.hidden = !(entries && nextCursor); older.textContent = busy ? t('account.log.olderLoading') : t('account.log.older');
      older.setAttribute('aria-disabled', String(busy || Boolean(editing?.pending)));   // not `disabled`: a disabled button drops keyboard focus mid-load
      retry.hidden = !loadFailed;
      if (keepFocus) { logStatus.tabIndex = -1; logStatus.focus(); }
      // One correction at a time: the other Edit buttons rest until Save or Cancel; Save waits for an older-page read and for its own request.
      for (const b of list.querySelectorAll('[data-edit-log]')) b.disabled = Boolean(editing);
      $('#log-editing').hidden = !editing; $('#log-cancel').hidden = !editing; $('#log-cancel').disabled = Boolean(editing?.pending);
      $('#log-save').textContent = editing ? t('account.log.saveChanges') : t('account.log.save');
      $('#log-save').disabled = Boolean((editing && (busy || editing.pending)) || logPos?.pending);   // a position request in flight keeps Save off
    };
    // The Trip choice: "No trip", the saved trips, and (while correcting an entry whose trip is not in the list) its exact id kept as a labelled choice.
    const renderTripOptions = (want = tripSelect.value) => {
      tripSelect.innerHTML = noTrip(t) + logTripOptionsHTML(trips, tripRegion);
      const kept = editing?.original.trip_id;
      if (kept && ![...tripSelect.options].some(o => o.value === kept)) tripSelect.insertAdjacentHTML('beforeend', `<option value="${esc(kept)}">${esc(t('account.log.tripUnavailable'))}</option>`);
      tripSelect.value = want;
    };
    const focusEdit = id => { [...list.querySelectorAll('[data-edit-log]')].find(b => b.dataset.editLog === id)?.focus(); };
    const leaveEdit = (focusId) => {
      const e = editing; editing = null; if (!e) return;
      logPos.invalidate();
      renderTripOptions(e.draft.trip); writeForm(e.draft); clearPositionErrors();
      drawLog(); if (focusId) focusEdit(focusId);
    };
    const openEdit = id => {
      const row = entries?.find(r => r.id === id); if (!row || editing) return;
      const draft = readForm(); logPos.invalidate();
      editing = {id, draft, pending: false, original: {...row}};
      renderTripOptions(row.trip_id || '');
      writeForm({started: localInputValue(row.started_at), ended: localInputValue(row.ended_at), outcome: row.outcome, count: row.outcome === 'fish' ? String(row.count) : '',
        species: row.species ?? '', method: row.method ?? '', trip: row.trip_id || '', lat: row.lat == null ? '' : String(row.lat), lon: row.lon == null ? '' : String(row.lon), note: row.note ?? ''});
      Object.assign(editing.original, {startedShown: $('#log-started').value, endedShown: $('#log-ended').value, latShown: $('#log-lat').value, lonShown: $('#log-lon').value});
      clearPositionErrors(); logStatus.textContent = '';
      drawLog(); $('#log-started').focus();
    };
    const saveEdit = async () => {
      const e = editing; if (!e || e.pending || busy) return;
      const gen = generation, mine = () => editing === e && live();
      try {
        await submitPositionForm($, 'log', () => logEditBody(readForm(), e.original, t), async body => {
          e.pending = true; logStatus.textContent = t('account.spotEdit.saving'); drawLog();
          let saved;
          try {
            saved = await api('catch-log/' + encodeURIComponent(e.id), {method: 'PATCH', body});
            if (!saved || saved.id !== e.id) throw Object.assign(Error('unconfirmed'), {unconfirmed: true});
          } catch (error) {
            e.pending = false;
            if (mine()) { logStatus.textContent = error?.status && !error.apiFallback && error.message ? error.message : t('account.log.updateFailed'); drawLog(); }
            return;
          }
          e.pending = false;
          if (!mine() || gen !== generation) return;
          // The stored row replaces this one where it stands, then the loaded rows are put back in the log's order; pages and cursor stay as they are.
          const i = entries.findIndex(r => r.id === saved.id); if (i >= 0) entries[i] = saved;
          sortLogEntries(entries);
          logStatus.textContent = ''; leaveEdit(saved.id); status(t('account.log.updated'));
        });
      } catch (error) { if (mine()) { e.pending = false; logStatus.textContent = error?.local ? error.message : passkeyMessage(error, t); drawLog(); } }
    };
    const showLog = async () => {
      const mine = ++generation; busy = false; gone = new Set();
      try {
        const page = await readLogPage();
        if (!live() || mine !== generation) return;
        entries = page.entries; nextCursor = page.nextCursor; loadFailed = false;
        logStatus.textContent = entries.length || nextCursor ? '' : t('account.log.none');
      } catch {
        if (!live() || mine !== generation) return;
        loadFailed = true; logStatus.textContent = t('account.log.loadFailed');
      }
      drawLog();
    };
    const showOlder = async () => {
      if (busy || !nextCursor || !live()) return;
      const mine = generation, cursor = nextCursor;
      busy = true; logStatus.textContent = ''; drawLog();
      try {
        const page = await readLogPage(cursor);
        if (!live() || mine !== generation) return;
        mergeOlderLogEntries(entries, page.entries, gone);
        nextCursor = page.nextCursor;
      } catch { if (live() && mine === generation) logStatus.textContent = t('account.log.olderFailed'); }
      finally { if (live() && mine === generation) { busy = false; drawLog(); } }
    };
    const loadTrips = async () => {
      try {
        const rows = (await api('trips')).trips;
        const region = await import('./region.js').then(m => m.getRegion(), () => null);   // only names the area; without it the label reads "region / point"
        if (!live()) return;
        trips = rows; tripRegion = region; renderTripOptions();
        drawLog();
      } catch { if (live()) status(t('account.log.tripsFailed')); }
    };
    list.addEventListener('click', async event => {
      const edit = event.target.closest('[data-edit-log]'); if (edit) { openEdit(edit.dataset.editLog); return; }
      const b = event.target.closest('[data-remove-log]'); if (!b || editing?.pending) return;
      const id = b.dataset.removeLog;
      try {
        await api('catch-log/' + encodeURIComponent(id), {method: 'DELETE', body: {}});
        // Only this row goes: older pages already shown and the cursor stay, and the cursor stays valid if it pointed at this row.
        gone.add(id);
        if (editing?.id === id) leaveEdit();
        if (live() && entries) { entries = entries.filter(row => row.id !== id); if (!entries.length && !nextCursor) logStatus.textContent = t('account.log.none'); drawLog(); }
      } catch (error) { status(passkeyMessage(error, t)); }
    });
    older.addEventListener('click', () => { if (!editing?.pending) showOlder(); });
    $('#log-filter-outcome').addEventListener('change', event => { view = {...view, outcome: event.target.value}; drawLog(); });
    $('#log-filter-species').addEventListener('change', event => { view = {...view, species: event.target.value}; drawLog(); });
    retry.addEventListener('click', () => { if (!editing?.pending) showLog(); });
    $('#log-cancel').addEventListener('click', () => { if (editing && !editing.pending) leaveEdit(editing.id); });
    $('#log-form').addEventListener('keydown', event => {
      if (event.key !== 'Escape' || !editing) return;
      event.preventDefault(); event.stopPropagation();
      if (!editing.pending) leaveEdit(editing.id);
    });
    $('#log-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (logPos.pending) return;   // a position is still being asked for: Save waits
      if (editing) { saveEdit(); return; }
      const field = n => $('#log-' + n).value;
      try {
        await submitPositionForm($, 'log', () => logBody({started: field('started'), ended: field('ended'), outcome: field('outcome'), count: field('count'), species: field('species'), method: field('method'), trip_id: field('trip'), lat: field('lat'), lon: field('lon'), note: field('note')}, t), async body => {
          await api('catch-log', {method: 'POST', body});
          logPos.invalidate(); $('#log-form').reset(); await showLog(); status(t('account.log.saved'));
        });
      } catch (error) { status(error?.local ? error.message : passkeyMessage(error, t)); }
    });
    logPos = createPositionControl({$, prefix: 'log', copy: t, alive: live, after: drawLog});
    showLog(); loadTrips();
    // BF-saved-spots: the list reads each spot against the shared protected-area screen; a screen that cannot load reads "unavailable".
    let screenOnce = null;
    const spotScreen = () => screenOnce ??= import('./protected-areas.js').then(m => m.initProtectedAreas(null, () => {})).catch(() => null);
    let spotRows = [], spotReadings = [], loadGen = 0, loading = false, editor = null;
    const spotList = $('#spot-list'), spotsChanged = () => { try { globalThis.dispatchEvent?.(new Event('skippercast:saved-spots-changed')); } catch { /* the Chart layer reads again on its next turn-on */ } }, showSpots = async () => {
      const gen = ++loadGen; loading = true; editor = null; syncSpotPos();
      try {
        const rows = (await api('spots')).spots;
        const verdicts = await spotVerdicts(rows, await spotScreen(), t);
        if (gen !== loadGen || open !== self) return;   // a newer read or a confirmed edit has already answered
        spotRows = rows; spotReadings = verdicts;
        spotList.innerHTML = spotRows.map((s, i) => spotItemHTML(s, verdicts[i], undefined, t)).join('');
      } catch (error) { if (gen === loadGen) status(passkeyMessage(error, t)); }
      finally { if (gen === loadGen) loading = false; }
    };
    // SC1137-09: edit a spot's name and note in its own row. One editor at a time; a draft is only the form's own fields.
    const rowOf = id => [...spotList.children].find(li => li.dataset.spotRow === id);
    const redrawRow = (id, focusEdit) => {
      const i = spotRows.findIndex(s => s.id === id), row = rowOf(id); if (i < 0 || !row) return;
      const holder = document.createElement('template'); holder.innerHTML = spotItemHTML(spotRows[i], spotReadings[i], undefined, t);
      row.replaceWith(holder.content.firstElementChild);
      if (focusEdit) rowOf(id)?.querySelector('[data-edit-spot]')?.focus();
    };
    const closeEditor = focusEdit => { const e = editor; editor = null; syncSpotPos(); if (e) redrawRow(e.id, focusEdit); };
    const openEditor = id => {
      const i = spotRows.findIndex(s => s.id === id), row = rowOf(id); if (i < 0 || !row || editor?.pending) return;
      closeEditor(false);
      const holder = document.createElement('template'); holder.innerHTML = spotEditHTML(spotRows[i], spotReadings[i], undefined, t);
      const li = holder.content.firstElementChild; row.replaceWith(li);
      fillSpotEdit(li.querySelector('form'), spotRows[i]);
      editor = {id, pending: false, token: {}};
      spotPos.invalidate(); syncSpotPos();   // a spot's position is never moved from here: the create button rests while a row is open
      li.querySelector('input').focus();
    };
    const saveEditor = async form => {
      const e = editor, token = e?.token; if (!e || e.pending) return;
      const mine = () => editor === e && open === self && form.isConnected;
      const say = text => { if (mine()) form.querySelector('[data-edit-status]').textContent = text; };
      const lock = on => { for (const el of form.querySelectorAll('input,textarea,button')) el.disabled = on; };
      const i = spotRows.findIndex(s => s.id === e.id), before = spotRows[i];
      e.pending = true; lock(true); say(t('account.spotEdit.saving'));
      let saved;
      try {
        saved = await api('spots/' + encodeURIComponent(e.id), {method: 'PATCH', body: spotEditBody({name: form.elements.name.value, note: form.elements.note.value})});
        if (!saved || saved.id !== before.id || saved.lat !== before.lat || saved.lon !== before.lon) throw Object.assign(Error('unconfirmed'), {unconfirmed: true});
      } catch (error) {
        e.pending = false;
        if (mine()) { lock(false); say(error?.status && !error.apiFallback && error.message ? error.message : t('account.spotEdit.failed')); }
        return;
      }
      e.pending = false;
      // Confirmed: the stored row replaces this spot where it stands; an older list read still in flight must not put the old name back.
      const j = spotRows.findIndex(s => s.id === saved.id); if (j >= 0) spotRows[j] = saved;
      const reread = loading; loadGen++; loading = false;
      if (editor === e) { editor = null; syncSpotPos(); }
      if (open === self && token) { redrawRow(saved.id, true); status(t('account.spotEdit.saved')); }
      spotsChanged();
      if (reread && open === self) showSpots();
    };
    spotList.addEventListener('click', event => {
      const edit = event.target.closest('[data-edit-spot]'); if (edit) { openEditor(edit.dataset.editSpot); return; }
      if (event.target.closest('[data-edit-cancel]') && editor && !editor.pending) closeEditor(true);
    });
    spotList.addEventListener('submit', event => { event.preventDefault(); const form = event.target.closest('form.spot-edit'); if (form) saveEditor(form); });
    spotList.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || !event.target.closest('form.spot-edit')) return;
      event.preventDefault(); event.stopPropagation();
      if (editor && !editor.pending) closeEditor(true);
    });
    spotList.addEventListener('click', async event => {
      const b = event.target.closest('[data-remove-spot]'); if (!b) return;
      try { await api('spots/' + encodeURIComponent(b.dataset.removeSpot), {method: 'DELETE', body: {}}); spotsChanged(); await showSpots(); } catch (error) { status(passkeyMessage(error, t)); }
    });
    const spotPos = createPositionControl({$, prefix: 'spot', copy: t, alive: () => open === self && spotList.isConnected, blocked: () => Boolean(editor)});
    const syncSpotPos = () => { if (!spotPos.pending) $('#spot-use-position').disabled = Boolean(editor); };
    $('#spot-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (spotPos.pending) return;   // a position is still being asked for: Save waits
      const field = n => $('#spot-' + n).value;
      try {
        await submitPositionForm($, 'spot', () => spotBody({name: field('name'), lat: field('lat'), lon: field('lon'), note: field('note')}), async body => {
          await api('spots', {method: 'POST', body});
          $('#spot-form').reset(); spotsChanged(); spotPos.invalidate(); await showSpots(); status(t('account.spots.saved'));
        });
      } catch (error) { status(passkeyMessage(error, t)); }
    });
    $('#spot-export').addEventListener('click', async () => {
      try {
        const screen = await spotScreen();
        if (screen && !screen.ready()) await screen.refresh();
        const {getRegion} = await import('./region.js'), out = await exportSpots(spotRows, screen, getRegion(), new Date(), t);
        const url = URL.createObjectURL(new Blob([out.gpx], {type: 'application/gpx+xml'})), a = document.createElement('a');
        a.href = url; a.download = 'SkipperCast-saved-spots.gpx'; a.click(); URL.revokeObjectURL(url);
        const one = out.exported === 1, vars = {exported: out.exported, withheld: out.withheld};
        status(out.withheld ? (one ? t('account.exp.doneHeld.one', vars) : t('account.exp.doneHeld.other', vars)) : (one ? t('account.exp.done.one', vars) : t('account.exp.done.other', vars)));
      } catch (error) { status(error?.message || t('account.exp.build')); }
    });
    showSpots();
    $('#account-add').addEventListener('click', async () => {
      status(t('account.status.addPrompt'));
      try {
        const lib = await loadPasskeyLibrary();
        if (open !== self) return;
        if (!lib.browserSupportsWebAuthn()) { status(t('account.status.unsupportedShort')); return; }
        const options = await api('auth/passkeys/options', {method: 'POST', body: {}});
        if (open !== self) return;
        const response = await lib.startRegistration({optionsJSON: options});
        if (open !== self) return;
        await api('auth/passkeys', {method: 'POST', body: {response}});
        await render(); status(t('account.status.added'));
      } catch (error) { if (open === self) status(passkeyMessage(error, t)); }
    });
    $('#account-signout').addEventListener('click', async () => {
      try { await api('auth/logout', {method: 'POST', body: {}}); finish(); } catch (error) { status(passkeyMessage(error, t)); }
    });
    $('#account-delete').addEventListener('click', async event => {
      if (!await confirmInPage(event.currentTarget, t('account.del.confirm'), t('account.del.yes'), t)) return;
      try { await api('privacy', {method: 'DELETE', body: {}}); status(t('account.del.done')); finish(); } catch (error) { status(passkeyMessage(error, t)); }
    });
    for (const button of body.querySelectorAll('[data-remove-passkey]')) button.addEventListener('click', async () => {
      if (!await confirmInPage(button, t('account.pk.confirm'), t('account.pk.confirmYes'), t)) return;
      try { await api('auth/passkeys', {method: 'DELETE', body: {id: button.dataset.removePasskey}}); await render(); status(t('account.status.removed')); }
      catch (error) { status(passkeyMessage(error, t)); }
    });
  };
  await render();
}

export async function initAccount() {
  const t = DEFAULT_COPY, entry = document.getElementById('account-entry');
  const remember = back => { try { sessionStorage.setItem(RETURN_KEY, back && back !== '#account' ? back : '#guide'); } catch { /* storage blocked */ } };
  const fromHash = event => {
    if (location.hash !== '#account') { open?.close(); return; }
    if (event?.oldURL) remember(new URL(event.oldURL).hash);
    openAccount();
  };
  window.addEventListener('hashchange', fromHash);
  entry?.addEventListener('click', () => { remember(location.hash || '#guide'); location.hash = 'account'; });
  if (location.hash === '#account') openAccount();
  try {
    const session = await api('session');
    if (entry) {
      entry.hidden = !session.signIn;
      entry.querySelector('span').textContent = session.signedIn ? (session.user?.display_name ? t('account.entry.signedInAs', {name: session.user.display_name}) : t('account.entry.signedIn')) : t('account.entry.signIn');
    }
  } catch { if (entry) entry.hidden = true; }
}
