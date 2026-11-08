// SC-GPSOFFLINE-1: the position check's words. Pure: props in, markup out, so the tests render it and no state, storage or request lives here.
// Phone first: large type, one answer line, the distance and the accuracy under it, and the official-rules link always last.
import {Button} from '../ui/Button.tsx';
import {t, type Language} from '../i18n.ts';
import {FT_PER_M, M_PER_NMI} from '../units.ts';
import {PLANNING_MARGIN_M} from '../../dist/geo-screen.js';
import type {PackState, PositionResult} from '../position-check.ts';

/** The page that holds CDFW's MPA rules and maps (the same place the planner's boundary popups link to). */
export const OFFICIAL_RULES_URL = 'https://wildlife.ca.gov/Conservation/Marine/MPAs';
/** What the angler is looking at: not asked yet, waiting for the fix, or a result. */
export type PositionState = {phase: 'idle'} | {phase: 'reading'} | {phase: 'done'; result: PositionResult};

/** "85 m (279 ft)" under a kilometre; "1.3 nmi (2.4 km)" above. Whole numbers for metres and feet. */
export function distanceText(metres: number): string {
  if (metres < 1000) return `${Math.round(metres)} m (${Math.round(metres * FT_PER_M)} ft)`;
  return `${(metres / M_PER_NMI).toFixed(1)} nmi (${(metres / 1000).toFixed(1)} km)`;
}

const day = (iso: string | null, lang: Language): string => iso && Number.isFinite(Date.parse(iso)) ? iso.slice(0, 10) : t('trip.pos.unknownDate', lang);

export function PositionView({state, pack, onCheck, lang}: {state: PositionState; pack: PackState; onCheck: () => void; lang: Language}) {
  const busy = state.phase === 'reading', done = state.phase === 'done' ? state.result : null;
  const reading = done && 'reading' in done ? done.reading : null;
  const checked = reading?.kind === 'checked' ? reading : null;
  const refusal = done && !('reading' in done) ? done.located.reason : null;
  const headline = !checked ? null : checked.where === 'inside' ? (checked.name ? t('trip.pos.inside', lang, {name: checked.name}) : t('trip.pos.insideUnnamed', lang))
    : checked.where === 'near' ? (checked.name ? t('trip.pos.near', lang, {name: checked.name}) : t('trip.pos.nearUnnamed', lang))
    : checked.name && checked.distanceM !== null ? t('trip.pos.outside', lang, {name: checked.name}) : t('trip.pos.outsideAll', lang);
  const fix = done && 'reading' in done && done.located.ok ? done.located.fix : null;
  return (
    <section class="pos-check" aria-labelledby="pos-heading">
      <h3 id="pos-heading">{t('trip.pos.heading', lang)}</h3>
      <p class="pos-note">{t('trip.pos.note', lang)}</p>
      {pack === 'none' ? <p class="pos-warn" role="status">{t('trip.pos.noPack', lang)}</p> : null}
      <Button variant="primary" class="pos-button" disabled={busy} onClick={onCheck}>{busy ? t('trip.pos.reading', lang) : t(done ? 'trip.pos.again' : 'trip.pos.button', lang)}</Button>
      <div class="pos-result" role="status" aria-live="polite">
        {refusal ? <p class="pos-warn">{t(refusal === 'denied' ? 'trip.pos.denied' : refusal === 'unsupported' ? 'trip.pos.unsupported' : 'trip.pos.unavailable', lang)}</p> : null}
        {reading?.kind === 'no-boundaries' ? <p class="pos-warn">{t('trip.pos.noBoundaries', lang)}</p> : null}
        {reading?.kind === 'not-covered' ? <p class="pos-warn">{t('trip.pos.notCovered', lang)}</p> : null}
        {checked && headline ? <>
          <p class="pos-verdict" data-where={checked.where}>{headline}</p>
          {checked.where === 'inside' ? <p class="pos-line">{t('trip.pos.onBoundary', lang)}</p>
            : checked.distanceM !== null ? <p class="pos-line">{t('trip.pos.distance', lang, {distance: distanceText(checked.distanceM)})}</p>
            : <p class="pos-line">{t('trip.pos.distanceFar', lang, {distance: distanceText(20000)})}</p>}
          <p class="pos-line">{checked.fix.accuracyM === null ? t('trip.pos.accuracyUnknown', lang) : t('trip.pos.accuracy', lang, {distance: distanceText(checked.fix.accuracyM)})}</p>
          {checked.lowAccuracy ? <p class="pos-warn">{t('trip.pos.lowAccuracy', lang)}</p> : null}
          {checked.stale ? <p class="pos-warn">{t('trip.pos.stale', lang, {date: day(checked.checkedAt, lang)})}</p> : <p class="pos-line pos-small">{t('trip.pos.checkedOn', lang, {date: day(checked.checkedAt, lang)})}</p>}
          <p class="pos-small">{t('trip.pos.margin', lang, {distance: distanceText(PLANNING_MARGIN_M)})}</p>
        </> : null}
        {fix && !checked ? <p class="pos-line">{fix.accuracyM === null ? t('trip.pos.accuracyUnknown', lang) : t('trip.pos.accuracy', lang, {distance: distanceText(fix.accuracyM)})}</p> : null}
      </div>
      <p class="pos-official">{t('trip.pos.official', lang)} <a href={OFFICIAL_RULES_URL} target="_blank" rel="noopener noreferrer">{t('trip.pos.officialLink', lang)}</a></p>
    </section>
  );
}
