// The day planner's state and actions (FE-51, #602): v2 signals over the
// shared export contract, replacing v1's dist/export-ui.js closure. The draft
// keeps v1's key and shape (trip-export.js `draftKey`, `readDraft`), so a plan
// saved before the port opens unchanged; selection, ranking, the protected-area
// screen and the GPX bytes are the same modules (trip-export.js, gpx.js,
// spot-ranking.js, reef-trip-data.js). web/app/Planner.tsx renders it; web/trip.ts
// builds it on first use with the region's atlas, screen and the Chart's view.
//
// A selection revision guards the slow calls: a change made while Best available
// or a restore loads wins over that call's answer, as in v1.
//
// Erasable syntax only: the node tests import this file by type stripping.
import {batch, computed, effect, signal, untracked} from '@preact/signals';
import {buildExport, draftKey, exportPresetTargets, isMeasuredTarget, offlineNotes, protectedPlanHits, protectedPlanNotes, readDraft} from '../dist/trip-export.js';
import {loadReefTrip} from '../dist/reef-trip-data.js';
import {bestSpots, waypointTitle} from '../dist/spot-ranking.js';
import {HOME_PORT_KEY} from '../dist/home-port.js';
import {track} from './telemetry.ts';

export type Layers = {waypoints: boolean; outlines: boolean; alignments: boolean; exclusions: boolean};
export type LayerKey = keyof Layers;
export type TripSpecies = 'reef' | 'lingcod' | 'rockfish';
export type RankedDraft = {sha256: string; species: TripSpecies; priorities: {id: string; rank: number}[]};
export type Draft = {ids: string[]; rankedPlan: RankedDraft | null; name: string; date: string; avoidScope: 'map' | 'region'; layers: Layers};
export type Target = {
  id: string; label: string; name?: string; latitude: number; longitude: number; habitat_grade?: string; canonical_habitat?: boolean;
  trip_rank?: number; trip_fit?: number; trip_species?: string; evidence_confidence?: {percent: number};
  neighborhood_depth_ft?: number[]; center_depth_ft?: number | null; terrain_interpretation?: string; species_fit?: Record<string, number>;
};
export type Area = {id: string};
export type ProtectedHit = {id: string; label: string; matches: {name: string; url: string; agency: string}[]};
export type Publication = {export_sha256?: string} & Record<string, unknown>;
export type Atlas = {targets: Target[]; areas: Area[]; drifts?: unknown[]; publication?: Publication; source_validation_date?: string};
export type Reefs = {targets: Target[]; areas: Area[]; publication: Publication & {export_sha256: string}; source_validation_date?: string};
/** The 2D-map calls the planner makes (web/trip.ts `mapView`). */
export type MapView = {
  getSize(): {x: number; y: number};
  getBounds(): {getWest(): number; getEast(): number; getNorth(): number; getSouth(): number; contains(p: [number, number]): boolean};
};
export type Port = {id: string; name: string; region: string; match: [number, number]};
export type Filters = {species: TripSpecies; limit: number; depth: number; scope: 'region' | 'map'; port: string; distance: number};
export type Preset = 'map' | 'filtered' | 'region' | 'none';
export type RankedDetail = {targets: Target[]; areas: Area[]; publication?: Publication; fit?: boolean};
export type Summary =
  | {ok: true; counts: {waypoints: number; tracks: number; outlines: number; alignments: number; exclusions: number; trackPoints: number; largestTrack: number}}
  | {ok: false; message: string};
type Region = {id: string; timezone: string; mpa: {bounds: number[]}};

export interface PlannerDeps {
  atlas: Atlas;
  /** dist/protected-areas.js's screen, passed through to the export contract. */
  screen: unknown;
  /** v1's region object (dist/region.js `getRegion`), which the export contract reads. */
  region: Region;
  map: MapView;
  /** The atlas targets the Chart shows now. */
  getVisible(): Target[];
  nav: {open(): void; showMap(): void; conditions(date: string): void};
  storage?: Pick<Storage, 'getItem' | 'setItem'> | null;
  now?: () => Date;
  loadReefs?: (region: string) => Promise<Reefs>;
  loadPorts?: () => Promise<{ports?: Port[]} | null>;
  /** The Boat range to consider saved on this device (web/reach.ts, #644): the distance filter starts from it; 20 nm without one. */
  reachNm?: number | null;
  /** The ranked set the Chart draws (web/trip.ts listens for `skippercast:trip-ranked`). */
  emit?: (detail: RankedDetail) => void;
}

const LOADING = 'Loading current screened reefs…';
const STORAGE_OK = 'Saved on this browser for each region. Separate from your account’s trip alerts.';
const STORAGE_OFF = 'Browser storage is unavailable. Keep this page open until you download your plan.';
const RANKED_LAYERS: Layers = {waypoints: true, outlines: true, alignments: false, exclusions: false};

/** The next Friday on or after `today` (YYYY-MM-DD), where Best available moves an undecided date. */
export function nextFriday(today: string): string {
  const d = new Date(today + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + (5 - d.getUTCDay() + 7) % 7);
  return d.toISOString().slice(0, 10);
}

/** The ranked fit for the plan's species: lingcod, reef rockfish, or the weaker of the two. */
export function planFit(t: Target, species: TripSpecies): number | undefined {
  const fit = t.species_fit ?? {};
  return species === 'lingcod' ? fit.lingcod : species === 'rockfish' ? fit['rockfish-reef'] : Math.min(fit.lingcod ?? NaN, fit['rockfish-reef'] ?? NaN);
}

// The shared JavaScript modules type their option bags from their defaults, too narrowly to call with real values.
type Loose<T> = (...args: unknown[]) => T;
const presetTargets = exportPresetTargets as unknown as Loose<Target[]>;
const rankBest = bestSpots as unknown as Loose<Target[]>;
const reefTrip = loadReefTrip as unknown as (region: string) => Promise<Reefs>;

const dispatch = (detail: RankedDetail): void => { document.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail})); };
const fetchPorts = async (): Promise<{ports?: Port[]} | null> => { const r = await fetch('data/home-ports.json'); return r.ok ? r.json() as Promise<{ports?: Port[]}> : null; };

export type Planner = ReturnType<typeof createPlanner>;

export function createPlanner(deps: PlannerDeps) {
  const {atlas, screen, region, map} = deps;
  const storage = deps.storage === undefined ? globalThis.localStorage : deps.storage;
  const now = deps.now ?? (() => new Date());
  const loadReefs = deps.loadReefs ?? reefTrip;
  const emit = deps.emit ?? dispatch;
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: region.timezone, year: 'numeric', month: '2-digit', day: '2-digit'}).format(now());
  let raw: string | null = null;
  try { raw = storage?.getItem(draftKey(region.id)) ?? null; } catch { /* storage blocked */ }
  let savedPort: string | null = null;
  try { savedPort = storage?.getItem(HOME_PORT_KEY) ?? null; } catch { /* storage blocked */ }

  const initial = readDraft(raw, atlas, today) as Draft;
  const draft = signal<Draft>(initial);
  const tripAtlas = signal<Atlas>({...atlas, targets: [...atlas.targets], areas: [...atlas.areas]});
  const ranked = signal(false), filtersDirty = signal(false), restorePending = signal(!!initial.rankedPlan);
  const allowResearch = signal(false), search = signal(''), loading = signal(false), portsReady = signal(false);
  const filters = signal<Filters>({species: 'reef', limit: 20, depth: 300, scope: 'region', port: '', distance: deps.reachNm ?? 20});
  const ports = signal<Port[]>([]);
  const scopeStatus = signal(''), actionStatus = signal(''), storageNote = signal(STORAGE_OK);
  /** Bumped when the screen's age or the map may have changed (open, boundaries, each minute while open). */
  const tick = signal(0);
  let revision = 0, restoring = false, canonical: Reefs | null = null;

  const persist = (next: Draft): void => {
    draft.value = next;
    try { storage?.setItem(draftKey(region.id), JSON.stringify(next)); storageNote.value = STORAGE_OK; } catch { storageNote.value = STORAGE_OFF; }
  };
  const selected = (): Target[] => draft.value.ids.map(id => tripAtlas.value.targets.find(t => t.id === id)).filter((t): t is Target => !!t);
  const rankedDetail = (): RankedDetail => ({targets: selected(), areas: tripAtlas.value.areas.filter(a => draft.value.ids.includes(a.id)), publication: tripAtlas.value.publication});
  const unrank = (): void => { ranked.value = false; emit({targets: [], areas: []}); };

  /** The export contract's request for the draft; throws what blocks an export. */
  function request(d: Draft = draft.value) {
    if (restorePending.value) throw Error('Saved ranked plan needs current reef data. Restore it or select Best available again.');
    if (filtersDirty.value) throw Error('Trip filters changed. Select Best available again before exporting.');
    if (d.layers.exclusions && d.avoidScope === 'map' && !map.getSize().x) throw Error('Open the map to choose its coverage first, or choose Whole selected region for protected-area outlines.');
    const b = map.getBounds();
    return {allowResearch: allowResearch.value, atlas: tripAtlas.value, screen, ids: d.ids, layers: d.layers, region, title: `${d.name || 'My fishing day'} · ${d.date || today}`,
      bounds: d.avoidScope === 'region' ? region.mpa.bounds : [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]};
  }

  /** What the counts depend on: a plan name or date keystroke never re-runs the screen or redraws the Chart. */
  const exportKey = computed(() => { const d = draft.value; return JSON.stringify([d.ids, d.layers, d.avoidScope]); });
  const summary = computed<Summary>(() => {
    void tick.value; void exportKey.value;
    try { return {ok: true, counts: (buildExport(request(draft.peek())) as {counts: Extract<Summary, {ok: true}>['counts']}).counts}; } catch (error) { return {ok: false, message: (error as Error).message}; }
  });
  const protectedHits = computed<ProtectedHit[]>(() => {
    void tick.value;
    return protectedPlanHits(screen, selected()) as ProtectedHit[];
  });
  const notesReady = computed(() => {
    if (summary.value.ok) return true;
    try { return !!protectedPlanNotes(request(), draft.value); } catch { return false; }
  });
  const spots = computed<Target[]>(() => {
    const q = search.value.trim().toLowerCase(), r = ranked.value, ids = draft.value.ids, research = allowResearch.value;
    return tripAtlas.value.targets
      .filter(t => (isMeasuredTarget(t) || research || ids.includes(t.id)) && (!r || t.trip_rank) && `${t.id} ${t.label} ${t.habitat_grade}`.toLowerCase().includes(q))
      .sort((a, b) => r ? (a.trip_rank ?? 0) - (b.trip_rank ?? 0) : 0);
  });
  /** While ranked, every valid change redraws the ranked set on the Chart. */
  const stopRanked = effect(() => { if (ranked.value && summary.value.ok) emit(untracked(rankedDetail)); });

  const portsLoaded = (deps.loadPorts ?? fetchPorts)().then(d => {
    const list = (d?.ports ?? []).filter(p => p.region === region.id);
    batch(() => { ports.value = list; filters.value = {...filters.value, port: list.some(p => p.id === savedPort) ? savedPort! : list[0]?.id ?? ''}; });
  }).catch(() => {}).finally(() => { portsReady.value = true; });

  function setFilter<K extends keyof Filters>(key: K, value: Filters[K]): void {
    revision++;
    filters.value = {...filters.value, [key]: value};
    if (ranked.value) { filtersDirty.value = true; scopeStatus.value = 'Trip filters changed. Select Best available again to apply them.'; }
  }
  function edit(patch: Partial<Pick<Draft, 'name' | 'date' | 'avoidScope'>>): void { revision++; persist({...draft.value, ...patch}); }
  function setLayer(key: LayerKey, on: boolean): void { revision++; persist({...draft.value, layers: {...draft.value.layers, [key]: on}}); }
  function toggleSpot(id: string, on: boolean): void {
    revision++;
    const ids = draft.value.ids;
    persist({...draft.value, ids: on ? [...new Set([...ids, id])] : ids.filter(x => x !== id)});
  }
  function setResearch(on: boolean): void {
    revision++;
    allowResearch.value = on;
    scopeStatus.value = on ? 'Research-coordinate export enabled for this session. Review the evidence class for each selected point.'
      : 'Research-coordinate export disabled. Saved research selections are retained but cannot be downloaded.';
    persist(draft.value);
  }
  function preset(scope: Preset): void {
    if (scope === 'filtered' && !allowResearch.value) { scopeStatus.value = 'Enable Research-coordinate export to use filtered research references.'; return; }
    revision++;
    // The ranked plan is dropped in the page; storage keeps it until the next save, so a reload after "selection is retained" still restores it, as in v1.
    batch(() => { filtersDirty.value = false; restorePending.value = false; unrank(); draft.value = {...draft.value, rankedPlan: null}; });
    if (scope === 'map' && !map.getSize().x) { scopeStatus.value = 'Open the map to choose an area first. Your selection is retained.'; return; }
    const targets = presetTargets({scope, targets: tripAtlas.value.targets, visible: deps.getVisible(), allowResearch: allowResearch.value,
      contains: (t: Target) => map.getBounds().contains([t.latitude, t.longitude])});
    batch(() => {
      persist({...draft.value, ids: targets.map(t => t.id)});
      scopeStatus.value = `${targets.length} spots selected. ${scope === 'region' ? 'Whole-region selection ignores map filters. Review individual spots below.' : 'Your previous selection has been replaced.'}`;
    });
  }
  function add(id: string): void {
    const t = tripAtlas.value.targets.find(x => x.id === id);
    if (!t) return;
    revision++;
    batch(() => {
      if (ranked.value && !t.trip_rank) unrank();
      if (!isMeasuredTarget(t) && !allowResearch.value) scopeStatus.value = 'Saved research reference. Enable Research-coordinate export to include it in a download.';
      if (!draft.value.ids.includes(id)) { persist({...draft.value, ids: [...draft.value.ids, id]}); track('spot_saved'); } else persist(draft.value);
    });
  }
  function open(): void { deps.nav.open(); tick.value++; }

  async function selectBest(): Promise<void> {
    const mine = ++revision, f = filters.value, b = map.getBounds();
    loading.value = true;
    scopeStatus.value = LOADING;
    try {
      await portsLoaded;
      const loaded = await loadReefs(region.id);
      if (mine !== revision) return;
      const port = ports.value.find(p => p.id === f.port);
      if (f.scope === 'map' && !map.getSize().x) throw Error('Open the map first to choose its area.');
      if (f.depth > 300 || f.depth < 25 || !Number.isFinite(f.distance) || f.distance <= 0) throw Error('Choose a depth from 25–300 ft and a positive distance.');
      const best = rankBest(loaded, screen, {species: f.species, count: f.limit, maxDepth: f.depth, maxDistanceNm: f.distance,
        bounds: f.scope === 'map' ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null,
        origin: port ? {latitude: port.match[0], longitude: port.match[1]} : null});
      if (!best.length) throw Error('No ranked reefs meet these filters and current checks. Widen the area or distance; no weaker spots were added.');
      canonical = loaded;
      const d = draft.value, ids = best.map(t => t.id);
      const name = d.name === 'My fishing day' ? 'Lingcod + rockfish' : d.name, date = d.date === today ? nextFriday(today) : d.date;
      batch(() => {
        tripAtlas.value = {...tripAtlas.value, publication: loaded.publication, source_validation_date: loaded.source_validation_date,
          targets: [...atlas.targets, ...loaded.targets.map(t => best.find(s => s.id === t.id) ?? t)], areas: [...atlas.areas, ...loaded.areas]};
        filtersDirty.value = false; restorePending.value = false;
        persist({...d, ids, name, date, layers: {...RANKED_LAYERS},
          rankedPlan: {sha256: loaded.publication.export_sha256, species: f.species, priorities: best.map(t => ({id: t.id, rank: t.trip_rank!}))}});
        ranked.value = true;
        scopeStatus.value = `${best.length} distinct reef spots ranked. Waypoints + reef outlines only. ${best.length < f.limit ? 'Fewer than your requested limit qualified. ' : ''}Check conditions for ${date} before committing to the trip.`;
      });
    } catch (error) {
      if (mine === revision) scopeStatus.value = (error as Error).message;
    } finally {
      loading.value = false;
      if (mine !== revision && scopeStatus.value === LOADING) scopeStatus.value = 'Selection changed while loading. Select Best available again to apply it.';
    }
  }

  /** A saved ranked plan, re-applied from the current publication only when it is the one the plan ranked. */
  async function restore(): Promise<void> {
    if (!restorePending.value || restoring || loading.value) return;
    restoring = true;
    const mine = revision;
    try {
      const loaded = await loadReefs(region.id), plan = draft.value.rankedPlan;
      if (!restorePending.value || !plan || mine !== revision) return;
      if (plan.sha256 !== loaded.publication.export_sha256) throw Error('Saved reef data changed. Select Best available again; your saved selections have been retained for review.');
      if (plan.priorities.some(p => !loaded.targets.some(t => t.id === p.id))) throw Error('Saved reefs are unavailable. Select Best available again.');
      canonical = loaded;
      batch(() => {
        tripAtlas.value = {...tripAtlas.value, publication: loaded.publication, source_validation_date: loaded.source_validation_date, areas: [...atlas.areas, ...loaded.areas],
          targets: [...atlas.targets, ...loaded.targets.map(t => {
            const p = plan.priorities.find(x => x.id === t.id);
            if (!p) return t;
            const s: Target = {...t, trip_rank: p.rank, trip_fit: planFit(t, plan.species), trip_species: plan.species};
            s.name = waypointTitle(s) as string;
            return s;
          })]};
        filters.value = {...filters.value, species: plan.species};
        restorePending.value = false;
        ranked.value = draft.value.ids.every(id => plan.priorities.some(p => p.id === id));
        scopeStatus.value = 'Saved ranked reefs restored from the current publication. Check your trip conditions before departure.';
      });
    } catch (error) {
      if (mine === revision) scopeStatus.value = (error as Error).message;
    } finally { restoring = false; }
  }

  /** The file for `kind`, after the publication and every boundary are checked again. */
  async function exportFile(kind: 'gpx' | 'notes'): Promise<File> {
    if (draft.value.ids.some(id => tripAtlas.value.targets.find(t => t.id === id)?.canonical_habitat)) {
      const latest = await loadReefs(region.id);
      if (latest.publication.export_sha256 !== canonical?.publication.export_sha256) throw Error('Reef data changed. Select Best available again before exporting.');
      tripAtlas.value = {...tripAtlas.value, publication: latest.publication};
    }
    // Repeat the authoritative screen here, even if the preview count was valid moments ago.
    const d = draft.value;
    if (kind === 'notes') {
      const context = protectedPlanNotes(request(), {...d, date: d.date || today});
      if (context) return new File([context], `SkipperCast-${region.id}-${d.date || today}-boundary-context.html`, {type: 'text/html'});
    }
    const result = buildExport(request()) as {gpx: string; counts: {waypoints: number}};
    const base = `SkipperCast-${region.id}-${d.date || today}-${result.counts.waypoints}wp`;
    return kind === 'notes'
      ? new File([offlineNotes(result, region, {...d, date: d.date || today}) as string], `${base}.html`, {type: 'text/html'})
      : new File([result.gpx], `${base}.gpx`, {type: 'application/gpx+xml'});
  }
  const save = (file: File): void => {
    const url = URL.createObjectURL(file), a = document.createElement('a');
    a.href = url; a.download = file.name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  async function deliver(kind: 'gpx' | 'share' | 'notes'): Promise<void> {
    try {
      const file = await exportFile(kind === 'notes' ? 'notes' : 'gpx');
      if (kind === 'share' && navigator.canShare?.({files: [file]})) {
        await navigator.share({files: [file], title: draft.value.name});
        actionStatus.value = 'File handed to the share sheet. Confirm the import inside your chartplotter app.';
      } else {
        save(file);
        actionStatus.value = `Download requested: ${file.name}. Find it in Downloads or your chosen save location.${kind === 'share' ? ' This browser cannot share this file directly.' : ''}`;
      }
    } catch (error) {
      actionStatus.value = (error as Error).name === 'AbortError' ? 'Share cancelled. Your plan is retained.' : (error as Error).message;
      tick.value++;
    }
  }

  function showOnMap(): void {
    if (!ranked.value || filtersDirty.value) return;
    deps.nav.showMap();
    emit({...rankedDetail(), fit: true});
  }
  const checkConditions = (): void => { deps.nav.conditions(draft.value.date); };

  return {
    today, region, draft, tripAtlas, ranked, filtersDirty, restorePending, allowResearch, search, loading, portsReady, filters, ports,
    scopeStatus, actionStatus, storageNote, tick, summary, spots, protectedHits, notesReady,
    setFilter, edit, setLayer, toggleSpot, setResearch, preset, add, review(id: string) { add(id); open(); }, open,
    selectBest, restore, exportFile, deliver, showOnMap, checkConditions,
    /** For tests and a region change: stop drawing the ranked set. */
    dispose: stopRanked,
  };
}
