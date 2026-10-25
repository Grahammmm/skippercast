import {useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {currentPort, loadPorts, savedPortId} from '../ports.ts';
import {nearestTideStation} from '../tide-stations.ts';
import {tideSelection as selection} from '../tide-selection.ts';

/** Each mounted layout shares the same per-region choice and request state. */
export function TideStationControl() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [draft, setDraft] = useState<{region: string; id: string} | null>(null);
  const region = selection.region.value;
  if (!region) return null;
  const chosen = selection.choice.value, station = selection.stations.value.find(s => s.id === chosen);
  const candidate = draft?.region === region.id ? draft.id : chosen ?? '';
  const stationName = (id: string) => selection.stations.value.find(s => s.id === id)?.name ?? id;
  async function nearest() {
    if (!region) return;
    setBusy(true); setNotice('');
    try {
      const [rows, ports] = await Promise.all([selection.list(), loadPorts()]);
      if (selection.region.peek() !== region) return;
      const port = currentPort(ports, region.id, savedPortId());
      const closest = port && nearestTideStation(rows, port.match);
      if (closest) {
        if (selection.choose(closest.id)) { setDraft(null); setNotice(`Nearest listed station to ${port!.name}: ${closest.name}.`); }
      }
      else setNotice('No listed tide station or port is available for this region.');
    } catch { setNotice('The port directory could not be read. Retry when connected.'); }
    finally { setBusy(false); }
  }
  return <div class="app-tide-station">
    <Button size="sm" variant="quiet" aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void selection.list(); }}>Tide station: {chosen ? station?.name ?? chosen : region.name}</Button>
    {open ? <div>
      <div role="group" aria-label="Saved tide stations">
        <p>Saved stations ({selection.saved.value.length}/3)</p>
        {selection.saved.value.map(id => <div key={id} style={{display: 'flex', flexWrap: 'wrap', gap: '0.25rem'}}>
          <Button size="sm" pressed={chosen === id} onClick={() => { setNotice(''); setDraft(null); selection.choose(id); }}>Use {stationName(id)}</Button>
          <Button size="sm" variant="quiet" aria-label={`Remove ${stationName(id)}`} onClick={() => { setDraft(null); selection.remove(id); setNotice(`${stationName(id)} removed from saved stations.`); }}>Remove</Button>
        </div>)}
      </div>
      <label>Prediction station <select style={{maxWidth: '100%'}} value={candidate} onChange={event => {
        setNotice('');
        const id = event.currentTarget.value;
        setDraft({region: region.id, id});
        if (!id) selection.choose(null);
      }}>
        <option value="">Region default — {region.name}</option>
        {chosen && !station ? <option value={chosen}>{chosen} — unavailable</option> : null}
        {selection.stations.value.map(s => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
      </select></label>
      <Button size="sm" disabled={!candidate} onClick={() => {
        if (selection.choose(candidate)) { setDraft(null); setNotice(`${stationName(candidate)} saved and active.`); }
      }}>Add current station</Button>
      <Button size="sm" disabled={busy} onClick={() => void nearest()}>Use nearest to port</Button>
      <p>Selection changes only the tide tile and chart. Bar and shore checks keep their reviewed reference station. Tide heights do not predict entrance currents.</p>
      <p>NOAA CO-OPS prediction stations within the region. Subordinate stations provide high/low events, not a continuous curve. Save up to three stations per region in this browser; an offline pack includes only the active station. Removing the active station returns to the region default.</p>
      {notice ? <p role="status">{notice}</p> : null}
    </div> : null}
    {chosen ? <p class="app-caveat">Selected tide display only; bar and shore checks use their configured reference station.</p> : null}
    {selection.loading.value ? <p role="status">Loading station predictions…</p> : null}
    {selection.error.value ? <p role="status">{selection.error.value} <Button size="sm" onClick={() => { void selection.list(); void selection.refresh(); }}>Retry tide station</Button></p> : null}
  </div>;
}
