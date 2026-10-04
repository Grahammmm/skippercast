// The web chat island (docs/plans/text-advisor/08-website.md § Web chat; TA-C3):
// a floating "Text SkipperCast" button that opens a chat panel. Messages go to
// POST /api/advisor/web/message, which runs the advisor inline and answers
// with its replies; a photo is uploaded first (POST /api/advisor/web/upload)
// and sent by id. Identity is the HttpOnly sc_adv cookie the server sets; the
// only thing kept in localStorage is whether the panel is open. Every string
// is in web/advisor/copy.ts. dist/chat.html mounts it today; TA-W1 embeds it
// on the site's pages.
import {render} from 'preact';
import {useEffect, useRef, useState} from 'preact/hooks';
import {CHAT_COPY as COPY, CHAT_MAX_PHOTO_BYTES, CHAT_STILL_THINKING_MS, CHAT_TIMEOUT_MS} from './copy.ts';

export const OPEN_KEY = 'skippercast-chat-open';

export interface ChatReply {id: string; text: string; links: string[]; media: string[]}
export interface ChatResponse {replies?: ChatReply[]; pending?: boolean; contact?: {language: string; linked: boolean}; error?: string}
interface Line {id: string; from: 'you' | 'skippercast'; text: string; media?: string[]; photo?: string}
interface Photo {id: string; name: string}

function readOpen(fallback: boolean): boolean {
  try { const v = localStorage.getItem(OPEN_KEY); return v === null ? fallback : v === '1'; } catch { return fallback; }
}
function writeOpen(open: boolean): void {
  try { localStorage.setItem(OPEN_KEY, open ? '1' : '0'); } catch { /* storage blocked */ }
}

/** The message a failed request shows. */
export function errorText(status: number): string {
  if (status === 429) return COPY.limited;
  if (status === 413) return COPY.photoTooLarge;
  if (status === 415) return COPY.photoType;
  return COPY.failed;
}

const post = (path: string, body: BodyInit, signal?: AbortSignal, json = true): Promise<Response> =>
  fetch(path, {method: 'POST', body, credentials: 'same-origin', signal, ...(json ? {headers: {'Content-Type': 'application/json'}} : {})});

let lineSeq = 0;
const nextId = (): string => `line-${++lineSeq}`;

export function Chat({defaultOpen = false}: {defaultOpen?: boolean}) {
  const [open, setOpen] = useState(() => readOpen(defaultOpen));
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState('');
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [busy, setBusy] = useState<'idle' | 'uploading' | 'thinking' | 'still'>('idle');
  const [notice, setNotice] = useState('');
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);

  useEffect(() => { writeOpen(open); if (open) input.current?.focus(); }, [open]);
  useEffect(() => { const el = list.current; if (el) el.scrollTop = el.scrollHeight; }, [lines, busy]);

  const close = (): void => { setOpen(false); requestAnimationFrame(() => launcher.current?.focus()); };

  async function attach(event: Event): Promise<void> {
    const picked = (event.currentTarget as HTMLInputElement).files?.[0];
    (event.currentTarget as HTMLInputElement).value = '';
    if (!picked) return;
    if (picked.size > CHAT_MAX_PHOTO_BYTES) { setNotice(COPY.photoTooLarge); return; }
    setNotice(''); setBusy('uploading');
    try {
      const form = new FormData();
      form.append('file', picked, picked.name);
      const response = await post('/api/advisor/web/upload', form, undefined, false);
      if (!response.ok) { setNotice(errorText(response.status)); return; }
      const {media_id: id} = await response.json() as {media_id: string};
      setPhoto({id, name: picked.name});
    } catch { setNotice(COPY.photoFailed); }
    finally { setBusy('idle'); }
  }

  async function send(event?: Event): Promise<void> {
    event?.preventDefault();
    const message = text.trim();
    if ((!message && !photo) || busy !== 'idle') return;
    const mine: Line = {id: nextId(), from: 'you', text: message, ...(photo ? {photo: photo.name} : {})};
    setLines(all => [...all, mine]);
    setText(''); setNotice(''); setBusy('thinking');
    const sentPhoto = photo; setPhoto(null);
    const controller = new AbortController();
    const still = setTimeout(() => setBusy('still'), CHAT_STILL_THINKING_MS);
    const stop = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
    try {
      const response = await post('/api/advisor/web/message', JSON.stringify({text: message, ...(sentPhoto ? {media_ids: [sentPhoto.id]} : {})}), controller.signal);
      if (!response.ok) { setNotice(errorText(response.status)); return; }
      const data = await response.json() as ChatResponse;
      if (data.pending) { setNotice(COPY.pending); return; }
      const replies = (data.replies ?? []).filter(r => r.text || r.media.length);
      setLines(all => [...all, ...replies.map(r => ({id: nextId(), from: 'skippercast' as const, text: r.text, media: r.media}))]);
    } catch { setNotice(controller.signal.aborted ? COPY.pending : COPY.failed); }
    finally { clearTimeout(still); clearTimeout(stop); setBusy('idle'); input.current?.focus(); }
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send(); }
  }

  if (!open) {
    return (
      <button ref={launcher} type="button" class="chat-launcher" aria-expanded="false" aria-controls="chat-panel" onClick={() => setOpen(true)}>
        {COPY.open}
      </button>
    );
  }
  const waiting = busy === 'thinking' || busy === 'still';
  return (
    <section id="chat-panel" class="chat-panel" aria-label={COPY.panelLabel} onKeyDown={e => { if (e.key === 'Escape') close(); }}>
      <header class="chat-head">
        <h2 class="chat-title">{COPY.heading}</h2>
        <button type="button" class="chat-close" aria-label={COPY.close} onClick={close}>×</button>
      </header>
      <ol ref={list} class="chat-log" tabIndex={0} aria-label={COPY.logLabel} aria-live="polite" aria-relevant="additions">
        <li class="chat-line is-skippercast"><span class="chat-who">{COPY.skippercast}</span><p>{COPY.greeting}</p></li>
        {lines.map(line => (
          <li key={line.id} class={`chat-line is-${line.from}`}>
            <span class="chat-who">{line.from === 'you' ? COPY.you : COPY.skippercast}</span>
            {line.photo ? <p class="chat-photo">{COPY.attached(line.photo)}</p> : null}
            {line.text ? <p>{line.text}</p> : null}
            {(line.media ?? []).map(src => <img key={src} src={src} alt="" class="chat-image" loading="lazy" />)}
          </li>
        ))}
      </ol>
      <p class="chat-status" role="status">
        {busy === 'uploading' ? COPY.uploading : busy === 'thinking' ? COPY.thinking : busy === 'still' ? COPY.stillThinking : notice}
      </p>
      <div class="chat-compose">
        {photo ? (
          <p class="chat-attached">
            <span>{COPY.attached(photo.name)}</span>
            <button type="button" class="chat-link-button" onClick={() => setPhoto(null)}>{COPY.removePhoto}</button>
          </p>
        ) : null}
        <label class="chat-label" for="chat-input">{COPY.inputLabel}</label>
        <textarea id="chat-input" ref={input} class="chat-input" rows={2} maxLength={2000} placeholder={COPY.placeholder} value={text}
          onInput={e => setText((e.currentTarget as HTMLTextAreaElement).value)} onKeyDown={onKey} />
        <div class="chat-actions">
          <label class="chat-attach">
            <span>{COPY.attach}</span>
            <input type="file" accept="image/*" disabled={busy !== 'idle'} onChange={attach} />
          </label>
          <button type="button" class="chat-send" disabled={waiting || busy === 'uploading' || (!text.trim() && !photo)} onClick={() => void send()}>{COPY.send}</button>
        </div>
      </div>
      <footer class="chat-foot">
        <span>{COPY.continueHeading}:</span>
        <a href="/text?s=web">{COPY.textUs}</a>
        <a href="/contact.vcf" download="SkipperCast.vcf">{COPY.saveContact}</a>
      </footer>
    </section>
  );
}

/** Mount the chat into `host` (dist/chat.html opens it by default). */
export function mountChat(host: Element | null, defaultOpen = false): boolean {
  if (!host) return false;
  host.replaceChildren();
  render(<Chat defaultOpen={defaultOpen} />, host);
  return true;
}

const host = typeof document === 'undefined' ? null : document.getElementById('advisor-chat');
if (host) mountChat(host, host.hasAttribute('data-open'));
