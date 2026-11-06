import {useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {language, t} from '../i18n.ts';
import {currentPort, loadPorts, savedPortId} from '../ports.ts';
import {nearestTideStation} from '../tide-stations.ts';
import {tideSelection as selection} from '../tide-selection.ts';
import {noticeText, selectionMessage, type TideNotice} from './tide-copy.ts';

/** Each mounted layout shares the same per-region choice and request state. The control's own statuses are kept as
 * `{id, vars}` and said at render, so a language switch reaches one that is pending or still showing. */
export function TideStationControl() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState<TideNotice | null>(null);
  const [draft, setDraft] = useState<{region: string; id: string} | null>(null);
  const lang = language.value;
  const region = selection.region.value;
  if (!region) return null;
  const chosen = selection.choice.value, station = selection.stations.value.find(s => s.id === chosen);
  const candidate = draft?.region === region.id ? draft.id : chosen ?? '';
  const stationName = (id: string) => selection.stations.value.find(s => s.id === id)?.name ?? id;
  async function nearest() {
    if (!region) return;
    setBusy(true); setNotice(null);
    try {
      const [rows, ports] = await Promise.all([selection.list(), loadPorts()]);
      if (selection.region.peek() !== region) return;
      const port = currentPort(ports, region.id, savedPortId());
      const closest = port && nearestTideStation(rows, port.match);
      if (closest) {
        if (selection.choose(closest.id)) { setDraft(null); setNotice({id: 'tideStation.nearest', vars: {port: port!.name, station: closest.name}}); }
      }
      else setNotice({id: 'tideStation.noneAvailable', vars: {}});
    } catch { setNotice({id: 'tideStation.portFail', vars: {}}); }
    finally { setBusy(false); }
  }
  return <div class="app-tide-station">
    <Button size="sm" variant="quiet" aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void selection.list(); }}>{t('tideStation.button', lang, {station: chosen ? station?.name ?? chosen : region.name})}</Button>
    {open ? <div>
      <div role="group" aria-label={t('tideStation.group', lang)}>
        <p>{t('tideStation.saved', lang, {n: selection.saved.value.length})}</p>
        {selection.saved.value.map(id => <div key={id} style={{display: 'flex', flexWrap: 'wrap', gap: '0.25rem'}}>
          <Button size="sm" pressed={chosen === id} onClick={() => { setNotice(null); setDraft(null); selection.choose(id); }}>{t('tideStation.use', lang, {station: stationName(id)})}</Button>
          <Button size="sm" variant="quiet" aria-label={t('tideStation.removeAria', lang, {station: stationName(id)})} onClick={() => { setDraft(null); selection.remove(id); setNotice({id: 'tideStation.removed', vars: {station: stationName(id)}}); }}>{t('tideStation.remove', lang)}</Button>
        </div>)}
      </div>
      <label>{t('tideStation.predictionLabel', lang)} <select style={{maxWidth: '100%'}} value={candidate} onChange={event => {
        setNotice(null);
        const id = event.currentTarget.value;
        setDraft({region: region.id, id});
        if (!id) selection.choose(null);
      }}>
        <option value="">{t('tideStation.regionDefault', lang, {region: region.name})}</option>
        {chosen && !station ? <option value={chosen}>{t('tideStation.unavailableOption', lang, {id: chosen})}</option> : null}
        {selection.stations.value.map(s => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
      </select></label>
      <Button size="sm" disabled={!candidate} onClick={() => {
        setNotice(null);
        if (selection.choose(candidate)) { setDraft(null); setNotice({id: 'tideStation.savedActive', vars: {station: stationName(candidate)}}); }
      }}>{t('tideStation.add', lang)}</Button>
      <Button size="sm" disabled={busy} onClick={() => void nearest()}>{t('tideStation.nearestButton', lang)}</Button>
      <p>{t('tideStation.caveat', lang)}</p>
      <p>{t('tideStation.about', lang)}</p>
      {notice ? <p role="status">{noticeText(notice, lang)}</p> : null}
    </div> : null}
    {chosen ? <p class="app-caveat">{t('tideStation.selectedOnly', lang)}</p> : null}
    {selection.loading.value ? <p role="status">{t('tideStation.loading', lang)}</p> : null}
    {selection.notice.value ? <p role="status">{selectionMessage(selection.notice.value, lang)}</p> : null}
    {selection.error.value ? <p role="status">{selectionMessage(selection.error.value, lang)} <Button size="sm" onClick={() => { void selection.refresh(); void selection.list(); }}>{t('tideStation.retry', lang)}</Button></p> : null}
  </div>;
}
