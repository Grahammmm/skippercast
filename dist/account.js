// Account sheet: create a SkipperCast account or sign in with a passkey or an
// emailed link, add or remove passkeys and the sign-in email, sign out, delete
// the account. Opens from the Guide entry or any #account link. An emailed link
// opens /#email-sign-in=<token>; initAccount posts the token and drops it from the
// address bar first. Passkey ceremonies use the vendored @simplewebauthn/browser
// (window.SimpleWebAuthnBrowser, loaded with SRI in index.html).
const RETURN_KEY = 'skippercast-account-return';
const LINK_HASH = '#email-sign-in=';
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

/** The token in an emailed sign-in link's hash, or null. */
export function linkToken(hash) {
  if (typeof hash !== 'string' || !hash.startsWith(LINK_HASH)) return null;
  const token = hash.slice(LINK_HASH.length);
  return /^[\w-]{43}$/.test(token) ? token : null;
}

const emailFormHTML = (label, button) => `<form id="account-email-form" class="account-email-form" novalidate>
    <label for="account-email">${label}</label>
    <input id="account-email" type="email" maxlength="254" autocomplete="email" inputmode="email" placeholder="you@example.com" required />
    <button type="submit" id="account-email-send">${button}</button></form>`;

function signedOutHTML(emailSignIn) {
  return `<h1 id="account-title">Save trips and alerts with an account</h1>
    <p class="home-port-intro">SkipperCast accounts use passkeys: Face ID, Touch ID or your device PIN. There is no password. The map and forecasts stay free without an account.</p>
    <label for="account-name">Name <span class="account-hint">(optional, shown only to you)</span></label>
    <input id="account-name" type="text" maxlength="60" autocomplete="username webauthn" placeholder="e.g. Graham" />
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-create" class="account-primary">Create account</button><button type="button" id="account-signin">Sign in with a passkey</button></div>
    ${emailSignIn ? `<h2 class="account-subhead">Or use an email link</h2>${emailFormHTML('Email address', 'Email me a sign-in link')}<p class="home-port-fine">We send a link that works once for 15 minutes. Opening it signs you in, or creates an account for that address. The address is used only for sign-in links.</p>` : ''}
    <p class="home-port-fine">Your passkey stays on your device or in your password manager; SkipperCast stores only its public key. Saved trips, alerts and boat comfort feedback belong to your account, and you can delete the account at any time.</p>`;
}

function emailHTML(email) {
  if (email.email) return `<h2 class="account-subhead">Sign-in email</h2>
    <ul class="account-passkeys"><li><span>${esc(email.email)}</span><button type="button" id="account-email-remove">Remove</button></li></ul>`;
  if (!email.available) return '';
  return `<h2 class="account-subhead">Sign-in email</h2>
    <p class="home-port-fine">Add an address so you can get back in with an emailed link if you lose your passkeys.</p>
    ${emailFormHTML('Email address', 'Send a confirmation link')}`;
}

function signedInHTML(session, passkeys, email = {email: null, available: false}) {
  const name = session.user?.display_name, lastWay = passkeys.length < 2 && !email.email;
  return `<h1 id="account-title">${name ? `Signed in as ${esc(name)}` : 'You are signed in'}</h1>
    <p class="home-port-intro">Your saved trips, alerts and comfort feedback are private to this account.</p>
    <h2 class="account-subhead">Passkeys</h2>
    <ul class="account-passkeys">${passkeys.map(p => `<li><span>Added ${esc(day(p.created_at))}${p.last_used_at ? ` · last used ${esc(day(p.last_used_at))}` : ''}</span>
      <button type="button" data-remove-passkey="${esc(p.id)}"${lastWay ? ' disabled title="Add another passkey or an email address before removing this one"' : ''}>Remove</button></li>`).join('')}</ul>${passkeys.length ? '' : '<p class="home-port-fine">No passkeys yet. Add one to sign in with Face ID, Touch ID or your device PIN.</p>'}
    ${emailHTML(email)}
    <p id="account-status" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="account-add">Add a passkey on this device</button><button type="button" id="account-signout">Sign out</button></div>
    <details class="account-danger"><summary>Delete account</summary>
      <p>Deletes your account, passkeys, saved trips, alerts, notification devices and comfort feedback. This cannot be undone.</p>
      <button type="button" id="account-delete">Delete my account and records</button></details>`;
}

// Wires the email form: posts the address to `path` and reports the result.
function emailForm(scrim, status, path, sentMessage) {
  const form = scrim.querySelector('#account-email-form');
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    const input = form.querySelector('#account-email'), button = form.querySelector('#account-email-send'), email = input.value.trim();
    if (!email || !input.checkValidity()) { status('Enter your email address.'); input.focus(); return; }
    button.disabled = true; status('Sending…');
    try { await api(path, {method: 'POST', body: {email}}); status(sentMessage(email)); }
    catch (error) { status(passkeyMessage(error)); }
    finally { button.disabled = false; }
  });
}

let open = null;
export async function openAccount(notice = '') {
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
  open = {close};

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
    body.innerHTML = signedOutHTML(session.emailSignIn);
    emailForm(scrim, status, 'auth/email/start', email => `Check ${email} for a sign-in link. It works once, for 15 minutes.`);
    if (notice) status(notice);
    const buttons = [$('#account-create'), $('#account-signin')];
    const busy = on => buttons.forEach(b => { b.disabled = on; });
    if (!supported()) { busy(true); status(notice || (session.emailSignIn ? 'This browser does not support passkeys. You can still sign in with an email link.' : 'This browser does not support passkeys. Try an up-to-date Safari, Chrome, Edge or Firefox.')); return; }
    const signIn = async (autofill = false) => {
      const options = await api('auth/login/options', {method: 'POST', body: {}});
      const response = await webauthn().startAuthentication({optionsJSON: options, useBrowserAutofill: autofill});
      await api('auth/login/verify', {method: 'POST', body: {response}});
      status('Signed in.'); finish();
    };
    $('#account-create').addEventListener('click', async () => {
      busy(true); status('Follow your device to create a passkey…');
      try {
        const name = $('#account-name').value.trim();
        const options = await api('auth/register/options', {method: 'POST', body: {display_name: name}});
        const response = await webauthn().startRegistration({optionsJSON: options});
        await api('auth/register/verify', {method: 'POST', body: {response, display_name: name}});
        status('Account created.'); finish();
      } catch (error) { status(passkeyMessage(error)); busy(false); }
    });
    $('#account-signin').addEventListener('click', async () => {
      busy(true); status('Choose your SkipperCast passkey…');
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
    let passkeys = [], email = {email: null, available: false}, problem = '';
    try { passkeys = (await api('auth/passkeys')).passkeys; } catch (error) { problem = passkeyMessage(error); }
    try { email = await api('auth/email'); } catch { /* shown without the email section */ }
    body.innerHTML = signedInHTML(session, passkeys, email);
    if (problem) status(problem);
    emailForm(scrim, status, 'auth/email', address => `Check ${address} and open the link to confirm it.`);
    $('#account-email-remove')?.addEventListener('click', async event => {
      if (!await confirmInPage(event.currentTarget, 'Remove this email address? Sign-in links will no longer work for this account.', 'Remove email')) return;
      try { await api('auth/email', {method: 'DELETE', body: {}}); await render(); status('Email address removed.'); }
      catch (error) { status(passkeyMessage(error)); }
    });
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
      if (!await confirmInPage(event.currentTarget, 'Delete your SkipperCast account and all saved trips, alerts, notification devices and comfort feedback? This cannot be undone.', 'Yes, delete everything')) return;
      try { await api('privacy', {method: 'DELETE', body: {}}); status('Your account has been deleted.'); finish(); } catch (error) { status(passkeyMessage(error)); }
    });
    for (const button of body.querySelectorAll('[data-remove-passkey]')) button.addEventListener('click', async () => {
      if (!await confirmInPage(button, 'Remove this passkey? You will not be able to sign in with it again.', 'Remove passkey')) return;
      try { await api('auth/passkeys', {method: 'DELETE', body: {id: button.dataset.removePasskey}}); await render(); status('Passkey removed.'); }
      catch (error) { status(passkeyMessage(error)); }
    });
  };
  await render();
  if (notice) status(notice);
}

// Opens an emailed sign-in link: the token leaves the address bar before the
// request, so it is not kept in history or shared by a copied URL.
async function useEmailLink(token) {
  history.replaceState(null, '', location.pathname + location.search + '#account');
  try {
    await api('auth/email/verify', {method: 'POST', body: {token}});
    try { sessionStorage.setItem(RETURN_KEY, '#guide'); } catch { /* storage blocked */ }
    finish();
  } catch (error) {
    openAccount(error.status === 503 ? 'Email sign-in is not available right now. Try again later.' : passkeyMessage(error));
  }
}

export async function initAccount() {
  const entry = document.getElementById('account-entry');
  const remember = back => { try { sessionStorage.setItem(RETURN_KEY, back && back !== '#account' ? back : '#guide'); } catch { /* storage blocked */ } };
  const fromHash = event => {
    const token = linkToken(location.hash);
    if (token) { useEmailLink(token); return; }
    if (location.hash !== '#account') { open?.close(); return; }
    if (event?.oldURL) remember(new URL(event.oldURL).hash);
    openAccount();
  };
  window.addEventListener('hashchange', fromHash);
  entry?.addEventListener('click', () => { remember(location.hash || '#guide'); location.hash = 'account'; });
  const token = linkToken(location.hash);
  if (token) useEmailLink(token);
  else if (location.hash === '#account') openAccount();
  try {
    const session = await api('session');
    if (entry) {
      entry.hidden = !session.signIn;
      entry.querySelector('span').textContent = session.signedIn ? `Signed in${session.user?.display_name ? ' as ' + session.user.display_name : ''}` : 'Sign in or create an account';
    }
  } catch { if (entry) entry.hidden = true; }
}
