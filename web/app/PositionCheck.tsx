// SC-GPSOFFLINE-1: the opt-in position check inside the trip dialog. One tap reads one position (never watched, so no track), screens it on this
// device with the planner's own protected-area screen, and shows the answer. The position is held in this component's state only: it is
// not stored, not sent, and dropped when the trip dialog closes. A saved legal pack answers the boundary files with no signal.
import {useEffect, useRef, useState} from 'preact/hooks';
import {region} from '../state.ts';
import {listPacks, loadProtectedScreen, tripOpen} from '../trip.ts';
import {language} from '../i18n.ts';
import {checkPosition, packState, type HeldScreen, type PackState} from '../position-check.ts';
import {PositionView, type PositionState} from './PositionView.tsx';

export function PositionCheck() {
  const [state, setState] = useState<PositionState>({phase: 'idle'}), [pack, setPack] = useState<PackState>('unknown');
  const run = useRef(0), open = tripOpen.value, id = region.value;
  // Closing the dialog (or changing region) forgets the last position.
  useEffect(() => { if (!open) { ++run.current; setState({phase: 'idle'}); } }, [open, id]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    listPacks().then(packs => { if (live) setPack(packState(packs, id)); }, () => { if (live) setPack('unknown'); });
    return () => { live = false; };
  }, [open, id]);
  const check = () => {
    const mine = ++run.current;
    setState({phase: 'reading'});
    void checkPosition(async () => {
      const loaded = await loadProtectedScreen(id);
      return loaded.state === 'loaded' ? loaded.screen as unknown as HeldScreen : null;
    }).then(result => { if (run.current === mine) setState({phase: 'done', result}); });
  };
  return <PositionView state={state} pack={pack} onCheck={check} lang={language.value} />;
}
