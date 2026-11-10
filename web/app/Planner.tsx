// The day planner inside the trip dialog (FE-51, #602): spots, layers and the
// GPX hand-off, rendered from web/planner.ts's signals. It replaces v1's
// dist/export-ui.js markup with the same controls, ids and copy, so a plan reads
// and exports as before. Loaded with the planner on first open. Styles:
// web/app/trip.css. SC0707-10: every word is a catalogue id read at render in the
// chosen language; the model's English messages go through web/planner-copy.ts.
import {useEffect, useLayoutEffect, useRef} from 'preact/hooks';
import {signal} from '@preact/signals';
import {coordinates} from '../state.ts';
import {session} from '../account.ts';
import {formatCoordinates} from '../../dist/coordinates.js';
import {USER_WAYPOINT_CATEGORIES} from '../../dist/trip-export.js';
import type {Filters, LayerKey, Planner as Model, Preset, ProtectedHit, Target, TripSpecies} from '../planner.ts';
import {ALERT_STORAGE_NOTE, PORTS_FAILED_NOTE, sharedConfidence, type AlertLegsFn} from '../planner.ts';
import {AREA_NOTE} from '../planner-alerts.ts';
import {tripLegs} from '../trip-legs.ts';
import {protectedScreen} from '../trip.ts';
import {cruiseSpeed} from '../limits.ts';
import {landWater, loadLandWaterLines, type LandWaterState} from '../land-water.ts';
import {language, t, type Language, type StringId} from '../i18n.ts';
import {categoryText, countText, evidenceLabel, fitText, hitReading, nmText, plannerText, plannerVerdict} from '../planner-copy.ts';
import {PlanRules} from './PlanRules.tsx';
import {waterRoute, type Route, type RoutePoint} from '../route.ts';
// Leg routes over the land/water product and lines the Boat brief reads (FSC-05), kept until either changes so a re-render does not search again.
let legRoutes: {model: unknown; lines: unknown; byKey: Map<string, Route>} | null = null;
function legRoute(lw: LandWaterState, id: string): (a: RoutePoint, b: RoutePoint) => Route {
  const model = lw.state === 'ready' && lw.region === id ? lw.model : null;
  if (!(legRoutes && legRoutes.model === model && legRoutes.lines === lw.lines)) legRoutes = {model, lines: lw.lines, byKey: new Map()};
  const byKey = legRoutes.byKey;
  return (a, b) => { const key = `${a.latitude},${a.longitude}>${b.latitude},${b.longitude}`; if (!byKey.has(key)) byKey.set(key, waterRoute(model, lw.lines, a, b)); return byKey.get(key)!; };
}

/** Device help: the published device name (a catalogue id for a name that is not a model's own), the translated steps and the official reference. */
const DEVICE_HELP: Readonly<Record<string, readonly [StringId, StringId, string]>> = {
  generic: ['planner.help.generic', 'planner.device.generic', 'https://www8.garmin.com/manuals/webhelp/GUID-3E67C80C-0812-4EEC-BC60-699751B9CF6F/EN-US/GPSMAP_x3_OM_EN-US.pdf'],
  garmin: ['planner.deviceName.garmin', 'planner.device.garmin', 'https://support.garmin.com/en-US/?faq=zFDPlv7AnK2eNWRp2AgMkA'],
  lowrance: ['planner.deviceName.lowrance', 'planner.device.lowrance', 'https://www.lowrance.com/hds-pro/specs/'],
  simrad: ['planner.deviceName.simrad', 'planner.device.simrad', 'https://www.simrad-yachting.com/en-eu/nsx/specifications/'],
  raymarine: ['planner.deviceName.raymarine', 'planner.device.raymarine', 'https://docs.raymarine.com/81406/en-US/latest/index.html'],
  inavx: ['planner.deviceName.inavx', 'planner.device.inavx', 'https://inavx.com/h/inavx/waypoints.htm'],
};
const LAYERS: readonly (readonly [LayerKey, StringId, StringId])[] = [
  ['waypoints', 'planner.layer.waypoints', 'planner.layer.waypoints.text'],
  ['outlines', 'planner.layer.outlines', 'planner.layer.outlines.text'],
  ['alignments', 'planner.layer.alignments', 'planner.layer.alignments.text'],
  ['exclusions', 'planner.layer.exclusions', 'planner.layer.exclusions.text'],
];
/** C1 and C4 short forms, verbatim from docs/legal/disclaimers.md (placement item 4: before a chartplotter file is downloaded). The English constants; the page renders them in the chosen language. */
export const EXPORT_CAVEATS = [t('brief.planning', 'en'), t('planner.caveat.c4', 'en')] as const;
const PRESETS: readonly Preset[] = ['map', 'filtered', 'region', 'none'];

/** The spot's checkbox title and lines, as v1 listed them. */
function SpotRow({t: spot, checked, hit, showConfidence = true, onToggle}: {t: Target; checked: boolean; hit?: ProtectedHit; showConfidence?: boolean; onToggle: (on: boolean) => void}) {
  const lang = language.value;
  const depth = spot.canonical_habitat ? (spot.neighborhood_depth_ft ?? []).map(n => Math.round(n)).join('–') : spot.center_depth_ft;
  return (
    <label class="export-check">
      <input type="checkbox" data-spot={spot.id} checked={checked} onChange={e => onToggle(e.currentTarget.checked)} />
      <span>
        <strong>{spot.trip_rank ? `#${spot.trip_rank} · ${fitText(spot.trip_fit, lang)}${showConfidence && Number.isFinite(spot.evidence_confidence?.percent) ? ` · ${t('planner.spot.confidence', lang, {n: spot.evidence_confidence!.percent})}` : ''}` : spot.label}</strong>
        <small>{evidenceLabel(spot, lang)}</small>
        <small>{formatCoordinates(spot.latitude, spot.longitude, coordinates.value)}</small>
        <small>{spot.trip_rank ? spot.name : spot.id} · {t('planner.spot.grade', lang, {grade: spot.habitat_grade ?? ''})} · {depth} ft</small>
        {spot.trip_rank && spot.distance_basis && typeof spot.distance_nm === 'number' && Number.isFinite(spot.distance_nm) ? <small>{nmText(spot.distance_nm, lang)} nm {t(spot.distance_basis === 'water' ? 'planner.dist.water' : 'planner.dist.straight', lang)}</small> : null}
        {spot.trip_rank ? <small>{spot.terrain_interpretation}</small> : null}
        {hit ? <small>{hitReading(hit, lang)} {t('planner.boundary.context', lang)} {hit.matches.map(m => <span key={m.url + m.name}>{m.name} · <a href={m.url} target="_blank" rel="noopener">{t('planner.boundary.link', lang, {agency: m.agency})}</a> </span>)}</small> : null}
      </span>
    </label>
  );
}

/** A leg's protected-area line after its distance and minutes: not checked, inside, or near; a checked clear leg adds nothing (no claim of safety). Plain text, so a closure's name is never markup. */
const legLine = (v: Parameters<typeof plannerVerdict>[0], lang: Language): string => { const line = plannerVerdict(v, lang); return line ? ` · ${line}` : ''; };

function BoundaryNote({hit}: {hit?: ProtectedHit}) {
  const lang = language.value;
  return hit ? <p>{hitReading(hit, lang)} {t('planner.boundary.context', lang)} {hit.matches.map(m => <span key={m.url + m.name}>{m.name} · <a href={m.url} target="_blank" rel="noopener">{t('planner.boundary.link', lang, {agency: m.agency})}</a> </span>)}</p> : null;
}

/** SC0022-11: the signed-in person's own spots as stops (plain text throughout). Add copies a name and a position into this browser's plan; the model reads the screen again on every Add. */
function SavedSpots({m}: {m: Model}) {
  const lang = language.value, state = m.savedSpotsState.value, rows = m.savedSpots.value, status = m.savedSpotsStatus.value;
  return (
    <section class="export-card" id="export-saved-spots" aria-label={t('planner.saved.aria', lang)}>
      <h3>{t('planner.saved.aria', lang)}</h3>
      <p class="export-note">{t('planner.saved.note', lang)}</p>
      {state === 'loading' ? <p role="status">{t('planner.saved.loading', lang)}</p> : null}
      {state === 'failed' ? <p role="status">{t('planner.saved.failed', lang)} <button type="button" onClick={() => void m.refreshSavedSpots()}>{t('planner.saved.retry', lang)}</button></p> : null}
      {state === 'ready' && !rows.length ? <p role="status">{t('planner.saved.none', lang)}</p> : null}
      {rows.length ? <ul aria-label={t('planner.saved.list', lang)}>{rows.map(r => <li key={r.id}>
        <strong>{r.name}</strong> <small>{formatCoordinates(r.latitude, r.longitude, coordinates.value)}</small> <small>{plannerText(r.reading, lang)}</small>{' '}
        <button type="button" disabled={r.refused} aria-label={t('planner.saved.addAria', lang, {name: r.name})} onClick={() => m.addSavedSpot(r.id)}>{t('planner.saved.add', lang)}</button>
      </li>)}</ul> : null}
      <p role="status" id="export-saved-spots-status">{plannerText(status, lang)}</p>
    </section>
  );
}

/** SC1822-04: the signed-in person's explicit "Alert me for this trip": a preview of exactly what is saved, then one private snapshot. Nothing is sent until the click. */
function AlertSave({m, legs, open}: {m: Model; legs: AlertLegsFn; open: boolean}) {
  useEffect(() => { if (!open) return; m.setAlertOpen(true); return () => m.setAlertOpen(false); }, [open, m]);
  const lang = language.value, plan = open ? m.alertPreview(legs) : null, status = m.alertStatus.value;
  if (!plan) return null;
  const p = plan.ok ? plan.preview : null, done = plan.ok && m.alertIsSaved(plan.body);
  return (
    <section class="export-card" id="planner-alert" aria-label={t('planner.alert.aria', lang)}>
      <h3>{t('planner.alert.aria', lang)}</h3>
      {p ? <>
        <p class="export-note" id="planner-alert-preview">{`${p.date} · ${p.area} · ${p.target} · ${p.hours} · ${t('planner.alert.limits', lang, {wind: p.limits.wind, gust: p.limits.gust, sea: p.limits.sea})} · ${plannerText(p.boat, lang)} · ${t(p.stops === 1 ? 'planner.alert.stop' : 'planner.alert.stops', lang, {n: p.stops})}, ${t(p.legs === 1 ? 'planner.alert.leg' : 'planner.alert.legs', lang, {n: p.legs})}`}</p>
        <ol aria-label={t('planner.alert.legsAria', lang)} id="planner-alert-legs">{p.legList.map((l, i) => <li key={i}>{`${l.from} → ${l.to} · ${nmText(l.nm, lang)} nm${l.basis === 'straight' ? t('planner.leg.straight', lang) : ''}${t('planner.leg.min', lang, {n: l.minutes})}${l.screen ? legLine(l.screen as Parameters<typeof plannerVerdict>[0], lang) : t('planner.alert.notChecked', lang)}`}</li>)}</ol>
        {p.legList.some(l => l.basis === 'straight') ? <p class="export-note" id="planner-alert-legs-note">{t('planner.leg.straightCaveat', lang)}{t('planner.leg.common', lang)}</p> : null}
        {p.groupNote ? <p class="export-note">{plannerText(p.groupNote, lang)}</p> : null}
        <p class="export-note">{plannerText(AREA_NOTE, lang)} {t('planner.alert.estimates', lang)}</p>
        <button type="button" id="planner-save-alert" disabled={m.alertBusy.value || done} onClick={() => void m.saveAlert(legs)}>{t('planner.alert.save', lang)}</button>
      </> : <p class="export-note" id="planner-alert-preview">{plan.ok ? '' : plannerText(plan.message, lang)}</p>}
      <p role="status" id="planner-alert-status">{plannerText(status, lang)}</p>
    </section>
  );
}

export function Planner({model: m, open}: {model: Model; open: boolean}) {
  // While the dialog shows: the screen's age each minute and new boundaries refresh the counts; opening restores a saved ranked plan, else ranks an empty one (SCJ-8).
  useEffect(() => {
    if (!open) return;
    m.tick.value++;
    void m.restore();
    m.openReady();
    const bump = () => { m.tick.value++; };
    document.addEventListener('skippercast:boundaries', bump);
    const timer = setInterval(bump, 60000);
    return () => { document.removeEventListener('skippercast:boundaries', bump); clearInterval(timer); };
  }, [open, m]);

  useEffect(() => { if (!open) return; m.setSavedSpotsOpen(true); return () => m.setSavedSpotsOpen(false); }, [open, m]);

  const lang = language.value;
  const d = m.draft.value, f = m.filters.value, s = m.summary.value, ranked = m.ranked.value, research = m.allowResearch.value;
  const blocked = !ranked || m.filtersDirty.value || !d.ids.length;
  const filter = <K extends keyof Filters>(key: K, parse: (v: string) => Filters[K]) => (e: Event) => m.setFilter(key, parse((e.currentTarget as HTMLInputElement).value));
  const device = DEVICE_HELP[deviceChoice.value] ?? DEVICE_HELP.generic!;
  const spots = m.spots.value, shared = sharedConfidence(spots);
  const port = !m.portsFailed.value && m.ports.value.find(p => p.id === f.port);
  const stops = m.orderedStops.value;
  const orderFocus = useRef<{id: string; direction: 'up' | 'down'} | null>(null);
  const orderButtons = useRef(new Map<string, HTMLButtonElement>());
  useLayoutEffect(() => {
    const wanted = orderFocus.current;
    if (!wanted) return;
    const other = wanted.direction === 'up' ? 'down' : 'up';
    (orderButtons.current.get(`${wanted.id}:${wanted.direction}`) ?? orderButtons.current.get(`${wanted.id}:${other}`))?.focus();
    orderFocus.current = null;
  }, [d.ids]);
  const move = (id: string, direction: 'up' | 'down') => {
    orderFocus.current = {id, direction};
    if (!m.moveStop(id, direction)) orderFocus.current = null;
  };
  // BF-closures-everywhere: the planner's shared screen for THIS region, else null (every leg then reads not checked). Its contents are mutable, so the tick (minute and boundary updates) is read here too.
  void m.tick.value;
  const shown = protectedScreen.value, screen = shown.state === 'loaded' && shown.region === m.region.id ? shown.screen : null;
  const route = tripLegs(port ? {name: port.name, lat: port.match[0], lon: port.match[1]} : null,
    stops.map(t => ({id: t.id, name: t.name || t.label || t.id, lat: t.latitude, lon: t.longitude})), cruiseSpeed.value,
    legRoute(landWater.value, m.region.id), screen);
  // The shoreline lines are asked for once when a leg waits on them (shared with the brief's request); the legs re-render when they land.
  const alertLegs: AlertLegsFn = stops => tripLegs(port ? {name: port.name, lat: port.match[0], lon: port.match[1]} : null, stops, cruiseSpeed.value, legRoute(landWater.value, m.region.id), screen);
  const waits = route.legs.some(leg => leg.why === 'lines-needed');
  useEffect(() => { if (waits) void loadLandWaterLines(m.region.id); }, [waits, m]);
  const minutes = (n: number | null): string => n === null ? '' : t('planner.leg.min', lang, {n});
  const storage = session.value.state === 'signed-in' && m.storageNote.value === t('pm.storageOk', 'en') ? ALERT_STORAGE_NOTE : m.storageNote.value;

  return (
    <div id="export-content">
      <div class="export-card export-plan">
        <div class="export-fields">
          <label>{t('planner.planName', lang)}<input id="export-name" maxLength={80} value={d.name} onInput={e => m.edit({name: e.currentTarget.value})} /></label>
          <label>{t('planner.fishingDate', lang)}<input type="date" id="export-date" value={d.date} onInput={e => m.edit({date: e.currentTarget.value})} /></label>
        </div>
        <p class="export-note" id="export-storage">{plannerText(storage, lang)}</p>
      </div>
      <PlanRules date={d.date} species={f.species} region={m.region} />
      <section class="export-card" aria-label={t('planner.waypoints.heading', lang)}>
        <h2>{t('planner.waypoints.heading', lang)}</h2>
        <p>{t('planner.waypoints.note', lang)}</p>
        <button id="waypoint-place" onClick={m.chooseWaypoint}>{t('planner.waypoints.place', lang)}</button>
        {m.waypointPosition.value ? <form onSubmit={e => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          m.saveWaypoint(String(data.get('name')), String(data.get('category')));
        }}>
          <p>{formatCoordinates(m.waypointPosition.value.latitude, m.waypointPosition.value.longitude, coordinates.value)}</p>
          <label>{t('planner.waypoints.name', lang)}<input name="name" maxLength={80} required /></label>
          <label for="waypoint-category">{t('planner.waypoints.category', lang)}</label><select id="waypoint-category" name="category">{USER_WAYPOINT_CATEGORIES.map(category => <option key={category} value={category}>{categoryText(category, lang)}</option>)}</select>
          <button type="submit">{t('planner.waypoints.save', lang)}</button> <button type="button" onClick={() => { m.waypointPosition.value = null; }}>{t('planner.cancel', lang)}</button>
        </form> : null}
        {(d.userWaypoints ?? []).map(wp => <article key={wp.id}>
          <label class="export-check"><input type="checkbox" checked={d.ids.includes(wp.id)} onChange={e => m.toggleSpot(wp.id, e.currentTarget.checked)} /><span>{wp.name} · {categoryText(wp.category, lang)}</span></label>
          <p>{formatCoordinates(wp.latitude, wp.longitude, coordinates.value)}</p>
          {d.ids.includes(wp.id) ? <BoundaryNote hit={m.protectedHits.value.find(h => h.id === wp.id)} /> : null}
          <button onClick={() => m.removeWaypoint(wp.id)} aria-label={t('planner.waypoints.removeAria', lang, {name: wp.name})}>{t('planner.waypoints.remove', lang)}</button>
        </article>)}
      </section>
      <details class="export-card" id="export-spots" open>
        <summary><span>{t('planner.step1', lang)}</span><strong id="export-selection-count">{t('planner.selected', lang, {n: d.ids.length})}</strong></summary>
        <div class="export-card-body">
          {stops.length > 0 && <section aria-label={t('planner.stops.heading', lang)}>
            <h3>{t('planner.stops.heading', lang)}</h3>
            <ol aria-label={t('planner.stops.aria', lang)}>{stops.map(stop => {
              const index = d.ids.indexOf(stop.id), name = stop.name || stop.label;
              return <li key={stop.id} data-stop-id={stop.id}>{name}{index >= 0 && (['up', 'down'] as const).map(direction =>
                (direction === 'up' ? index > 0 : index < d.ids.length - 1) ? <button key={direction} type="button" disabled={m.restorePending.value}
                  ref={el => { const key = `${stop.id}:${direction}`; if (el) orderButtons.current.set(key, el); else orderButtons.current.delete(key); }}
                  aria-label={t(direction === 'up' ? 'planner.order.upAria' : 'planner.order.downAria', lang, {name})}
                  onClick={() => move(stop.id, direction)}>{t(direction === 'up' ? 'planner.order.up' : 'planner.order.down', lang)}</button> : null)}</li>;
            })}</ol>
            {!port && <p>{t('planner.stops.noPort', lang)}</p>}
            <ol aria-label={t('planner.order.legs', lang)}>{route.legs.map((leg, i) => <li key={i}>{`${leg.from} → ${leg.to} · ${nmText(leg.nm, lang)} nm${leg.basis === 'straight' ? t('planner.leg.straight', lang) : ''}${minutes(leg.runMin)}${legLine(leg.screen, lang)}`}</li>)}</ol>
            <p>{t('planner.leg.total', lang, {nm: nmText(route.totalNm, lang), minutes: minutes(route.totalRunMin)})}</p>
            <p class="export-note">{route.legs.some(leg => leg.basis === 'straight') ? t('planner.leg.straightCaveat', lang) : ''}{t('planner.leg.common', lang)}</p>
          </section>}
          {route.skipped.length > 0 && <p>{t('planner.leg.skipped', lang, {names: route.skipped.join(', ')})}</p>}
          <button class="primary export-best" id="export-best" disabled={!m.portsReady.value || m.loading.value} onClick={() => void m.selectBest()}>{t('planner.best', lang, {n: f.limit})}</button>
          {m.portsFailed.value && <p class="export-note" id="export-ports-note">{plannerText(PORTS_FAILED_NOTE, lang)}</p>}
          <p class="export-note">{t('planner.rankedNote', lang)}</p>
          <details class="export-trip-filters">
            <summary>{t('planner.filters', lang)}</summary>
            <div class="export-fields">
              <label>{t('planner.target', lang)}<select id="export-species" value={f.species} onChange={filter('species', v => v as TripSpecies)}>
                <option value="reef">{t('planner.target.reef', lang)}</option><option value="lingcod">{t('planner.target.lingcod', lang)}</option><option value="rockfish">{t('planner.target.rockfish', lang)}</option></select></label>
              <label>{t('planner.maxSpots', lang)}<select id="export-limit" value={String(f.limit)} onChange={filter('limit', Number)}>
                {[10, 20, 30, 50].map(n => <option key={n} value={String(n)}>{n}</option>)}</select></label>
              <label>{t('planner.maxDepth', lang)}<input id="export-depth" type="number" min="25" max="300" defaultValue={String(f.depth)} onChange={filter('depth', Number)} /></label>
              <label>{t('planner.searchArea', lang)}<select id="export-best-scope" value={f.scope} onChange={filter('scope', v => v as Filters['scope'])}>
                <option value="region">{t('planner.scope.region', lang)}</option><option value="map">{t('planner.scope.map', lang)}</option></select></label>
              <label>{t('planner.fromPort', lang)}<select id="export-port" value={f.port} onChange={filter('port', String)}>
                <option value="">{t('planner.noLimit', lang)}</option>{m.ports.value.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
              <label>{t('planner.maxDistance', lang)}<input id="export-distance" type="number" min="1" max="100" defaultValue={String(f.distance)} onChange={filter('distance', Number)} /></label>
            </div>
            <p class="export-note">{t('planner.distanceNote', lang)}</p>
          </details>
          <p><button id="export-map" disabled={blocked} onClick={m.showOnMap}>{t('planner.showMap', lang)}</button> <button id="export-conditions" disabled={blocked} onClick={m.checkConditions}>{t('planner.conditions', lang)}</button></p>
          <details>
            <summary>{t('planner.how', lang)}</summary>
            <p>{t('planner.how.fit', lang)}</p>
            <p>{t('planner.how.index', lang)}</p>
          </details>
          <label class="export-check"><input id="export-research" type="checkbox" checked={research} onChange={e => m.setResearch(e.currentTarget.checked)} />
            <span><strong>{t('planner.research.label', lang)}</strong><small>{t('planner.research.text', lang)}</small></span></label>
          <p class="export-note">{t('planner.research.note', lang)}</p>
          <p>{t('planner.presets.intro', lang)}</p>
          <div class="export-presets">
            {PRESETS.map(scope => <button key={scope} data-scope={scope} id={scope === 'filtered' ? 'export-filtered-research' : undefined} disabled={scope === 'filtered' && !research} onClick={() => m.preset(scope)}>{t(`planner.preset.${scope}` as StringId, lang)}</button>)}
          </div>
          <p id="export-scope-status" role="status">{plannerText(m.scopeStatus.value, lang)}</p>
          <label>{t('planner.find', lang)}<input id="export-search" type="search" placeholder={t('planner.find.placeholder', lang)} autoComplete="off" value={m.search.value} onInput={e => { m.search.value = e.currentTarget.value; }} /></label>
          {shared === null ? null : <p id="export-shared-confidence">{t('planner.sharedConfidence', lang, {n: shared})}</p>}
          <div id="export-spot-list" class="export-spot-list" role="group" aria-label={t('planner.spotList.aria', lang)}>
            {spots.length ? spots.map(spot => <SpotRow key={spot.id} t={spot} showConfidence={shared === null} checked={d.ids.includes(spot.id)} hit={m.protectedHits.value.find(h => h.id === spot.id)} onToggle={on => m.toggleSpot(spot.id, on)} />)
              : <p>{t('planner.spotList.empty', lang)}</p>}
          </div>
          {session.value.state === 'signed-in' ? <SavedSpots m={m} /> : null}
        </div>
      </details>
      <AlertSave m={m} legs={alertLegs} open={open} />
      <details class="export-card" id="export-layers">
        <summary><span>{t('planner.layers', lang)}</span><strong id="export-layer-count">{t('planner.layers.count', lang, {n: Object.values(d.layers).filter(Boolean).length + (m.contourTracks.value ? 1 : 0)})}</strong></summary>
        <div class="export-card-body export-checks">
          {m.launch.value || d.launchId ? <label class="export-check"><input type="checkbox" checked={!!d.launchId} onChange={e => m.setLaunch(e.currentTarget.checked)} /><span>{t('planner.layers.launch', lang, {name: m.launch.value?.name ?? '—'})}</span></label> : null}
          {LAYERS.map(([id, name, description]) => (
            <label key={id} class="export-check"><input type="checkbox" data-layer={id} checked={d.layers[id]} onChange={e => m.setLayer(id, e.currentTarget.checked)} />
              <span><strong>{t(name, lang)}</strong><small>{t(description, lang)}</small></span></label>
          ))}
          <label class="export-check"><input type="checkbox" data-export="contours" checked={m.contourTracks.value} onChange={e => m.setContourTracks(e.currentTarget.checked)} />
            <span><strong>{t('planner.layer.contours', lang)}</strong><small>{t('planner.layer.contours.text', lang)}</small></span></label>
          <label>{t('planner.coverage', lang)}<select id="export-avoid-scope" value={d.avoidScope} onChange={e => m.edit({avoidScope: e.currentTarget.value === 'region' ? 'region' : 'map'})}>
            <option value="map">{t('planner.coverage.map', lang)}</option><option value="region">{t('planner.coverage.region', lang)}</option></select></label>
          <p class="export-note">{t('planner.layers.note', lang)}</p>
        </div>
      </details>
      <section class="export-card export-transfer" aria-labelledby="export-transfer-title">
        <h2 id="export-transfer-title">{t('planner.transfer', lang)}</h2>
        <div id="export-counts" class="export-counts" aria-live="polite">
          {s.ok ? <><strong>{s.counts.waypoints} <span>{t('planner.counts.waypoints', lang)}</span></strong><strong>{s.counts.tracks} <span>{t('planner.counts.tracks', lang)}</span></strong></> : t('planner.counts.plan', lang, {n: d.ids.length})}
        </div>
        <p id="export-validation" role="status">{s.ok
          ? t('planner.validation', lang, {outlines: s.counts.outlines, alignments: s.counts.alignments, exclusions: s.counts.exclusions,
            contours: s.counts.contours === undefined ? '' : t('planner.validation.contours', lang, {n: s.counts.contours}),
            points: countText(s.counts.trackPoints, lang), largest: countText(s.counts.largestTrack, lang), capacity: s.counts.tracks > 15 ? t('planner.validation.capacity', lang) : ''})
          : plannerText(s.message, lang)}</p>
        {!s.ok && m.protectedHits.value.slice(0, 3).map(h => <p key={h.id}>{t('planner.notExported', lang, {label: h.label, names: h.matches.map(a => a.name).join(', ')})} <button onClick={() => m.removeWaypoint(h.id)}>{t('planner.remove', lang, {label: h.label})}</button></p>)}
        <p class="export-note">{t('planner.snapshot', lang)}</p>
        <p id="export-caveats" class="export-note">{t('brief.planning', lang)} {t('planner.caveat.c4', lang)}</p>
        <div class="export-actions">
          <button class="primary" id="export-download" disabled={!s.ok} onClick={() => void m.deliver('gpx')}>{t('planner.download', lang)}</button>
          <button id="export-share" disabled={!s.ok} onClick={() => void m.deliver('share')}>{m.preparing.value ? t('planner.preparing', lang) : t('planner.share', lang)}</button>
          <button id="export-notes" disabled={!m.notesReady.value} onClick={() => void m.deliver('notes')}>{t('planner.notes', lang)}</button>
        </div>
        <p id="export-action-status" role="status">{plannerText(m.actionStatus.value, lang)}</p>
        <section aria-labelledby="route-export-title">
          <h3 id="route-export-title">{t('planner.route.title', lang)}</h3>
          <p>{t('planner.route.note', lang)}</p>
          <p class="export-note">{t('planner.route.warning', lang)}</p>
          <p><a href="https://wildlife.ca.gov/Conservation/Marine/MPAs" target="_blank" rel="noopener">CDFW MPA</a> · <a href="https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas" target="_blank" rel="noopener">NOAA</a></p>
          <button id="export-route" disabled={!s.ok || m.routing.value} onClick={() => void m.deliverRoute()}>{t(m.routing.value ? 'planner.route.busy' : 'planner.route.download', lang)}</button>
          <p role="status">{m.routeStatus.value}</p>
        </section>
        {!s.ok && m.notesReady.value ? <p>{t('planner.withheld', lang)}</p> : null}
        <details class="export-help">
          <summary>{t('planner.help', lang)}</summary>
          <label>{t('planner.help.device', lang)}<select id="export-device" value={deviceChoice.value} onChange={e => { deviceChoice.value = e.currentTarget.value; }}>
            {Object.entries(DEVICE_HELP).map(([id, [name]]) => <option key={id} value={id}>{t(name, lang)}</option>)}</select></label>
          <p id="export-device-help">{t(device[1], lang)}</p>
          <a id="export-device-source" href={device[2]} target="_blank" rel="noopener">{t('planner.help.source', lang)}</a>
          <ol><li>{t('planner.help.step1', lang)}</li><li>{t('planner.help.step2', lang)}</li><li>{t('planner.help.step3', lang)}</li></ol>
          <p>{t('planner.help.caveat', lang)}</p>
          <p>{t('planner.help.notes', lang)}</p>
        </details>
      </section>
    </div>
  );
}

/** The chartplotter whose import help shows; this page session only, as in v1. */
const deviceChoice = signal('generic');
