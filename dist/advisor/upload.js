// The upload link page (dist/upload.html, served at /u/<token>; TA-C4).
// One file, sent with XMLHttpRequest to POST /api/advisor/upload/<token> so the
// page can show upload progress (fetch cannot report request-body progress in
// Safari). The CSP has form-action 'none', so there is deliberately no <form>
// submission; connect-src 'self' allows this request.
import {UPLOAD_COPY as COPY, UPLOAD_MAX_BYTES} from '../../web/advisor/copy.ts';

const $ = id => document.getElementById(id);
const token = decodeURIComponent(location.pathname.replace(/^\/u\//, '').replace(/\/$/, ''));
const els = {
  form: $('upload-form'), file: $('upload-file'), name: $('upload-name'), send: $('upload-send'),
  progress: $('upload-progress'), bar: $('upload-bar'), percent: $('upload-percent'), status: $('upload-status'), again: $('upload-again'),
};

$('upload-heading').textContent = COPY.heading;
$('upload-intro').textContent = COPY.intro;
$('upload-choose').textContent = COPY.choose;
els.send.textContent = COPY.send;
els.again.textContent = COPY.another;

function show(message, kind) {
  els.status.textContent = message;
  els.status.className = `upload-status${kind ? ` is-${kind}` : ''}`;
  els.status.hidden = !message;
}

function reset() {
  els.file.value = '';
  els.name.hidden = true;
  els.form.hidden = false;
  els.progress.hidden = true;
  els.again.hidden = true;
  els.send.disabled = false;
  els.send.textContent = COPY.send;
  show('');
}

/** The message for a finished request that did not succeed. */
export function errorFor(status) {
  if (status === 413) return COPY.tooLarge;
  if (status === 415) return COPY.unsupported;
  if (status === 404) return COPY.expired;
  return COPY.failed;
}

els.file.addEventListener('change', () => {
  const file = els.file.files?.[0];
  els.name.textContent = file ? file.name : '';
  els.name.hidden = !file;
  show(file && file.size > UPLOAD_MAX_BYTES ? COPY.tooLarge : '', file && file.size > UPLOAD_MAX_BYTES ? 'error' : '');
});

els.send.addEventListener('click', () => {
  const file = els.file.files?.[0];
  if (!file) { show(COPY.noFile, 'error'); return; }
  if (file.size > UPLOAD_MAX_BYTES) { show(COPY.tooLarge, 'error'); return; }
  const body = new FormData();
  body.append('file', file, file.name);
  const request = new XMLHttpRequest();
  request.open('POST', `/api/advisor/upload/${encodeURIComponent(token)}`);
  els.send.disabled = true;
  els.send.textContent = COPY.sending;
  els.progress.hidden = false;
  show('');
  request.upload.addEventListener('progress', event => {
    if (!event.lengthComputable) return;
    const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
    els.bar.value = percent;
    els.percent.textContent = COPY.progress(percent);
  });
  request.addEventListener('load', () => {
    els.progress.hidden = true;
    if (request.status >= 200 && request.status < 300) {
      els.form.hidden = true;
      show(COPY.done, 'done');
      els.again.hidden = false;
      return;
    }
    els.send.disabled = false;
    els.send.textContent = COPY.send;
    show(errorFor(request.status), 'error');
  });
  request.addEventListener('error', () => {
    els.progress.hidden = true;
    els.send.disabled = false;
    els.send.textContent = COPY.send;
    show(COPY.failed, 'error');
  });
  request.send(body);
});

els.again.addEventListener('click', reset);
