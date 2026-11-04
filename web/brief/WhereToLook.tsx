// "Where to look" (FE-34, design § 10): the top four places from web/ranking.ts,
// one source at a time, its label shown and its basis in a popover. Each row is a
// button: an atlas mark selects `?spot=`, a terrain habitat `?habitat=` (each
// dropping the other), counted as a pick so the mark card opens and takes focus,
// in every presentation. A seafloor publication place (SCJ-2a) moves the Chart to it
// instead. The row matching the address's selection is pressed, so
// a pick on the map shows here too.
// #644: Boat and Kayak show the range to consider under the list (Set range
// until one is saved, then "Range 12 nm"; under it, so the phone's half sheet
// still shows the top pick), which opens Your limits at that
// field; the list keeps only places inside it. With a cruise speed, a Boat
// pick shows its one-way run time. SC1322-10: a Boat pick's distance, run time and range use the water
// route (web/ranking.ts `routedPicks`) where one is computed, else the straight line, labelled. SC2207-05: Kayak's distance
// and range use the same route from its chosen launch (no run time), with a short reason beside a straight line.
// CI6-01B: the list ranks only places its land/water check confirms as water
// (web/land-water.ts); the region's index loads with the brief, and the lines file
// only when a place falls in a cell the index leaves mixed.
import {signal} from '@preact/signals';
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {LimitsDialog, LimitsForm} from '../app/LimitsPanel.tsx';
import {markData, markScreen, picked, spotHref} from '../map/marks.ts';
import {coastSpecies, habitatHref} from '../map/stage.ts';
import {cruiseSpeed} from '../limits.ts';
import {launchOrigin, loadLaunchPoints} from '../launches.ts';
import {homePortOrigin, loadRegionPorts, plannerPort, regionPorts, savedPortId} from '../ports.ts';
import {depthLimitFt, PROFILE_TABLE} from '../profile.ts';
import {isReachProfile, nmText, reachFor, shoreSwimLimit, spearPlan} from '../reach.ts';
import {loadShoreLines, shoreLines} from '../shore-distance.ts';
import {landWater, loadLandWater, loadLandWaterLines, placeFor, type LandWaterState} from '../land-water.ts';
import {loadReefPublication, ranking, recheckReefPublication, reefPublication, regionLoad, routedPicks, ROUTE_BUDGET, TOP, type Pick, type Ranking, type RoutedPick, type RouteFn} from '../ranking.ts';
import {waterRoute, type Route, type RouteFailure} from '../route.ts';
import {fitCamera} from '../map/ranked.ts';
import {cameraParam} from '../map/stage.ts';
import {habitat, navigate, profile, region, selection, setParams, species} from '../state.ts';
import {loadProtectedScreen, protectedScreen} from '../trip.ts';
import {durationText, runMinutes} from './run.ts';
import {regionCoverage, regionPlans, targetState} from '../species.ts';
import {planFor, noPlanText} from '../search-plan.ts';
import {regionInfo} from '../app/region-info.ts';
import {NO_REASONS, reasonsFor, targetEvidence} from '../area-reasons.ts';

export type {Pick, Ranking};

/** SCJ-2b: bumped on each `skippercast:boundaries` (the planner's screen redrew or refreshed), so the list is computed again. */
const screenTick = signal(0);

/** The list for the address and loaded data now, read from the signals so the brief re-renders when they change. */
export function currentRanking(now = Date.now(), top?: number): Ranking {
  const p = profile.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget, id = region.value;
  void screenTick.value;
  // #644: Kayak measures from its chosen launch; Spear from shore keeps to the swim limit once the shoreline loads.
  // SCJ-2c: otherwise every profile measures from the planner's port (its choice this session, else the saved home,
  // else the region's first port); only when the region's ports fail or are none does the region's harbor remain.
  const maxYd = p === 'spear' ? shoreSwimLimit() : null, lines = shoreLines.value;
  const launch = p === 'kayak' ? launchOrigin(id) : null, ports = regionPorts.value, planned = plannerPort.value;
  const home = launch || !id ? null : homePortOrigin(id, ports, planned?.region === id ? planned.id : null, savedPortId());
  const originPending = !launch && !!id && (ports?.region !== id || ports.state === 'loading');
  return ranking({region: id, profile: p, target, coast: coastSpecies(species.value, p), data: markData.value, screen: markScreen.value, terrain: {state: 'idle'}, now, reachNm: reachFor(p),
    origin: launch ?? home, originPending,
    shore: maxYd === null ? null : {maxYd, lines: lines && lines.region === id ? lines.lines : null},
    place: placeFor(landWater.value, id), missing: regionLoad.value?.id === id && regionLoad.value.state === 'missing',
    publication: reefPublication.value, plannerScreen: protectedScreen.value, ...(top ? {top} : {})});
}

// SC1322-10: routes by region, origin and place; a new product, lines file or region starts afresh, so a re-render routes nothing again.
let routes: {id: string | null; model: unknown; lines: unknown; route: RouteFn; memo: Map<string, Route>} | null = null;
/**
 * The Boat list by water: only this region's land/water product is used, and each route is computed once. At most `fresh`
 * routes not already memoised are computed; a pick past that keeps its labelled straight line for now, and `left` counts them.
 */
export function boatPicks(r: Ranking, lw: LandWaterState = landWater.value, id: string | null = region.value, route: RouteFn = waterRoute,
  fresh = Infinity, left: {n: number} = {n: 0}): RoutedPick[] {
  const model = lw.state === 'ready' && lw.region === id ? lw.model : null, lines = model ? lw.lines : null;
  if (!(routes && routes.id === id && routes.model === model && routes.lines === lines && routes.route === route)) routes = {id, model, lines, route, memo: new Map()};
  const memo = routes.memo, once: RouteFn = (m, l, from, to) => {
    const key = `${id}|${from.latitude},${from.longitude}>${to.latitude},${to.longitude}`, hit = memo.get(key);
    if (hit) return hit;
    if (fresh <= 0) { left.n++; return null; }
    const got = route(m, l, from, to);
    if (got) { fresh--; memo.set(key, got); }
    return got;
  };
  return routedPicks(r.picks, r.origin, model, lines, r.reach ?? null, TOP, once);
}

/** SC2207-05: why a Kayak pick still shows a straight line: the route's own failure, or that it is not computed yet. */
const ROUTE_WHY: Readonly<Record<RouteFailure, string>> = {
  'no-product': 'no land/water data',
  'lines-needed': 'shoreline still loading',
  'start-not-water': 'launch/origin not on confirmed water',
  'end-not-water': 'place not on confirmed water',
  'no-route': 'no water path found',
  'too-far': 'route search limit reached',
};
export function routeWhyText(pick: Pick & {basis?: 'water' | 'straight'; why?: RouteFailure}): string | null {
  if (pick.basis !== 'straight' || pick.nm === null) return null;
  return pick.why ? ROUTE_WHY[pick.why] ?? 'water route not computed' : 'water route not computed';
}

/** Bumped once the routes the painted Boat list still lacks are all computed, so it renders again by water. */
const routeTick = signal(0);
/**
 * SC1322-10: the brief paints the Boat list from memoised routes only (the rest on their straight line), then computes the
 * missing routes one per task after the paint, so a slow route (an all-mixed index, many lines to scan) never holds the
 * list back. Returns the cancel for the effect cleanup.
 */
export function routeAfterPaint(r: Ranking, lw: LandWaterState, id: string | null, route: RouteFn = waterRoute, done: () => void = () => { routeTick.value++; }): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const step = () => {
    const left = {n: 0};
    boatPicks(r, lw, id, route, 1, left);
    timer = left.n ? setTimeout(step, 0) : undefined;
    if (!left.n) done();
  };
  timer = setTimeout(step, 0);
  return () => clearTimeout(timer);
}

/** Select a pick's mark or habitat (a history entry), as a click on the map would; a publication place moves the Chart to it. */
/** BF-closures-everywhere: the line a pick's protected-area verdict adds, as plain text (rendered as a text child, so a closure's name is never markup); null when it is clear. */
export function screenLine(v: Pick['screen']): string | null {
  if (!v.screened) return 'Protected areas not checked';
  if (v.inside) return `Inside ${v.name ?? 'a protected area'}`;
  return v.distanceM !== null && v.distanceM <= 70 ? `${Math.round(v.distanceM)} m from ${v.name ?? 'a protected area'}` : null;
}
export function choosePick(pick: Pick, href: string = location.href): void {
  if (pick.kind === 'reef') {
    const at = pick.at && fitCamera([pick.at]);
    if (at) setParams({view: cameraParam(at)});
    return;
  }
  picked.value++;
  navigate(pick.kind === 'spot' ? spotHref(href, pick.id) : habitatHref(href, pick.id));
}

const selected = (pick: Pick): boolean => pick.kind === 'spot' ? selection.value === pick.id : pick.kind === 'habitat' && habitat.value === pick.id;

/** A Boat pick's one-way run at the saved cruise speed: "run 30 min" by water; "run ≥ 25 min" on the straight line, a lower bound. Empty without a speed or a distance. */
export function pickRun(nm: number | null, speedKn: number | null, basis: 'water' | 'straight' = 'straight'): string {
  const min = nm === null || speedKn === null ? null : runMinutes(nm, speedKn);
  return min === null ? '' : ` · run ${basis === 'water' ? '' : '≥ '}${durationText(min)}`;
}

/**
 * Boat and Kayak: the range to consider, or the ask for one, opening Your limits at the range field. Hidden while the
 * list has no harbor to measure from (before the marks load, or a region without one), where no range is applied.
 */
function RangeControl({measured}: {measured: string | undefined}) {
  const [open, setOpen] = useState(false);
  const p = profile.value;
  if (p === 'spear') return <DiveControl />;
  if (!isReachProfile(p) || !measured) return null;
  const nm = reachFor(p), label = PROFILE_TABLE[p].label, from = measured || 'the harbor';
  return (
    <>
      <Button variant="ghost" size="sm" class="app-where-range" aria-haspopup="dialog" data-reach={nm ?? undefined} onClick={() => setOpen(true)}
        title={nm === null ? 'Set how far out to look' : `Range to consider: ${nmText(nm)} ${p === 'boat' || p === 'kayak' ? 'by water where routed, else straight line,' : 'straight line'} from ${from}`}>
        {nm === null ? 'Set range' : `Range ${nmText(nm)}`}
      </Button>
      <LimitsDialog open={open} onClose={() => setOpen(false)} title={`Your limits · ${label}`}>
        <LimitsForm profile={p} focusReach onDone={() => setOpen(false)} />
      </LimitsDialog>
    </>
  );
}

/** The words for Spear's dive limits: the depth, then where from and the swim when set. */
export function diveText(depthFt: number, plan: {from: 'shore' | 'boat' | null; shoreYd: number | null}): string {
  const from = plan.from === 'boat' ? ' · from a boat' : plan.from === 'shore' ? plan.shoreYd === null ? ' · from shore' : ` · ${plan.shoreYd} yd from shore` : '';
  return `To ${depthFt} ft${from}`;
}

/** Spear: its dive limits, opening Your limits at the depth field. */
function DiveControl() {
  const [open, setOpen] = useState(false);
  const depth = depthLimitFt('spear') ?? 0;
  return (
    <>
      <Button variant="ghost" size="sm" class="app-where-range" aria-haspopup="dialog" data-dive={depth} onClick={() => setOpen(true)} title="Your dive limits">
        {diveText(depth, spearPlan.value)}
      </Button>
      <LimitsDialog open={open} onClose={() => setOpen(false)} title="Your limits · Spear">
        <LimitsForm profile="spear" focusDepth onDone={() => setOpen(false)} />
      </LimitsDialog>
    </>
  );
}

/**
 * MYB-3: with no picks, a target the picker labels "search plan only" shows the region's search plan for it in place
 * of the empty list; with none to show, the empty text says so. Every other target keeps the empty text as it was.
 */
function EmptyOrPlan({empty}: {empty: string}) {
  const p = profile.value, id = region.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget, loaded = regionPlans.value;
  const plans = loaded && loaded.region === id ? loaded.plans : null;
  if (!plans || targetState(target, p, plans, regionCoverage(id)) !== 'plan') return <p class="app-empty">{empty}</p>;
  const plan = planFor(target, loaded, id), info = regionInfo.value;
  if (!plan) return <p class="app-empty">{empty} {noPlanText(info?.id === id ? info.name : null)}</p>;
  return (
    <div data-plan={plan.id}>
      <h3 class="ui-eyebrow">Search plan</h3>
      <ul class="app-picks">
        {plan.items.map((item, i) => <li key={i} data-field={item.field}>{item.label}: {item.text}</li>)}
      </ul>
      {plan.basis ? <p data-field="tactics_basis">{plan.basis}</p> : null}
    </div>
  );
}

/**
 * BF-why-this-area: the selected place's dated reasons, up to three, each with its source, from the records the ranker read for it
 * (its atlas mark or published place); a place without any shows the explicit empty line. Text is rendered as text, never markup.
 */
function Why({pick}: {pick: Pick}) {
  const data = markData.value, pub = reefPublication.value;
  const found = pick.kind === 'spot' ? data?.atlas?.targets.find(t => t.id === pick.id) : pick.kind === 'reef' && pub.state === 'ready' ? pub.loaded.targets.find(t => t.id === pick.id) : undefined;
  const reasons = found ? reasonsFor(pick.id, targetEvidence(found, pick.kind === 'spot' ? data?.atlas : null, data?.region.source_names), Date.now()) : [];
  if (!reasons.length) return <p class="app-empty app-pick-why" data-why="none">{NO_REASONS}</p>;
  return (
    <ul class="app-pick-why" data-why="reasons" aria-label="Why this area">
      {reasons.map((x, i) => (
        <li key={i}><span class="ui-mono">{x.date}</span> {x.text} · {x.sourceURL ? <a href={x.sourceURL} target="_blank" rel="noopener noreferrer">{x.source}</a> : x.source}</li>
      ))}
    </ul>
  );
}

export function WhereToLook({ranking: given}: {ranking?: Ranking} = {}) {
  const boat = profile.value === 'boat', kayak = profile.value === 'kayak', water = boat || kayak, r = given ?? currentRanking(Date.now(), water ? ROUTE_BUDGET : undefined), id = region.value, speed = cruiseSpeed.value;
  // SC1322-10: Boat (and, SC2207-05, Kayak from its launch) list by water where routed; other profiles keep the ranking's picks as they are. The render uses
  // memoised routes only and routes the rest after the paint (routeAfterPaint), so the list never waits on a route.
  const lw = landWater.value, unrouted = {n: 0};
  void routeTick.value;
  const picks: readonly (Pick & {basis?: 'water' | 'straight'; why?: RouteFailure})[] = water ? boatPicks(r, lw, id, waterRoute, 0, unrouted) : r.picks;
  useEffect(() => unrouted.n ? routeAfterPaint(r, lw, id) : undefined);
  // The lines file is asked for once the region's index is ready and a candidate still waits on it (a mixed cell),
  // so a list that was pending on the index itself asks as soon as the index lands; clean cells never load it.
  // A Boat or Kayak route that needs the lines (lines-needed) does not ask for them: that pick keeps its labelled straight line.
  const wantLines = !!id && !!r.pending && lw.region === id && lw.state === 'ready' && lw.lines === null;
  // SCJ-2a: the publication loads once per region, and its live manifest is checked again now (a cached one) and each
  // minute, as the planner checks its plan, so a held, unavailable or superseded publication stops ranking.
  useEffect(() => {
    if (!id) return;
    const was = reefPublication.peek();
    void (was.state !== 'idle' && was.region === id ? recheckReefPublication(id) : loadReefPublication(id));
    const timer = setInterval(() => { void recheckReefPublication(id); }, 60000);
    return () => clearInterval(timer);
  }, [id]);
  // SCJ-2b: the planner's protected-area screen, which admits the publication's places, loads with the brief.
  useEffect(() => { if (id) void loadProtectedScreen(id); }, [id]);
  useEffect(() => {
    const bump = () => { screenTick.value++; };
    document.addEventListener('skippercast:boundaries', bump);
    return () => document.removeEventListener('skippercast:boundaries', bump);
  }, []);
  // #644: Kayak's launch list and, for Spear from shore, the shoreline, each loaded once per region when needed.
  const p = profile.value, swimming = p === 'spear' && shoreSwimLimit() !== null;
  useEffect(() => { if (id && p === 'kayak') void loadLaunchPoints(id); }, [id, p]);
  useEffect(() => { if (id && swimming) void loadShoreLines(id); }, [id, swimming]);
  useEffect(() => { if (id) void loadLandWater(id); }, [id]);
  useEffect(() => { if (id) void loadRegionPorts(id); }, [id]);
  useEffect(() => { if (id && wantLines) void loadLandWaterLines(id); }, [id, wantLines, lw.model]);
  return (
    <section class="app-where" data-source={r.source ?? undefined}>
      <div class="app-where-head">
        <h2 class="ui-eyebrow">Where to look</h2>
        {r.source ? <span class="app-where-source ui-mono">{r.label}</span> : null}
        {r.source ? <Popover iconOnly summary={`About the ${r.label.toLowerCase()} ranking`} align="end">{r.basis}</Popover> : null}
      </div>
      {picks.length ? (
        <ol class="app-picks">
          {picks.map((pick, i) => (
            <li key={pick.id} data-mark={pick.id}>
              <button type="button" class="app-pick" aria-pressed={selected(pick)} onClick={() => choosePick(pick)}>
                <span class="app-pick-rank ui-mono">{i + 1}</span>
                <span>{pick.name} <span class="ui-mono">{pick.distance} · {pick.depth}{boat ? pickRun(pick.nm, speed, pick.basis) : ''}</span>{kayak && routeWhyText(pick) ? <span class="app-pick-route-why" data-route-why={pick.why ?? 'not-computed'}> · {routeWhyText(pick)}</span> : null}</span>
                <span class="app-fit ui-eyebrow">{pick.fit}</span>
                <span class="app-pick-reason">{pick.reason}</span>
                {screenLine(pick.screen) && <span class="app-pick-reason">{screenLine(pick.screen)}</span>}
              </button>
              {selected(pick) ? <Why pick={pick} /> : null}
            </li>
          ))}
        </ol>
      ) : <EmptyOrPlan empty={r.empty} />}
      <RangeControl measured={r.harbor} />
    </section>
  );
}
