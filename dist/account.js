// Account sheet: create a SkipperCast account or sign in with a passkey, add or
// remove passkeys, sign out, delete the account. Opens from the Guide entry or
// any #account link. Passkey ceremonies use the vendored @simplewebauthn/browser
// (window.SimpleWebAuthnBrowser, loaded with SRI in app.html).
const RETURN_KEY = 'skippercast-account-return';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const day = iso => iso ? new Date(iso).toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'}) : '';

async function api(path, {method = 'GET', body} = {}) {
  const response = await fetch('/api/' + path, {method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20000)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = Error(data.error || 'Could not complete this request.'); error.status = response.status; throw error; }
  return data;
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
export function passkeyMessage(error) {
  const name = error?.name, code = error?.code;
  if (code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED' || name === 'InvalidStateError') return 'This device already has a passkey for this account.';
  if (name === 'NotAllowedError' || name === 'AbortError') return 'The passkey request was cancelled or timed out. Try again when ready.';
  if (name === 'SecurityError') return 'Passkeys are not available on this address.';
  if (error?.status === 429) return 'Too many attempts. Wait a minute and try again.';
  return error?.message ? error.message.charAt(0).toUpperCase() + error.message.slice(1) + '.' : 'Something went wrong. Try again.';
}

/**
 * An in-page confirmation under `anchor` (not window.confirm, which blocks the
 * page and automation). Resolves true for the confirm button, false for Cancel
 * or Escape. Only one is shown per anchor.
 */
export function confirmInPage(anchor, message, confirmLabel) {
  anchor.parentElement.querySelector(':scope > .account-confirm')?.remove();
  const box = document.createElement('div');
  box.className = 'account-confirm';
  box.setAttribute('role', 'alertdialog');
  box.innerHTML = `<p>${esc(message)}</p><div class="home-port-actions"><button type="button" data-confirm="no">Cancel</button><button type="button" data-confirm="yes" class="account-destructive">${esc(confirmLabel)}</button></div>`;
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
const supported = () => !!webauthn()?.browserSupportsWebAuthn?.();

function finish() {
  // Reload so trip alerts, feedback and AI lookup pick up the new session,
  // returning to the screen that sent the person here.
  let back = '#guide';
  try { back = sessionStorage.getItem(RETURN_KEY) || back; sessionStorage.removeItem(RETURN_KEY); } catch { /* storage blocked */ }
  history.replaceState(null, '', location.pathname + location.search + back);
  location.reload();
}

const OUTCOME_WORDS = {fish: 'Fish', blank: 'Blank: no fish', unknown: 'Not sure'};
/** One catch-log entry as list HTML. Every stored string is escaped, so markup in a note shows as plain text. */
export function logItemHTML(row) {
  const bits = [day(row.started_at), OUTCOME_WORDS[row.outcome] ?? row.outcome, row.outcome === 'fish' ? `${row.count} fish` : '', row.species, row.method,
    row.lat != null && row.lon != null ? `${row.lat}, ${row.lon}` : ''].filter(Boolean);
  return `<li><span>${bits.map(esc).join(' · ')}</span>${row.note ? `<p class="account-hint">${esc(row.note)}</p>` : ''}
    <button type="button" data-remove-log="${esc(row.id)}">Remove</button></li>`;
}

/** The form's fields as the log route's body: a blank sends no count, a position is sent only when both boxes are filled. */
export function logBody(f) {
  const num = v => (String(v ?? '').trim() === '' ? null : Number(v));
  const started = f.started ? new Date(f.started) : new Date();
  const out = {started_at: started.toISOString(), outcome: f.outcome, method: f.method || null, species: f.species || null, note: f.note || null, lat: num(f.lat), lon: num(f.lon)};
  if (f.outcome === 'fish') out.count = num(f.count);
  return out;
}

const logFormHTML = () => `<h2 class="account-subhead">Catch log</h2>
    <p class="home-port-fine">Private to this account. Record a blank day as well as a good one. A position is never shared, mapped or put in a feed.</p>
    <form id="log-form" autocomplete="off">
      <label for="log-started">When</label><input id="log-started" type="datetime-local" />
      <label for="log-outcome">What happened</label><select id="log-outcome"><option value="blank">Blank: no fish</option><option value="fish">Fish</option><option value="unknown">Not sure</option></select>
      <label for="log-count">Fish count</label><input id="log-count" type="number" min="1" max="9999" step="1" />
      <label for="log-species">Target species</label><input id="log-species" type="text" maxlength="60" />
      <label for="log-method">Method</label><input id="log-method" type="text" maxlength="40" />
      <label for="log-lat">Latitude <span class="account-hint">(optional, private)</span></label><input id="log-lat" type="number" step="any" />
      <label for="log-lon">Longitude <span class="account-hint">(optional, private)</span></label><input id="log-lon" type="number" step="any" />
      <label for="log-note">Note</label><input id="log-note" type="text" maxlength="1000" />
      <div class="home-port-actions"><button type="submit" id="log-save">Save to my log</button></div>
    </form>
    <ul class="account-passkeys" id="log-list"></ul>`;

/** One saved spot as list HTML. Name, note and verdict are escaped, so markup in them shows as plain text. */
export function spotItemHTML(spot, verdict) {
  const name = String(spot.name ?? '').replace(/[\u0000-\u001f\ufffe\uffff]/g, '').trim() || 'Unnamed spot';
  return `<li><span>${esc(name)} · ${esc(spot.lat)}, ${esc(spot.lon)}</span>${verdict?.text ? `<p class="account-hint">${esc(verdict.text)}</p>` : ''}${spot.note ? `<p class="account-hint">${esc(spot.note)}</p>` : ''}
    <button type="button" data-remove-spot="${esc(spot.id)}">Remove</button></li>`;
}

/** The form's fields as the spots route's body. A position is always sent; the route refuses a missing or unreadable one. */
export function spotBody(f) {
  const num = v => (String(v ?? '').trim() === '' ? null : Number(v));
  return {name: f.name ?? '', lat: num(f.lat), lon: num(f.lon), note: f.note || null};
}

/** Each spot's protected-area reading from the shared screen: excluded (with the boundary named), unavailable, or clear (no text). */
export async function spotVerdicts(spots, screen) {
  const {protectedHitReading} = await import('./trip-export.js');
  return spots.map(s => {
    const r = screen?.ready?.() ? screen.inspect({latitude: s.lat, longitude: s.lon}) : null;
    if (!r?.fresh) return {status: 'unavailable', text: 'Protected-area check unavailable, so this spot cannot be exported yet.'};
    if (r.status !== 'excluded') return {status: 'clear', text: ''};
    return {status: 'excluded', text: `${protectedHitReading({inside: r.matches.every(m => m.inside === true), reef: false})} ${r.names.join(', ')}. Not exported.`};
  });
}

/**
 * The saved spots as one GPX file through the planner's own export path (dist/trip-export.js `buildExport`, so gpx.js
 * names are cleaned and made unique by its one serialiser). A spot inside or near a protected area is left out and named;
 * with the screen stale or missing nothing is exported. The file must pass the same GPX check the planner runs.
 */
export async function exportSpots(spots, screen, region, now = new Date()) {
  const {buildExport} = await import('./trip-export.js'), {checkGpx} = await import('../web/gpx-check.ts');
  if (!spots.length) throw Error('You have no saved spots to export.');
  const verdicts = await spotVerdicts(spots, screen);
  if (verdicts.some(v => v.status === 'unavailable')) throw Error('Protected-area checks are unavailable or older than 36 hours. Return to the map and refresh before exporting.');
  const held = spots.filter((s, i) => verdicts[i].status !== 'clear'), clear = spots.filter((s, i) => verdicts[i].status === 'clear');
  if (!clear.length) throw Error('Every saved spot is inside or near a protected area, so nothing was exported.');
  const points = clear.map(s => ({id: 'user:' + s.id, name: s.name.trim() ? s.name : 'Waypoint', category: 'other', latitude: s.lat, longitude: s.lon}));
  const out = buildExport({atlas: {targets: [], areas: [], drifts: []}, screen, ids: points.map(p => p.id), region, title: 'SkipperCast saved spots', now, userWaypoints: points});
  const check = checkGpx(out.gpx, {waypoints: clear.length});
  if (!check.ok) throw Error(`The GPX file failed its own check: ${check.problems[0]}. Nothing was handed over.`);
  return {gpx: out.gpx, exported: clear.length, withheld: held.length};
}

const spotFormHTML = () => `<h2 class="account-subhead">Saved spots</h2>
    <p class="home-port-fine">Private to this account. A spot and its note are never shared, mapped, put in a feed or shown to anyone else. Spots inside a protected area are shown with that reading and left out of the GPX file.</p>
    <form id="spot-form" autocomplete="off">
      <label for="spot-name">Name</label><input id="spot-name" type="text" maxlength="80" />
      <label for="spot-lat">Latitude</label><input id="spot-lat" type="number" step="any" required />
      <label for="spot-lon">Longitude</label><input id="spot-lon" type="number" step="any" required />
      <label for="spot-note">Private note</label><input id="spot-note" type="text" maxlength="1000" />
      <div class="home-port-actions"><button type="submit" id="spot-save">Save this spot</button><button type="button" id="spot-export">Download my spots as GPX</button></div>
    </form>
    <ul class="account-passkeys" id="spot-list"></ul>`;

function signedOutHTML() {
  return `<h1 id="account-title">Save trips and alerts with an account</h1>
    <p class="home-port-intro">SkipperCast accounts use passkeys: Face ID, Touch ID or your device PIN. There is no password. The map and forecasts stay free without an account.</p>
    <label for="account-name">Name <span class="account-hint">(optional, shown only to you)</span></label>
    <input id="account-name" type="text" maxlength="60" autocomplete="username webauthn" placeholder="e.g. Graham" />
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-create" class="account-primary">Create account</button><button type="button" id="account-signin">Sign in with a passkey</button></div>
    <p class="home-port-fine">Your passkey stays on your device or in your password manager; SkipperCast stores only its public key. Saved trips, alerts and boat comfort feedback belong to your account, and you can delete the account at any time.</p>`;
}

function signedInHTML(session, passkeys) {
  const name = session.user?.display_name;
  return `<h1 id="account-title">${name ? `Signed in as ${esc(name)}` : 'You are signed in'}</h1>
    <p class="home-port-intro">Your saved trips, alerts and comfort feedback are private to this account.</p>
    <h2 class="account-subhead">Passkeys</h2>
    <ul class="account-passkeys">${passkeys.map(p => `<li><span>Added ${esc(day(p.created_at))}${p.last_used_at ? ` · last used ${esc(day(p.last_used_at))}` : ''}</span>
      <button type="button" data-remove-passkey="${esc(p.id)}"${passkeys.length < 2 ? ' disabled title="Add another passkey before removing this one"' : ''}>Remove</button></li>`).join('')}</ul>
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-add">Add a passkey on this device</button><button type="button" id="account-signout">Sign out</button></div>
    ${logFormHTML()}
    ${spotFormHTML()}
    <details class="account-danger"><summary>Delete account</summary>
      <p>Deletes your account, passkeys, saved trips, alerts, notification devices, catch log, saved spots and comfort feedback. This cannot be undone.</p>
      <button type="button" id="account-delete">Delete my account and records</button></details>`;
}

let open = null;
export async function openAccount() {
  if (open) return;
  const previous = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim account-scrim';
  scrim.innerHTML = `<section class="home-port-card account-card" role="dialog" aria-modal="true" aria-labelledby="account-title">
    <div class="home-port-kicker">YOUR ACCOUNT</div><div id="account-body"><h1 id="account-title">Account</h1><p role="status">Checking your account…</p></div>
    <button type="button" class="home-port-close" aria-label="Close account">×</button></section>`;
  document.body.append(scrim);
  document.body.classList.add('choosing-home-port');
  const $ = sel => scrim.querySelector(sel), body = $('#account-body');
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
  scrim.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); close(); } });

  let session;
  try { session = await api('session'); }
  catch { body.innerHTML = '<h1 id="account-title">Account</h1><p class="home-port-intro">Accounts need a connection. Try again when you are online.</p>'; return; }
  if (!session.signIn) { body.innerHTML = '<h1 id="account-title">Account</h1><p class="home-port-intro">Accounts are not available on this site.</p>'; return; }

  if (!session.signedIn) {
    body.innerHTML = signedOutHTML();
    const buttons = [$('#account-create'), $('#account-signin')];
    const busy = on => buttons.forEach(b => { b.disabled = on; });
    if (!supported()) { busy(true); status('This browser does not support passkeys. Try an up-to-date Safari, Chrome, Edge or Firefox.'); return; }
    // #597: once the person taps Create or Sign in, or this dialog is closed or replaced, a passkey-autofill request
    // still waiting for its options must not start: its ceremony would abort theirs through the shared abort service.
    let manual = false;
    const signIn = async (autofill = false) => {
      const options = await api('auth/login/options', {method: 'POST', body: {}});
      if (autofill && (manual || open !== self)) return;
      const response = await webauthn().startAuthentication({optionsJSON: options, useBrowserAutofill: autofill});
      await api('auth/login/verify', {method: 'POST', body: {response}});
      status('Signed in.'); finish();
    };
    $('#account-create').addEventListener('click', async () => {
      manual = true; busy(true); status('Follow your device to create a passkey…');
      try {
        const name = $('#account-name').value.trim();
        const options = await api('auth/register/options', {method: 'POST', body: {display_name: name}});
        const response = await webauthn().startRegistration({optionsJSON: options});
        await api('auth/register/verify', {method: 'POST', body: {response, display_name: name}});
        status('Account created.'); finish();
      } catch (error) { status(passkeyMessage(error)); busy(false); }
    });
    $('#account-signin').addEventListener('click', async () => {
      manual = true; busy(true); status('Choose your SkipperCast passkey…');
      try { await signIn(false); } catch (error) { status(passkeyMessage(error)); busy(false); }
    });
    // Passkey autofill: suggestions appear in the name field where supported.
    try {
      // Only the server's answer is shown: the browser ends a pending autofill
      // request (AbortError/NotAllowedError) whenever a button starts another.
      if (await webauthn().browserSupportsWebAuthnAutofill()) signIn(true).catch(error => { if (open && error?.status) status(passkeyMessage(error)); });
    } catch { /* optional */ }
    $('#account-name').focus();
    return;
  }

  const render = async () => {
    let passkeys = [];
    try { passkeys = (await api('auth/passkeys')).passkeys; } catch (error) { status(passkeyMessage(error)); }
    body.innerHTML = signedInHTML(session, passkeys);
    const list = $('#log-list'), showLog = async () => {
      try { const {entries} = await api('catch-log'); list.innerHTML = entries.map(logItemHTML).join(''); } catch (error) { status(passkeyMessage(error)); }
    };
    list.addEventListener('click', async event => {
      const b = event.target.closest('[data-remove-log]'); if (!b) return;
      try { await api('catch-log/' + encodeURIComponent(b.dataset.removeLog), {method: 'DELETE', body: {}}); await showLog(); } catch (error) { status(passkeyMessage(error)); }
    });
    $('#log-form').addEventListener('submit', async event => {
      event.preventDefault();
      const field = n => $('#log-' + n).value;
      try {
        await api('catch-log', {method: 'POST', body: logBody({started: field('started'), outcome: field('outcome'), count: field('count'), species: field('species'), method: field('method'), lat: field('lat'), lon: field('lon'), note: field('note')})});
        $('#log-form').reset(); await showLog(); status('Saved to your log.');
      } catch (error) { status(passkeyMessage(error)); }
    });
    showLog();
    // BF-saved-spots: the list reads each spot against the shared protected-area screen; a screen that cannot load reads "unavailable".
    let screenOnce = null;
    const spotScreen = () => screenOnce ??= import('./protected-areas.js').then(m => m.initProtectedAreas(null, () => {})).catch(() => null);
    let spotRows = [];
    const spotList = $('#spot-list'), showSpots = async () => {
      try {
        spotRows = (await api('spots')).spots;
        const verdicts = await spotVerdicts(spotRows, await spotScreen());
        spotList.innerHTML = spotRows.map((s, i) => spotItemHTML(s, verdicts[i])).join('');
      } catch (error) { status(passkeyMessage(error)); }
    };
    spotList.addEventListener('click', async event => {
      const b = event.target.closest('[data-remove-spot]'); if (!b) return;
      try { await api('spots/' + encodeURIComponent(b.dataset.removeSpot), {method: 'DELETE', body: {}}); await showSpots(); } catch (error) { status(passkeyMessage(error)); }
    });
    $('#spot-form').addEventListener('submit', async event => {
      event.preventDefault();
      const field = n => $('#spot-' + n).value;
      try {
        await api('spots', {method: 'POST', body: spotBody({name: field('name'), lat: field('lat'), lon: field('lon'), note: field('note')})});
        $('#spot-form').reset(); await showSpots(); status('Saved to your spots.');
      } catch (error) { status(passkeyMessage(error)); }
    });
    $('#spot-export').addEventListener('click', async () => {
      try {
        const screen = await spotScreen();
        if (screen && !screen.ready()) await screen.refresh();
        const {getRegion} = await import('./region.js'), out = await exportSpots(spotRows, screen, getRegion());
        const url = URL.createObjectURL(new Blob([out.gpx], {type: 'application/gpx+xml'})), a = document.createElement('a');
        a.href = url; a.download = 'SkipperCast-saved-spots.gpx'; a.click(); URL.revokeObjectURL(url);
        status(`Downloaded ${out.exported} spot${out.exported === 1 ? '' : 's'}${out.withheld ? `; ${out.withheld} left out because of a protected area` : ''}.`);
      } catch (error) { status(error?.message || 'Could not build the GPX file.'); }
    });
    showSpots();
    $('#account-add').addEventListener('click', async () => {
      if (!supported()) { status('This browser does not support passkeys.'); return; }
      status('Follow your device to add a passkey…');
      try {
        const options = await api('auth/passkeys/options', {method: 'POST', body: {}});
        const response = await webauthn().startRegistration({optionsJSON: options});
        await api('auth/passkeys', {method: 'POST', body: {response}});
        await render(); status('Passkey added.');
      } catch (error) { status(passkeyMessage(error)); }
    });
    $('#account-signout').addEventListener('click', async () => {
      try { await api('auth/logout', {method: 'POST', body: {}}); finish(); } catch (error) { status(passkeyMessage(error)); }
    });
    $('#account-delete').addEventListener('click', async event => {
      if (!await confirmInPage(event.currentTarget, 'Delete your SkipperCast account and all saved trips, alerts, notification devices, catch log, saved spots and comfort feedback? This cannot be undone.', 'Yes, delete everything')) return;
      try { await api('privacy', {method: 'DELETE', body: {}}); status('Your account has been deleted.'); finish(); } catch (error) { status(passkeyMessage(error)); }
    });
    for (const button of body.querySelectorAll('[data-remove-passkey]')) button.addEventListener('click', async () => {
      if (!await confirmInPage(button, 'Remove this passkey? You will not be able to sign in with it again.', 'Remove passkey')) return;
      try { await api('auth/passkeys', {method: 'DELETE', body: {id: button.dataset.removePasskey}}); await render(); status('Passkey removed.'); }
      catch (error) { status(passkeyMessage(error)); }
    });
  };
  await render();
}

export async function initAccount() {
  const entry = document.getElementById('account-entry');
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
      entry.querySelector('span').textContent = session.signedIn ? `Signed in${session.user?.display_name ? ' as ' + session.user.display_name : ''}` : 'Sign in or create an account';
    }
  } catch { if (entry) entry.hidden = true; }
}
