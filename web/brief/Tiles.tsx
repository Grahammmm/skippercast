// The brief's four tiles (FE-37, design § 10): Wind, Swell, Water and Tide
// from the FE-31 model (web/brief/model.ts), each with its source and age in
// mono, a stale state past its limit that still shows the reading and how old
// it is, and a basis popover naming the source, its clock and the limit. A
// tile with no reading shows "—" and says it is unavailable; nothing is
// filled in. Before the model has a brief, the tiles show their empty state.
import {Tile, type TileHue, type TileProps} from '../ui/Tile.tsx';
import type {IconName} from '../ui/icons.tsx';
import type {BriefTile, TileId} from './types.ts';
import {language, num, t, type Language, type StringId} from '../i18n.ts';
import {tileDetailText, tileSourceName} from './tile-copy.ts';

const LOOK: Readonly<Record<TileId, {icon: IconName; hue: TileHue}>> = {
  wind: {icon: 'wind', hue: 'mint'}, swell: {icon: 'wave', hue: 'blue'}, water: {icon: 'temperature', hue: 'coral'}, tide: {icon: 'tide', hue: 'amber'},
};

const LABELS: ReadonlySet<string> = new Set(['Wind', 'Swell', 'Water', 'Tide']);

/** The tiles that read a forecast for the day; water is a buoy reading and tide an astronomical prediction. */
const FORECAST_TILES: ReadonlySet<TileId> = new Set(['wind', 'swell']);

/** "45 min", "2 h", "3 d": how old a reading is; a clock ahead of this device says so. */
export function ageText(ms: number, lang: Language = 'en'): string {
  if (ms < 0) return t('tile.age.ahead', lang);
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return t('tile.age.minutes', lang, {n: minutes});
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? t('tile.age.hours', lang, {n: hours}) : t('tile.age.days', lang, {n: Math.floor(hours / 24)});
}

/** The tile's source line: the source and its age (marked last good after a failed check), or that no reading is available. */
export function sourceLine(tile: BriefTile, compact = false, lang: Language = 'en'): string {
  const source = tile.source;
  if (tile.state === 'unavailable' || tile.ageMs === null) return t('tile.source.unavailable', lang, {source});
  const age = ageText(tile.ageMs, lang);
  const id = tile.lastGood ? (compact ? 'tile.source.lastGoodCompact' : 'tile.source.lastGoodFull') : (compact ? 'tile.source.compact' : 'tile.source.full');
  return t(id, lang, {source, age});
}

/**
 * One model tile as the shared Tile's props. Compact (the mobile sheet below
 * full) keeps the reading, its short source with the age ("NDBC 46042 · 5 h") and the stale state, and leaves the detail
 * line and basis for the full sheet, so the four tiles fit the half detent.
 */
export function tileProps(tile: BriefTile, compact = false, dense = false, lang: Language = 'en'): TileProps {
  // The reference level: the model's own datum when it has one, else the last part of the English tide line.
  const datum = tile.id !== 'tide' ? null : tile.display ? tile.display.datum ?? null : tile.detail.includes(' · ') ? tile.detail.split(' · ').at(-1) : null;
  const sourceName = tileSourceName(tile, lang);
  const name = tile.sourceUrl ? <a href={tile.sourceUrl} target="_blank" rel="noopener">{sourceName}</a> : sourceName;
  const shown = sourceName === tile.source ? tile : {...tile, source: sourceName};
  // English prints the value as always; Spanish only swaps the decimal separator (the model's one decimal; -0 reads 0).
  const reading = tile.value === null ? '—' : lang === 'en' ? String(tile.value) : num(tile.value === 0 ? 0 : tile.value, lang, 1);
  if (compact) {
    return {label: tile.label, ...LOOK[tile.id], reading, unit: tile.unit,
      source: sourceLine(shown, true, lang), stale: tile.state === 'stale'};
  }
  return {
    label: tile.label, ...LOOK[tile.id], reading, unit: tile.unit, detail: tileDetailText(tile, lang),
    source: sourceLine(shown, dense, lang), stale: tile.state === 'stale',
    basis: <>{t(`tile.basis.${tile.id}` as StringId, lang)}{datum ? t('tile.basis.reference', lang, {datum: String(datum)}) : ''}{t('tile.basis.source', lang)}{name}.{tile.lastGood ? t('tile.basis.lastGood', lang) : ''}{t('tile.basis.staleAfter', lang, {hours: Math.round(tile.limitMs / 3_600_000)})}</>,
  };
}

/** The four tiles in their empty state; the swell source follows the profile (§ 8). */
export function emptyTiles(nearshore: boolean, lang: Language = 'en'): TileProps[] {
  const swell = nearshore ? 'nearshore' : 'offshore';
  return [
    {label: 'Wind', ...LOOK.wind, reading: '—', unit: 'kt', source: 'NWS —', basis: t('tile.empty.basis.wind', lang)},
    {label: 'Swell', ...LOOK.swell, reading: '—', unit: 'ft', source: t(`tile.empty.source.${swell}` as StringId, lang), basis: t(`tile.empty.basis.${swell}` as StringId, lang)},
    {label: 'Water', ...LOOK.water, reading: '—', unit: '°F', source: t('tile.empty.source.buoy', lang), basis: t('tile.empty.basis.water', lang)},
    {label: 'Tide', ...LOOK.tide, reading: '—', unit: 'ft', source: t('tile.empty.source.station', lang), basis: t('tile.empty.basis.tide', lang)},
  ];
}

/**
 * The model's tiles (compact in the sheet below full; dense in the desktop column: the short source
 * line on one row of four, detail and basis kept), or the empty state before there is a brief. On a
 * provisional day the forecast tiles (wind, swell) say so on their source line, beside the reading.
 */
export function Tiles({tiles, nearshore = false, compact = false, dense = false, provisional = false}: {tiles: readonly BriefTile[] | null; nearshore?: boolean; compact?: boolean; dense?: boolean; provisional?: boolean}) {
  const lang = language.value, label = (name: string) => LABELS.has(name) ? t(`tile.${name.toLowerCase()}` as StringId, lang) : name;
  const props = tiles ? tiles.map(tile => {
    const p = tileProps(tile, compact, dense, lang);
    return provisional && FORECAST_TILES.has(tile.id) ? {...p, source: t('tile.source.provisional', lang, {source: p.source ?? ''})} : p;
  }) : emptyTiles(nearshore, lang);
  return <div class={dense ? 'app-tiles app-tiles--dense' : 'app-tiles'}>{props.map(tile => <Tile key={tile.label} {...tile} label={label(tile.label)} />)}</div>;
}
