// Port chooser (FE-08, design § 7, D11): the landing's "Where are you
// launching?" input and, wrapped in PortDialog, the app's port sheet. Search
// over the home ports with v1's matching, the featured ports before a query,
// Enter for the top match, "Use my location" with v1's geolocation rules and
// privacy line, and "Explore the coast". It never opens on its own: the map
// is never blocked. Styles: web/landing/port-input.css.
import {useEffect, useId, useRef, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {Button, IconButton} from '../ui/Button.tsx';
import {COPY, listPorts, locatePort, type Port} from '../ports.ts';

export type PortInputProps = {
  /** The directory; null while it loads, and an empty list when it failed. */
  ports: readonly Port[] | null;
  onChoose: (port: Port) => void;
  onExplore: () => void;
  /** The input's label; the landing's question by default. */
  label?: string;
  autoFocus?: boolean;
  /** Start with "Use my location" (the command bar's locate entry). */
  locate?: boolean;
  geolocation?: Geolocation | null;
};

export function PortInput({ports, onChoose, onExplore, label = COPY.question, autoFocus = false, locate = false, geolocation}: PortInputProps) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [nearest, setNearest] = useState<Port | null>(null);
  const list = ports ?? [];
  const matches = nearest && !query ? [nearest] : listPorts(list, query, showAll);

  const findNearby = async () => {
    setFeedback(COPY.finding);
    const found = await locatePort(list, geolocation);
    if (found.ok) { setNearest(found.port); setQuery(''); setFeedback(COPY.found(found.port)); }
    else { setFeedback(COPY[found.reason]); input.current?.focus(); }
  };
  useEffect(() => { if (autoFocus) input.current?.focus(); }, [autoFocus]);
  useEffect(() => { if (locate && ports) void findNearby(); }, [locate, ports]);

  return (
    <form class="port-input" onSubmit={event => { event.preventDefault(); if (matches[0]) onChoose(matches[0]); }}>
      <label class="port-input-label" for={id}>{label}</label>
      <div class="port-input-row">
        <input ref={input} id={id} type="search" autocomplete="off" autofocus={autoFocus} placeholder={COPY.placeholder} value={query} aria-describedby={`${id}-note`}
          onInput={event => { setQuery((event.currentTarget as HTMLInputElement).value); setNearest(null); setFeedback(''); }} />
        <Button type="submit" variant="primary" icon="arrow" disabled={!matches[0]}>Go</Button>
      </div>
      <div class="port-input-results" aria-live="polite">
        {ports === null ? <p class="port-input-empty">Loading ports…</p> : null}
        {ports && !matches.length ? <p class="port-input-empty">{ports.length ? COPY.empty : 'Port choices are unavailable. Explore the coast instead.'}</p> : null}
        <ul class="port-input-list">
          {matches.map(port => (
            <li key={port.id}>
              <button type="button" class="port-input-option" data-port={port.id} onClick={() => onChoose(port)}>
                <strong>{port.name}</strong><span>{COPY.detail(port)}</span>
              </button>
            </li>
          ))}
        </ul>
        {ports && !query && !nearest && !showAll ? <Button variant="quiet" size="sm" onClick={() => setShowAll(true)}>See all {ports.length} ports</Button> : null}
      </div>
      <p class="port-input-feedback" role="status">{feedback}</p>
      <div class="port-input-actions">
        <Button icon="target" onClick={findNearby} disabled={!ports}>Use my location</Button>
        <Button icon="map" onClick={onExplore}>Explore the coast</Button>
      </div>
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
export function PortDialog({open, onClose, title = 'Change port', children}: PortDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} class="port-dialog" aria-labelledby={id} onClose={onClose}>
      <div class="port-dialog-head">
        <h2 id={id}>{title}</h2>
        <IconButton icon="close" label="Close" onClick={onClose} />
      </div>
      {open ? children : null}
    </dialog>
  );
}
