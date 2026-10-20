// Selected-mark card (FE-05, design § 9): one card for whatever is selected,
// with name, kind, reading, source and age, the regulations line, the action
// row and a basis link. FE-11 filled it from the Chart (a clicked shoreline
// segment); FE-18 adds the atlas reef marks (`?spot=`, in every presentation),
// survey habitat and geology outlines, and the terrain's habitat (`?habitat=`)
// with the renderer's own evidence lines, or restored without graphics, while
// the Chart shows. FE-80: in 2D and 3D the renderer has no panels of its own
// (host chrome), so a terrain reading (its measured or modelled label, value,
// place and source line with its date, verbatim) and the selected habitat's
// evidence show here, with a link that opens the renderer's sources sheet. A mark that names its rules
// page (a protected area, FE-19; an atlas mark or outline, FE-18) links that
// official page; the card never states the rules itself. A pick moves focus to
// the card's heading; the close button, or Escape with no basis open, clears
// the selection and returns focus to where it was (the chart, after a click).
// FE-51: an atlas mark's "Add to trip" and "GPX" go to the trip planner
// (web/trip.ts), as v1's spot sheet does; a ranked trip spot's pin (#495) opens
// it in the plan with v1's "Review & export"; other selections have no trip action.
// FE-82: in 2D and 3D a protected area or charter ground picked on the terrain
// (stage.ts `terrainPick`) gets the card the Chart's click gives it; a reef mark
// picked there selects `?spot=`, as on the Chart.
// FE-54: a habitat card (reef mark, survey or geology outline, terrain habitat,
// charter ground) adds the target's rules at a glance (web/regs.ts, v1's row):
// the reviewed registry's own bag and size clauses, its check date and the
// official page. A protected area or withheld mark keeps its own words instead.
import {computed} from '@preact/signals';
import {useEffect, useRef} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {Popover} from '../ui/Popover.tsx';
import {chartMark} from '../map/chart.ts';
import type {ChartMark} from '../map/coastline.ts';
import {habitatCard, markData, picked, spotCard} from '../map/marks.ts';
import type {CoastReading} from '../../packages/coast/src/embed-types.ts';
import {shownPresentation, terrainActions, terrainDetail, terrainMark, terrainPick, terrainReading} from '../map/stage.ts';
import {navigate, profile, selection, setParams, species} from '../state.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {loadRegs, regsData, regulationState, ruleSummary, verifiedText, type RulesRegion} from '../regs.ts';
import {zone} from './App.tsx';
import {dockState} from './TimeDock.tsx';
import {addToTrip, reviewTrip, tripIds} from '../trip.ts';
import {drawnSpots} from '../map/ranked.ts';
import {MarkForecast} from '../brief/MarkForecast.tsx';
import type {LatLon} from '../brief/mark-forecast.ts';

export type Mark = ChartMark;
export {terrainCard} from '../map/habitat.ts';

/** The card's placeholder while the region's marks load. */
export const placeholderMark = (id: string): Mark => ({id, name: id, kind: 'Mark', reading: '—', source: 'Source —', basis: 'The mark loads with the map engine; its source and age show here.'});

/** The id prefix of a terrain reading's card. */
export const READING = 'reading:';
/** A terrain inspection as a card: the renderer's strings verbatim (label as the kind, its source line with the date). */
export const readingCard = (r: CoastReading): Mark => ({
  id: `${READING}${r.latitude.toFixed(5)},${r.longitude.toFixed(5)}`, name: r.value, kind: r.label, reading: r.location, source: r.detail,
  basis: `${r.source.label}, ${r.source.kind}, dated ${r.source.sourceDate}. The reading is the original nearest displayed sample; not for navigation.`,
});

/**
 * What the card shows: on the Chart, its own selection, then the terrain's; in
 * 2D and 3D an overlay picked on the terrain, a terrain reading, then the
 * terrain's habitat selection. The link's atlas mark shows in every presentation.
 */
export const currentMark = computed<Mark | null>(() => {
  const chart = shownPresentation.value === 'chart', spot = spotCard.value, reading = terrainReading.value;
  return (chart ? chartMark.value ?? habitatCard.value : terrainPick.value ?? (reading ? readingCard(reading) : null) ?? habitatCard.value)
    ?? (spot === undefined ? placeholderMark(selection.value!) : spot);
});

/** The cards that speak for a place to fish, so carry the target's rules. */
const RULED = /^(?:spot|survey|geology|habitat|charter):/;

/** The target's rules at a glance for the dock's hour, or nothing while the region loads. */
export function RulesLine({mark}: {mark: Mark}) {
  const region = markData.value?.region as RulesRegion | undefined, loaded = regsData.value;
  useEffect(() => { if (region) void loadRegs(region); }, [region?.id]);
  if (!region || !RULED.test(mark.id) || mark.withheld) return null;
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget, data = loaded?.region === region.id ? loaded.data : null;
  const at = dockState(new Date(), zone()).at, day = new Intl.DateTimeFormat('en-CA', {timeZone: zone(), year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
  const state = regulationState(data, target, region, Date.now(), day, at), s = ruleSummary(data, target, state, region);
  const name = target === 'reef' ? 'Lingcod & rockfish' : state.profile?.name ?? target;
  const cell = (label: string, values: readonly string[]) => values.length ? <div><dt>{label}</dt>{values.map(v => <dd key={v} class="ui-mono">{v}</dd>)}</div> : null;
  return (
    <div class="app-mark-regs" role="group" aria-label={`Rules at a glance: ${name}`}>
      <p><span class="app-mark-regs-badge" data-status={s.status}>{s.label}</span> <span class="ui-mono">{verifiedText(s)}</span></p>
      <dl>{cell('Bag', s.bag)}{cell('Size', s.size)}{cell('Depth', s.depth ? [s.depth] : [])}</dl>
      <a href={s.link} target="_blank" rel="noopener" aria-label={`${s.linkLabel} for ${name} (official page, opens in a new tab)`}>{s.linkLabel}</a>
    </div>
  );
}

/** Drop the selection from the address (?spot= and ?focus= are read, never written, by the store). */
export function clearSelection(href: string): string {
  const url = new URL(href);
  url.searchParams.delete('spot'); url.searchParams.delete('focus');
  return url.href;
}

/** Clear whichever selection the card shows. */
function clearMark(mark: Mark): void {
  if (mark === chartMark.peek()) { chartMark.value = null; return; }
  if (mark === terrainPick.peek()) { terrainPick.value = null; return; }
  if (mark.id.startsWith(READING)) { terrainReading.value = null; return; }
  if (mark.id.startsWith('habitat:')) {
    // The stage then tells the renderer (selectHabitat(null)), as the scene's own close button does.
    terrainMark.value = null; terrainDetail.value = null;
    setParams({habitat: null});
    return;
  }
  navigate(clearSelection(location.href), {replace: true});
}

/** The last pick the card answered with focus, and where focus was before it. */
let answered = 0, returnTo: HTMLElement | null = null;

/**
 * Where a mark's forecast is read (BP CI6-06): an atlas reef mark the screen shows, or a ranked trip spot still drawn.
 * Never for a withheld mark, whose position the card keeps to itself; other selections have no forecast row.
 */
export function markPlace(mark: Mark): LatLon | null {
  if (mark.withheld) return null;
  const at = (t: {latitude: number; longitude: number} | undefined): LatLon | null =>
    t && Number.isFinite(t.latitude) && Number.isFinite(t.longitude) ? {lat: t.latitude, lon: t.longitude} : null;
  if (mark.trip) return at(drawnSpots.value.find(s => s.id === mark.trip));
  if (mark.id.startsWith('spot:') && mark === spotCard.value) return at(markData.value?.atlas?.targets.find(t => `spot:${t.id}` === mark.id));
  return null;
}

export function MarkCard({mark}: {mark?: Mark} = {}) {
  const selected = mark ?? currentMark.value, request = picked.value;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // A pick, never a link or a restore, moves focus to the card so its reading is announced.
    if (!selected || request === answered || !heading.current) return;
    answered = request;
    const active = document.activeElement;
    returnTo = active instanceof HTMLElement && active !== document.body ? active : null;
    heading.current.focus();
  }, [request, selected?.id]);
  if (!selected) return null;
  // A terrain reading or habitat links the renderer's sources and assumptions sheet beside its basis.
  const sources = shownPresentation.value !== 'chart' && /^(?:reading|habitat):/.test(selected.id) ? terrainActions.value : null;
  // Only an atlas mark or a ranked spot joins a trip: v1's planner exports those. A mark the run-time screen withholds (#489) never does.
  const spot = selected === spotCard.value && !selected.withheld ? selection.value : selected.trip ?? null;
  const target = spot ? markData.value?.atlas?.targets.find(t => t.id === spot) as {canonical_habitat?: boolean} | undefined : undefined;
  const place = markPlace(selected);
  const close = () => {
    const back = returnTo?.isConnected ? returnTo : document.querySelector<HTMLElement>('.app-chart canvas');
    returnTo = null;
    clearMark(selected);
    back?.focus();
  };
  return (
    <section class="app-mark" aria-label="Selected mark"
      onKeyDown={event => { if (event.key === 'Escape' && !event.currentTarget.querySelector('details[open]')) { event.preventDefault(); close(); } }}>
      <div class="app-mark-head">
        <h2 tabIndex={-1} ref={heading}>{selected.name}</h2>
        <IconButton icon="close" label="Clear selection" size="sm" onClick={close} />
      </div>
      <p class="app-mark-kind">{selected.kind}</p>
      <p class="ui-reading">{selected.reading}</p>
      <p class="app-mark-source ui-mono">{selected.source}</p>
      {selected.rules ? (
        <p class="app-mark-rules">{selected.rules}{selected.regulations ? <>{' '}
          <a href={selected.regulations.href} target="_blank" rel="noopener" aria-label={`${selected.regulations.label} (official page, opens in a new tab)`}>{selected.regulations.label}</a>
        </> : null}</p>
      ) : null}
      <RulesLine mark={selected} />
      {place ? <MarkForecast place={place} /> : null}
      <div class="app-mark-actions">
        <Button size="sm" icon={spot && tripIds.value.includes(spot) ? 'check' : 'plus'} disabled={!spot} onClick={() => { if (spot) void addToTrip(spot); }}>
          {spot && tripIds.value.includes(spot) ? 'Added to trip' : target && target.canonical_habitat !== true ? 'Save research reference' : 'Add to trip'}</Button>
        <Button size="sm" icon="download" disabled={!spot} onClick={() => { if (spot) void reviewTrip(spot); }}>{selected.trip ? 'Review & export' : 'GPX'}</Button>
        {selected.regulations ? (
          <a class="ui-button ui-button--ghost ui-button--sm" href={selected.regulations.href} target="_blank" rel="noopener"
            aria-label={`Regulations: ${selected.regulations.label} (official page, opens in a new tab)`}>
            <Icon name="shield" size={16} />Regulations
          </a>
        ) : <Button size="sm" icon="shield" disabled>Regulations</Button>}
      </div>
      <div class="app-mark-basis">
        <Popover>{selected.basis}{selected.terms?.map(t => (
          <p key={t.href}><a href={t.href} target="_blank" rel="noopener" aria-label={`${t.label} (publisher's page, opens in a new tab)`}>{t.label}</a></p>
        ))}</Popover>
        {sources ? <Button variant="quiet" size="sm" icon="info" onClick={() => sources.sources()}>Terrain sources</Button> : null}
      </div>
    </section>
  );
}
