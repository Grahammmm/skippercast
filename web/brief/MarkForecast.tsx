// The mark card's forecast (BP CI6-06): wind, seas and surface current for a
// reef mark or a ranked trip spot at the dock's hour, from the regional
// forecast the brief loads (web/brief/mark-forecast.ts has the rules). Model
// wind and seas are point series in every region, so the block says so and
// shows them at the regional point, named. The WCOFS surface current reads the
// sampled ocean cell nearest the mark, with its distance, when one is in
// reach. NOAA and ECMWF keep their own rows. A gap reads "—" with its reason.
import {useEffect} from 'preact/hooks';
import {regionInfo, zone} from '../app/region-info.ts';
import {dockState} from '../app/TimeDock.tsx';
import {Popover} from '../ui/Popover.tsx';
import {language, t, type Language} from '../i18n.ts';
import {ensureRegionalForecast, regionalForecast} from './Brief.tsx';
import {CELL_REACH, hourText, markForecast, readingSource, type LatLon, type MarkReading} from './mark-forecast.ts';

const basis = (point: string, lang: Language) => t('markForecast.basis', lang, {point, reach: CELL_REACH});

function Row({name, r, at, tz, lang}: {name: string; r: MarkReading; at: number; tz: string; lang: Language}) {
  return (
    <div data-gap={r.value === null ? 'true' : undefined}>
      <dt>{name}</dt>
      <dd class="ui-mono">{r.value ?? '—'}</dd>
      <dd class="app-mark-forecast-source">{r.value === null ? t('markForecast.gapLine', lang, {reason: r.gap}) : readingSource(r, at, tz, lang)}</dd>
    </div>
  );
}

/** The forecast block for a mark at `place`; nothing until the region is known. */
export function MarkForecast({place, now = new Date()}: {place: LatLon; now?: Date}) {
  const info = regionInfo.value, id = info?.id ?? null;
  useEffect(() => { if (info) void ensureRegionalForecast(info.id, info.center); }, [id]);
  if (!info) return null;
  const tz = zone(), at = dockState(now, tz).at, lang = language.value, f = markForecast(regionalForecast.value, info.id, place, at, now.getTime(), tz, lang);
  return (
    <section class="app-mark-forecast" aria-label={t('markForecast.aria', lang)}>
      <p class="app-mark-forecast-head"><span class="ui-eyebrow">{t('markForecast.eyebrow', lang)}</span> <span class="ui-mono">{t('markForecast.valid', lang, {hour: hourText(at, tz, lang)})}</span></p>
      {!f ? <p class="app-mark-forecast-note">{t('markForecast.unloaded', lang)}</p> : (
        <>
          <p class="app-mark-forecast-note">{t('markForecast.note', lang, {point: f.point})}</p>
          <dl>
            {f.families.flatMap(family => family.rows.map(r => <Row key={`${family.family}-${r.label}`} name={t(r.label === 'Wind' ? 'markForecast.rowWind' : 'markForecast.rowSeas', lang, {family: family.label})} r={r} at={at} tz={tz} lang={lang} />))}
            <Row name={t('markForecast.current', lang)} r={f.current} at={at} tz={tz} lang={lang} />
          </dl>
          <Popover>{basis(f.point, lang)}</Popover>
        </>
      )}
    </section>
  );
}
