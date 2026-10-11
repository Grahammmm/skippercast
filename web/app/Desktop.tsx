// Desktop layout (FE-05, design § 6): the 332 px brief column beside the map
// stage with its chrome. The brief renders the FE-31 model through
// web/brief/Brief.tsx (FE-37): headline, deck, four tiles, the lower-exposure
// window, the caveat, the notice, fleet and local-report lines and the
// footer; before a brief is in hand it shows its empty state. "Where to look"
// is web/brief/WhereToLook.tsx (FE-34); the tide sparkline is
// web/brief/TideSpark.tsx (FE-33). The map is MapStage.tsx (FE-71); in the Conditions view
// (FE-32) the view covers the map above the time dock, and the map stays
// mounted. Mobile.tsx (FE-06) composes the same pieces into
// the sheet in its own order.
import {BriefFooter, BriefLinks, BriefTiles, Caveat, Deck, Headline, LowerExposure, currentBrief} from '../brief/Brief.tsx';
import {TideSpark} from '../brief/TideSpark.tsx';
import {WhereToLook, type Ranking} from '../brief/WhereToLook.tsx';
import {LayerRail} from './LayerRail.tsx';
import {Legend} from './Legend.tsx';
import {MapStage} from './MapStage.tsx';
import {MarkCard} from './MarkCard.tsx';
import {TimeDock} from './TimeDock.tsx';
import {Conditions} from './views/Conditions.tsx';
import {appView} from '../state.ts';

export {emptyTiles} from '../brief/Tiles.tsx';
export {DISCLAIMER} from '../brief/Brief.tsx';

export function Brief({ranking, now = new Date()}: {ranking?: Ranking; now?: Date} = {}) {
  const brief = currentBrief(now);
  return (
    <aside class="app-brief" aria-label="Brief" data-basis={brief?.basis}>
      <span class="ui-eyebrow">{brief ? brief.label : 'Today\'s brief'}</span>
      <Headline brief={brief} />
      <Deck brief={brief} />
      <BriefTiles brief={brief} />
      <TideSpark brief={brief} now={now} />
      <WhereToLook ranking={ranking} />
      <LowerExposure brief={brief} />
      <Caveat brief={brief} />
      <BriefLinks brief={brief} />
      <BriefFooter />
    </aside>
  );
}

export function Desktop({now = new Date()}: {now?: Date} = {}) {
  return (
    <main class="app-main">
      <Brief now={now} />
      <MapStage>
        {appView.value === 'conditions' ? <Conditions now={now} /> : <><div class="app-chrome-left"><MarkCard /><Legend /></div><LayerRail /></>}
        <TimeDock now={now} />
      </MapStage>
    </main>
  );
}
