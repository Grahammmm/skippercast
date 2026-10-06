// Desktop layout (FE-05, design § 6): the 332 px brief column beside the map
// stage with its chrome. The brief here is the shell's empty state, bound to
// the profile: tiles show "—" with their source line and basis until FE-30
// wires web/brief/daily.ts; the map is a token-coloured stage until FE-11.
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

export function Brief({picks = []}: {picks?: readonly Pick[]} = {}) {
  const p = PROFILE_TABLE[profile.value];
  return (
    <aside class="app-brief" aria-label="Brief">
      <span class="ui-eyebrow">Today's brief</span>
      <h1>Waiting for readings.</h1>
      <div class="app-tiles">{emptyTiles(p.swellTile === 'nearshore').map(tile => <Tile key={tile.label} {...tile} />)}</div>
      <figure class="app-spark" aria-label="Tide curve"><span>—</span></figure>
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
      <p class="app-caveat">{p.caveat}</p>
      <footer class="app-brief-footer">{DISCLAIMER} <a href="sources.html">Sources</a></footer>
    </aside>
  );
}

export function Desktop() {
  return (
    <main class="app-main">
      <Brief />
      <section class="app-stage" aria-label="Map">
        <div class="app-map"><span>Map unavailable.</span></div>
        <MarkCard />
        <LayerRail />
        <Legend />
        <TimeDock />
      </section>
    </main>
  );
}
