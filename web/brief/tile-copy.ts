// SC1137-02: the brief tiles' detail line and the source-gap sentences in the reader's language.
//
// The model (model.ts, tide-stations.ts) keeps building the English `.detail` / gap `.text` that the
// advisor, alerts and offline notes read, and adds `display` metadata: the same branches as a finite list
// of app phrases. This adapter, used only by the brief page, says those phrases from the catalogue. It
// never parses the English line, so a station, buoy or site name (a `literal` part) is never translated.
// English returns the original string untouched.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {num, t, type Language, type StringId} from '../i18n.ts';
import {ageText} from '../confidence.ts';
import type {BriefTile, GapDisplay, SourceGap, TileDetailPart} from './types.ts';

const SEP = ' · ';
const lower = (band: string) => band.toLowerCase();
const SIDE: Readonly<Record<'onshore' | 'offshore' | 'cross-shore', StringId>> = {onshore: 'tile.detail.side.onshore', offshore: 'tile.detail.side.offshore', 'cross-shore': 'tile.detail.side.crossShore'};
const BAND: Readonly<Record<string, StringId>> = {small: 'tile.detail.band.small', moderate: 'tile.detail.band.moderate', large: 'tile.detail.band.large', heavy: 'tile.detail.band.heavy',
  low: 'tile.detail.band.low', strong: 'tile.detail.band.strong', light: 'tile.detail.band.light', fresh: 'tile.detail.band.fresh'};
const TREND: Readonly<Record<'Rising' | 'Falling' | 'Turning', StringId>> = {Rising: 'tile.detail.rising', Falling: 'tile.detail.falling', Turning: 'tile.detail.turning'};
const STAGE: Readonly<Record<'ebb' | 'flood' | 'midEbb', StringId>> = {ebb: 'tile.detail.ebb', flood: 'tile.detail.flood', midEbb: 'tile.detail.midEbb'};
const BAR: Readonly<Record<'clear' | 'caution' | 'hazardous' | 'unknown', StringId>> = {clear: 'tile.detail.bar.clear', caution: 'tile.detail.bar.caution', hazardous: 'tile.detail.bar.hazardous', unknown: 'tile.detail.bar.unknown'};

const band = (value: string, lang: Language) => t(BAND[lower(value)]!, lang);
const side = (value: 'onshore' | 'offshore' | 'cross-shore', lang: Language) => t(SIDE[value], lang);

/** One part of a detail line, said in `lang`. */
export function partText(part: TileDetailPart, lang: Language): string {
  switch (part.kind) {
    case 'literal': return part.text;
    case 'gust': return part.value === null ? t('tile.detail.unknownGust', lang) : t('tile.detail.gust', lang, {value: num(part.value, lang)});
    case 'direction': return t('tile.detail.direction', lang, {direction: part.value});
    case 'windSide': return side(part.side, lang);
    case 'kayakWind': return part.side ? t('tile.detail.kayakWindSide', lang, {band: band(part.band, lang), side: side(part.side, lang)}) : band(part.band, lang);
    case 'surf': return t('tile.detail.surf', lang, {band: band(part.band, lang)}) + (part.offshore ? t('tile.detail.offshoreEstimate', lang) : '');
    case 'longSwell': return t('tile.detail.longSwell', lang);
    case 'surge': return t('tile.detail.surge', lang, {band: band(part.band, lang)});
    case 'kayakSeas': return t('tile.detail.seas', lang, {band: band(part.band, lang)});
    case 'shortChop': return t('tile.detail.shortChop', lang);
    case 'launchSurf': return t('tile.detail.launchSurf', lang) + (part.offshore ? t('tile.detail.offshoreEstimate', lang) : '');
    case 'tideTrend': return t(TREND[part.trend], lang);
    case 'nextEvent': return t(part.type === 'H' ? 'tile.detail.nextHigh' : 'tile.detail.nextLow', lang);
    case 'veryLow': return t('tile.detail.veryLow', lang);
    case 'tideStage': return t(STAGE[part.stage], lang);
    case 'barBand': return t(BAR[part.band], lang);
    case 'offshoreForecast': return t('tile.detail.offshoreForecast', lang);
    case 'noNearshore': return t('tile.detail.noNearshore', lang);
    case 'buoy': return t('tile.detail.buoy', lang, {name: part.name});
    case 'noBuoy': return t('tile.detail.noBuoy', lang);
    case 'tideUnavailable': return tideEmptyText('unavailable', lang);
    case 'predictionsUnavailable': return t('tile.detail.predictionsUnavailable', lang);
  }
}

/** The line under a tile's reading. English (and a tile without display metadata) is the model's own `.detail`. */
export function tileDetailText(tile: BriefTile, lang: Language = 'en'): string {
  if (lang === 'en' || !tile.display) return tile.detail;
  return tile.display.parts.map(part => partText(part, lang)).filter(Boolean).join(SEP);
}

/** The tide series' empty wording (web/tides.ts TIDE_UNAVAILABLE and TIDE_NO_CURVE); the sparkline reads it in SC1137-03. */
export function tideEmptyText(kind: 'unavailable' | 'noCurve', lang: Language = 'en'): string {
  return t(kind === 'unavailable' ? 'tide.unavailable' : 'tide.noCurve', lang);
}

/** The tile's source name; a tile with no source says so in `lang` (the model's `source` stays the English "No source"). */
export function tileSourceName(tile: BriefTile, lang: Language = 'en'): string {
  return lang !== 'en' && tile.display?.sourceMissing ? t('tile.detail.noSource', lang) : tile.source;
}

function clockText(clock: NonNullable<GapDisplay['clock']>, lang: Language): string {
  const ms = clock.ageMs;
  if (clock.what === 'ended') return ms >= 0 ? t('tile.clock.ended', lang, {age: ageText(ms)}) : t('tile.clock.runs', lang, {age: ageText(-ms)});
  const id: StringId = clock.what === 'reading' ? 'tile.clock.reading' : clock.what === 'issued' ? 'tile.clock.issued' : clock.what === 'retrieved' ? 'tile.clock.retrieved' : 'tile.clock.fetched';
  return t(id, lang, {age: ageText(ms)});
}

/** A source-gap sentence. English, an unknown status and a gap without display metadata are the model's own `.text`. */
export function sourceGapText(gap: SourceGap, lang: Language = 'en'): string {
  const display = gap.display;
  if (lang === 'en' || !display || display.kind === 'other') return gap.text;
  const label = gap.label, clock = display.clock ? clockText(display.clock, lang) : null;
  switch (display.kind) {
    case 'stale': return clock ? t('tile.gap.staleClock', lang, {label, clock}) : t('tile.gap.stale', lang, {label});
    case 'retained': return clock ? t('tile.gap.retainedClock', lang, {label, clock}) : t('tile.gap.retained', lang, {label});
    case 'failedEmpty': return t('tile.gap.failedEmpty', lang, {label});
    case 'missing': return t('tile.gap.missing', lang, {label});
    case 'failedCheck': return clock ? t('tile.gap.failedCheckClock', lang, {label, clock}) : t('tile.gap.failedCheck', lang, {label});
  }
}
