// The map stage (FE-71, design § 3A.2): the Chart host (MapLibre, FE-11,
// registered with the stage as a renderer), the terrain host whose shadow root
// packages/coast mounts into, and the Chart / 2D / 3D toggle in the map chrome
// with its status line. web/map/stage.ts owns the renderers; this component
// creates one stage while it is mounted and destroys it when it unmounts (a
// layout change), which releases the terrain's WebGL context. The Chart's
// run-time layers (FE-17's swell, FE-16's water temperature, FE-22's clouds, FE-23's
// aerial base, CI6-13's depth contours, FE-21's charter grounds and commercial AIS, FE-24's admin fleet activity) are created with it; the swell reads a click first, since it draws above
// the water temperature.
// FE-80: in 2D and 3D the terrain's zoom, reset and top view are the stage's own
// buttons, styled as the Chart's MapLibre zoom group and placed where it sits.
import type {ComponentChildren} from 'preact';
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import {useEffect, useRef, useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Chip} from '../ui/Chip.tsx';
import type {Presentation} from '../coast-context.ts';
import {aerialSoft, createAerial, createImageryStartup, createSharpStart} from '../map/aerial.ts';
import {createCharterGrounds} from '../map/charter-grounds.ts';
import {createShore} from '../map/shore.ts';
import {chartFailed, createChart, markUnavailable, unavailable} from '../map/chart.ts';
import {seafloorRough, seafloorState} from '../map/seafloor.ts';
import {createCommercialAis} from '../map/commercial-ais.ts';
import {createDepthContours} from '../map/depth-contours.ts';
import {createClouds} from '../map/clouds.ts';
import {createFleetActivity} from '../map/fleet.ts';
import {regionPlace} from '../map/currents.ts';
import {coastPalette, readPalette} from '../map/palette.ts';
import {createReach} from '../map/reach.ts';
import {createPlanningRouteLayer} from '../map/planning-route.ts';
import {createContrast} from '../map/contrast.ts';
import {createFronts} from '../map/fronts.ts';
import {createWaterTemp} from '../map/sst.ts';
import {createChlorophyll} from '../map/chlorophyll.ts';
import {createSwell} from '../map/swell.ts';
import {createPreviewLayers, previewOn} from '../map/preview-layers.ts';
import type {Engine} from '../map/engine.ts';
import {BOTTOM_RELIEF, reliefWanted} from '../map/layers.ts';
import {createStations} from '../map/stations.ts';
import {dailyFeed, verdictEpoch} from '../brief/Brief.tsx';
import {mapFirstIdle} from '../map-ready.ts';
import {createWind} from '../map/wind.ts';
import type {HourClock} from '../clock.ts';
import {camera, choosePresentation, createStage, shownPresentation, terrainActions, terrainBlocked, terrainReason} from '../map/stage.ts';
import {language, t, type StringId} from '../i18n.ts';
import {poster, posterPlacement} from '../map/poster.ts';
import {appView, base, layers, profile, region, species} from '../state.ts';
import {cancelWaypointPlacement, placementRefused, verdictLine, waypointPlacement} from '../waypoint-placement.ts';
import {currentRegionInfo, zone} from './App.tsx';
import {MAP_ID} from './SkipLinks.tsx';

export const PRESENTATIONS: ReadonlyArray<{value: Presentation; label: string}> = [
  {value: 'chart', label: 'Chart'}, {value: '2d', label: '2D'}, {value: '3d', label: '3D'},
];
/** SC1352-06: each presentation's catalogue label, shown in the page's language at render; PRESENTATIONS stays the English compatibility list. */
const PRESENTATION_IDS: Readonly<Record<Presentation, StringId>> = {chart: 'stage.chart', '2d': 'stage.2d', '3d': 'stage.3d'};
const NOTE_ID = 'app-stage-note';

// DATA-LIVE-9: the regional bottom relief is public. It draws only for a region whose reviewed pointer resolves
// `ready` (web/map/bottom-relief.ts), is on by default and has no admin gate or toggle. The older Morro study
// preview, which an admin can still turn on, takes the Chart instead (web/map/layers.ts `reliefWanted`).
/** True from the relief's first draw until it is retired; the honesty line shows only while something is drawn. */
export const reliefDrawn = signal(false);
const clearUnavailable = (layer: string) => { unavailable.value = unavailable.peek().filter(l => l !== layer); };
const basemapAvailable = computed(() => !unavailable.value.includes('basemap'));

function watchBottomRelief(engine: ReadonlySignal<Engine | null>) {
  return {destroy: effect(() => {
    const e = engine.value, id = region.value;
    if (!e || !id || !reliefWanted({presentation: shownPresentation.value, view: appView.value, basemapAvailable: basemapAvailable.value,
      studyPreviewOn: previewOn.value.includes('seafloor')})) return;
    let cancelled = false, handle: {destroy(): void} | undefined;
    clearUnavailable(BOTTOM_RELIEF);
    void import('../map/bottom-relief.ts').then(relief => {
      if (cancelled) return;
      handle = relief.attachBottomRelief({engine: e, region: id,
        seafloorOn: () => layers.value.includes('seafloor'),
        fieldOn: () => layers.value.includes('water-temp') || layers.value.includes('chlorophyll') ||
          previewOn.value.some(layer => layer === 'sst' || layer === 'chlorophyll'),
        ready: () => { reliefDrawn.value = true; },
        // No `ready` pointer is normal (most regions have none yet): nothing was promised, so nothing is said.
        // Only a relief that was drawn and then failed its checks is reported.
        unavailable: error => { const was = reliefDrawn.peek(); reliefDrawn.value = false; if (was) markUnavailable(BOTTOM_RELIEF, error); }});
    }).catch(() => { /* the module did not load: nothing was drawn or promised, so nothing is said */ });
    return () => { cancelled = true; handle?.destroy(); reliefDrawn.value = false; clearUnavailable(BOTTOM_RELIEF); };
  })};
}

/** The relief's honesty line, with no source names (those live on the sources page), while it is drawn; a status if it fails after drawing. */
function DepthShadingNote() {
  if (shownPresentation.value !== 'chart') return null;
  const lang = language.value;
  if (unavailable.value.includes(BOTTOM_RELIEF)) return <p class="app-stage-note" role="status">{t('tile.source.unavailable', lang, {source: t('layer.relief.label', lang)})}</p>;
  return reliefDrawn.value ? <p class="app-stage-note" data-bottom-relief-note role="status">{t('layer.relief.shading', lang)}</p> : null;
}

/** RF1925-2: the selected Chart could not start (chartFailed is a sticky start-up failure; a working 2D or 3D terrain is not a failed map). The one test every map-only control shares. */
export const mapUnavailable = computed(() => chartFailed.value && shownPresentation.value === 'chart');

/** RF2115-5: the visit's first Chart is shown and has neither drawn its first idle frame nor failed. Visit-wide, one-way (web/map-ready.ts): never restarts after the first idle. */
export const chartLoading = computed(() => shownPresentation.value === 'chart' && !chartFailed.value && !mapFirstIdle.value);
/** R4-SC-09: the Chart host stays aria-busy after that first idle while the aerial base is still the first view's preview. */
const chartBusy = computed(() => chartLoading.value || (shownPresentation.value === 'chart' && !chartFailed.value && aerialSoft.value));

/** The Chart could not start: say so, and offer a reload of the current page (the same address) as the only retry. */
export function MapUnavailable() {
  const lang = language.value;
  return (
    <div class="app-stage-note app-stage-failed" style={{margin: 'var(--space-4)', maxWidth: '28rem', zIndex: 1}}>
      <p role="status" style={{margin: '0 0 var(--space-3)'}}><strong>{t('map.mpa.mapUnavailable', lang)}</strong> {t('stage.graphicsUnavailable', lang)}</p>
      <Button variant="primary" onClick={() => location.reload()}>{t('stage.retryMap', lang)}</Button>
    </div>
  );
}

/** Chart, 2D, 3D; where no terrain can show, the terrain choices are disabled and point at the reason in the status line. */
export function PresentationToggle() {
  const shown = shownPresentation.value, blocked = terrainBlocked.value, lang = language.value;
  const loading = chartLoading.value;
  const armed = waypointPlacement.value === region.value && shown === 'chart', refused = armed && placementRefused.value ? verdictLine(placementRefused.value, lang) : null;
  return (
    <div class={armed ? 'app-presentation app-presentation--placing' : 'app-presentation'}>
      <p class="app-stage-note" data-chart-loading-status role="status" aria-live="polite" aria-atomic="true">{loading ? t('stage.loadingChart', lang) : ''}</p>
      <p id={NOTE_ID} class="app-stage-note" role="status">{blocked === null ? '' : terrainReason(blocked, lang)}</p>
      {armed ? <p class="app-stage-note" role="status">{t('stage.placePrompt', lang)} {refused ? <>{refused}. </> : null}<Button size="sm" variant="quiet" onClick={cancelWaypointPlacement}>{t('stage.cancelWaypoint', lang)}</Button></p> : null}
      {shown === 'chart' && seafloorRough.value ? <p class="app-stage-note" data-seafloor-rough role="status">{t('stage.seafloorRough', lang)}</p> : null}
      <DepthShadingNote />
      <div role="group" aria-label={t('stage.presentation', lang)} class="ui-segmented">
        {PRESENTATIONS.map(p => {
          const off = p.value !== 'chart' && !!blocked;
          return (
            <Chip key={p.value} on={p.value === shown} disabled={off} aria-describedby={off ? NOTE_ID : undefined}
              onClick={() => { if (p.value !== shown) choosePresentation(p.value); }}>{t(PRESENTATION_IDS[p.value], lang)}</Chip>
          );
        })}
      </div>
    </div>
  );
}

/** The terrain's view buttons (FE-80), in the Chart's zoom-control group; absent until the renderer mounts. */
export function TerrainControls() {
  const a = terrainActions.value, lang = language.value;
  if (!a || shownPresentation.value === 'chart') return null;
  return (
    <div class="app-terrain-controls" role="group" aria-label={t('stage.terrainView', lang)}>
      <IconButton icon="plus" label={t('stage.zoomIn', lang)} onClick={() => a.zoom('in')} />
      <IconButton icon="minus" label={t('stage.zoomOut', lang)} onClick={() => a.zoom('out')} />
      <IconButton icon="target" label={t('stage.resetView', lang)} onClick={() => a.reset()} />
      <IconButton icon="compass" label={t('stage.viewAbove', lang)} onClick={() => a.top()} />
    </div>
  );
}

/**
 * #617: the region's coast outline over the empty Chart until MapLibre's first complete frame (web/map/poster.ts),
 * placed for the shared camera in a host of the stage's size. Decorative: the map's own coastline replaces it.
 */
export function ChartPoster() {
  const ref = useRef<SVGSVGElement>(null), [size, setSize] = useState<{w: number; h: number} | null>(null);
  const p = poster.value, c = camera.value;
  useEffect(() => { const host = ref.current?.parentElement; if (host) setSize({w: host.clientWidth, h: host.clientHeight}); }, [!!p]);
  if (!p || !c || p.region !== region.value) return null;
  const at = size ? posterPlacement(p, c, size.w, size.h) : null;
  return (
    <svg ref={ref} class="app-poster" aria-hidden="true" focusable="false" viewBox={`0 0 ${p.width} ${p.height}`} width={p.width} height={p.height}
      style={at ? {transform: `translate(${at.x}px, ${at.y}px) scale(${at.scale})`} : {visibility: 'hidden'}}>
      <path class="app-poster-glow" d={p.path} />
      <path class="app-poster-line" d={p.path} />
    </svg>
  );
}

/** Token colours for the renderer; without web/tokens.css the embed keeps its defaults. */
const palette = () => { try { return coastPalette(readPalette()); } catch { return undefined; } };
/** The token palette the registry's terrain overlays take their roles from (FE-82). */
const overlayPalette = () => { try { return readPalette(); } catch { return undefined; } };

/** The map stage with whatever chrome the layout puts over it. */
export function MapStage({children, clock}: {children?: ComponentChildren; clock?: HourClock} = {}) {
  const terrainHost = useRef<HTMLDivElement>(null), chartHost = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const place = () => regionPlace(currentRegionInfo(), profile.value, species.value ?? '');
    // SCB-12: an early canvas must not flood the brief's link with large aerial tiles.
    // Release once, even when the brief settles as failed/timed out; refreshes never detach imagery.
    const imagery = createImageryStartup(() => verdictEpoch.value?.sealed === true);
    const aerialWaiting = computed(() => !imagery.ready.value && base.value === 'aerial' && !!currentRegionInfo()?.aerial);
    // R4-SC-09: the first view's aerial base is a quarter-pixel preview; the full image follows once the map has first
    // settled and the seafloor's first view has landed (or SHARP_WAIT_MAX_MS after that settle), so the two do not share the link.
    const sharp = createSharpStart(() => mapFirstIdle.value, () => seafloorState.value.status === 'checking');
    const stage = createStage({host: terrainHost.current!, palette, overlayPalette, center: () => currentRegionInfo()?.center ?? null, zone, clock,
      renderers: [() => createChart({host: chartHost.current!, zone, place,
        idleReady: () => !aerialWaiting.value,
        layers: [engine => createChlorophyll({engine}), engine => createSwell({engine, zone, place}), engine => createContrast({engine, zone, place}), engine => createFronts({engine, place}), engine => createWind({engine, zone}), engine => createWaterTemp({engine, zone, place}), engine => createClouds({engine, zone}),
          engine => createStations({engine, zone, feed: () => dailyFeed.value}),
          engine => createAerial({engine: computed(() => aerialWaiting.value ? null : engine.value), offer: () => currentRegionInfo()?.aerial ?? null, sharp: () => sharp.ready.value}), engine => createDepthContours({engine, host: chartHost.current!}),
          engine => createShore({engine}), engine => createCharterGrounds({engine}), engine => createCommercialAis({engine}), engine => createFleetActivity({engine, zone}),
          engine => createReach({engine, host: chartHost.current!}),
          engine => createPlanningRouteLayer({engine, host: chartHost.current!}),
          watchBottomRelief,
          engine => createPreviewLayers({engine, failures: {list: unavailable, clear: clearUnavailable}})]})]});
    return () => { imagery.destroy(); sharp.destroy(); stage.destroy(); };
  }, [clock]);
  const shown = shownPresentation.value, lang = language.value, failed = mapUnavailable.value;
  return (
    <section class="app-stage" tabIndex={-1} aria-label={t('stage.map', lang)} id={MAP_ID}>
      <div class="app-map" hidden={shown !== 'chart'}>
        <div class="app-chart" ref={chartHost} hidden={chartFailed.value} aria-busy={chartBusy.value ? 'true' : 'false'} />
        {failed ? <MapUnavailable /> : <ChartPoster />}
      </div>
      <div class="app-terrain" ref={terrainHost} tabIndex={-1} hidden={shown === 'chart'} data-coast-theme="tokens" />
      {failed ? null : <><TerrainControls /><PresentationToggle /></>}
      {children}
    </section>
  );
}
