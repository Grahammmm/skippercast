// Desktop layout (FE-05, design § 6): the 332 px brief column beside the map
// stage with its chrome. The brief here is the shell's empty state, bound to
// the profile: tiles show "—" with their source line and basis until FE-30
// wires web/brief/daily.ts; the map is a token-coloured stage until FE-11.
// The brief's pieces are exported so Mobile.tsx (FE-06) composes them into
// the sheet in its own order.
import type {ComponentChildren} from 'preact';
import {Tile, type TileProps} from '../ui/Tile.tsx';
import {PROFILE_TABLE} from '../profile.ts';
import {profile} from '../state.ts';
import {LayerRail} from './LayerRail.tsx';
import {Legend} from './Legend.tsx';
import {MarkCard} from './MarkCard.tsx';
import {TimeDock} from './TimeDock.tsx';

/** One "where to look" row (§ 10); FE-30 ranks them from the profile table. */
export interface Pick {readonly id: string; readonly name: string; readonly distance: string; readonly depth: string; readonly fit: string; readonly reason: string}

/** The four tiles in their empty state; the swell source follows the profile (§ 8). */
export function emptyTiles(nearshore: boolean): TileProps[] {
  return [
    {label: 'Wind', icon: 'wind', hue: 'mint', reading: '—', unit: 'kt', source: 'NWS —', basis: 'NWS forecast hour or the nearest station observation, in knots with the gust; the issue time sets the age.'},
    {label: 'Swell', icon: 'wave', hue: 'blue', reading: '—', unit: 'ft', source: nearshore ? 'Nearshore site —' : 'Offshore —',
      basis: nearshore ? 'Nearest fresh nearshore model site (CDIP MOP): significant height and period.' : 'Offshore buoy or model forecast: significant height and period.'},
    {label: 'Water', icon: 'temperature', hue: 'coral', reading: '—', unit: '°F', source: 'Buoy —', basis: 'Buoy observation with its time; without a fresh buoy the tile stays blank.'},
    {label: 'Tide', icon: 'tide', hue: 'amber', reading: '—', unit: 'ft', source: 'Station —', basis: 'Station tide curve: height and trend; the reference level is named here once the station loads.'},
  ];
}

export const DISCLAIMER = 'Forecasts, observations and habitat carry separate clocks; check the rules before you fish.';

export const Headline = () => <h1>Waiting for readings.</h1>;

export function Tiles() {
  const p = PROFILE_TABLE[profile.value];
  return <div class="app-tiles">{emptyTiles(p.swellTile === 'nearshore').map(tile => <Tile key={tile.label} {...tile} />)}</div>;
}

export const TideSpark = () => <figure class="app-spark" aria-label="Tide curve"><span>—</span></figure>;

export function Picks({picks = []}: {picks?: readonly Pick[]} = {}) {
  return (
    <>
      <h2 class="ui-eyebrow">Where to look</h2>
      {picks.length ? (
        <ol class="app-picks">
          {picks.map((pick, i) => (
            <li key={pick.id} class="app-pick" data-mark={pick.id}>
              <span class="app-pick-rank ui-mono">{i + 1}</span>
              <span>{pick.name} <span class="ui-mono">{pick.distance} · {pick.depth}</span></span>
              <span class="app-fit ui-eyebrow">{pick.fit}</span>
              <span class="app-pick-reason">{pick.reason}</span>
            </li>
          ))}
        </ol>
      ) : <p class="app-empty">No ranked places yet.</p>}
    </>
  );
}

export const Caveat = () => <p class="app-caveat">{PROFILE_TABLE[profile.value].caveat}</p>;

/** The one disclaimer line per page with the sources link; `children` adds links after it. */
export const BriefFooter = ({children}: {children?: ComponentChildren} = {}) =>
  <footer class="app-brief-footer">{DISCLAIMER} <a href="sources.html">Sources</a>{children}</footer>;

export function Brief({picks = []}: {picks?: readonly Pick[]} = {}) {
  return (
    <aside class="app-brief" aria-label="Brief">
      <span class="ui-eyebrow">Today's brief</span>
      <Headline />
      <Tiles />
      <TideSpark />
      <Picks picks={picks} />
      <Caveat />
      <BriefFooter />
    </aside>
  );
}

/** The map stage: the engine's host (FE-11) with whatever chrome the layout puts over it. */
export function MapStage({children}: {children?: ComponentChildren} = {}) {
  return (
    <section class="app-stage" aria-label="Map">
      <div class="app-map"><span>Map unavailable.</span></div>
      {children}
    </section>
  );
}

export function Desktop() {
  return (
    <main class="app-main">
      <Brief />
      <MapStage>
        <MarkCard />
        <LayerRail />
        <Legend />
        <TimeDock />
      </MapStage>
    </main>
  );
}
