// Home-port wind and swell alert card in the Conditions view (SCFEAT-ALERT-1, matrix recommendation 8). The saved
// home port (web/ports.ts) and two thresholds kept on this device (web/port-alert.ts) are compared with the regional
// forecast the view already loads. No account, saved trip or server push: it only shows an in-app state, with the
// forecast's source and both clocks. Shown only when the saved port belongs to the region on screen.
import {useEffect, useState} from 'preact/hooks';
import type {TargetedSubmitEvent} from 'preact';
import {Button} from '../ui/Button.tsx';
import {regionalForecast} from '../brief/Brief.tsx';
import {briefForecast} from '../conditions.ts';
import {language, num, t, type Language} from '../i18n.ts';
import {clearThresholds, evaluatePortAlert, loadThresholds, saveThresholds, WINDOW_HOURS, type Thresholds} from '../port-alert.ts';
import {loadPorts, savedPortId, type Port} from '../ports.ts';
import {region} from '../state.ts';
import {localTime} from '../view-copy.ts';

const when = (iso: string, tz: string, lang: Language) => !Number.isFinite(Date.parse(iso)) ? iso : localTime(new Date(iso), tz, lang, {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});

export function PortAlert({now, tz}: {now: Date; tz: string}) {
  const lang = language.value;
  const [port, setPort] = useState<Port | null>(null);
  const [limits, setLimits] = useState<Thresholds | null>(() => loadThresholds());
  const [note, setNote] = useState<'saved' | 'cleared' | 'invalid' | null>(null);
  useEffect(() => {
    const id = savedPortId();
    if (!id) return;
    let live = true;
    loadPorts().then(list => { if (live) setPort(list.find(p => p.id === id) ?? null); }, () => {});
    return () => { live = false; };
  }, []);
  if (!port || port.region !== region.value) return null;

  const save = (event: TargetedSubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const saved = saveThresholds({windKt: Number(f.get('windKt')), swellFt: Number(f.get('swellFt'))});
    if (saved) setLimits(saved);
    setNote(saved ? 'saved' : 'invalid');
  };
  const raw = regionalForecast.value?.region === region.value ? regionalForecast.value : null;
  const forecast = briefForecast(raw);
  const result = limits ? evaluatePortAlert(limits, forecast, now.getTime()) : null;
  const stateId = !result ? 'portAlert.state.none' : result.state === 'alert' ? 'portAlert.state.alert' : result.state === 'clear' ? 'portAlert.state.clear' : result.state === 'stale' ? 'portAlert.state.stale' : 'portAlert.state.nodata';
  return (
    <section class="app-port-alert" aria-labelledby="app-port-alert-title" data-state={result?.state ?? 'none'}>
      <h3 id="app-port-alert-title" class="ui-eyebrow">{t('portAlert.title', lang)}</h3>
      <p class="small">{t('portAlert.intro', lang, {port: port.name})}</p>
      <form class="insight-form" onSubmit={save}>
        <label>{t('portAlert.wind', lang)}<input name="windKt" type="number" min="1" max="60" step="1" defaultValue={limits?.windKt ?? 15} required /></label>
        <label>{t('portAlert.swell', lang)}<input name="swellFt" type="number" min="0.5" max="30" step="0.5" defaultValue={limits?.swellFt ?? 6} required /></label>
        <Button type="submit" variant="primary">{t('portAlert.save', lang)}</Button>
        {limits ? <Button type="button" onClick={() => { clearThresholds(); setLimits(null); setNote('cleared'); }}>{t('portAlert.clear', lang)}</Button> : null}
      </form>
      <p role="status" class="small">{note ? t(note === 'saved' ? 'portAlert.saved' : note === 'cleared' ? 'portAlert.cleared' : 'portAlert.invalid', lang) : ''}</p>
      <p role="status"><strong>{t(stateId, lang, {hours: WINDOW_HOURS})}</strong></p>
      {result?.exceedances.length ? <ul>{result.exceedances.map(e => <li key={e.kind}>{t(e.kind === 'wind' ? 'portAlert.hit.wind' : 'portAlert.hit.swell', lang, {value: num(e.value, lang), time: when(e.at, tz, lang), limit: num(e.kind === 'wind' ? limits!.windKt : limits!.swellFt, lang)})}</li>)}</ul> : null}
      {result && result.source ? <p class="small">{t('portAlert.source', lang, {source: result.source, issued: when(result.issuedAt!, tz, lang), fetched: when(result.fetchedAt!, tz, lang)})}</p> : null}
      <p class="small">{t('portAlert.notnav', lang)}</p>
    </section>
  );
}
