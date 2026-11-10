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
// SC0022-05: a signed-in person's "Save this spot" keeps the selected mark's name and position as a private
// account spot (web/saved-spots.ts); the shared protected-area screen says no first, in words, and nothing
// about the spot reaches the address, a share link, a feed or usage measurement.
import {computed} from '@preact/signals';
import {useEffect, useRef, useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {Popover} from '../ui/Popover.tsx';
import {chartMark} from '../map/chart.ts';
import type {ChartMark} from '../map/coastline.ts';
import {habitatCard, markData, picked, spotCard} from '../map/marks.ts';
import type {CoastReading} from '../../packages/coast/src/embed-types.ts';
import {choosePresentation, shownPresentation, terrainActions, terrainDetail, terrainMark, terrainPick, terrainReading} from '../map/stage.ts';
import {coordinates, navigate, profile, region as stateRegion, selection, setParams} from '../state.ts';
import {formatCoordinates} from '../../dist/coordinates.js';
import {RulesLine} from './RulesCard.tsx';
import {session, type Session} from '../account.ts';
import {resultMessage, saveMarkSpot, screenMarkPosition, spotCandidate, uncertainResult, type PositionRefusal, type SpotResult} from '../saved-spots.ts';
import {language, t, type StringId} from '../i18n.ts';
import {copyText, resolveMarkCopy} from '../mark-copy.ts';
import {addPlaceToTrip, addToTrip, loadProtectedScreen, placeTripId, protectedScreen, reviewPlace, reviewTrip, tripIds, type ProtectedScreen} from '../trip.ts';
import {regulationsCopy, regulationsLink} from '../map/habitat.ts';
import {drawnSpots} from '../map/ranked.ts';
import {SAVED_CARD_PREFIX, savedSpotDistancePosition, setSavedSpotsOn} from '../map/saved-spots.ts';
import {cruiseSpeed} from '../limits.ts';
import {launchOrigin, loadLaunchPoints} from '../launches.ts';
import {homePortOrigin, loadRegionPorts, plannerPort, regionPorts, savedPortId} from '../ports.ts';
import {landWater, loadLandWater, loadLandWaterLines} from '../land-water.ts';
import {harborOrigin, type Origin} from '../ranking.ts';
import {markDistanceLine, routeAfterPaint, straightDistance, type MarkDistance as MarkDistanceResult} from '../mark-distance.ts';
import {mapFocusTarget} from './map-focus.ts';
import {MarkForecast} from '../brief/MarkForecast.tsx';
import type {LatLon} from '../brief/mark-forecast.ts';
import {PrivateMapLog} from './PrivateMapLog.tsx';
import {regionalForecast} from '../brief/Brief.tsx';
import {zone} from './region-info.ts';

export type Mark = ChartMark;
export {RulesLine};
export {terrainCard} from '../map/habitat.ts';

/** The card's placeholder while the region's marks load. */
export const placeholderMark = (id: string): Mark => ({
  id, name: id, kind: t('mark.placeholder.kind'), reading: '—', source: t('mark.placeholder.source'), basis: t('mark.placeholder.basis'),
  copy: {kind: [{id: 'mark.placeholder.kind'}], source: [{id: 'mark.placeholder.source'}], basis: [{id: 'mark.placeholder.basis'}]},
});

/** The id prefix of a terrain reading's card. */
export const READING = 'reading:';
/** A terrain inspection as a card: the renderer's strings verbatim (label as the kind, its source line with the date). */
export const readingCard = (r: CoastReading): Mark => ({
  id: `${READING}${r.latitude.toFixed(5)},${r.longitude.toFixed(5)}`, name: r.value, kind: r.label, reading: '', source: r.detail,
  position: {latitude: r.latitude, longitude: r.longitude},
  basis: t('mark.readingBasis', 'en', {label: r.source.label, kind: r.source.kind, date: r.source.sourceDate}),
  copy: {basis: [{id: 'mark.readingBasis', vars: {label: r.source.label, kind: r.source.kind, date: r.source.sourceDate}}]},
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

/**
 * SC1822-09: where a selected mark's distance is measured to: a private pin's gated in-memory point (never a position on the card, and
 * checked before any ordinary coordinate), a public mark's own non-withheld position, or a ranked trip spot's drawn row. Null otherwise.
 */
function distanceTarget(mark: Mark): {latitude: number; longitude: number} | null {
  if (mark.withheld) return null;
  if (mark.id.startsWith(SAVED_CARD_PREFIX)) return savedSpotDistancePosition(mark);
  if (mark.position) return mark.position;
  const drawn = mark.trip ? drawnSpots.value.find(s => s.id === mark.trip) : undefined;
  return drawn ? {latitude: drawn.latitude, longitude: drawn.longitude} : null;
}

type Routed = {readonly region: string | null; readonly from: Origin; readonly to: {latitude: number; longitude: number}; readonly model: unknown; readonly lines: unknown; readonly result: MarkDistanceResult | null};
const sameAt = (a: {latitude: number; longitude: number}, b: {latitude: number; longitude: number}): boolean => a.latitude === b.latitude && a.longitude === b.longitude;

/**
 * SC1822-09: for Boat and Kayak, one line under the position: the home port's (or Kayak's launch's) name and the distance by water or, when
 * no route is computed, the labelled straight line, with the one-way run at the saved cruise speed. The straight line paints at once; one
 * water route for this mark alone is tried after the paint, and again once the lines file loads. Display only: never stored, exported or shared.
 */
export function MarkDistance({mark}: {mark: Mark}) {
  const p = profile.value, id = stateRegion.value, speed = cruiseSpeed.value, lw = landWater.value;
  const launch = p === 'kayak' ? launchOrigin(id) : null, ports = regionPorts.value, planned = plannerPort.value, data = markData.value;
  const home = launch || !id ? null : homePortOrigin(id, ports, planned?.region === id ? planned.id : null, savedPortId());
  const pending = !launch && !!id && (ports?.region !== id || ports.state === 'loading');
  const harbor = !launch && !home && !pending && id && data?.region.id === id ? harborOrigin(data) : null;
  const from = !id ? null : launch ?? home ?? harbor, to = distanceTarget(mark);
  const model = lw.state === 'ready' && lw.region === id ? lw.model : null, lines = model ? lw.lines : null;
  const [routed, setRouted] = useState<Routed | null>(null);
  useEffect(() => { if (id) { void loadRegionPorts(id); void loadLandWater(id); if (p === 'kayak') void loadLaunchPoints(id); } }, [id, p]);
  const current = !!routed && !!from && !!to && routed.region === id && routed.model === model && routed.lines === lines && sameAt(routed.from, from) && sameAt(routed.to, to);
  const failure = current ? routed.result?.why ?? null : null;
  // The route for this pair, once per stable (region, origin, mark, product, lines) key; a failure is kept, so a re-render never asks again.
  useEffect(() => {
    if (!from || !to || !model || current) return;
    return routeAfterPaint(from, to, model, lines, result => setRouted({region: id, from, to, model, lines, result}));
  }, [id, from?.latitude, from?.longitude, to?.latitude, to?.longitude, model, lines, current]);
  // Losing the target (a private pin's access, a cleared mark) erases the displayed result at once.
  useEffect(() => { if (!to && routed) setRouted(null); }, [!to, routed]);
  // A mixed cell blocked the search: the lines file is asked for once for this product; its arrival is a new key.
  useEffect(() => { if (failure === 'lines-needed' && id && model && lines === null) void loadLandWaterLines(id); }, [failure, id, model, lines]);
  if (!from || !to) return null;
  const shown = current && routed.result ? routed.result : straightDistance(from, to);
  return shown ? <p class="ui-mono" data-mark-distance={shown.basis}>{markDistanceLine(from.name, shown, speed, 'en')}</p> : null;
}

const COPY_REASON = {context: 'mark.copy.reason.context', noPosition: 'mark.copy.reason.noPosition', notChecked: 'mark.copy.reason.notChecked',
  inside: 'mark.copy.reason.inside', margin: 'mark.copy.reason.margin'} as const satisfies Record<Exclude<PositionRefusal, 'withheld'>, StringId>;
type CopyLife = {readonly key: string; readonly life: number};
type CopyStatus = {readonly at: CopyLife; readonly state: 'pending' | 'copied' | 'failed'} | {readonly at: CopyLife; readonly state: 'refused'; readonly reason: PositionRefusal; readonly loaded: ProtectedScreen};

/**
 * SC2252-09: "Copy position" beside the card's position line writes exactly the displayed `text` to the clipboard, nothing else, only when
 * the shared protected-area screen allows the mark (web/saved-spots.ts `screenMarkPosition`, the save path's own rule, with no account);
 * otherwise the screen's reason shows and there is no button. Asked again at the click. Nothing is sent or stored. An answer belongs to
 * the mark, its point, the region and the text, in this lifetime of them: a late answer for another (or an earlier A of A→B→A) says nothing.
 */
export function CopyPositionAction({mark, text}: {mark: Mark; text: string}) {
  const where = stateRegion.value, loaded = protectedScreen.value, lang = language.value, at = mark.position;
  const key = JSON.stringify([mark.id, at?.latitude ?? null, at?.longitude ?? null, where, text]);
  const [status, setStatus] = useState<CopyStatus | null>(null);
  const life = useRef<CopyLife>({key, life: 0}), pending = useRef<CopyLife | null>(null), mounted = useRef(true);
  if (life.current.key !== key) life.current = {key, life: life.current.life + 1};
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const answer = screenMarkPosition(mark, where, loaded);
  const screenable = answer.allowed || answer.reason === 'notChecked' || answer.reason === 'inside' || answer.reason === 'margin';
  // The region's one shared screen (web/trip.ts dedupes it); its arrival re-renders through the signal.
  useEffect(() => { if (where && screenable) void loadProtectedScreen(where); }, [where, screenable, mark.id, at?.latitude, at?.longitude]);
  const own = status && status.at === life.current ? status : null;
  const reason = own?.state === 'refused' && own.loaded === loaded ? own.reason : answer.allowed ? null : answer.reason;
  if (reason === 'withheld') return null;
  if (reason) return <p class="app-mark-copy" role="status">{t(COPY_REASON[reason], lang)}</p>;
  const copy = () => {
    const mine = life.current;
    if (pending.current === mine) return;
    // Asked again now: a screen that went stale or changed since the paint refuses here, and nothing is written.
    const now = screenMarkPosition(mark, stateRegion.peek(), protectedScreen.peek());
    if (!now.allowed) { setStatus({at: mine, state: 'refused', reason: now.reason, loaded: protectedScreen.peek()}); return; }
    let wrote: Promise<unknown>;
    // The write starts inside the click, before any wait, so the browser still counts it as the person's own act.
    try { wrote = Promise.resolve(navigator.clipboard.writeText(text)); } catch { setStatus({at: mine, state: 'failed'}); return; }
    pending.current = mine;
    setStatus({at: mine, state: 'pending'});
    void wrote.then(() => 'copied' as const, () => 'failed' as const).then(state => {
      if (pending.current === mine) pending.current = null;
      if (mounted.current && life.current === mine) setStatus({at: mine, state});
    });
  };
  return (
    <div class="app-mark-copy" style={{display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-1)'}}>
      <Button size="sm" icon={own?.state === 'copied' ? 'check' : undefined} aria-disabled={own?.state === 'pending' ? 'true' : undefined} onClick={copy}>{t('mark.copy.action', lang)}</Button>
      <p role="status">{own?.state === 'copied' ? t('mark.copy.copied', lang) : own?.state === 'failed' ? t('mark.copy.failed', lang) : ''}</p>
    </div>
  );
}

/**
 * SC1722-16: the explicit "Show on Chart" press after a confirmed save. Only while the session that saved is still the signed-in one and the
 * region is still the saved region does it turn the private saved-spots layer on (Chart-only, page memory only) and, from 2D or 3D, open
 * the Chart through the ordinary presentation change. No mark, point or row is handed on; saving alone never calls this.
 */
function showSavedSpotsOnChart(saved: {readonly session: Session; readonly region: string | null}): void {
  if (session.peek() !== saved.session || stateRegion.peek() !== saved.region) return;
  setSavedSpotsOn(true);
  if (shownPresentation.peek() !== 'chart') choosePresentation('chart');
}

type SaveKey = {readonly id: string; readonly name: string; readonly lat: number | null; readonly lon: number | null; readonly region: string | null; readonly session: Session};
type SaveStatus = {readonly key: SaveKey; readonly state: 'pending' | SpotResult['state']; readonly result: SpotResult | null};
const sameSave = (a: SaveKey | null, b: SaveKey | null): boolean =>
  !!a && !!b && a.id === b.id && a.name === b.name && a.lat === b.lat && a.lon === b.lon && a.region === b.region && a.session === b.session;

/**
 * SC0022-05: "Save this spot" for a signed-in person, with its plain-text status. A save belongs to the mark's identity, name, position,
 * region and session: a different mark, region or account resets it, and a late answer for another one is ignored.
 */
export function SaveSpotAction({mark}: {mark: Mark}) {
  const who = session.value, where = stateRegion.value, at = mark.position, lang = language.value;
  const key: SaveKey = {id: mark.id, name: mark.name, lat: at ? at.latitude : null, lon: at ? at.longitude : null, region: where, session: who};
  const [status, setStatus] = useState<SaveStatus | null>(null);
  const latest = useRef(key), inflight = useRef<SaveKey | null>(null), mounted = useRef(true);
  latest.current = key;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setStatus(null); }, [key.id, key.name, key.lat, key.lon, key.region, key.session]);
  if (who.state !== 'signed-in') return null;
  const shown = status && sameSave(status.key, key) ? status : null, candidate = spotCandidate(mark);
  const blocked = 'state' in candidate ? candidate : null;
  const save = async () => {
    if (blocked || shown?.state === 'pending' || shown?.state === 'saved' || sameSave(inflight.current, key)) return;
    const mine = key;
    inflight.current = mine;
    setStatus({key: mine, state: 'pending', result: null});
    const result = await saveMarkSpot(mark).catch(uncertainResult);
    if (sameSave(inflight.current, mine)) inflight.current = null;
    if (!mounted.current || !sameSave(latest.current, mine)) return;
    setStatus({key: mine, state: result.state, result});
  };
  const saved = shown?.state === 'saved';
  const showOnChart = () => { if (mounted.current && sameSave(latest.current, key) && shown?.state === 'saved') showSavedSpotsOnChart(key); };
  return (
    <>
      <Button size="sm" icon={saved ? 'check' : 'plus'} disabled={!!blocked || shown?.state === 'pending' || saved} onClick={() => { void save(); }}>
        {shown?.state === 'pending' ? t('mark.save.pending', lang) : saved ? t('mark.save.saved', lang) : t('mark.save.action', lang)}</Button>
      {saved ? <Button size="sm" icon="map" onClick={showOnChart}>{t('mark.save.showChart', lang)}</Button> : null}
      <div class="app-mark-why" style={{flexBasis: '100%'}}>
        <p>{t('mark.save.helper', lang)}</p>
        <p role="status">{shown?.result && shown.state !== 'pending' ? resultMessage(shown.result, lang) : blocked ? resultMessage(blocked, lang) : ''}</p>
      </div>
    </>
  );
}

export function MarkCard({mark}: {mark?: Mark} = {}) {
  const selected = mark ?? currentMark.value, request = picked.value, lang = language.value;
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
  // SC0922-04: a private saved-spot card (web/map/saved-spots.ts) offers no trip, GPX or save action: it has no position of its own to hand on.
  const privateSaved = selected.id.startsWith(SAVED_CARD_PREFIX);
  // SCJ-1: a habitat card (the brief's recommended places) joins a trip, or opens it for GPX, as a user waypoint, and links its region's rules page.
  const habitat = selected.id.startsWith('habitat:'), survey = selected.id.startsWith('survey:'), at = selected.withheld ? undefined : selected.position;
  const where = (habitat || survey) && at && Number.isFinite(at.latitude) && Number.isFinite(at.longitude)
    ? {id: selected.id, name: (survey && selected.kind === t('mark.kind.kelp', 'en') ? `${t('mark.kind.kelp', 'en')} · ${selected.name}` : selected.name).slice(0, 80), latitude: at.latitude, longitude: at.longitude, shore: survey ? ![t('mark.kind.hard', 'en'), t('mark.kind.mixed', 'en')].includes(selected.kind) : /\bshore\b/i.test(`${selected.name} ${selected.kind}`)} : null;
  const added = spot ? tripIds.value.includes(spot) : !!where && tripIds.value.includes(survey ? `user:survey-${where.id.slice(7).replace(/[^a-zA-Z0-9-]/g, '-').slice(0, 72)}` : placeTripId(where.id));
  const regulations = selected.regulations ?? (habitat && markData.value?.region ? regulationsLink(markData.value.region) : undefined);
  // The fallback link (a habitat card with no regulations of its own) is named in the page's language too.
  const regulationsName = !regulations || selected.regulations ? '' : lang === 'es' && markData.value?.region ? copyText(regulationsCopy(markData.value.region), lang) : regulations.label;
  const close = () => {
    const back = returnTo?.isConnected ? returnTo : mapFocusTarget(document);
    returnTo = null;
    clearMark(selected);
    back?.focus();
  };
  const shown = resolveMarkCopy(selected, lang);
  // SC2252-09: one string for the position line and its copy, in the person's chosen format.
  const positionText = selected.position && !selected.withheld ? formatCoordinates(selected.position.latitude, selected.position.longitude, coordinates.value) : null;
  return (
    <section class="app-mark" aria-label={t('mark.selected', lang)}
      onKeyDown={event => { if (event.key === 'Escape' && !event.currentTarget.querySelector('details[open]')) { event.preventDefault(); close(); } }}>
      <div class="app-mark-head">
        <h2 tabIndex={-1} ref={heading}>{shown.name}</h2>
        <IconButton icon="close" label={t('mark.clear', lang)} size="sm" onClick={close} />
      </div>
      <p class="app-mark-kind">{shown.kind}</p>
      {selected.reading ? <p class="ui-reading">{shown.reading}</p> : null}
      {positionText !== null ? <p class="ui-mono">{positionText}</p> : null}
      {positionText !== null && !privateSaved ? <CopyPositionAction mark={selected} text={positionText} /> : null}
      {(profile.value === 'boat' || profile.value === 'kayak') && !selected.withheld ? <MarkDistance mark={selected} /> : null}
      <p class="app-mark-source ui-mono">{shown.source}</p>
      {selected.provider ? <a href={selected.provider.href} target="_blank" rel="noopener">{selected.provider.label}</a> : null}
      {selected.rules ? (
        <p class="app-mark-rules">{shown.rules}{selected.regulations ? <>{' '}
          <a href={selected.regulations.href} target="_blank" rel="noopener" aria-label={t('mark.officialAria', lang, {label: shown.regulationsLabel!})}>{shown.regulationsLabel}</a>
        </> : null}</p>
      ) : null}
      <RulesLine mark={selected} />
      {place ? <MarkForecast place={place} /> : null}
      {!privateSaved && stateRegion.value ? <PrivateMapLog key={`${stateRegion.value}:${selected.id}`} mark={selected} region={stateRegion.value} forecast={regionalForecast.value} tz={zone()} /> : null}
      {privateSaved ? null : <div class="app-mark-actions">
        <Button size="sm" icon={added ? 'check' : 'plus'} disabled={!spot && !where} onClick={() => { if (spot) void addToTrip(spot); else if (where) void addPlaceToTrip(where); }}>
          {added ? t('mark.added', lang) : target && target.canonical_habitat !== true ? t('mark.research', lang) : t('mark.add', lang)}</Button>
        <Button size="sm" icon="download" disabled={!spot && !where} onClick={() => { if (spot) void reviewTrip(spot); else if (where) void reviewPlace(where); }}>{selected.trip ? t('mark.review', lang) : 'GPX'}</Button>
        {regulations ? (
          <a class="ui-button ui-button--ghost ui-button--sm" href={regulations.href} target="_blank" rel="noopener"
            aria-label={t('mark.regulationsAria', lang, {label: selected.regulations ? shown.regulationsLabel! : regulationsName})}>
            <Icon name="shield" size={16} />{t('mark.regulations', lang)}
          </a>
        ) : <Button size="sm" icon="shield" disabled>{t('mark.regulations', lang)}</Button>}
        <SaveSpotAction mark={selected} />
      </div>}
      {!selected.withheld && (survey && !where || /^(geology|charter|fleet):/.test(selected.id)) ? <p class="app-mark-why">{t(survey ? 'mark.pick' : selected.id.startsWith('geology:') ? 'mark.geology' : 'mark.activity', lang)}</p> : null}
      {habitat && !selected.withheld && !where ? <p class="app-mark-why">{t('mark.noPosition', lang)}</p> : null}
      <div class="app-mark-basis">
        <Popover>{shown.basis}{selected.terms?.map((term, i) => (
          <p key={term.href}><a href={term.href} target="_blank" rel="noopener" aria-label={t('mark.publisherAria', lang, {label: shown.terms[i] ?? term.label})}>{shown.terms[i] ?? term.label}</a></p>
        ))}</Popover>
        {sources ? <Button variant="quiet" size="sm" icon="info" onClick={() => sources.sources()}>{t('mark.sources', lang)}</Button> : null}
      </div>
    </section>
  );
}
