// Desktop layout (FE-05, design § 6): the 300 px brief column beside the map
// stage with its chrome. The brief renders the FE-31 model through
// web/brief/Brief.tsx (FE-37): the day verdict and its limit (#616), four
// tiles on one row, Details (readings line, deck, gaps, caveat), the
// lower-exposure window, the notice, fleet and local-report lines and the
// footer; before a brief is in hand it shows its empty state. "Where to look"
// is web/brief/WhereToLook.tsx (FE-34); the tide sparkline is
// web/brief/TideSpark.tsx (FE-33). The map is MapStage.tsx (FE-71); in the Conditions view
// (FE-32) the view covers the map above the time dock, and the map stays
// mounted. Mobile.tsx (FE-06) composes the same pieces into
// the sheet in its own order.
// is web/brief/WhereToLook.tsx (FE-34); the tide sparkline (FE-33) is still a
// placeholder. The map is MapStage.tsx (FE-71); in the Conditions view (FE-32)
// the view covers the map above the time dock, and the map stays mounted. The
// Fleet view (FE-53) takes the brief column's place, so the map it drives stays
// in view. Mobile.tsx (FE-06) composes the same pieces into
// and the History view (FE-35) the view covers the map above the time dock,
// and the map stays mounted.
// Mobile.tsx (FE-06) composes the same pieces into
// the sheet in its own order. The Reports view (FE-52) covers the brief and
// the map; the stage stays mounted beneath it.
import {BriefFooter, BriefLinks, BriefTiles, Details, LowerExposure, Verdict, currentBrief} from '../brief/Brief.tsx';
import {TideSpark} from '../brief/TideSpark.tsx';
import {WhereToLook, type Ranking} from '../brief/WhereToLook.tsx';
import {RunLine} from '../brief/Run.tsx';
import {Guard} from '../ui/Guard.tsx';
import {LayerRail} from './LayerRail.tsx';
import {Legend} from './Legend.tsx';
import {MapStage} from './MapStage.tsx';
import {MarkCard} from './MarkCard.tsx';
import {TimeDock} from './TimeDock.tsx';
import {Conditions} from './views/Conditions.tsx';
import {Fleet} from './views/Fleet.tsx';
import {History} from './views/History.tsx';
import {Reports} from './views/Reports.tsx';
import {appView} from '../state.ts';

export {emptyTiles} from '../brief/Tiles.tsx';
export {DISCLAIMER} from '../brief/Brief.tsx';

export function Brief({ranking, now = new Date()}: {ranking?: Ranking; now?: Date} = {}) {
  const brief = currentBrief(now);
  return (
    <aside class="app-brief" aria-label="Brief" data-basis={brief?.basis}>
      {/* SC-LAUNCH-3: the lead names its own day (tomorrow until a time is chosen); the eyebrow heads the evidence for the dock's day. */}
      <Guard name="verdict"><Verdict now={now} /></Guard>
      <span class="ui-eyebrow">{brief ? brief.label : 'Today\'s brief'}</span>
      <Guard name="tiles"><BriefTiles brief={brief} dense /></Guard>
      <Guard name="details"><Details brief={brief} /></Guard>
      <Guard name="tide"><TideSpark brief={brief} now={now} /></Guard>
      <Guard name="where-to-look"><WhereToLook ranking={ranking} /></Guard>
      <Guard name="lower-exposure"><LowerExposure brief={brief} /></Guard>
      <Guard name="run"><RunLine brief={brief} ranking={ranking} now={now} /></Guard>
      <Guard name="brief-links"><BriefLinks brief={brief} /></Guard>
      <BriefFooter />
    </aside>
  );
}

export function Desktop({now = new Date()}: {now?: Date} = {}) {
  return (
    <main class="app-main">
      {appView.value === 'fleet' ? <aside class="app-brief" aria-label="Fleet"><Guard name="fleet"><Fleet /></Guard></aside> : <Brief now={now} />}
      <MapStage>
        {appView.value === 'conditions' ? <Guard name="conditions"><Conditions now={now} /></Guard> : appView.value === 'history' ? <Guard name="history"><History now={now} /></Guard> : <><div class="app-chrome-left"><Guard name="mark-card"><MarkCard /></Guard><Guard name="legend"><Legend /></Guard></div><Guard name="layer-rail"><LayerRail /></Guard></>}
        <Guard name="time-dock"><TimeDock now={now} /></Guard>
      </MapStage>
      {appView.value === 'reports' ? <div class="app-page"><Guard name="reports"><Reports now={now} /></Guard></div> : null}
    </main>
  );
}
