// The brief's four tiles (FE-37, design § 10): Wind, Swell, Water and Tide
// from the FE-31 model (web/brief/model.ts), each with its source and age in
// mono, a stale state past its limit that still shows the reading and how old
// it is, and a basis popover naming the source, its clock and the limit. A
// tile with no reading shows "—" and says it is unavailable; nothing is
// filled in. Before the model has a brief, the tiles show their empty state.
import {Tile, type TileHue, type TileProps} from '../ui/Tile.tsx';
import type {IconName} from '../ui/icons.tsx';
import type {BriefTile, TileId} from './types.ts';

const LOOK: Readonly<Record<TileId, {icon: IconName; hue: TileHue}>> = {
  wind: {icon: 'wind', hue: 'mint'}, swell: {icon: 'wave', hue: 'blue'}, water: {icon: 'temperature', hue: 'coral'}, tide: {icon: 'tide', hue: 'amber'},
};

const BASIS: Readonly<Record<TileId, string>> = {
  wind: 'Forecast hour nearest the selected time, in knots with the gust; the issue time sets the age.',
  swell: 'Significant height and period from the source named here.',
  water: 'Latest buoy water temperature with its observation time.',
  tide: 'Tide prediction nearest the selected time, in feet.',
};

/** "45 min", "2 h", "3 d": how old a reading is; a clock ahead of this device says so. */
export function ageText(ms: number): string {
  if (ms < 0) return 'clock ahead';
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/** The tile's source line: the source and its age, or that no reading is available. */
export function sourceLine(tile: BriefTile): string {
  return tile.state === 'unavailable' || tile.ageMs === null ? `${tile.source} · unavailable` : `${tile.source} · ${ageText(tile.ageMs)} old`;
}

/**
 * One model tile as the shared Tile's props. Compact (the mobile sheet below
 * full) keeps the reading, its age and the stale state, and leaves the detail
 * line and basis for the full sheet, so the four tiles fit the half detent.
 */
export function tileProps(tile: BriefTile, compact = false): TileProps {
  const datum = tile.id === 'tide' && tile.detail.includes(' · ') ? tile.detail.split(' · ').at(-1) : null;
  const name = tile.sourceUrl ? <a href={tile.sourceUrl} target="_blank" rel="noopener">{tile.source}</a> : tile.source;
  if (compact) {
    return {label: tile.label, ...LOOK[tile.id], reading: tile.value === null ? '—' : String(tile.value), unit: tile.unit,
      source: tile.state === 'unavailable' || tile.ageMs === null ? 'unavailable' : `${ageText(tile.ageMs)} old`, stale: tile.state === 'stale'};
  }
  return {
    label: tile.label, ...LOOK[tile.id], reading: tile.value === null ? '—' : String(tile.value), unit: tile.unit, detail: tile.detail,
    source: sourceLine(tile), stale: tile.state === 'stale',
    basis: <>{BASIS[tile.id]}{datum ? ` Reference level: ${datum}.` : ''} Source: {name}. Shown as stale after {Math.round(tile.limitMs / 3_600_000)} h.</>,
  };
}

/** The four tiles in their empty state; the swell source follows the profile (§ 8). */
export function emptyTiles(nearshore: boolean): TileProps[] {
  return [
    {label: 'Wind', ...LOOK.wind, reading: '—', unit: 'kt', source: 'NWS —', basis: 'NWS forecast hour or the nearest station observation, in knots with the gust; the issue time sets the age.'},
    {label: 'Swell', ...LOOK.swell, reading: '—', unit: 'ft', source: nearshore ? 'Nearshore site —' : 'Offshore —',
      basis: nearshore ? 'Nearest fresh nearshore model site (CDIP MOP): significant height and period.' : 'Offshore buoy or model forecast: significant height and period.'},
    {label: 'Water', ...LOOK.water, reading: '—', unit: '°F', source: 'Buoy —', basis: 'Buoy observation with its time; without a fresh buoy the tile stays blank.'},
    {label: 'Tide', ...LOOK.tide, reading: '—', unit: 'ft', source: 'Station —', basis: 'Station tide curve: height and trend; the reference level is named here once the station loads.'},
  ];
}

/** The model's tiles (compact in the sheet below full), or the empty state before there is a brief. */
export function Tiles({tiles, nearshore = false, compact = false}: {tiles: readonly BriefTile[] | null; nearshore?: boolean; compact?: boolean}) {
  const props = tiles ? tiles.map(tile => tileProps(tile, compact)) : emptyTiles(nearshore);
  return <div class="app-tiles">{props.map(tile => <Tile key={tile.label} {...tile} />)}</div>;
}
