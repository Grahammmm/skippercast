// Mobile layout (FE-06, design § 6 mobile, D8): the map fills the viewport;
// a top strip over it holds the brand and location card, the layers button
// and the Boat / Shore / Spear switch; one bottom sheet with three detents
// holds the brief (peek: the time window, freshness and headline; half: the
// four tiles and the top pick; full: the whole brief with the day, target
// and area menus, the area group holding the port and locate controls as on
// the desktop, FE-08) with the hour slider pinned at its top edge; a four-tab
// nav sits under the sheet. The layers button swaps the sheet's content for
// the rail and the legend; a selected mark replaces the peek content with
// its card. Every piece is the desktop's, composed in this order.
import {useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Segmented} from '../ui/Chip.tsx';
import {Range} from '../ui/Dock.tsx';
import {Sheet, type Detent} from '../ui/Sheet.tsx';
import {day, selection} from '../state.ts';
import {zone} from './App.tsx';
import {AreaSelect, PortControl, ProfileSwitch, TargetSelect, windowText} from './CommandBar.tsx';
import {AccountMenu} from './AccountMenu.tsx';
import {BriefFooter, Caveat, Headline, Picks, TideSpark, Tiles, type Pick} from './Desktop.tsx';
import {LayerRail} from './LayerRail.tsx';
import {Legend} from './Legend.tsx';
import {MapStage} from './MapStage.tsx';
import {MarkCard} from './MarkCard.tsx';
import {Brand, FreshnessDot, Location, ViewNav} from './Masthead.tsx';
import {dayOptions, dockState, hourText, selectTime} from './TimeDock.tsx';

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

/** The hour slider and its readout, pinned at the sheet's top edge. */
export function HourEdge({now}: {now: Date}) {
  const tz = zone(), state = dockState(now, tz);
  return (
    <div class="app-sheet-hour" role="group" aria-label="Time">
      <Range label="Hour" value={state.hour} max={23} onChange={h => selectTime(now, tz, state.day, h)} valueText={hourText} class="ui-dock-range" />
      <output class="ui-dock-readout ui-mono" aria-live="off">{hourText(state.hour)}</output>
    </div>
  );
}

/** The brief in sheet order; a selected mark's card stands in for the eyebrow and headline. */
export function SheetBrief({now, picks = [], onFocus}: {now: Date; picks?: readonly Pick[]; onFocus?: () => void}) {
  const tz = zone(), state = dockState(now, tz);
  return (
    <div class="app-sheet-brief" onFocusIn={onFocus}>
      {selection.value ? <MarkCard /> : (
        <>
          <div class="app-sheet-head">
            <span class="ui-eyebrow">{windowText(now, tz)}</span>
            <FreshnessDot />
          </div>
          <Headline />
        </>
      )}
      <Tiles />
      <Picks picks={picks} />
      <TideSpark />
      <div class="app-sheet-menus">
        <Segmented label="Day" options={dayOptions(now, tz, day.value)} value={state.day} onChange={d => selectTime(now, tz, d, state.hour)} />
        <TargetSelect />
        <div class="app-area" role="group" aria-label="Area and port">
          <AreaSelect />
          <PortControl />
        </div>
      </div>
      <Caveat />
      <BriefFooter><AccountMenu inline /></BriefFooter>
    </div>
  );
}

/** The layer rail and the legend as the sheet's content. */
export function LayersPanel({onClose}: {onClose: () => void}) {
  return (
    <div class="app-sheet-layers">
      <div class="app-sheet-head">
        <span class="ui-eyebrow">Layers</span>
        <Button size="sm" icon="close" onClick={onClose}>Done</Button>
      </div>
      <LayerRail />
      <Legend />
    </div>
  );
}

export function Mobile({now = new Date()}: {now?: Date} = {}) {
  const [detent, setDetent] = useState<Detent>('peek');
  const [panel, setPanel] = useState<Panel>('brief');
  const apply = ({panel: p, detent: d}: {panel: Panel; detent: Detent}) => { setPanel(p); setDetent(d); };
  const layersOpen = panel === 'layers';
  return (
    <div class="app-mobile">
      <MapStage />
      <header class="app-top">
        <div class="app-top-row">
          <div class="app-top-card">
            <Brand />
            <Location />
          </div>
          <IconButton icon="layers" label="Layers" variant="ghost" pressed={layersOpen} onClick={() => apply(toggleLayers(panel, detent))} />
        </div>
        <ProfileSwitch class="app-profile" />
      </header>
      <Sheet label={layersOpen ? 'Layers' : 'Brief'} detent={detent} onDetent={next => apply(afterDetent(panel, next))}
        class={['app-sheet', selection.value ? 'app-sheet--mark' : ''].filter(Boolean).join(' ')} edge={<HourEdge now={now} />}>
        {layersOpen ? <LayersPanel onClose={() => apply(toggleLayers(panel, detent))} /> : <SheetBrief now={now} onFocus={() => { if (detent === 'peek') setDetent('half'); }} />}
      </Sheet>
      <ViewNav icons class="app-tabs" />
    </div>
  );
}
