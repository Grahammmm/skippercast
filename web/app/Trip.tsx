// The trip plan and the offline section (FE-51, design § 6 and § 9). The plan
// is the day planner (web/planner.ts, drawn by Planner.tsx and loaded on first
// open) inside a modal dialog that follows `#export`, so Back closes it and a
// reload restores a ranked plan. Offline is this app's own: the chart pack and the coastal
// snapshots, each with its saved time, and each snapshot product with the time
// its source assembled it. SC0707-10: every word is a catalogue id read at render; a status
// is kept as an id and its variables, so a language change updates it without a second save or delete.
import {useEffect, useRef, useState} from 'preact/hooks';
import {formatBytes, relativeTime} from '../../dist/offline-core.js';
import {Button, IconButton} from '../ui/Button.tsx';
import {PortDialog} from '../landing/PortInput.tsx';
import {PositionCheck} from './PositionCheck.tsx';
import {region} from '../state.ts';
import {
  KEEP_WORDS, canSaveCoastal, closeTrip, deleteCoastal, estimateWords, listPacks, loadPlanner, offlineOpen, plannerView, readCoastal, saveCoastal, savePack, savePackKept, storageLine, tripError, tripOpen, tripReady,
  type PackMeta, type Progress,
} from '../trip.ts';
import {oceanLines} from '../trip-ocean-lines.ts';
import {tidePackMessage} from '../brief/remaining-copy.ts';
import {forecastEndLine} from '../trip-forecast-end.ts';
import {language, localeOf, t, type Language, type StringId} from '../i18n.ts';
import {regionInfo, zone} from './App.tsx';

const PHASES: Readonly<Record<string, StringId>> = {files: 'trip.phase.files', tiles: 'trip.phase.tiles', shell: 'trip.phase.shell', basemap: 'trip.phase.basemap'};
const PRODUCTS: Readonly<Record<string, StringId>> = {'/api/coast/report': 'trip.product.report', '/api/coast/ocean': 'trip.product.ocean', '/api/coast/history': 'trip.product.history'};

/** A status line kept as its catalogue id and variables (and an English tail the store supplies), never as translated text. */
type Status = {id: StringId; vars?: Readonly<Record<string, string | number>>; missing?: number; tail?: string} | null;
const statusText = (s: Status, lang: Language): string => !s ? '' : t(s.id, lang, {...s.vars, ...(s.id === 'trip.status.failed' && typeof s.vars?.detail === 'string' ? {detail: tidePackMessage(s.vars.detail, lang)} : {}), ...(s.missing === undefined ? {} : {missing: s.missing ? t(s.missing === 1 ? 'trip.status.missing.one' : 'trip.status.missing', lang, {n: s.missing}) : ''})}) + (s.tail ?? '');

/** "Oct 9, 3:42 PM PDT" in the region's zone ("9 oct, 3:42 p. m. PDT" in Spanish). */
export const stamp = (iso: string, timeZone = zone(), lang: Language = 'en'): string =>
  new Date(iso).toLocaleString(localeOf(lang), {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone, timeZoneName: 'short'});

/** How long ago `iso` was: English is the shared relativeTime; Spanish keeps its thresholds. Null when the time cannot be read. */
export function agoText(iso: string, lang: Language = 'en', now = Date.now()): string | null {
  if (lang !== 'es') return relativeTime(iso, now);
  const at = Date.parse(iso);
  if (!Number.isFinite(at) || at <= 0) return null;
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 1) return t('trip.ago.now', lang);
  if (minutes < 60) return t('trip.ago.min', lang, {n: minutes});
  const hours = Math.round(minutes / 60);
  return hours < 48 ? t('trip.ago.hour', lang, {n: hours}) : t('trip.ago.day', lang, {n: Math.round(hours / 24)});
}
const Saved = ({iso, lang}: {iso: string; lang: Language}) => {
  const when = agoText(iso, lang);
  if (lang === 'es' && when === null) return <>{t('trip.time.unavailable', lang)}</>;
  return <>{when ?? ''} · <time dateTime={iso}>{stamp(iso, zone(), lang)}</time></>;
};

/** Items the save could not store: the top-level list plus the v2 phase's own (a shoreline, land-water or contour file, a base map tile); one URL counts once. */
export const packMissing = (m: PackMeta): number => new Set([...m.missing, ...m.v2?.missing ?? []]).size;

/** A saved pack's tile line: chart tiles, and base map tiles when the v2 app saved it. */
export function packTiles(m: PackMeta, lang: Language = 'en'): string {
  const zoom = m.tiles.max_zoom === null ? '' : t('trip.tiles.zoom', lang, {min: m.tiles.min_zoom, max: m.tiles.max_zoom});
  const base = m.v2 ? t('trip.tiles.base', lang, {saved: m.v2.basemap.saved, planned: m.v2.basemap.planned}) : '';
  const missing = packMissing(m);
  const gaps = missing === 0 ? '' : missing === 1 ? t('trip.tiles.missingOne', lang) : t('trip.tiles.missing', lang, {n: missing});
  return `${t('trip.tiles', lang, {saved: m.tiles.saved, planned: m.tiles.planned})}${base}${zoom}${gaps}`;
}

/** The planner-load refusal the store wrote in English, in `lang`; any other text is shown as it is. */
function loadFailed(error: string, lang: Language): string {
  if (lang !== 'es') return error;
  const [head = '', tail = ''] = t('trip.loadFailed', 'en', {detail: '\u0000'}).split('\u0000');
  return error.length >= head.length + tail.length && error.startsWith(head) && error.endsWith(tail) ? t('trip.loadFailed', lang, {detail: error.slice(head.length, error.length - tail.length)}) : error;
}

function TripDialog() {
  const ref = useRef<HTMLDialogElement>(null), open = tripOpen.value, error = tripError.value, planner = plannerView.value, lang = language.value;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { dialog.showModal(); dialog.scrollTop = 0; dialog.querySelector<HTMLElement>('#export-heading')?.focus(); }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} id="export-panel" class="app-trip" aria-labelledby="export-heading" onClose={closeTrip}>
      <div class="port-dialog-head">
        <h2 id="export-heading" tabIndex={-1}>{t('trip.title', lang)}</h2>
        <IconButton icon="close" label={t('trip.close', lang)} onClick={closeTrip} />
      </div>
      {/* RF1935-1: the status and Retry belong to an open dialog; this one is always mounted, so a closed, never-used planner would otherwise keep "Loading the trip planner" in the page. */}
      {open && !tripReady.value ? <p role="status">{error ? loadFailed(error, lang) : t('trip.loading', lang)}</p> : null}
      {open && error ? <Button size="sm" onClick={() => void loadPlanner()}>{t('trip.retry', lang)}</Button> : null}
      {planner ? <planner.View model={planner.model} open={open} /> : null}
      <PositionCheck />
      <Button icon="download" disabled={!region.value} onClick={() => { closeTrip(); offlineOpen.value = true; }}>{t('trip.legal.open', lang)}</Button>
    </dialog>
  );
}

const LEGAL_PARTS: Readonly<Record<string, StringId>> = {rules: 'trip.legal.rules', areas: 'trip.legal.areas', regulations: 'trip.legal.regulations', 'mpa-boundaries': 'trip.legal.mpa-boundaries', 'additional-closures': 'trip.legal.additional-closures'};

export function LegalChecklist({meta, lang}: {meta: PackMeta; lang: Language}) {
  const legal = meta.legal, unknown = t('trip.legal.unknown', lang);
  return <details>
    <summary>{t('trip.legal.heading', lang)}: {t(legal?.complete ? 'trip.legal.complete' : 'trip.legal.incomplete', lang)}{!legal || legal.stale ? ` · ${t('trip.legal.stale', lang)}` : ''}</summary>
    {!legal || legal.stale ? <p role="status">{t('trip.legal.stale', lang)}</p> : null}
    <p>{t('trip.legal.note', lang)}</p>
    <ul>{legal?.items.map(item => <li key={item.id}>
      <strong>{t(LEGAL_PARTS[item.id]!, lang)}: {t(item.saved ? 'trip.legal.saved' : 'trip.legal.missing', lang)}</strong>
      <p>{t('trip.legal.dates', lang, {saved: item.saved_at ?? unknown, generated: item.generated_at ?? unknown, reviewed: item.reviewed_at ?? unknown, from: item.valid_from ?? unknown, through: item.valid_through ?? unknown})}</p>
      {item.id === 'areas' ? <p>{t('trip.legal.checked', lang, {checked: item.checked_at ?? unknown})}</p> : null}
      {item.sources.map((url, i) => <a key={url} href={url} target="_blank" rel="noopener noreferrer">{t('trip.legal.source', lang, {n: i + 1})} · {new URL(url).hostname} </a>)}
    </li>)}</ul>
  </details>;
}

function ChartPack() {
  const lang = language.value, id = region.value, name = regionInfo.value?.name ?? id ?? t('trip.thisRegion', lang);
  const [packs, setPacks] = useState<{cache: string; meta: PackMeta}[] | null>(null);
  const [busy, setBusy] = useState<AbortController | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [room, setRoom] = useState<{used: number; quota: number} | null>(null);
  const [inventoryState, setInventoryState] = useState<'loading' | 'success' | 'error'>('loading');
  const refreshId = useRef(0);
  const refresh = async () => {
    const request = ++refreshId.current;
    setInventoryState('loading');
    try {
      const next = await listPacks();
      if (request !== refreshId.current) return;
      setPacks(next); setInventoryState('success');
      void storageLine().then(r => { if (request === refreshId.current) setRoom(r); });
    } catch {
      // An unreadable inventory is not evidence that the device has no packs.
      // Keep the last successful listing, if any, but qualify it below.
      if (request === refreshId.current) setInventoryState('error');
    }
  };
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 60000);
    return () => { clearInterval(timer); ++refreshId.current; };
  }, []);
  const save = async () => {
    if (!id || busy) return;
    if (!navigator.onLine) { setStatus({id: 'trip.status.offline'}); return; }
    const controller = new AbortController();
    setBusy(controller); setStatus(null);
    try {
      const {meta, keep} = await savePackKept(() => savePack(id, controller.signal, setProgress));
      setStatus({id: 'trip.status.saved', vars: {name: meta.region_name, bytes: formatBytes(meta.bytes)}, missing: packMissing(meta), ...(KEEP_WORDS[keep] ? {tail: ` ${KEEP_WORDS[keep]}`} : {})});
    } catch (e) {
      setStatus(controller.signal.aborted ? {id: 'trip.status.cancelled'} : {id: 'trip.status.failed', vars: {detail: (e as Error).message}});
    } finally { setBusy(null); setProgress(null); void refresh(); }
  };
  const remove = async (cache: string) => {
    if (busy) return;
    try { await caches.delete(cache); setStatus({id: 'trip.status.deleted'}); } catch { setStatus({id: 'trip.status.deleteFailed'}); }
    finally { void refresh(); }
  };
  return (
    <section class="app-offline" aria-labelledby="app-offline-pack">
      <h3 id="app-offline-pack">{t('trip.pack.heading', lang)}</h3>
      <p>{t('trip.pack.intro', lang)}</p>
      <p>{t('trip.pack.check', lang)}</p>
      <p>{t('trip.pack.ocean', lang)}</p>
      <div class="app-offline-actions">
        <Button variant="primary" icon="download" disabled={!id || !!busy} onClick={() => void save()}>{t('trip.save', lang, {name})}</Button>
        {busy ? <Button onClick={() => busy.abort()}>{t('trip.cancel', lang)}</Button> : null}
      </div>
      {progress ? <progress max={Math.max(1, progress.total)} value={progress.done} aria-label={t('trip.saving', lang)} /> : null}
      <p role="status" aria-live="polite">{progress ? t('trip.progress', lang, {phase: PHASES[progress.phase] ? t(PHASES[progress.phase]!, lang) : progress.phase, done: progress.done, total: progress.total, bytes: formatBytes(progress.bytes)}) : statusText(status, lang)}</p>
      {inventoryState !== 'success' ? <p role="status" aria-live="polite">
        {inventoryState === 'loading' ? t('trip.checking', lang) : t('trip.checkFailed', lang)}
        {packs !== null ? t('trip.retained', lang) : ''}
      </p> : null}
      <ul class="app-offline-list">
        {packs?.length ? packs.map(({cache, meta}) => {
          const ocean = oceanLines(meta, new Date(), zone(), lang);
          return (
          <li key={cache}>
            <div><strong>{meta.region_name}</strong><span class="ui-mono">{t('trip.saved', lang)} <Saved iso={meta.saved_at} lang={lang} /> · {formatBytes(meta.bytes)}</span><span>{packTiles(meta, lang)}</span><span>{forecastEndLine(meta, new Date(), zone())}</span>
              {ocean ? <><span>{t('tripOcean.water', lang, {line: ocean.water})}</span><span>{t('tripOcean.currents', lang, {line: ocean.currents})}</span></> : null}<LegalChecklist meta={meta} lang={lang} /></div>
            <Button size="sm" disabled={!!busy} onClick={() => void remove(cache)} aria-label={t('trip.deleteAria', lang, {name: meta.region_name})}>{t('trip.delete', lang)}</Button>
          </li>
          );
        }) : inventoryState === 'success' ? <li>{t('trip.empty', lang)}</li> : null}
      </ul>
      {room ? <p>{estimateWords(room)}</p> : null}
    </section>
  );
}

type Snapshot = {saved_at: string; bytes: number; products: {path: string; bytes: number; generated_at: string}[]};
function CoastalReadings() {
  const lang = language.value;
  const [meta, setMeta] = useState<Snapshot | null | undefined>(undefined);
  const [writable, setWritable] = useState(false);
  const [busy, setBusy] = useState<AbortController | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const show = () => readCoastal().then(m => setMeta(m as Snapshot | null), () => { setMeta(null); setStatus({id: 'trip.coastal.unavailable'}); });
  useEffect(() => { void show(); void canSaveCoastal().then(setWritable, () => setWritable(false)); }, []);
  const save = async () => {
    const controller = new AbortController();
    setBusy(controller); setStatus({id: 'trip.coastal.saving'});
    try { await saveCoastal(controller.signal); setStatus(null); } catch (e) {
      setStatus({id: (e as {committed?: boolean}).committed ? 'trip.coastal.committed'
        : controller.signal.aborted ? 'trip.coastal.cancelled' : 'trip.coastal.failed'});
    } finally { setBusy(null); void show(); }
  };
  const remove = async () => {
    try { await deleteCoastal(); setStatus({id: 'trip.coastal.deleted'}); } catch { setStatus({id: 'trip.coastal.deleteFailed'}); }
    void show();
  };
  return (
    <section class="app-offline" aria-labelledby="app-offline-coastal">
      <h3 id="app-offline-coastal">{t('trip.coastal.heading', lang)}</h3>
      <p>{t('trip.coastal.intro', lang)}</p>
      <div class="app-offline-actions">
        <Button icon="download" disabled={!writable || !!busy} onClick={() => void save()}>{t('trip.coastal.save', lang)}</Button>
        {busy ? <Button onClick={() => busy.abort()}>{t('trip.cancel', lang)}</Button> : <Button disabled={!meta || !writable} onClick={() => void remove()}>{t('trip.coastal.delete', lang)}</Button>}
      </div>
      <p role="status" aria-live="polite">{status ? statusText(status, lang) : (meta ? <>{t('trip.saved', lang)} <Saved iso={meta.saved_at} lang={lang} /> · {formatBytes(meta.bytes)}</> : meta === null ? t('trip.coastal.none', lang) : t('trip.coastal.checking', lang))}</p>
      {meta ? (
        <ul class="app-offline-list">
          {meta.products.map(p => <li key={p.path}><strong>{PRODUCTS[p.path] ? t(PRODUCTS[p.path]!, lang) : p.path}</strong><span class="ui-mono">{formatBytes(p.bytes)} · {t('trip.coastal.assembled', lang)} <time dateTime={p.generated_at}>{stamp(p.generated_at, zone(), lang)}</time></span></li>)}
        </ul>
      ) : null}
    </section>
  );
}

/** Both dialogs at the app's root: the plan's stays mounted, so a layout change keeps the planner's open sections; the offline one mounts while open. */
export function Trip() {
  return (
    <>
      <TripDialog />
      {offlineOpen.value ? (
        <PortDialog open onClose={() => { offlineOpen.value = false; }} title={t('trip.saveOffline', language.value)}>
          <ChartPack />
          <CoastalReadings />
        </PortDialog>
      ) : null}
    </>
  );
}
