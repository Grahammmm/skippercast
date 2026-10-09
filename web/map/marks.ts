// Reef marks, survey habitat and geology on the Chart, and one selection for the mark
// card (FE-18, design § 9, § 3A.2). A region's layers (region.json `assets`) load once
// whatever the presentation, so a shared `?spot=` names its mark in 2D and 3D too. One
// selection at a time: a mark click writes `?spot=` and drops `?habitat=`, a terrain pick
// does the reverse (stage.ts `habitatHref`), an outline or coastline pick drops both. On
// the Chart a `?habitat=` the terrain has not restored resolves through packages/coast's
// `resolveHabitatSelection`, metadata only (coast-habitat.js). Erasable syntax only.
import {computed, effect, signal} from '@preact/signals';
import {hasCoastTerrain} from '../coast-context.ts';
import {PROFILE_TABLE, terrainDepthLimitFt} from '../profile.ts';
import {habitat, navigate, profile, region, selection, species, withParams} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import {
  EMPTY, atlasCard, geologyCard, geologyFeatures, markFeatures, receiptCard, surveyCard, surveyFeatures, terrainCard, terrainDetailCard,
  type Atlas, type Collection, type Geology, type HabitatReceipt, type MarkData, type RegionData, type Survey,
} from './habitat.ts';
import {GEOLOGY_SOURCE, MARKS_SOURCE, SELECTION_SOURCE, SURVEY_SOURCE} from './layers.ts';
import type {Palette} from './palette.ts';
import {LABEL_FONT} from './style.ts';
import {coastSpecies, shownPresentation, terrainDetail, terrainMark} from './stage.ts';

/** The pickable layers: a 44 px transparent target under each mark ring, and the two kinds of outline. */
export const MARK_PICK = 'marks-target';
export const SURVEY_PICK = 'survey-habitat-fill';
export const GEOLOGY_PICK = 'geology-fill';
/** Habitat and marks draw from `?view=` zoom 10 (§ 9): MapLibre zoom 9. */
const MIN_ZOOM = 9;

/** The region's published layers; null while they load. */
export const markData = signal<MarkData | null>(null);
/** The `?habitat=` receipt the Chart restored without the terrain. */
export const habitatReceipt = signal<HabitatReceipt | null>(null);
/** Counts picks (never links), so the mark card takes focus only when someone chose a mark. */
export const picked = signal(0);
const target = computed(() => species.value ?? PROFILE_TABLE[profile.value].defaultTarget);
/** The terrain's selection while the link still names it (a mark click or Back drops `?habitat=`, and with it the card). */
const linked = computed(() => { const id = habitat.value, s = terrainMark.value; return id && s?.id === id ? s : null; });

const points = (at: readonly ({latitude: number; longitude: number} | null | undefined)[]): Collection => ({type: 'FeatureCollection',
  features: at.filter(p => !!p).map(p => ({type: 'Feature', geometry: {type: 'Point', coordinates: [p!.longitude, p!.latitude]}, properties: {}}))});

/** Each FE-18 source's GeoJSON for the Chart. */
export const markSources: Readonly<Record<string, {readonly value: Collection}>> = {
  [SURVEY_SOURCE]: computed(() => surveyFeatures(markData.value, target.value)),
  [GEOLOGY_SOURCE]: computed(() => geologyFeatures(markData.value, target.value)),
  [MARKS_SOURCE]: computed(() => markFeatures(markData.value?.atlas, target.value, profile.value)),
  [SELECTION_SOURCE]: computed(() => points([markData.value?.atlas?.targets.find(t => t.id === selection.value), linked.value ?? habitatReceipt.value])),
};

/** The link's atlas mark as a card; null without one or when the atlas lacks it (v1 ignores it too); undefined while the layers load. */
export const spotCard = computed<ChartMark | null | undefined>(() => {
  const id = selection.value, data = markData.value;
  if (!id) return null;
  const t = data?.atlas?.targets.find(x => x.id === id);
  return !data ? undefined : t ? atlasCard(t, data, target.value) : null;
});

/** The terrain's habitat selection as a card on the Chart: the renderer's evidence once it speaks, else its position, else the receipt. */
export const habitatCard = computed<ChartMark | null>(() => {
  const s = linked.value, detail = terrainDetail.value, receipt = habitatReceipt.value;
  if (s) return detail && detail.id === s.id ? terrainDetailCard(detail, coastSpecies(species.value, profile.value)) : terrainCard(s);
  return receipt && receipt.id === habitat.value ? receiptCard(receipt) : null;
});

/** `href` without the link's selections (`?spot=` and `?habitat=`), or with `spot` as the only one. */
export function spotHref(href: string, spot: string | null): string {
  const url = new URL(withParams(href, {habitat: null}));
  if (spot) url.searchParams.set('spot', spot); else url.searchParams.delete('spot');
  return url.href;
}

/**
 * One Chart click. A reef mark selects its spot (a history entry) and returns null;
 * a survey or geology outline, or `other` (the coastline's card), is the Chart's own
 * selection and drops the link's; empty water changes nothing in the link.
 */
export function chartPick(layer: string | null, properties: Record<string, unknown> | null, other: ChartMark | null = null): ChartMark | null {
  const id = properties?.id, data = markData.peek();
  const find = <T extends Collection>(c: T | null | undefined) => c?.features.find(f => f.properties.id === id)?.properties;
  if (layer === MARK_PICK && typeof id === 'string') {
    picked.value++;
    if (selection.peek() !== id || habitat.peek()) navigate(spotHref(location.href, id));
    return null;
  }
  const survey = layer === SURVEY_PICK ? find(data?.survey) : undefined, geology = layer === GEOLOGY_PICK ? find(data?.geology) : undefined;
  const mark = survey ? surveyCard(survey, data!.survey!) : geology ? geologyCard(geology, data!.geology!) : other;
  if (!mark) return null;
  if (selection.peek() || habitat.peek()) navigate(spotHref(location.href, null));
  picked.value++;
  return mark;
}

/** The Chart's FE-18 sources and layers, coloured from the palette: habitat fills and geology go in § 9's habitat slot, marks and the selection near the top. */
export function markStyle(p: Palette) {
  const source = () => ({type: 'geojson', data: EMPTY});
  const kind = ['match', ['get', 'kind'], 'rock', p.depth1, 'mixed', p.muted, 'sediment', p.amber, 'kelp', p.mint, p.muted];
  return {
    sources: {[SURVEY_SOURCE]: source(), [GEOLOGY_SOURCE]: source(), [MARKS_SOURCE]: source(), [SELECTION_SOURCE]: source()},
    habitat: [
      {id: SURVEY_PICK, type: 'fill', source: SURVEY_SOURCE, minzoom: MIN_ZOOM, paint: {'fill-color': kind, 'fill-opacity': 0.25}},
      {id: GEOLOGY_PICK, type: 'fill', source: GEOLOGY_SOURCE, minzoom: MIN_ZOOM, paint: {'fill-color': kind, 'fill-opacity': 0.06}},
      {id: 'geology-line', type: 'line', source: GEOLOGY_SOURCE, minzoom: MIN_ZOOM, paint: {'line-color': kind, 'line-width': 1.2, 'line-dasharray': [3, 2]}},
    ],
    marks: [
      {id: MARK_PICK, type: 'circle', source: MARKS_SOURCE, minzoom: MIN_ZOOM, paint: {'circle-radius': 22, 'circle-color': p.bg, 'circle-opacity': 0}},
      {id: 'marks-ring', type: 'circle', source: MARKS_SOURCE, minzoom: MIN_ZOOM,
        paint: {'circle-radius': 9, 'circle-color': p.bg, 'circle-opacity': 0.75, 'circle-stroke-color': p.mint, 'circle-stroke-width': 2}},
      {id: 'marks-fit', type: 'symbol', source: MARKS_SOURCE, minzoom: MIN_ZOOM, filter: ['has', 'fit'],
        layout: {'text-field': ['get', 'fit'], 'text-font': [LABEL_FONT], 'text-size': 11, 'text-allow-overlap': true, 'text-ignore-placement': true},
        paint: {'text-color': p.text}},
      {id: 'selection-ring', type: 'circle', source: SELECTION_SOURCE, paint: {'circle-radius': 15, 'circle-opacity': 0, 'circle-stroke-color': p.text, 'circle-stroke-width': 2.5}},
    ],
  };
}

type Resolver = typeof import('./coast-habitat.js');
export interface MarksOptions {
  fetchFn?: typeof fetch;
  /** The page URL region files resolve against. */
  page?: () => string;
  /** A registry layer whose file failed (chart.ts `markUnavailable`). */
  onError?: (layer: string, error: unknown) => void;
  resolver?: () => Promise<Resolver>;
  now?: () => number;
}

const isCollection = (d: {type?: unknown; features?: unknown; region_id?: unknown} | null, region: string): boolean =>
  d?.type === 'FeatureCollection' && Array.isArray(d.features) && (d.region_id === undefined || d.region_id === region);

/** Loads each region's layers and restores a `?habitat=` on the Chart; created with the Chart (web/map/chart.ts). */
export function createMarks(options: MarksOptions = {}): {destroy(): void} {
  const {fetchFn = (...a) => fetch(...a), page = () => location.href, onError = () => {}, resolver = () => import('./coast-habitat.js'), now = Date.now} = options;
  let run = 0, controller: AbortController | undefined, expiry: ReturnType<typeof setTimeout> | undefined;
  const json = async (path: string): Promise<unknown> => {
    const response = await fetchFn(new URL(path, page()).href, {signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  };
  async function read(id: string, current: number): Promise<void> {
    const meta = await json(`regions/${encodeURIComponent(id)}/region.json`) as RegionData;
    const part = async <T>(key: string, layer: string, valid: (d: never) => boolean): Promise<T | null> => {
      const path = meta.assets?.[key];
      if (!path) return null;
      try {
        const d = await json(path);
        if (!valid(d as never)) throw new Error(`${path} is not ${id}'s ${key}`);
        return d as T;
      } catch (error) { if (current === run) onError(layer, error); return null; }
    };
    const [atlas, survey, geology] = await Promise.all([
      part<Atlas>('atlas', 'marks', (d: Atlas | null) => Array.isArray(d?.targets)),
      part<Survey>('survey_habitat', 'habitat', (d: Survey | null) => isCollection(d, id)),
      part<Geology>('geology', 'habitat', (d: Geology | null) => isCollection(d, id)),
    ]);
    if (current === run) markData.value = {region: {...meta, id}, atlas, survey, geology};
  }
  const disposers = [
    effect(() => {
      const id = region.value, current = ++run;
      markData.value = null;
      if (id) read(id, current).catch(error => { if (current === run) onError('marks', error); });
    }),
    effect(() => {
      const id = habitat.value, r = region.value, s = coastSpecies(species.value, profile.value), depthLimitFt = terrainDepthLimitFt(profile.value);
      const wanted = !!id && !!r && hasCoastTerrain(r) && shownPresentation.value === 'chart' && terrainMark.value?.id !== id;
      controller?.abort(); clearTimeout(expiry);
      habitatReceipt.value = null;
      if (!wanted) return;
      const c = controller = new AbortController();
      resolver().then(m => m.resolveHabitatSelection({id, species: s, depthLimitFt}, {signal: c.signal})).then(receipt => {
        const left = receipt ? Date.parse(receipt.expiresAt) - now() : 0;
        if (c.signal.aborted || !receipt || receipt.id !== id || !(left > 0)) return;
        habitatReceipt.value = receipt;
        expiry = setTimeout(() => { if (habitatReceipt.peek() === receipt) habitatReceipt.value = null; }, Math.min(left, 2 ** 31 - 1));
      }, () => {});
    }),
  ];
  return {
    destroy() {
      run++; controller?.abort(); clearTimeout(expiry);
      for (const dispose of disposers) dispose();
      markData.value = null; habitatReceipt.value = null;
    },
  };
}
