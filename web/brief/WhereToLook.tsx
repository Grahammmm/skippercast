// "Where to look" (FE-34, design § 10): the top four places from web/ranking.ts,
// one source at a time, its label shown and its basis in a popover. Each row is a
// button: an atlas mark selects `?spot=`, a terrain habitat `?habitat=` (each
// dropping the other), counted as a pick so the mark card opens and takes focus,
// in every presentation. The row matching the address's selection is pressed, so
// a pick on the map shows here too.
// #644: Boat and Kayak show the range to consider under the list (Set range
// until one is saved, then "Range 12 nm"; under it, so the phone's half sheet
// still shows the top pick), which opens Your limits at that
// field; the list keeps only places inside it. With a cruise speed, a Boat
// pick shows its one-way straight-line run time, a lower bound.
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {LimitsDialog, LimitsForm} from '../app/LimitsPanel.tsx';
import {hasCoastTerrain} from '../coast-context.ts';
import {markData, markScreen, picked, spotHref} from '../map/marks.ts';
import {coastSpecies, habitatHref} from '../map/stage.ts';
import {cruiseSpeed} from '../limits.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {isReachProfile, nmText, reachFor} from '../reach.ts';
import {loadTerrainHabitat, ranking, terrainHabitat, type Pick, type Ranking} from '../ranking.ts';
import {habitat, navigate, profile, region, selection, species} from '../state.ts';
import {durationText, runMinutes} from './run.ts';

export type {Pick, Ranking};

/** The list for the address and loaded data now, read from the signals so the brief re-renders when they change. */
export function currentRanking(now = Date.now()): Ranking {
  const p = profile.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget;
  return ranking({region: region.value, profile: p, target, coast: coastSpecies(species.value, p), data: markData.value, screen: markScreen.value, terrain: terrainHabitat.value, now, reachNm: reachFor(p)});
}

/** Select a pick's mark or habitat (a history entry), as a click on the map would. */
export function choosePick(pick: Pick, href: string = location.href): void {
  picked.value++;
  navigate(pick.kind === 'spot' ? spotHref(href, pick.id) : habitatHref(href, pick.id));
}

const selected = (pick: Pick): boolean => pick.kind === 'spot' ? selection.value === pick.id : habitat.value === pick.id;

/** A Boat pick's one-way run at the saved cruise speed ("run ≥ 25 min"): straight line, so the real run is longer. Empty without a speed or a distance. */
export function pickRun(nm: number | null, speedKn: number | null): string {
  const min = nm === null || speedKn === null ? null : runMinutes(nm, speedKn);
  return min === null ? '' : ` · run ≥ ${durationText(min)}`;
}

/** Boat and Kayak: the range to consider, or the ask for one, opening Your limits at the range field. */
function RangeControl() {
  const [open, setOpen] = useState(false);
  const p = profile.value;
  if (!isReachProfile(p)) return null;
  const nm = reachFor(p), label = PROFILE_TABLE[p].label;
  return (
    <>
      <Button variant="ghost" size="sm" class="app-where-range" aria-haspopup="dialog" data-reach={nm ?? undefined} onClick={() => setOpen(true)}
        title={nm === null ? 'Set how far out to look' : `Range to consider: ${nmText(nm)} straight line from the harbor`}>
        {nm === null ? 'Set range' : `Range ${nmText(nm)}`}
      </Button>
      <LimitsDialog open={open} onClose={() => setOpen(false)} title={`Your limits · ${label}`}>
        <LimitsForm profile={p} focusReach onDone={() => setOpen(false)} />
      </LimitsDialog>
    </>
  );
}

export function WhereToLook({ranking: given}: {ranking?: Ranking} = {}) {
  const r = given ?? currentRanking(), id = region.value, boat = profile.value === 'boat', speed = cruiseSpeed.value;
  useEffect(() => { if (id && hasCoastTerrain(id)) void loadTerrainHabitat(); }, [id]);
  return (
    <section class="app-where" data-source={r.source ?? undefined}>
      <div class="app-where-head">
        <h2 class="ui-eyebrow">Where to look</h2>
        {r.source ? <span class="app-where-source ui-mono">{r.label}</span> : null}
        {r.source ? <Popover iconOnly summary={`About the ${r.label.toLowerCase()} ranking`} align="end">{r.basis}</Popover> : null}
      </div>
      {r.picks.length ? (
        <ol class="app-picks">
          {r.picks.map((pick, i) => (
            <li key={pick.id} data-mark={pick.id}>
              <button type="button" class="app-pick" aria-pressed={selected(pick)} onClick={() => choosePick(pick)}>
                <span class="app-pick-rank ui-mono">{i + 1}</span>
                <span>{pick.name} <span class="ui-mono">{pick.distance} · {pick.depth}{boat ? pickRun(pick.nm, speed) : ''}</span></span>
                <span class="app-fit ui-eyebrow">{pick.fit}</span>
                <span class="app-pick-reason">{pick.reason}</span>
              </button>
            </li>
          ))}
        </ol>
      ) : <p class="app-empty">{r.empty}</p>}
      <RangeControl />
    </section>
  );
}
