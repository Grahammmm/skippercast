// The trip plan and the offline section (FE-51, design § 6 and § 9). The plan
// is the day planner (web/planner.ts, drawn by Planner.tsx and loaded on first
// open) inside a modal dialog that follows `#export`, so Back closes it and a
// reload restores a ranked plan. Offline is this app's own: the chart pack and the coastal
// snapshots, each with its saved time, and each snapshot product with the time
// its source assembled it.
import {useEffect, useRef, useState} from 'preact/hooks';
import {formatBytes, relativeTime} from '../../dist/offline-core.js';
import {Button, IconButton} from '../ui/Button.tsx';
import {PortDialog} from '../landing/PortInput.tsx';
import {region} from '../state.ts';
import {
  canSaveCoastal, closeTrip, deleteCoastal, listPacks, loadPlanner, offlineOpen, plannerView, readCoastal, saveCoastal, savePack, tripError, tripOpen, tripReady,
  type PackMeta, type Progress,
} from '../trip.ts';
import {regionInfo, zone} from './App.tsx';

const PHASES: Readonly<Record<string, string>> = {files: 'Data and rules', tiles: 'NOAA chart tiles', shell: 'This app', basemap: 'Base map tiles'};
const PRODUCTS: Readonly<Record<string, string>> = {'/api/coast/report': 'Local report', '/api/coast/ocean': 'Surface currents', '/api/coast/history': 'Measured history'};

/** "Oct 9, 3:42 PM PDT" in the region's zone. */
export const stamp = (iso: string, timeZone = zone()): string =>
  new Date(iso).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone, timeZoneName: 'short'});
const Saved = ({iso}: {iso: string}) => <>{relativeTime(iso) ?? ''} · <time dateTime={iso}>{stamp(iso)}</time></>;

/** A saved pack's tile line: chart tiles, and base map tiles when the v2 app saved it. */
export function packTiles(m: PackMeta): string {
  const zoom = m.tiles.max_zoom === null ? '' : ` (zoom ${m.tiles.min_zoom}–${m.tiles.max_zoom})`;
  const base = m.v2 ? ` · ${m.v2.basemap.saved} of ${m.v2.basemap.planned} base map tiles` : '';
  return `${m.tiles.saved} of ${m.tiles.planned} chart tiles${base}${zoom}${m.missing.length ? ` · ${m.missing.length} items missing` : ''}`;
}

function TripDialog() {
  const ref = useRef<HTMLDialogElement>(null), open = tripOpen.value, error = tripError.value, planner = plannerView.value;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { dialog.showModal(); dialog.scrollTop = 0; dialog.querySelector<HTMLElement>('#export-heading')?.focus(); }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} id="export-panel" class="app-trip" aria-labelledby="export-heading" onClose={closeTrip}>
      <div class="port-dialog-head">
        <h2 id="export-heading" tabIndex={-1}>Trip plan and GPX</h2>
        <IconButton icon="close" label="Close the trip plan" onClick={closeTrip} />
      </div>
      {tripReady.value ? null : <p role="status">{error || 'Loading the trip planner…'}</p>}
      {error ? <Button size="sm" onClick={() => void loadPlanner()}>Try again</Button> : null}
      {planner ? <planner.View model={planner.model} open={open} /> : null}
    </dialog>
  );
}

function ChartPack() {
  const id = region.value, name = regionInfo.value?.name ?? id ?? 'this region';
  const [packs, setPacks] = useState<{cache: string; meta: PackMeta}[] | null>(null);
  const [busy, setBusy] = useState<AbortController | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [status, setStatus] = useState('');
  const [inventoryState, setInventoryState] = useState<'loading' | 'success' | 'error'>('loading');
  const refreshId = useRef(0);
  const refresh = async () => {
    const request = ++refreshId.current;
    setInventoryState('loading');
    try {
      const next = await listPacks();
      if (request !== refreshId.current) return;
      setPacks(next); setInventoryState('success');
    } catch {
      // An unreadable inventory is not evidence that the device has no packs.
      // Keep the last successful listing, if any, but qualify it below.
      if (request === refreshId.current) setInventoryState('error');
    }
  };
  useEffect(() => { void refresh(); return () => { ++refreshId.current; }; }, []);
  const save = async () => {
    if (!id || busy) return;
    if (!navigator.onLine) { setStatus('You are offline. Connect to save this region; saved regions are unchanged.'); return; }
    const controller = new AbortController();
    setBusy(controller); setStatus('');
    try {
      const meta = await savePack(id, controller.signal, setProgress);
      setStatus(`Saved ${meta.region_name} · ${formatBytes(meta.bytes)}.${meta.missing.length ? ` ${meta.missing.length} items could not be saved and will be missing offline.` : ''}`);
    } catch (e) {
      setStatus(controller.signal.aborted ? 'Cancelled. Nothing new was saved.' : `Could not save: ${(e as Error).message}`);
    } finally { setBusy(null); setProgress(null); void refresh(); }
  };
  const remove = async (cache: string) => { await caches.delete(cache); setStatus('Saved region deleted.'); void refresh(); };
  return (
    <section class="app-offline" aria-labelledby="app-offline-pack">
      <h3 id="app-offline-pack">Chart pack</h3>
      <p>Saves the region's data, rules, protected areas, latest forecast, NOAA chart tiles, base map at zoom 8–12 and this app on this device. The list below shows when each region was saved.</p>
      <p>Check the saved pack before leaving coverage.</p>
      <p>Water temp and current tiles are not prefetched. Recently viewed tiles may be saved; coverage varies. For Morro Bay and Cambria, save Coastal readings below for water temperature and currents.</p>
      <div class="app-offline-actions">
        <Button variant="primary" icon="download" disabled={!id || !!busy} onClick={() => void save()}>Save {name} for offline</Button>
        {busy ? <Button onClick={() => busy.abort()}>Cancel</Button> : null}
      </div>
      {progress ? <progress max={Math.max(1, progress.total)} value={progress.done} aria-label="Saving" /> : null}
      <p role="status" aria-live="polite">{progress ? `${PHASES[progress.phase] ?? progress.phase} · ${progress.done} of ${progress.total} · ${formatBytes(progress.bytes)}` : status}</p>
      {inventoryState !== 'success' ? <p role="status" aria-live="polite">
        {inventoryState === 'loading' ? 'Checking saved regions…' : 'Saved regions could not be checked. Offline storage may be unavailable.'}
        {packs !== null ? ' Last checked listing; not rechecked.' : ''}
      </p> : null}
      <ul class="app-offline-list">
        {packs?.length ? packs.map(({cache, meta}) => (
          <li key={cache}>
            <div><strong>{meta.region_name}</strong><span class="ui-mono">Saved <Saved iso={meta.saved_at} /> · {formatBytes(meta.bytes)}</span><span>{packTiles(meta)}</span></div>
            <Button size="sm" onClick={() => void remove(cache)} aria-label={`Delete the saved ${meta.region_name}`}>Delete</Button>
          </li>
        )) : inventoryState === 'success' ? <li>Nothing saved on this device yet.</li> : null}
      </ul>
    </section>
  );
}

type Snapshot = {saved_at: string; bytes: number; products: {path: string; bytes: number; generated_at: string}[]};
function CoastalReadings() {
  const [meta, setMeta] = useState<Snapshot | null | undefined>(undefined);
  const [writable, setWritable] = useState(false);
  const [busy, setBusy] = useState<AbortController | null>(null);
  const [status, setStatus] = useState('');
  const show = () => readCoastal().then(m => setMeta(m as Snapshot | null), () => { setMeta(null); setStatus('Offline storage is unavailable. Online readings remain usable.'); });
  useEffect(() => { void show(); void canSaveCoastal().then(setWritable, () => setWritable(false)); }, []);
  const save = async () => {
    const controller = new AbortController();
    setBusy(controller); setStatus('Saving the three public snapshots…');
    try { await saveCoastal(controller.signal); setStatus(''); } catch (e) {
      setStatus((e as {committed?: boolean}).committed ? 'New readings saved; clearing the older copy failed. Delete them to clear both.'
        : controller.signal.aborted ? 'Save cancelled. Previous saved readings are unchanged.' : 'Save failed. Previous saved readings are unchanged; check the connection or storage.');
    } finally { setBusy(null); void show(); }
  };
  const remove = async () => {
    try { await deleteCoastal(); setStatus('Saved readings deleted.'); } catch { setStatus('Saved readings could not be deleted. Offline storage may be unavailable.'); }
    void show();
  };
  return (
    <section class="app-offline" aria-labelledby="app-offline-coastal">
      <h3 id="app-offline-coastal">Coastal readings</h3>
      <p>The public SLO report, surface currents and measured history as published, each with its source time. Terrain and imagery stay online.</p>
      <div class="app-offline-actions">
        <Button icon="download" disabled={!writable || !!busy} onClick={() => void save()}>Save coastal readings</Button>
        {busy ? <Button onClick={() => busy.abort()}>Cancel</Button> : <Button disabled={!meta || !writable} onClick={() => void remove()}>Delete saved readings</Button>}
      </div>
      <p role="status" aria-live="polite">{status || (meta ? <>Saved <Saved iso={meta.saved_at} /> · {formatBytes(meta.bytes)}</> : meta === null ? 'No coastal readings saved.' : 'Checking saved readings…')}</p>
      {meta ? (
        <ul class="app-offline-list">
          {meta.products.map(p => <li key={p.path}><strong>{PRODUCTS[p.path] ?? p.path}</strong><span class="ui-mono">{formatBytes(p.bytes)} · source assembled <time dateTime={p.generated_at}>{stamp(p.generated_at)}</time></span></li>)}
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
        <PortDialog open onClose={() => { offlineOpen.value = false; }} title="Save for offline">
          <ChartPack />
          <CoastalReadings />
        </PortDialog>
      ) : null}
    </>
  );
}
