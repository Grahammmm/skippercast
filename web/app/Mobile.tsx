// Mobile layout (FE-06, design § 6 mobile, D8): the map fills the viewport;
// a top strip over it holds the brand and location card, the layers button
// and the Boat / Shore / Spear switch; one bottom sheet with three detents
// holds the brief (peek: the time window, freshness and the day verdict with
// its limit (#616); half: the
// four tiles and the top pick; full: the whole brief (FE-37: deck, the
// lower-exposure window, caveat, notice, fleet and local lines) with the day, target
// and area menus, the area group holding the port and locate controls as on
// the desktop, FE-08) with the hour slider pinned at its top edge; a four-tab
// nav sits under the sheet. The layers button swaps the sheet's content for
// the rail and the legend; a selected mark replaces the peek content with
// its card. In the Conditions view (FE-32) and the Fleet view (FE-53) the
// sheet holds that view instead of the brief. Every piece is the desktop's,
// composed in this order. The Reports view (FE-52) opens from its tab (SCJ-9)
// or the sheet's footer and replaces the sheet with its page over the map.
// its card. In the Conditions (FE-32) and History (FE-35) views the sheet holds that view instead
// of the brief. Every piece is the desktop's, composed in this order. The
// Reports view (FE-52) opens from its tab or the sheet's footer and replaces
// the sheet with its page over the map.
import type {ComponentChildren} from 'preact';
import {useEffect, useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Segmented} from '../ui/Chip.tsx';
import {Range} from '../ui/Dock.tsx';
import {Sheet, type Detent} from '../ui/Sheet.tsx';
import {zone} from './App.tsx';
import {AreaSelect, PortControl, ProfileSwitch, TargetSelect, windowText} from './CommandBar.tsx';
import {LimitsControl} from './LimitsPanel.tsx';
import {AccountMenu} from './AccountMenu.tsx';
import {BriefFooter, PrintBrief, BriefLinks, BriefTiles, Details, LowerExposure, SavedLine, Verdict, currentBrief, leadDate, leadDayText} from '../brief/Brief.tsx';
import {TideSpark} from '../brief/TideSpark.tsx';
import {WhereToLook, type Ranking} from '../brief/WhereToLook.tsx';
import {RunLine} from '../brief/Run.tsx';
import {Guard} from '../ui/Guard.tsx';
import {boatEntryOpen} from './FirstRun.tsx';
import {LayerRail} from './LayerRail.tsx';
import {Legend} from './Legend.tsx';
import {MapStage, mapUnavailable} from './MapStage.tsx';
import {useHourNow, type HourClock} from '../clock.ts';
import {MarkCard, currentMark} from './MarkCard.tsx';
import {Brand, DegradedNotice, FreshnessDot, Location, ViewNav, viewLabel} from './Masthead.tsx';
import {Conditions} from './views/Conditions.tsx';
import {Fleet} from './views/Fleet.tsx';
import {History} from './views/History.tsx';
import {Reports} from './views/Reports.tsx';
import {PlanView} from './PlanView.tsx';
import {appView, navigate, withParams, type AppView} from '../state.ts';
import {waypointPlacement} from '../waypoint-placement.ts';
import {language, t} from '../i18n.ts';
import {dayOptions, dockState, hourText, localParts, readout, selectDay, selectHour} from './TimeDock.tsx';
import {useDayVerdicts, withVerdicts} from './day-verdicts.ts';

/** What the sheet shows: the brief, or the layer rail with the legend. */
export type Panel = 'brief' | 'layers';

/** The detent and panel after the sheet moves: the layers panel closes when the sheet drops to peek. */
export function afterDetent(panel: Panel, next: Detent): {panel: Panel; detent: Detent} {
  return {panel: next === 'peek' ? 'brief' : panel, detent: next};
}

/** The detent and panel after the layers button: open at half, or back to the brief. */
export function toggleLayers(panel: Panel, detent: Detent): {panel: Panel; detent: Detent} {
  return panel === 'layers' ? {panel: 'brief', detent} : {panel: 'layers', detent: detent === 'peek' ? 'half' : detent};
}

/** History's series sits below the peek detent's clipped body, so entering History opens a peeked sheet to full. */
export const viewDetent = (view: AppView, detent: Detent): Detent => view === 'history' && detent === 'peek' ? 'full' : detent;

/** The boat step's fields and Save / Not now sit below the peek detent's clipped body, so showing it opens a peeked sheet to full. */
export const boatEntryDetent = (open: boolean, detent: Detent): Detent => open && detent === 'peek' ? 'full' : detent;

/** The first-run prompt yields the sheet to the layers panel; it is still due and returns when Layers closes. */
export const showsFirstRun = (panel: Panel): boolean => panel !== 'layers';

/** The hour slider and its readout, pinned at the sheet's top edge. */
export function HourEdge({now}: {now: Date}) {
  const tz = zone(), state = dockState(now, tz), outside = state.index < 0, lang = language.value;
  const at = (i: number): number => state.hours[i] ?? state.at;
  return (
    <div class="app-sheet-hour" role="group" aria-label={t('shell.time', lang)}>
      <Range label={t('shell.hour', lang)} value={Math.max(0, state.index)} max={outside ? 0 : state.hours.length - 1} onChange={i => selectHour(now, tz, at(i))} disabled={outside}
        valueText={i => outside ? readout(state, tz, lang) : hourText(localParts(new Date(at(i)), tz).hour, lang)} class="ui-dock-range" />
      <output class="ui-dock-readout ui-mono" aria-live="off">{readout(state, tz, lang)}</output>
    </div>
  );
}

/** The brief in sheet order; a selected mark's card stands in for the eyebrow and headline. Below full the tiles are compact (detail and basis at full). */
export function SheetBrief({now, ranking, onFocus, detent = 'full'}: {now: Date; ranking?: Ranking; onFocus?: () => void; detent?: Detent}) {
  const tz = zone(), state = dockState(now, tz), brief = currentBrief(now), answers = useDayVerdicts(now, tz);
  // SC-LAUNCH-3: the head introduces the lead, so it names the lead's day. When the lead answers
  // for another day than the dock's (tomorrow, until a time is chosen) the dock's heading moves
  // below the lead to head the dock-day evidence, as the desktop column does.
  const lead = leadDate(now), apart = lead !== state.day, dockHead = <span class="ui-eyebrow">{windowText(now, tz, language.value)}</span>;
  const lang = language.value, leadText = leadDayText(lead, now, tz, lang);
  return (
    <div class="app-sheet-brief" onFocusIn={onFocus} data-basis={brief?.basis}>
      {currentMark.value && !mapUnavailable.value ? <Guard name="mark-card"><MarkCard /></Guard> : (
        <>
          <div class="app-sheet-head">
            {apart ? <span class="ui-eyebrow">{leadText.charAt(0).toUpperCase() + leadText.slice(1)}</span> : dockHead}
            <FreshnessDot />
          </div>
          <DegradedNotice />
          <Guard name="saved-brief"><SavedLine now={now} /></Guard>
          <Guard name="verdict"><Verdict now={now} /></Guard>
          {apart ? dockHead : null}
        </>
      )}
      <Guard name="tiles"><BriefTiles brief={brief} compact={detent !== 'full'} /></Guard>
      <Guard name="where-to-look"><WhereToLook ranking={ranking} /></Guard>
      <Guard name="details"><Details brief={brief} /></Guard>
      <Guard name="lower-exposure"><LowerExposure brief={brief} /></Guard>
      <Guard name="run"><RunLine brief={brief} ranking={ranking} now={now} /></Guard>
      <Guard name="tide"><TideSpark brief={brief} now={now} /></Guard>
      <div class="app-sheet-menus">
        <Segmented label={t('shell.day', lang)} options={withVerdicts(dayOptions(now, tz, state.day, lang), answers, lang)} value={state.day} onChange={d => selectDay(now, tz, d, state)} />
        <TargetSelect />
        <div class="app-area" role="group" aria-label={t('command.areaPort', lang)}>
          <AreaSelect />
          <PortControl />
        </div>
      </div>
      <Guard name="brief-links"><BriefLinks brief={brief} /></Guard>
      <PrintBrief now={now} />
      <BriefFooter><ReportsLink /><AccountMenu inline /></BriefFooter>
    </div>
  );
}

/** The sheet footer's second way into the Reports view (the Reports tab is the first). */
export const ReportsLink = () =>
  <a href={withParams(typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href, {view: 'reports'})} class="app-reports-link"
    onClick={event => { event.preventDefault(); if (appView.value !== 'reports') navigate(withParams(location.href, {view: 'reports'})); }}>{viewLabel('reports', language.value)}</a>;

/** The layer rail and the legend as the sheet's content. */
export function LayersPanel({onClose}: {onClose: () => void}) {
  const lang = language.value;
  if (mapUnavailable.value) return null;
  return (
    <div class="app-sheet-layers">
      <div class="app-sheet-head">
        <span class="ui-eyebrow">{t('shell.layers', lang)}</span>
        <Button size="sm" icon="close" onClick={onClose}>{t('shell.done', lang)}</Button>
      </div>
      <Guard name="layer-rail"><LayerRail /></Guard>
      <Guard name="legend"><Legend /></Guard>
    </div>
  );
}

export function Mobile({now: fixedNow, clock, firstRun}: {now?: Date; clock?: HourClock; firstRun?: ComponentChildren} = {}) {
  const now = useHourNow(fixedNow, clock);
  const [detent, setDetent] = useState<Detent>('peek');
  const [panel, setPanel] = useState<Panel>('brief');
  const apply = ({panel: p, detent: d}: {panel: Panel; detent: Detent}) => { setPanel(p); setDetent(d); };
  useEffect(() => setDetent(d => viewDetent(appView.value, d)), [appView.value]);
  useEffect(() => setDetent(d => boatEntryDetent(boatEntryOpen.value, d)), [boatEntryOpen.value]);
  const lang = language.value;
  // RF1925-2: no Chart, no layers: the stored panel is kept, but the sheet shows the ordinary view and the trigger is gone.
  const noMap = mapUnavailable.value, shownPanel: Panel = noMap ? 'brief' : panel;
  const layersOpen = shownPanel === 'layers', conditions = appView.value === 'conditions', fleet = appView.value === 'fleet';
  return (
    <main class="app-mobile">
      <MapStage clock={clock} />
      <header class="app-top">
        <div class="app-top-row">
          <div class="app-top-card">
            <Brand />
            <Location />
          </div>
          {noMap ? null : <IconButton icon="layers" label={t('shell.layers', lang)} variant="ghost" pressed={layersOpen} onClick={() => apply(toggleLayers(panel, detent))} />}
          <LimitsControl compact />
        </div>
        <ProfileSwitch class="app-profile" />
      </header>
      {appView.value === 'reports' || appView.value === 'plan' ? <div class="app-mobile-page">{firstRun}{appView.value === 'plan' ? <Guard name="plan"><TargetSelect /><PlanView now={now} /></Guard> : <Guard name="reports"><Reports now={now} /></Guard>}</div> : <Sheet landmark={false} label={layersOpen ? t('shell.layers', lang) : appView.value === 'conditions' || appView.value === 'fleet' || appView.value === 'history' ? viewLabel(appView.value, lang) : t('shell.brief', lang)} detent={waypointPlacement.value ? 'peek' : detent} onDetent={next => apply(afterDetent(panel, next))}
        class={['app-sheet', currentMark.value && !noMap ? 'app-sheet--mark' : ''].filter(Boolean).join(' ')} edge={<Guard name="time-dock"><HourEdge now={now} /></Guard>}
        onBodyFocus={event => {
          const target = event.target as Element | null;
          // Pointer focus must not move a pressed choice before its click is delivered.
          if (target?.closest('.app-firstrun') && target.matches(':focus-visible') && detent !== 'full') {
            setDetent('full');
            // Full lays the card out again (the peek row becomes the whole card), which moves the focused choice: bring it back.
            requestAnimationFrame(() => target.scrollIntoView({block: 'nearest'}));
          }
        }}>
        {showsFirstRun(shownPanel) ? firstRun : null}
        {layersOpen ? <LayersPanel onClose={() => apply(toggleLayers(panel, detent))} /> : appView.value === 'conditions' ? <Guard name="conditions"><Conditions now={now} /></Guard> : appView.value === 'fleet' ? <Guard name="fleet"><Fleet onShowMap={() => setDetent('peek')} /></Guard> : appView.value === 'history' ? <Guard name="history"><History now={now} /></Guard> : <SheetBrief now={now} detent={detent} onFocus={() => { if (detent === 'peek') setDetent('half'); }} />}
      </Sheet>}
      <ViewNav icons class="app-tabs" />
    </main>
  );
}
