// "Where to look" (FE-34, design § 10): the top four places from web/ranking.ts,
// one source at a time, its label shown and its basis in a popover. Each row is a
// button: an atlas mark selects `?spot=`, a terrain habitat `?habitat=` (each
// dropping the other), counted as a pick so the mark card opens and takes focus,
// in every presentation. The row matching the address's selection is pressed, so
// a pick on the map shows here too.
import {useEffect} from 'preact/hooks';
import {Popover} from '../ui/Popover.tsx';
import {hasCoastTerrain} from '../coast-context.ts';
import {markData, markScreen, picked, spotHref} from '../map/marks.ts';
import {coastSpecies, habitatHref} from '../map/stage.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {loadTerrainHabitat, ranking, terrainHabitat, type Pick, type Ranking} from '../ranking.ts';
import {habitat, navigate, profile, region, selection, species} from '../state.ts';

export type {Pick, Ranking};

/** The list for the address and loaded data now, read from the signals so the brief re-renders when they change. */
export function currentRanking(now = Date.now()): Ranking {
  const p = profile.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget;
  return ranking({region: region.value, profile: p, target, coast: coastSpecies(species.value, p), data: markData.value, screen: markScreen.value, terrain: terrainHabitat.value, now});
}

/** Select a pick's mark or habitat (a history entry), as a click on the map would. */
export function choosePick(pick: Pick, href: string = location.href): void {
  picked.value++;
  navigate(pick.kind === 'spot' ? spotHref(href, pick.id) : habitatHref(href, pick.id));
}

const selected = (pick: Pick): boolean => pick.kind === 'spot' ? selection.value === pick.id : habitat.value === pick.id;

export function WhereToLook({ranking: given}: {ranking?: Ranking} = {}) {
  const r = given ?? currentRanking(), id = region.value;
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
                <span>{pick.name} <span class="ui-mono">{pick.distance} · {pick.depth}</span></span>
                <span class="app-fit ui-eyebrow">{pick.fit}</span>
                <span class="app-pick-reason">{pick.reason}</span>
              </button>
            </li>
          ))}
        </ol>
      ) : <p class="app-empty">{r.empty}</p>}
    </section>
  );
}
