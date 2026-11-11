// The Boat brief's run line (roadmap P2): fishing time at the chosen place
// and when to turn back, from web/brief/run.ts. The place is the "Where to
// look" pick the user selected, else the top pick, named either way. SC2207-02:
// the picks are the list as painted (WhereToLook's listedBoatPicks, the same
// memoised water routes and range), so the run never names or times a place the
// list dropped, and it never searches a route itself. Picks have already passed
// the protected-area screen and the depth limit, so a withheld mark never gets
// a fishing time. Without a cruise speed the line
// asks for one and opens the Boat limits form at that field; without a window
// it names the input that is missing. The method sits in the basis popover.
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {LimitsDialog, LimitsForm} from '../app/LimitsPanel.tsx';
import {regionInfo, zone} from '../app/region-info.ts';
import {cruiseSpeed, wantedHours} from '../limits.ts';
import {ROUTE_BUDGET, type Ranking, type RoutedPick} from '../ranking.ts';
import {habitat, profile, region, selection, species} from '../state.ts';
import {landWater, loadLandWaterLines} from '../land-water.ts';
import type {RouteFailure} from '../route.ts';
import {barNote, durationText, planRun, ROUND_MIN, runRouteNote, runRouteScreen, type RunPlace, type RunState} from './run.ts';
import {loadProtectedScreen, protectedScreen, type ProtectedScreen} from '../trip.ts';
import {currentRanking, listedBoatPicks} from './WhereToLook.tsx';
import type {Brief} from './types.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {loadRegs, regsData, regulationState, ruleSummary, openingAt} from '../regs.ts';
import {fishingHours, type FishingHours} from './fishing-hours.ts';
import {entranceWindow} from '../../packages/coast/src/entrance-window.ts';
import {EntranceCurrent} from './EntranceCurrent.tsx';
import {language, num, t, type Language, type StringId} from '../i18n.ts';
import {clock} from './clock.ts';

/**
 * The catalogue sentence, in `lang`, for an upstream English sentence: `text` is matched whole against the English of each id in
 * `ids` (a `{name}` takes whatever the producer wrote there, kept verbatim, `fix` aside); null when none matches, so an unknown
 * sentence is never guessed at.
 */
function known(text: string, ids: readonly StringId[], lang: Language, fix: (value: string) => string = v => v): string | null {
  for (const id of ids) {
    const names: string[] = [];
    const pattern = t(id).split(/(\{\w+\})/).map(part => {
      const named = /^\{(\w+)\}$/.exec(part);
      if (!named) return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      names.push(named[1]!);
      return '([\\s\\S]+?)';
    }).join('');
    const hit = new RegExp(`^${pattern}$`).exec(text);
    if (hit) return t(id, lang, Object.fromEntries(names.map((name, i) => [name, fix(hit[i + 1]!)])));
  }
  return null;
}

/** The sentences the run's producers (run.ts, daily.ts, entrance-window.ts) write in English, each a catalogue entry. */
const REASON_IDS: readonly StringId[] = ['run.window.alert', 'run.window.noForecast', 'run.window.stale', 'run.window.alertCheck', 'run.window.incomplete', 'run.window.custom', 'run.window.none',
  'run.entrance.noWindow', 'run.entrance.noHours', 'run.entrance.noBearing', 'run.entrance.missing', 'run.entrance.caution', 'run.entrance.clear', 'run.bar',
  'run.route.unchecked', 'run.route.inside', 'run.route.near'];

/** An upstream sentence in `lang`: its catalogue Spanish when it is one of the finite known sentences, else as it came. */
const reasonText = (text: string, lang: Language): string => lang === 'en' ? text : known(text, REASON_IDS, lang, v => v === t('where.screen.area') ? t('where.screen.area', lang) : v) ?? text;
/** The same for display: a sentence with no Spanish is marked as English on a Spanish page, never hidden or guessed. */
const said = (text: string, lang: Language) => lang === 'es' && reasonText(text, lang) === text ? <span lang="en">{text}</span> : reasonText(text, lang);

export function EntranceLine({brief, tz}: {brief: Brief; tz: string}) {
  if (!brief.bar) return null;
  const lang = language.value;
  const result = entranceWindow(brief.bar.hours, {entrance: brief.bar.entrance,
    sunrise: brief.sunrise ? Date.parse(brief.sunrise) : null, sunset: brief.sunset ? Date.parse(brief.sunset) : null,
    formatHour: at => clock(at, tz, lang)});
  const times = result.judged && result.departBy !== null && result.returnBy !== null
    ? t('run.entrance.times', lang, {depart: clock(new Date(result.departBy).toISOString(), tz, lang), back: clock(new Date(result.returnBy).toISOString(), tz, lang)}) : '';
  return <p class="app-run-entrance">{brief.bar.entrance.name}: {times}{said(result.reason, lang)}</p>;
}

const WHY_IDS: readonly RouteFailure[] = ['no-product', 'lines-needed', 'start-not-water', 'end-not-water', 'no-route', 'too-far'];

/**
 * The run's place, from the list as painted: the selected listed pick, else the first listed one; null when none is
 * listed or its distance is not a usable number. `unranked` says a selection was made that is not among the listed
 * picks (never listed, or dropped by the range), so the line says whose times it shows. The distance and its basis are
 * the list's own, copied, never computed again.
 */
export function runPlace(picks: readonly RoutedPick[], spot: string | null, hab: string | null): (RunPlace & {chosen: boolean; unranked: boolean}) | null {
  const {chosen, pick} = pickForRun(picks, spot, hab);
  if (!pick || typeof pick.nm !== 'number' || !Number.isFinite(pick.nm) || pick.nm < 0) return null;
  return {name: pick.name, nm: pick.nm, basis: pick.basis, ...(pick.why ? {why: pick.why} : {}), chosen: !!chosen, unranked: !chosen && !!(spot || hab)};
}

/** The listed pick the run is timed for: the selected spot or habitat, else the first listed one. The route screen reads the same pick, so it never names another place's route. */
function pickForRun(picks: readonly RoutedPick[], spot: string | null, hab: string | null): {chosen: RoutedPick | undefined; pick: RoutedPick | undefined} {
  const chosen = picks.find(p => p.kind === 'spot' ? p.id === spot : p.kind === 'habitat' && p.id === hab);
  return {chosen, pick: chosen ?? picks[0]};
}

/** The protected-area screen to read now: only a loaded one for exactly this region that says it is current; else null (the line says not checked). */
export function runScreenFor(loaded: ProtectedScreen, id: string | null): unknown {
  if (!id || loaded.state !== 'loaded' || loaded.region !== id) return null;
  try { return loaded.screen.ready() ? loaded.screen : null; } catch { return null; }
}

/** Calls `onChange` on each `skippercast:boundaries` (the planner's screen redrew or refreshed) until the returned stop; nothing without a document. */
export function watchBoundaries(onChange: () => void, doc: Pick<Document, 'addEventListener' | 'removeEventListener'> | undefined = typeof document === 'undefined' ? undefined : document): () => void {
  if (!doc) return () => {};
  doc.addEventListener('skippercast:boundaries', onChange);
  return () => doc.removeEventListener('skippercast:boundaries', onChange);
}

// A straight line with no reason is a route the list has not computed yet, not a failed one.
const distanceText = (p: RunPlace, lang: Language): string => {
  const nm = lang === 'es' ? p.nm.toFixed(1).replace('.', ',') : p.nm.toFixed(1);
  if (p.basis === 'water') return t('where.distance.water', lang, {nm});
  const why = p.why && WHY_IDS.includes(p.why) ? t('run.why.failed', lang, {why: t(`run.why.${p.why}`, lang)}) : t('run.why.pending', lang);
  return t('run.distance.straightWhy', lang, {nm, why});
};

const kt = (n: number, lang: Language = 'en') => lang === 'es' ? num(n, lang, 1) : Number(n.toFixed(1)).toString();

/** The basis: what the sum uses and what it leaves to the skipper. */
export const runBasis = (harbor: string, lang: Language = 'en') => t('run.basis.text', lang, {harbor, round: ROUND_MIN});

/** The line's words for a run state; `tz` is the region's time zone. */
export function runText(state: RunState, tz: string, unranked = false, lang: Language = 'en'): {lead: string; times?: string; run?: string; note?: string} {
  const top = unranked && (state.kind === 'ok' || state.kind === 'no-time') ? t('run.lead.unranked', lang) : '';
  const text = words(state, tz, lang);
  const note = state.kind === 'ok' || state.kind === 'no-time' ? barNote(state.window) ?? undefined : undefined;
  return {...text, lead: top + text.lead, ...(note ? {note: reasonText(note, lang)} : {})};
}

function words(state: RunState, tz: string, lang: Language): {lead: string; times?: string; run?: string} {
  const at = (iso: string) => clock(iso, tz, lang);
  switch (state.kind) {
    case 'no-speed': return {lead: t('run.lead.noSpeed', lang)};
    case 'no-place': return {lead: t('run.lead.noPlace', lang)};
    case 'no-window': return {lead: reasonText(state.reason, lang)};
    case 'over': return {lead: t('run.lead.over', lang, {start: at(state.window.start), end: at(state.window.end)})};
    case 'no-time': return {lead: t('run.lead.noTime', lang, {name: state.place.name, start: at(state.window.start), end: at(state.window.end), speed: kt(state.speedKn, lang)}),
      run: t('run.detail.each', lang, {distance: distanceText(state.place, lang), duration: durationText(state.runMin)})};
    case 'ok': return {lead: t('run.lead.ok', lang, {duration: durationText(state.fishMin), name: state.place.name}),
      times: t('run.times', lang, {depart: at(state.depart), arrive: at(state.arrive), turn: at(state.turnBack), back: at(state.back), start: at(state.window.start), end: at(state.window.end)}),
      run: t('run.detail.eachSpeed', lang, {distance: distanceText(state.place, lang), duration: durationText(state.runMin), speed: kt(state.speedKn, lang)})};
  }
}

export function fishingWords(result: FishingHours, tz: string, sunset: string | null, opensAt: number | null, lang: Language = 'en'): string {
  const duration = durationText, at = (iso: string) => clock(iso, tz, lang);
  if (result.kind === 'closed') return t('run.hours.closed', lang, {label: result.label, reason: result.reason});
  if (result.kind === 'no-wanted') return '';
  const edge = 'endedBy' in result ? result.endedBy === 'opening' && opensAt !== null ? t('run.hours.edge.opening', lang, {time: at(new Date(opensAt).toISOString())})
    : result.endedBy === 'daylight' && sunset ? t('run.hours.edge.daylight', lang, {time: at(sunset)}) : t('run.hours.edge.conditions', lang) : '';
  const unconfirmed = t('run.hours.unconfirmed', lang);
  if (result.kind === 'none') return (result.rulesUnconfirmed ? unconfirmed : '') + t('run.hours.none', lang, {edge});
  const wanted = t('run.hours.wanted', lang, {duration: duration(result.wantedMin)});
  if (result.kind === 'beyond-daylight') return wanted + t('run.hours.beyond', lang, {duration: duration(result.daylightMin)});
  const available = wanted + t('run.hours.available', lang, {duration: duration(result.availableMin)});
  if (result.kind === 'enough') return t('run.hours.enough', lang, {available, spare: duration(result.spareMin)});
  return result.rulesUnconfirmed ? unconfirmed + t('run.hours.unknownShort', lang, {available}) : t('run.hours.short', lang, {available, short: duration(result.shortMin), edge});
}

/** Fishing time and the return for the Boat brief; nothing for the other profiles or before the brief loads. */
export function RunLine({brief, ranking, now}: {brief: Brief | null; ranking?: Ranking; now: Date}) {
  const [open, setOpen] = useState(false);
  const rules = regionInfo.value?.rules;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  const boat = !!brief && profile.value === 'boat' && brief.profile === 'boat', id = region.value;
  // The list's own picks and memoised routes: this line never starts a route search.
  const r = boat ? ranking ?? currentRanking(now.getTime(), ROUTE_BUDGET) : null, lw = landWater.value;
  const listed = r ? listedBoatPicks(r, lw, id) : [], place = runPlace(listed, selection.value, habitat.value);
  // Request missing shoreline detail only when the run can display a distance, not at every Boat startup.
  // WhereToLook re-routes the shared list when these lines land; Run stays a memo-only route consumer.
  const speed = cruiseSpeed.value, shows = boat && !!brief?.windows.length && speed !== null && speed > 0;
  useEffect(() => { if (id && shows && place?.why === 'lines-needed') void loadLandWaterLines(id); }, [id, shows, place?.why]);
  // SC0452-07: the run's route is screened against the shared protected-area screen Where to look loads (one loader, no new request);
  // a boundary refresh renders the line again, so a screen that goes stale or unavailable takes its old note away.
  const [, setRevision] = useState(0);
  useEffect(() => { if (id && shows && place) void loadProtectedScreen(id); }, [id, shows, !!place]);
  useEffect(() => watchBoundaries(() => setRevision(n => n + 1)), []);
  if (!brief || !r) return null;
  const lang = language.value;
  const state = planRun(brief, place, cruiseSpeed.value, now), tz = zone();
  const text = runText(state, tz, place?.unranked, lang), harbor = r.harbor ?? t('where.harbor', lang);
  const target = species.value ?? PROFILE_TABLE.boat.defaultTarget;
  const loaded = regsData.value, data = loaded?.region === rules?.id ? loaded?.data : null;
  const active = state.kind === 'ok' || state.kind === 'no-time';
  // The route of the place whose distance is timed, never the first raw pick; nothing for a state with no run to show.
  const routeNote = active && text.run ? runRouteNote(runRouteScreen(r.origin, pickForRun(listed, selection.value, habitat.value).pick ?? null, runScreenFor(protectedScreen.value, id), id)) : null;
  const date = active ? new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(state.window.start)) : '';
  const opensAt = rules ? openingAt(data, target, rules, date) : null;
  // Read at the opening (not before it) so a timed opener clips rather than closing the whole day.
  const rule = rules ? regulationState(data, target, rules, now.getTime(), date, opensAt) : {status: 'unknown', label: t('rules.status.unknown', lang), reason: t('run.rules.unavailable', lang), today: date, issues: []};
  const summary = rules ? ruleSummary(data, target, rule, rules, lang) : null;
  const result = active ? fishingHours(state, {wantedMin: wantedHours.value === null ? null : wantedHours.value * 60, sunrise: brief.sunrise, sunset: brief.sunset, rule: {...rule, opensAt, label: target === 'reef' ? 'Lingcod & rockfish' : rule.profile?.name ?? target}}) : null;
  const verdict = result?.kind === 'closed' && lang === 'es'
    ? <>{fishingWords({...result, reason: ''}, tz, brief.sunset, opensAt, lang)}<span lang="en">{result.reason}</span></>
    : result ? fishingWords(result, tz, brief.sunset, opensAt, lang) : '';
  if (state.kind === 'ok' && result && result.kind !== 'no-wanted') text.lead = t('run.lead.wanted', lang, {name: state.place.name});
  // Nothing to time: range removed every place the ranking found; or places are listed with no distance (no harbor position).
  if (state.kind === 'no-place' && r.picks.length) text.lead = listed.length ? t('run.lead.noHarbor', lang)
    : r.reach != null ? t('run.lead.noRange', lang) : text.lead;
  // Upstream English with no catalogue sentence is marked English on a Spanish page (never hidden or guessed at).
  const lead = state.kind === 'no-window' && text.lead === state.reason ? said(state.reason, lang) : text.lead;
  const note = state.kind === 'ok' || state.kind === 'no-time' ? barNote(state.window) : null;
  return (
    <section class="app-run" aria-label={t('run.aria', lang)} data-state={state.kind}>
      <EntranceLine brief={brief} tz={tz} />
      <EntranceCurrent brief={brief} tz={tz} now={now} />
      <p class="app-run-lead"><span class="ui-eyebrow">{t('run.fishing', lang)}</span> {lead}</p>
      {text.times ? <p class="app-run-times ui-mono">{text.times}{brief.sunrise && brief.sunset ? t('run.daylight', lang, {start: clock(brief.sunrise, tz, lang), end: clock(brief.sunset, tz, lang)}) : ''}</p> : null}
      {verdict ? <p class="app-run-hours" data-kind={result!.kind}>{note ? <>{said(note, lang)}{t('run.bar.check', lang)}</> : ''}{verdict}{' '}
        {['scheduled', 'restricted'].includes(rule.status) ? <>{summary?.label ?? rule.label}: {lang === 'es' ? <span lang="en">{rule.reason}</span> : rule.reason} </> : ''}
        {summary ? <a href={summary.link}>{summary.linkLabel}</a> : null}</p> : null}
      {note ? <p class="app-run-note">{said(note, lang)}.</p> : null}
      {text.run ? (
        <p class="app-run-detail ui-mono">
          {text.run}{place && !place.chosen ? t('run.topPick', lang) : ''}{' '}
          <Popover summary={t('run.basis', lang)} align="start">{runBasis(harbor, lang)}</Popover>
        </p>
      ) : null}
      {routeNote ? <p class="app-run-protected">{said(routeNote, lang)}</p> : null}
      {state.kind === 'no-speed' || result?.kind === 'no-wanted' ? <>
        <Button variant="ghost" size="sm" icon="settings" aria-haspopup="dialog" onClick={() => setOpen(true)}>{t(state.kind === 'no-speed' ? 'run.set.speed' : 'run.set.hours', lang)}</Button>
        <LimitsDialog open={open} onClose={() => setOpen(false)} title={t('where.limits', lang, {profile: t('where.profile.boat', lang)})}>
          <LimitsForm profile="boat" focusCruise={state.kind === 'no-speed'} focusWanted={result?.kind === 'no-wanted'} onDone={() => setOpen(false)} />
        </LimitsDialog>
      </> : null}
    </section>
  );
}
