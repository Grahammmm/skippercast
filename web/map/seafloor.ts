// Seafloor candidates and cells in the Chart (FE-14, docs/plans/front-end/design.md § 9):
// the region's seafloor publication (docs/seafloor.md "Regional publication
// contract (M4)") read from its PMTiles archive with v1's gate, decoder and
// wording (dist/seafloor-data.js). Fail closed, as v1: nothing draws unless the
// manifest is ready and unexpired, and a refresh or expiry hides what is drawn
// before anything is fetched (the #395 race fix). Two further gates bind each
// feature to the publication: its reach must be "habitat-screened" in the
// regional ledger whose SHA-256 the manifest names (a held reach never draws),
// and a candidate needs a passed whole-polygon screen, no hold reason and its
// source rights. Every drawn feature carries its basis sentence and rights.
// Candidates are terrain screening from surveys, never evidence of fish; depth
// is nominal in each survey's own vertical reference.
//
// Erasable syntax only: tests/test_seafloor_layer.mjs imports this file by type stripping.
import {computed, effect, signal, untracked} from '@preact/signals';
import {
  FIT_STYLE, GRADE_STYLE, HABITAT_LABEL, archiveURL, decodeTile, dedupeById, habitatDetails, ledgerURL, loadManifest,
  sourceRightsDetails, tileFeatures, tilesForBounds,
} from '../../dist/seafloor-data.js';
import {PROFILE_TABLE, withinDepth, type Profile} from '../profile.ts';
import {layers, profile, region, species} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import {SEAFLOOR_SOURCE} from './layers.ts';
import type {Palette} from './palette.ts';
import {camera, coastSpecies, shownPresentation, type Camera} from './stage.ts';

export {SEAFLOOR_SOURCE};
export const SEAFLOOR_CELLS = 'seafloor-cells';
export const SEAFLOOR_FILL = 'seafloor-fill';
export const SEAFLOOR_LINE = 'seafloor-line';
export const SEAFLOOR_UNRANKED = 'seafloor-unranked';
/** Every MapLibre layer the Seafloor rail entry turns on and off, bottom to top. */
export const SEAFLOOR_LAYERS = [SEAFLOOR_CELLS, SEAFLOOR_FILL, SEAFLOOR_LINE, SEAFLOOR_UNRANKED] as const;
/** Candidates, search areas and interpreted areas are selectable; cells are not. */
export const SEAFLOOR_PICK = SEAFLOOR_FILL;
/** v1's data zoom, the `?view=` zoom it draws from and its tile cap (dist/seafloor-layer.js). */
export const TILE_ZOOM = 12, MIN_VIEW_ZOOM = 10, MAX_TILES = 64;
export const RETRY_DELAYS = [30000, 60000, 120000, 240000, 300000] as const;
/** The only ledger status whose reach may draw (src/skippercast/seafloor/publish.py). */
export const SCREENED = 'habitat-screened';
/** v1's messages (dist/seafloor-data.js manifestState, dist/seafloor-layer.js). */
export const EXPIRED = 'Seafloor screening has expired and is being refreshed';
export const INCOMPLETE = 'Seafloor publication is incomplete';
export const NO_PUBLICATION = 'No seafloor publication for this region';
const RETRY_STATES = new Set(['updating', 'unavailable']);
const MAX_DELAY = 2147483647;

export type Tone = 'strong' | 'moderate' | 'some' | 'unknown' | 'search' | 'interpreted' | 'cell';
export interface SourceRight {readonly id: string; readonly credit: string; readonly notice: string; readonly policyURL: string}
type Geometry = {readonly type: 'MultiPolygon'; readonly coordinates: number[][][][]};
export interface TileFeature {readonly properties?: Record<string, unknown>; readonly geometry: Geometry}
export interface SeafloorFeature {
  readonly id: string;
  readonly kind: 'candidate' | 'search' | 'interpreted' | 'cell';
  readonly reach: string;
  readonly properties: Record<string, unknown>;
  readonly geometry: Geometry;
  /** The depth survey (the first source) and its year. */
  readonly survey: {readonly id: string; readonly year: number | 'unknown'};
  readonly basis: string;
  readonly rights: readonly SourceRight[];
}
/** What the publication admits beyond its manifest: the screened reaches and the credits every cell carries. */
export interface Publication {readonly screened: ReadonlySet<string>; readonly rights: readonly SourceRight[]}

const parse = (value: unknown): unknown => {
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { return value; }
};
const KINDS: Readonly<Record<string, SeafloorFeature['kind']>> = {habitat: 'candidate', 'search-area': 'search', 'classified-area': 'interpreted'};
const NOTICE = 'Planning only. Not a navigation chart. Check current CDFW regulations.';
const CELL_BASIS = 'Surveyed 250 m cell: at least a quarter of its provisional reference band has valid original survey depth; coverage only, with no habitat rank.';

/** A habitat feature that may draw, with its basis and rights, or null for anything held, unscreened or uncredited. */
export function admitHabitat(feature: TileFeature, pub: Publication): SeafloorFeature | null {
  const p = feature.properties ?? {};
  const {id, reach, status} = p;
  if (typeof id !== 'string' || !id || typeof reach !== 'string' || !pub.screened.has(reach)) return null;
  if (typeof status !== 'string' || !Object.hasOwn(KINDS, status)) return null;
  const screen = parse(p.screen) as {status?: unknown} | null, holds = parse(p.hold_reasons);
  if (screen?.status !== 'pass' || !Array.isArray(holds) || holds.length || p.habitat_quality_hold) return null;
  const rights = sourceRightsDetails(p.source_rights) as SourceRight[];
  if (!rights.length) return null;
  const kind = KINDS[status]!, d = habitatDetails(p);
  const survey = {id: d.source.ids[0] ?? 'unknown', year: d.source.year};
  const grid = `survey ${survey.id}, ${survey.year}, on a ${d.source.resolution} grid`;
  const coarse = Number(p.resolution_m) > 4 ? ' Broad area, not an individual pile.' : '';
  const basis = kind === 'candidate'
    ? `${HABITAT_LABEL}. Nominal depth (${d.source.datum}); verify on your sounder.${coarse} Terrain screening of ${grid}; fish presence is unverified.`
    : kind === 'search'
      ? `Measured rough-bottom search area, unranked: surrounding measurements cannot support a terrain grade. Nominal depth (${d.source.datum}); search with your sounder. From ${grid}; fish presence is unverified.`
      : `${d.title}, unranked: terrain grade and species fit are unknown. Within the nominal 25–300 ft band (vertical datum ${d.source.datum}); verify on your sounder. From the publisher's interpretation of ${d.source.ids.join(' and ') || 'its survey'}; fish presence is unverified.`;
  return {id, kind, reach, properties: p, geometry: feature.geometry, survey, basis, rights};
}

/** A coverage cell (tier 1 or more) of a screened reach, carrying the publication's credits; blank water stays blank. */
export function admitCell(feature: TileFeature, pub: Publication): SeafloorFeature | null {
  const p = feature.properties ?? {};
  if (typeof p.id !== 'string' || !p.id || typeof p.reach !== 'string' || !pub.screened.has(p.reach)) return null;
  if (!(Number(p.tier) >= 1) || !pub.rights.length) return null;
  return {id: `cell:${p.id}`, kind: 'cell', reach: p.reach, properties: p, geometry: feature.geometry,
    survey: {id: typeof p.source_id === 'string' ? p.source_id : 'unknown', year: 'unknown'}, basis: CELL_BASIS, rights: pub.rights};
}

/** The publication's credits from its manifest, for the coverage cells. */
export function publicationRights(manifest: Pick<Manifest, 'source_attribution' | 'source_use_notice'>): SourceRight[] {
  const credits = Array.isArray(manifest.source_attribution) ? manifest.source_attribution : [];
  const notice = typeof manifest.source_use_notice === 'string' ? manifest.source_use_notice : '';
  if (!notice || !credits.length || credits.some(c => typeof c !== 'string' || !c)) return [];
  return credits.map(credit => ({id: 'publication', credit: credit as string, notice, policyURL: ''}));
}

export async function sha256(bytes: ArrayBuffer): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
}

/** The habitat-screened reaches of the publication's own ledger, or null unless the ledger's bytes match `ledger_sha256`. */
export async function screenedReaches(id: string, manifest: Pick<Manifest, 'ledger_sha256'>, fetchFn: typeof fetch): Promise<Set<string> | null> {
  try {
    const response = await fetchFn(ledgerURL(id), {cache: 'no-store'});
    if (!response.ok || typeof manifest.ledger_sha256 !== 'string') return null;
    const bytes = await response.arrayBuffer();
    if (await sha256(bytes) !== manifest.ledger_sha256) return null;
    const ledger = JSON.parse(new TextDecoder().decode(bytes)) as {region?: unknown; reaches?: unknown};
    if (ledger.region !== id || !Array.isArray(ledger.reaches)) return null;
    return new Set(ledger.reaches.filter(r => r?.region === id && r?.status === SCREENED && typeof r.id === 'string').map(r => r.id as string));
  } catch { return null; }
}

const RANK: Readonly<Record<string, Tone>> = {A: 'strong', B: 'moderate', C: 'some', 3: 'strong', 2: 'moderate', 1: 'some'};
/** A feature's colour role: terrain grade or the fit key's value for candidates; a fixed role otherwise. */
export function toneOf(f: SeafloorFeature, view: string): Tone {
  if (f.kind !== 'candidate') return f.kind;
  const value = String(view === 'terrain' ? f.properties.terrain_grade : f.properties[view]);
  return Object.hasOwn(RANK, value) ? RANK[value]! : 'unknown';
}

/** The publication's species-fit key for a target (`fit_lingcod`), or null for a target without one. */
export function fitKey(target: string | null, p: Profile): string | null {
  const group = coastSpecies(target, p);
  return group === 'all' ? null : `fit_${group.replace(/-/g, '_')}`;
}
const fitName = (key: string): string => key.slice(4).replace(/_/g, ' ');

export type SeafloorCollection = {type: 'FeatureCollection'; features: {type: 'Feature'; properties: {id: string; tone: Tone}; geometry: Geometry}[]};
export const EMPTY: SeafloorCollection = Object.freeze({type: 'FeatureCollection', features: []}) as SeafloorCollection;
export const collection = (features: readonly SeafloorFeature[], view: string): SeafloorCollection =>
  ({type: 'FeatureCollection', features: features.map(f => ({type: 'Feature', properties: {id: f.id, tone: toneOf(f, view)}, geometry: f.geometry}))});

/** The empty GeoJSON source the Chart style starts with. */
export const seafloorSource = () => ({type: 'geojson' as const, data: EMPTY});

/** The four layers, hidden until the publication admits something; the depth ramp ranks grade and fit (strongest brightest). */
export function seafloorLayers(p: Palette) {
  const color = ['match', ['get', 'tone'], 'strong', p.depth0, 'moderate', p.depth1, 'some', p.depth2, 'search', p.amber, 'interpreted', p.blue, p.muted];
  const of = (tones: Tone[]) => ['in', ['get', 'tone'], ['literal', tones]];
  const layout = {visibility: 'none'};
  return [
    {id: SEAFLOOR_CELLS, type: 'fill', source: SEAFLOOR_SOURCE, filter: of(['cell']), layout, paint: {'fill-color': p.depth3, 'fill-opacity': 0.35}},
    {id: SEAFLOOR_FILL, type: 'fill', source: SEAFLOOR_SOURCE, filter: ['!', of(['cell'])], layout,
      paint: {'fill-color': color, 'fill-opacity': ['match', ['get', 'tone'], ['search', 'interpreted'], 0.12, 'unknown', 0.2, 0.5]}},
    {id: SEAFLOOR_LINE, type: 'line', source: SEAFLOOR_SOURCE, filter: of(['strong', 'moderate', 'some', 'unknown']), layout, paint: {'line-color': color, 'line-width': 1}},
    {id: SEAFLOOR_UNRANKED, type: 'line', source: SEAFLOOR_SOURCE, filter: of(['search', 'interpreted']), layout,
      paint: {'line-color': color, 'line-width': 1.5, 'line-dasharray': [3, 2]}},
  ];
}

/** The legend's key for a view, in v1's words (dist/seafloor-data.js GRADE_STYLE, FIT_STYLE). */
export function legendKey(view: 'terrain' | 'fit'): [Tone, string][] {
  const ranked: [Tone, string][] = view === 'terrain'
    ? [['strong', GRADE_STYLE.A.label], ['moderate', GRADE_STYLE.B.label], ['some', GRADE_STYLE.C.label]]
    : [['strong', FIT_STYLE[3].label], ['moderate', FIT_STYLE[2].label], ['some', FIT_STYLE[1].label], ['unknown', 'Fit unknown']];
  return [...ranked, ['search', 'Rough-bottom search area · unranked'], ['interpreted', 'Interpreted rock habitat · unranked'], ['cell', 'Surveyed 250 m cell']];
}

/** The legend's survey line, "Surveys a (2010), b (2008) and 2 more": at most three named. */
export function surveyLine(surveys: readonly string[]): string {
  const named = surveys.slice(0, 3).join(', '), more = surveys.length - 3;
  return `${surveys.length === 1 ? 'Survey' : 'Surveys'} ${named}${more > 0 ? ` and ${more} more` : ''}`;
}

/** The mark card for a drawn feature: what it is, its nominal depth, its survey, and its basis with the source credits. */
export function seafloorMark(f: SeafloorFeature, view: string): ChartMark {
  const d = habitatDetails(f.properties), fit = view === 'terrain' ? null : f.properties[view];
  const kind = f.kind === 'candidate'
    ? [`Terrain grade ${d.grade}`, view === 'terrain' ? '' : [1, 2, 3].includes(fit as number) ? `fits ${fitName(view)} habitat ${fit} of 3` : `${fitName(view)} fit unknown`].filter(Boolean).join(' · ')
    : f.kind === 'search' ? 'Rough-bottom search area · unranked' : 'Interpreted rock habitat · unranked';
  const notice = typeof f.properties.planning_notice === 'string' ? f.properties.planning_notice : NOTICE;
  return {
    id: `seafloor:${f.id}`, name: f.kind === 'candidate' ? HABITAT_LABEL : d.title, kind, reading: d.depth,
    source: `Survey ${f.survey.id} · ${f.survey.year} · ${d.source.resolution} grid`,
    basis: [f.basis, ...f.rights.map(r => `${r.credit} ${r.notice}`), notice].join(' '),
  };
}

/** The map's [west, south, east, north] for a north-up camera (`?view=` zoom, 256 px tiles) and a size in CSS pixels. */
export function viewBounds(c: Camera, width: number, height: number): [number, number, number, number] {
  const world = 256 * 2 ** c.zoom, s = Math.sin(c.latitude * Math.PI / 180);
  const x = (c.longitude + 180) / 360 * world, y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * world;
  const lon = (px: number) => px / world * 360 - 180, lat = (py: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * py / world))) * 180 / Math.PI;
  return [lon(x - width / 2), lat(y + height / 2), lon(x + width / 2), lat(y - height / 2)];
}

export type SeafloorStatus = 'off' | 'checking' | 'ready' | 'held' | 'updating' | 'expired' | 'unavailable';
export interface SeafloorState {
  readonly status: SeafloorStatus;
  readonly note: string;
  /** The view drawn and the target's fit name when the drawn candidates carry it ("lingcod"). */
  readonly view: 'terrain' | 'fit';
  readonly fit: string | null;
  /** Depth surveys of the drawn features with their years ("csumb-scc-block11-2m-native (2010)"). */
  readonly surveys: readonly string[];
  readonly credits: readonly string[];
  readonly drawn: number;
}
const OFF: SeafloorState = Object.freeze({status: 'off', note: '', view: 'terrain', fit: null, surveys: [], credits: [], drawn: 0});
export const seafloorState = signal<SeafloorState>(OFF);
/** Terrain grade or the target's species fit; species fit draws only where the publication carries it. */
export const seafloorView = signal<'terrain' | 'fit'>('fit');

export interface ArchiveHeader {readonly minLon: number; readonly minLat: number; readonly maxLon: number; readonly maxLat: number; readonly maxZoom: number}
export interface ArchiveReader {getHeader(): Promise<ArchiveHeader>; getZxy(z: number, x: number, y: number): Promise<{data: ArrayBuffer} | undefined>}
export interface SeafloorEngine {setVisible(layerId: string, visible: boolean): void; setData(sourceId: string, data: SeafloorCollection): void}
export interface SeafloorOptions {
  engine: SeafloorEngine;
  /** A PMTiles reader for the archive's absolute URL. */
  open(url: string): ArchiveReader;
  /** The Chart's size in CSS pixels. */
  size(): {width: number; height: number};
  fetchFn?: typeof fetch;
  page?: () => string;
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (id: unknown) => void;
  /** Called whenever drawn features leave the map, so a card showing one can close. */
  onHide?: () => void;
}
/** The manifest fields this layer reads (docs/seafloor.md "URLs and layers"). */
export interface Manifest {
  readonly region: string; readonly archive_sha256: string; readonly expires_at: string;
  readonly ledger_sha256?: unknown; readonly source_attribution?: unknown; readonly source_use_notice?: unknown;
}
type Gate = {state: string; reason: string; published?: boolean; manifest?: Manifest};
type Tile = {habitat: TileFeature[]; cells: TileFeature[]};

export function createSeafloor(o: SeafloorOptions): {mark(id: string): ChartMark | null; destroy(): void} {
  const {engine, fetchFn = (...a) => fetch(...a), page = () => location.href, now = Date.now} = o;
  const setTimer = o.setTimer ?? ((fn, ms) => { const t = setTimeout(fn, ms) as unknown as {unref?: () => void}; t.unref?.(); return t; });
  const clearTimer = o.clearTimer ?? (t => clearTimeout(t as ReturnType<typeof setTimeout>));
  let state: SeafloorStatus = 'off', enabling = 0, loading = 0, attempt = 0, timer: unknown = null, alive = true, shown = false;
  let manifest: Gate['manifest'] | null = null, pub: Publication | null = null, archive: ArchiveReader | null = null, header: ArchiveHeader | null = null;
  // `drawn` holds the selectable features; `filled` says whether the source holds anything, cells included.
  let archiveKey = '', drawn = new Map<string, SeafloorFeature>(), view = 'terrain', filled = false;
  const tiles = new Map<string, Promise<Tile>>();
  const publish = (s: Partial<SeafloorState>) => { seafloorState.value = {...OFF, ...s}; };
  const cancel = () => { if (timer !== null) clearTimer(timer); timer = null; };
  const schedule = (ms: number) => { cancel(); timer = setTimer(() => { timer = null; void enable(true); }, ms); };
  function hide(): void {
    if (shown) for (const id of SEAFLOOR_LAYERS) engine.setVisible(id, false);
    if (shown || filled) { engine.setData(SEAFLOOR_SOURCE, EMPTY); o.onHide?.(); }
    shown = false; filled = false; drawn = new Map();
  }
  function drop(): void { archive = null; header = null; archiveKey = ''; tiles.clear(); }
  function fail(status: SeafloorStatus, reason: string, retry: boolean): void {
    state = status; drop(); hide();
    const delay = retry ? RETRY_DELAYS[attempt++] : undefined;
    if (delay !== undefined) schedule(delay);
    publish({status, note: delay !== undefined ? `${reason} · retrying in ${delay / 1000}s` : retry ? `${reason} · toggle layer to retry` : reason});
  }
  /** v1's currentPublication: past `expires_at`, hide everything before any refresh. */
  function current(): boolean {
    if (state !== 'ready' || !manifest) return false;
    if (Date.parse(manifest.expires_at) > now()) return true;
    state = 'expired'; ++loading; drop(); hide();
    publish({status: 'expired', note: EXPIRED});
    return false;
  }

  async function enable(retry = false): Promise<void> {
    if (!alive) return;
    cancel();
    const request = ++enabling; ++loading;
    // A pending refresh must never leave an old publication visible (v1, #395).
    state = 'checking'; hide();
    const id = region.peek();
    if (!on.peek() || !id) { state = 'off'; publish(OFF); return; }
    if (!retry) attempt = 0;
    publish({status: 'checking', note: 'Checking seafloor publication…'});
    const gate = await loadManifest(id, fetchFn, now()) as Gate;
    if (request !== enabling) return;
    if (gate.state !== 'ready' || !gate.manifest) {
      if (gate.published === false) fail('unavailable', NO_PUBLICATION, false);
      else fail(gate.state as SeafloorStatus, gate.reason, RETRY_STATES.has(gate.state));
      return;
    }
    const screened = await screenedReaches(id, gate.manifest, fetchFn);
    if (request !== enabling) return;
    if (!screened) { fail('unavailable', INCOMPLETE, true); return; }
    const key = `${id}:${gate.manifest.archive_sha256}`;
    if (key !== archiveKey) drop();
    manifest = gate.manifest;
    pub = {screened, rights: publicationRights(manifest)};
    try {
      archive ??= o.open(new URL(archiveURL(id), page()).href);
      archiveKey = key;
      header = await archive.getHeader();
    } catch {
      if (request === enabling) fail('unavailable', 'Seafloor layer unavailable · try again later', false);
      return;
    }
    if (request !== enabling) return;
    attempt = 0; state = 'ready';
    if (!current()) return;
    schedule(Math.min(Date.parse(manifest.expires_at) - now(), MAX_DELAY));
    if (!shown) { for (const layer of SEAFLOOR_LAYERS) engine.setVisible(layer, true); shown = true; }
    await draw();
  }

  async function draw(): Promise<void> {
    if (!alive || state !== 'ready' || !current() || shownPresentation.peek() !== 'chart') return;
    const at = camera.peek(), head = header, reader = archive, admit = pub;
    if (!at || !head || !reader || !admit) return;
    const ready = (note: string, more: Partial<SeafloorState> = {}) => publish({status: 'ready', note, ...more});
    const clear = (note: string) => { if (filled) { engine.setData(SEAFLOOR_SOURCE, EMPTY); filled = false; drawn = new Map(); o.onHide?.(); } ready(note); };
    if (at.zoom < MIN_VIEW_ZOOM) return clear('Zoom in to see seafloor candidates');
    const {width, height} = o.size();
    const [w, s, e, n] = viewBounds(at, width, height);
    const box: [number, number, number, number] = [Math.max(w, head.minLon), Math.max(s, head.minLat), Math.min(e, head.maxLon), Math.min(n, head.maxLat)];
    if (box[0] >= box[2] || box[1] >= box[3]) return clear('No published seafloor survey in this view; the rest of the coast is unassessed');
    const wanted = tilesForBounds(box, Math.min(TILE_ZOOM, head.maxZoom)) as [number, number, number][];
    if (wanted.length > MAX_TILES) return clear('Zoom in to load seafloor candidates');
    const token = ++loading;
    let parts: Tile[];
    try {
      parts = await Promise.all(wanted.map(([z, x, y]) => tile(reader, z, x, y)));
    } catch {
      if (token === loading) ready('Seafloor candidates could not load · try again');
      return;
    }
    if (token !== loading || !current()) return;
    const p = profile.peek(), limit = PROFILE_TABLE[p].maxDepthFt;
    const admitted = (dedupeById(parts.flatMap(t => t.habitat)) as TileFeature[]).map(f => admitHabitat(f, admit)).filter(f => f !== null);
    const habitat = admitted.filter(f => withinDepth(p, Number.isFinite(f.properties.depth_min_ft) ? f.properties.depth_min_ft as number : null));
    const cells = (dedupeById(parts.flatMap(t => t.cells)) as TileFeature[]).map(f => admitCell(f, admit)).filter(f => f !== null);
    const key = fitKey(species.peek(), p), fit = key && habitat.some(f => f.kind === 'candidate' && Object.hasOwn(f.properties, key)) ? key : null;
    view = seafloorView.peek() === 'fit' && fit ? fit : 'terrain';
    drawn = new Map(habitat.map(f => [f.id, f]));
    engine.setData(SEAFLOOR_SOURCE, collection([...cells, ...habitat], view));
    filled = cells.length + habitat.length > 0;
    const ranked = habitat.filter(f => f.kind === 'candidate').length, deeper = admitted.length - habitat.length;
    ready([`${ranked} candidate${ranked === 1 ? '' : 's'} · ${habitat.length - ranked} unranked in view`,
      deeper ? `${deeper} deeper than the ${PROFILE_TABLE[p].label} limit (${limit} ft nominal) left out` : ''].filter(Boolean).join(' · '), {
      view: view === 'terrain' ? 'terrain' : 'fit', fit: fit ? fitName(fit) : null, drawn: habitat.length + cells.length,
      surveys: [...new Set(habitat.map(f => `${f.survey.id} (${f.survey.year})`))].sort(),
      credits: [...new Set([...habitat, ...cells].flatMap(f => f.rights.map(r => r.credit)))],
    });
  }

  function tile(reader: ArchiveReader, z: number, x: number, y: number): Promise<Tile> {
    const key = `${z}/${x}/${y}`;
    let pending = tiles.get(key);
    if (!pending) {
      pending = reader.getZxy(z, x, y).then(t => {
        if (!t) return {habitat: [], cells: []};
        const decoded = decodeTile(new Uint8Array(t.data));
        return {habitat: tileFeatures(decoded, 'habitat', z, x, y) as TileFeature[], cells: tileFeatures(decoded, 'cells', z, x, y) as TileFeature[]};
      });
      const mine = pending;
      mine.catch(() => { if (tiles.get(key) === mine) tiles.delete(key); });
      tiles.set(key, mine);
    }
    return pending;
  }

  const on = computed(() => layers.value.includes('seafloor'));
  const disposers = [
    effect(() => { on.value; region.value; untracked(() => void enable()); }),
    effect(() => { camera.value; shownPresentation.value; profile.value; species.value; seafloorView.value; untracked(() => void draw()); }),
  ];
  return {
    mark(id) { const f = drawn.get(id); return f ? seafloorMark(f, view) : null; },
    destroy() {
      if (!alive) return;
      alive = false; ++enabling; ++loading; cancel();
      for (const dispose of disposers) dispose();
      drop(); drawn = new Map(); seafloorState.value = OFF;
    },
  };
}
