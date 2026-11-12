// Port chooser (FE-08, design § 7, D11): the landing's "Where are you
// launching?" input and, wrapped in PortDialog, the app's port sheet. Search
// over the home ports with v1's matching, the featured ports before a query,
// Enter for the top match, "Use my location" with v1's geolocation rules and
// privacy line, "Explore the coast", and "Forget saved home" when v1, v2 or
// /coast holds one (FE-83). It never opens on its own: the map
// is never blocked. Styles: web/landing/port-input.css.
import {useEffect, useId, useLayoutEffect, useRef, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {Button, IconButton} from '../ui/Button.tsx';
import {closeOnScrim, rememberOpener, restoreFocus} from '../ui/focus-return.ts';
import {forgetHome, hasSavedHome, listPorts, locatePort, type CookieJar, type HomeStorage, type Port} from '../ports.ts';
import {language, t} from './i18n.ts';
import {portCopy} from './copy.ts';
import {Icon} from '../ui/icons.tsx';
import {useScrollCue} from '../ui/scroll-cue.ts';
import type {Located} from '../ports.ts';

type Feedback = null | {kind: 'found'; port: Port} | {kind: 'finding' | 'forgotten' | 'empty' | Extract<Located, {ok: false}>['reason']};

export type PortInputProps = {
  /** The directory; null while it loads, and an empty list when it failed. */
  ports: readonly Port[] | null;
  onChoose: (port: Port) => void;
  onExplore: () => void;
  /** Ask for the list again after it failed (the landing's step 1); shown as "Try again" only for an empty list. */
  onRetry?: () => void;
  /** The input's label; the landing's question by default. */
  label?: string;
  autoFocus?: boolean;
  /** Start with "Use my location" (the command bar's locate entry). */
  locate?: boolean;
  geolocation?: Geolocation | null;
  /** The home memory (the browser's by default; tests pass stand-ins). */
  storage?: HomeStorage | null;
  cookies?: CookieJar | null;
};

export function PortInput({ports, onChoose, onExplore, onRetry, label: labelProp, autoFocus = false, locate = false, geolocation, storage, cookies}: PortInputProps) {
  const lang = language.value, COPY = portCopy(lang), label = labelProp ?? COPY.question;
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLDivElement>(null);
  useScrollCue(results);
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const feedbackText = feedback?.kind === 'found' ? COPY.found(feedback.port) : feedback ? COPY[feedback.kind] : '';
  const failed = feedback && ['denied', 'unavailable', 'timedOut', 'unsupported'].includes(feedback.kind);
  const [saved, setSaved] = useState(() => hasSavedHome(storage, cookies));
  // One forget for v1, v2 and /coast (FE-83); this visit keeps its address.
  const forget = () => { forgetHome(storage, cookies); setSaved(false); setFeedback({kind: 'forgotten'}); };
  const [nearest, setNearest] = useState<Port | null>(null);
  const list = ports ?? [];
  const matches = nearest && !query ? [nearest] : listPorts(list, query, showAll);

  const attempt = useRef(0);
  const live = useRef(false);
  const invalidate = () => { attempt.current++; };
  // Layout cleanup closes the old context before any pending answer can resume.
  useLayoutEffect(() => {
    live.current = true;
    return () => { live.current = false; invalidate(); };
  }, [ports, geolocation]);
  const choose = (port: Port) => { invalidate(); onChoose(port); };
  const explore = () => { invalidate(); onExplore(); };
  const findNearby = async () => {
    const mine = ++attempt.current;
    setFeedback({kind: 'finding'});
    const found = await locatePort(list, geolocation);
    if (!live.current || mine !== attempt.current) return;
    if (found.ok) { setNearest(found.port); setQuery(''); setFeedback({kind: 'found', port: found.port}); }
    else { setFeedback({kind: found.reason}); input.current?.focus(); }
  };
  useEffect(() => { if (autoFocus) input.current?.focus(); }, [autoFocus]);
  useEffect(() => { if (locate && ports) void findNearby(); }, [locate, ports, geolocation]);

  return (
    <form class="port-input" onSubmit={event => { event.preventDefault(); if (matches[0]) choose(matches[0]); }}>
      <label class="port-input-label" for={id}>{label}</label>
      <div class="port-input-row">
        <input ref={input} id={id} type="search" autocomplete="off" autofocus={autoFocus} placeholder={COPY.placeholder} value={query} aria-describedby={`${id}-note`}
          onInput={event => { invalidate(); setQuery((event.currentTarget as HTMLInputElement).value); setNearest(null); setFeedback(null); }} />
        <Button type="submit" variant="primary" icon="arrow" disabled={!matches[0]}>{t('landing.port.go', lang)}</Button>
      </div>
      <div ref={results} class="port-input-results ui-scroll-cue" aria-live="polite">
        {ports === null ? <p class="port-input-empty">{t('landing.port.loading', lang)}</p> : null}
        {ports && !matches.length ? <p class="port-input-empty">{ports.length ? COPY.empty : t('landing.port.listDown', lang)}</p> : null}
        {ports && !ports.length && onRetry ? <Button size="sm" onClick={onRetry}>{t('landing.port.retry', lang)}</Button> : null}
        <ul class="port-input-list">
          {matches.map(port => (
            <li key={port.id}>
              <button type="button" class="port-input-option" data-port={port.id} onClick={() => choose(port)}>
                <strong>{port.name}</strong><span>{COPY.detail(port)}</span>
              </button>
            </li>
          ))}
        </ul>
        {ports && !query && !nearest && !showAll ? <Button variant="quiet" size="sm" onClick={() => setShowAll(true)}>{t('landing.port.all', lang, {n: ports.length})}</Button> : null}
      </div>
      <p class={`port-input-feedback${failed ? ' port-input-feedback--error' : ''}`} role="status" aria-live="polite" aria-atomic="true">{failed ? <Icon name="info" /> : null}<span>{feedbackText}</span></p>
      <div class="port-input-actions">
        <Button icon="target" onClick={findNearby} disabled={!ports}>{t('landing.port.locate', lang)}</Button>
        <Button icon="map" onClick={explore}>{t('landing.port.explore', lang)}</Button>
      </div>
      {saved ? <Button variant="quiet" size="sm" class="port-input-forget" onClick={forget}>{COPY.forget}</Button> : null}
      <p id={`${id}-note`} class="port-input-note">{COPY.privacy}</p>
    </form>
  );
}

export type PortDialogProps = {
  open: boolean;
  onClose: () => void;
  /** The dialog's heading. */
  title?: string;
  children: ComponentChildren;
};

/** The app's port sheet: a native modal dialog (Escape, the focus trap and the autofocus are the browser's), opened only by a control. */
export function PortDialog({open, onClose, title, children}: PortDialogProps) {
  const lang = language.value;
  const ref = useRef<HTMLDialogElement>(null), opener = useRef<HTMLElement | null>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { opener.current = rememberOpener(); dialog.showModal(); }
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} class="port-dialog" aria-labelledby={id} onClick={closeOnScrim} onClose={() => { restoreFocus(opener.current); onClose(); }}>
      <div class="port-dialog-head">
        <h2 id={id}>{title ?? t('landing.port.dialog', lang)}</h2>
        <IconButton icon="close" label={t('landing.port.close', lang)} onClick={onClose} />
      </div>
      {open ? children : null}
    </dialog>
  );
}
