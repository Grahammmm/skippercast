// SC-GPSOFFLINE-1: the opt-in position check inside the trip dialog. One tap reads one position (never watched, so no track), screens it on this
// device with the planner's own protected-area screen, and shows the answer. The position is held in this component's state only: it is
// not stored, not sent, and dropped when the trip dialog closes. A saved legal pack answers the boundary files with no signal.
import {useEffect, useRef, useState} from 'preact/hooks';
import {region} from '../state.ts';
import {listPacks, loadProtectedScreen, tripOpen} from '../trip.ts';
import {language} from '../i18n.ts';
import {checkPosition, packState, type HeldScreen, type PackState} from '../position-check.ts';
import {PositionView, type PositionState} from './PositionView.tsx';

const IDLE: PositionState = {phase: 'idle'};

export function PositionCheck() {
  // Retained state is tagged with the region that requested it, so a reading never shows in another region, even for the render before effects run.
  const [held, setHeld] = useState<{id: string; state: PositionState}>({id: '', state: IDLE});
  const [packed, setPacked] = useState<{id: string; pack: PackState}>({id: '', pack: 'unknown'});
  const run = useRef(0), open = tripOpen.value, id = region.value;
  const now = useRef({open, id});
  now.current = {open, id};
  // Closing the dialog, changing region or unmounting forgets the last position and voids any pending answer.
  useEffect(() => {
    ++run.current;
    setHeld({id, state: IDLE});
    return () => { ++run.current; };
  }, [open, id]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    listPacks().then(packs => { if (live) setPacked({id, pack: packState(packs, id)}); }, () => { if (live) setPacked({id, pack: 'unknown'}); });
    return () => { live = false; };
  }, [open, id]);
  const check = () => {
    const mine = ++run.current, asked = id;
    setHeld({id: asked, state: {phase: 'reading'}});
    void checkPosition(async () => {
      const loaded = await loadProtectedScreen(asked);
      return loaded.state === 'loaded' ? loaded.screen as unknown as HeldScreen : null;
    }).then(result => { if (run.current === mine && now.current.open && now.current.id === asked) setHeld({id: asked, state: {phase: 'done', result}}); });
  };
  const state = open && held.id === id ? held.state : IDLE;
  const pack = packed.id === id ? packed.pack : 'unknown';
  return <PositionView state={state} pack={pack} onCheck={check} lang={language.value} />;
}
