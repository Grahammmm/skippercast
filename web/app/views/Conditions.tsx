// Conditions view (FE-32, docs/plans/front-end/design.md § 10): the heading, a
// summary row for the selected hour, packages/coast `chart()` through
// CoastMarkup (rows from web/conditions.ts), a caption, each source's clock,
// the selected day's tide events and the profile's before-you-go notes. The
// chart's cursor is the store's `hour`: a drag on the chart writes it as the
// time dock does, so the map's hour moves with it. The surface-current choice
// is the Currents rail entry's own control (`?current=`), not a copy.
import {useEffect, useState} from 'preact/hooks';
import {Segmented} from '../../ui/Chip.tsx';
import {currentBrief, ensureRegionalForecast, regionalForecast} from '../../brief/Brief.tsx';
import {coastBinding, coastReport} from '../../coast-data.ts';
import {coastRows, conditionsRows, conditionsSpan, FAMILIES, forecastRows, readingsAt, sourceClocks, type Family} from '../../conditions.ts';
import {CDFW_REGULATIONS} from '../../map/habitat.ts';
import {disagreements, sentence} from '../../model-disagreement.ts';
import disagreeStyles from './model-disagreement.css?url';
import {PROFILE_TABLE} from '../../profile.ts';
import {language, localeOf, num, t, type Language} from '../../i18n.ts';
import {profile, region, species} from '../../state.ts';
import {loadRegs, regsData} from '../../regs.ts';
import {SeasonStrip} from '../SeasonStrip.tsx';
import {PortAlert} from '../PortAlert.tsx';
import {regionInfo, zone} from '../App.tsx';
import {CoastMarkup} from '../CoastMarkup.tsx';
import {HourlyTable} from './HourlyTable.tsx';
import {CurrentSource} from '../LayerRail.tsx';
import {dockState, localParts, selectHour} from '../TimeDock.tsx';
import {moonLine} from '../../moon.ts';
import {PlanLink, TargetRules, targetRules} from '../PlanView.tsx';
import {conditionsCopy, fixed, localTime} from '../../view-copy.ts';

/** Load the forecast for the region shown (shared with the brief, once per region). */
function useForecast(): void {
  const id = region.value, near = regionInfo.value?.id === id ? regionInfo.value.center : null;
  useEffect(() => { if (id) void ensureRegionalForecast(id, near); }, [id, near?.[0], near?.[1]]);
}

const FAMILY_OPTIONS = (Object.keys(FAMILIES) as Family[]).map(value => ({value, label: FAMILIES[value].label}));
const timeText = (iso: string, tz: string, withDay = false, lang: Language = 'en') => localTime(new Date(iso), tz, lang, {...withDay ? {weekday: 'short'} : {}, hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});
/** The selected hour's weekday: English keeps the dock's own short name, another language formats it in the region zone. */
const dayName = (at: number | string, tz: string, lang: Language): string =>
  lang === 'en' ? localParts(new Date(at), tz).weekday : new Intl.DateTimeFormat(localeOf(lang), {timeZone: tz, weekday: 'long'}).format(new Date(at));
const value = (v: number | null, unit: string, lang: Language = 'en') => {
  if (v === null) return '—';
  const digits = unit === 'ft' ? 1 : 0;
  return `${lang === 'en' ? Number(v.toFixed(digits)) : num(Number(v.toFixed(digits)), lang, digits)} ${unit}`;
};

export function Conditions({now = new Date()}: {now?: Date} = {}) {
  useForecast();
  const lang = language.value, copy = conditionsCopy(lang);
  const rulesRegion = regionInfo.value?.id === region.value ? regionInfo.value.rules ?? null : null;
  useEffect(() => { if (rulesRegion && regsData.peek()?.region !== rulesRegion.id) void loadRegs(rulesRegion); }, [rulesRegion]);
  const rules = regsData.value?.region === rulesRegion?.id ? regsData.value?.data : null;
  const [family, setFamily] = useState<Family>('gfs');
  const tz = zone(), state = dockState(now, tz), selected = new Date(state.at).toISOString();
  const forecast = regionalForecast.value?.region === region.value ? regionalForecast.value : null;
  const report = coastReport.value?.data ?? null, binding = coastBinding.value;
  const span = conditionsSpan(now);
  const local = report && binding ? coastRows(report, binding.areaId, now) : {rows: [], site: null};
  const rows = copy.rows(conditionsRows(forecastRows(forecast, family, span.start), local.rows));
  const brief = currentBrief(now);
  const clocks = sourceClocks(forecast, family, report && binding ? report : null, local.site);
  const notes = PROFILE_TABLE[profile.value], disagree = forecast ? disagreements(forecast, now, tz) : [];
  return (
    <section class="app-conditions" aria-labelledby="app-conditions-title">
      <header class="app-conditions-head">
        <h2 id="app-conditions-title">{t('conditions.title', lang)}</h2>
        <Segmented label={t('conditions.family', lang)} options={FAMILY_OPTIONS} value={family} onChange={setFamily} />
      </header>
      {disagree.length ? <><link rel="stylesheet" href={disagreeStyles} />
        <ul class="app-conditions-disagree" aria-label={t('conditions.disagree.aria', lang)}>{disagree.map(d => <li key={d.date}>{sentence(d, now, tz, lang)}</li>)}</ul></> : null}
      <PortAlert now={now} tz={tz} />
      <dl class="app-conditions-now" aria-label={t('conditions.now.aria', lang, {time: timeText(selected, tz, true, lang)})}>
        {readingsAt(rows, selected).map(r => <div key={r.label}><dt class="ui-eyebrow">{r.label}</dt><dd class="ui-mono">{value(r.value, r.unit, lang)}</dd></div>)}
      </dl>
      <div class="app-conditions-chart" role="region" aria-label={t('conditions.chart.aria', lang)} tabIndex={0}>
        <CoastMarkup renderer="chart" args={[rows, span.start, span.end, selected, tz, {windows: [...brief?.windows ?? []], ...copy.chart ? {copy: copy.chart} : {}}]}
          onCursor={at => selectHour(now, tz, Date.parse(at))} />
      </div>
      <p class="app-conditions-caption">{t(local.rows.length ? 'conditions.caption.local' : 'conditions.caption.nolocal', lang, {model: FAMILIES[family].label, point: forecast?.point.id ?? '—'})}</p>
      <HourlyTable forecast={forecast} tide={local.rows.find(r => r.label === 'Tide') ?? null} at={state.at} tz={tz} now={now} />
      <h3 class="ui-eyebrow">{t('conditions.clocks', lang)}</h3>
      <ul class="app-conditions-clocks">
        {clocks.map(c => <li key={c.label}>{copy.source(c.label)} <span class="ui-mono">{c.at ? `${copy.kind(c.kind)} ${timeText(c.at, tz, true, lang)}` : copy.kind(null)}</span></li>)}
      </ul>
      <h3 class="ui-eyebrow">{t('conditions.tides', lang)}</h3>
      {brief?.tideEvents.length ? (
        <ul class="app-conditions-tides">
          {brief.tideEvents.map(e => <li key={e.at}>{t(e.type === 'H' ? 'conditions.tide.high' : 'conditions.tide.low', lang)} <span class="ui-mono">{timeText(e.at, tz, false, lang)} · {fixed(e.heightFt, 1, lang)} ft {brief.tideDatum}</span></li>)}
        </ul>
      ) : <p class="app-empty">{t('conditions.tide.none', lang, {day: dayName(state.at, tz, lang) || t('conditions.tide.day', lang)})}</p>}
      <p class="app-conditions-moon">{moonLine(state.day, tz)}</p>
      <h3 class="ui-eyebrow">{t('conditions.before', lang)}</h3>
      <ul class="app-conditions-notes">
        <li>{lang === 'en' ? notes.caveat : copy.caveat(profile.value)}</li>
        {brief?.alerts.map(a => <li key={a.id}><a href={a.url} target="_blank" rel="noopener">{a.event}</a></li>)}
        {brief?.notice ? <li><a href={brief.notice.url} target="_blank" rel="noopener">{t('conditions.notice', lang, {name: brief.notice.name})}</a></li> : null}
        <li>{targetRules(now).available ? <TargetRules now={now} /> : <><TargetRules now={now} /><a href={CDFW_REGULATIONS} target="_blank" rel="noopener">{t('conditions.cdfw', lang)}</a></>}</li>
        <li><PlanLink /></li>
      </ul>
      {rulesRegion ? <SeasonStrip data={rules} species={species.value ?? notes.defaultTarget} region={rulesRegion} year={Number(new Intl.DateTimeFormat('en-US', {timeZone: tz, year: 'numeric'}).format(now))} /> : null}
      <h3 class="ui-eyebrow">{t('conditions.current', lang)}</h3>
      <div class="app-conditions-current"><CurrentSource /><p class="app-empty">{t('conditions.currentNote', lang)}</p></div>
    </section>
  );
}
