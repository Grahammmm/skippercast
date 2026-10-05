// The "send me my data" page (dist/my-data.html, served at /my-data#<token>;
// docs/legal/threat-model.md § 9.3, hardening). The token is the URL fragment,
// which browsers never send; the button POSTs it to /api/advisor/export in the
// X-Export-Token header, so it is in no request URL or log, and saves the JSON
// the answer carries. No <form>: the CSP has form-action 'none'; connect-src
// 'self' allows this request.
import {EXPORT_COPY as COPY} from '../../web/advisor/copy.ts';

const $ = id => document.getElementById(id);
/** The token from the fragment (#<token>), or '' when the link has none. */
export const tokenFrom = hash => { const raw = String(hash || '').replace(/^#/, ''); return /^[\w-]{1,600}$/.test(raw) ? raw : ''; };
const token = tokenFrom(location.hash);
const button = $('data-download'), status = $('data-status');

$('data-heading').textContent = COPY.heading;
$('data-intro').textContent = COPY.intro;
button.textContent = COPY.download;

function show(message, kind) {
  status.textContent = message;
  status.className = `upload-status${kind ? ` is-${kind}` : ''}`;
  status.hidden = !message;
}

if (!token) { button.hidden = true; show(COPY.expired, 'error'); }

button.addEventListener('click', async () => {
  button.disabled = true;
  show(COPY.working, '');
  try {
    const response = await fetch('/api/advisor/export', {method: 'POST', headers: {'X-Export-Token': token}, credentials: 'omit', cache: 'no-store'});
    if (!response.ok) { show(response.status === 404 ? COPY.expired : COPY.failed, 'error'); button.disabled = false; return; }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = 'skippercast-data.json';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    show(COPY.done, 'done');
  } catch {
    show(COPY.failed, 'error');
  }
  button.disabled = false;
});
