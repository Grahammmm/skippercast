// The map stage (FE-71, design § 3A.2): the Chart host (MapLibre, FE-11,
// registered with the stage as a renderer), the terrain host whose shadow root
// packages/coast mounts into, and the Chart / 2D / 3D toggle in the map chrome
// with its status line. web/map/stage.ts owns the renderers; this component
// creates one stage while it is mounted and destroys it when it unmounts (a
// layout change), which releases the terrain's WebGL context. The Chart's
// run-time layers (FE-17's swell, FE-16's water temperature, FE-22's clouds, FE-23's
// aerial base, FE-21's charter grounds and commercial AIS, FE-24's admin fleet activity) are created with it; the swell reads a click first, since it draws above
// the water temperature.
// FE-80: in 2D and 3D the terrain's zoom, reset and top view are the stage's own
// buttons, styled as the Chart's MapLibre zoom group and placed where it sits.
import type {ComponentChildren} from 'preact';
import {useEffect, useRef} from 'preact/hooks';
import {IconButton} from '../ui/Button.tsx';
import {Chip} from '../ui/Chip.tsx';
import type {Presentation} from '../coast-context.ts';
import {createAerial} from '../map/aerial.ts';
import {createCharterGrounds} from '../map/charter-grounds.ts';
import {chartFailed, createChart} from '../map/chart.ts';
import {createCommercialAis} from '../map/commercial-ais.ts';
import {createClouds} from '../map/clouds.ts';
import {createFleetActivity} from '../map/fleet.ts';
import {regionPlace} from '../map/currents.ts';
import {coastPalette, readPalette} from '../map/palette.ts';
import {createWaterTemp} from '../map/sst.ts';
import {createSwell} from '../map/swell.ts';
import {choosePresentation, createStage, shownPresentation, terrainActions, terrainBlocked} from '../map/stage.ts';
import {profile, region, species} from '../state.ts';
import {regionInfo, zone} from './App.tsx';

export const PRESENTATIONS: ReadonlyArray<{value: Presentation; label: string}> = [
  {value: 'chart', label: 'Chart'}, {value: '2d', label: '2D'}, {value: '3d', label: '3D'},
];
const NOTE_ID = 'app-stage-note';

/** Chart, 2D, 3D; where no terrain can show, the terrain choices are disabled and point at the reason in the status line. */
export function PresentationToggle() {
  const shown = shownPresentation.value, blocked = terrainBlocked.value;
  return (
    <div class="app-presentation">
      <p id={NOTE_ID} class="app-stage-note" role="status">{blocked ?? ''}</p>
      <div role="group" aria-label="Map presentation" class="ui-segmented">
        {PRESENTATIONS.map(p => {
          const off = p.value !== 'chart' && !!blocked;
          return (
            <Chip key={p.value} on={p.value === shown} disabled={off} aria-describedby={off ? NOTE_ID : undefined}
              onClick={() => { if (p.value !== shown) choosePresentation(p.value); }}>{p.label}</Chip>
          );
        })}
      </div>
    </div>
  );
}

/** The terrain's view buttons (FE-80), in the Chart's zoom-control group; absent until the renderer mounts. */
export function TerrainControls() {
  const a = terrainActions.value;
  if (!a || shownPresentation.value === 'chart') return null;
  return (
    <div class="app-terrain-controls" role="group" aria-label="Terrain view">
      <IconButton icon="plus" label="Zoom in" onClick={() => a.zoom('in')} />
      <IconButton icon="minus" label="Zoom out" onClick={() => a.zoom('out')} />
      <IconButton icon="target" label="Reset map view" onClick={() => a.reset()} />
      <IconButton icon="compass" label="View from above" onClick={() => a.top()} />
    </div>
  );
}

/** Token colours for the renderer; without web/tokens.css the embed keeps its defaults. */
const palette = () => { try { return coastPalette(readPalette()); } catch { return undefined; } };
/** The token palette the registry's terrain overlays take their roles from (FE-82). */
const overlayPalette = () => { try { return readPalette(); } catch { return undefined; } };

/** The map stage with whatever chrome the layout puts over it. */
export function MapStage({children}: {children?: ComponentChildren} = {}) {
  const terrainHost = useRef<HTMLDivElement>(null), chartHost = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const place = () => regionPlace(regionInfo.value, profile.value, species.value ?? '');
    const stage = createStage({host: terrainHost.current!, palette, overlayPalette, center: () => regionInfo.value?.center ?? null, zone,
      renderers: [() => createChart({host: chartHost.current!, zone, place,
        layers: [engine => createSwell({engine, zone, place}), engine => createWaterTemp({engine, zone, place}), engine => createClouds({engine, zone}),
          engine => createAerial({engine, offer: () => regionInfo.value?.id === region.value ? regionInfo.value?.aerial ?? null : null}),
          engine => createCharterGrounds({engine}), engine => createCommercialAis({engine}), engine => createFleetActivity({engine, zone})]})]});
    return () => stage.destroy();
  }, []);
  const shown = shownPresentation.value;
  return (
    <section class="app-stage" aria-label="Map">
      <div class="app-map" hidden={shown !== 'chart'}>
        <div class="app-chart" ref={chartHost} hidden={chartFailed.value} />
        {chartFailed.value ? <span>Map unavailable.</span> : null}
      </div>
      <div class="app-terrain" ref={terrainHost} hidden={shown === 'chart'} data-coast-theme="tokens" />
      <TerrainControls />
      <PresentationToggle />
      {children}
    </section>
  );
}
