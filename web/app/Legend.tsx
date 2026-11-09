// Legend (FE-05, design § 6): the map's one legend, a row per layer that is
// on with its swatch (app.css paints the ramps from the cartography tokens).
// A registry layer whose source failed (web/map/chart.ts `unavailable`, FE-11)
// is named here so the gap reads as missing data, never as empty water.
// Seafloor (FE-14) adds its key for the drawn view (terrain grade or the
// target's species fit, switchable here), the surveys and years drawn, the
// credits in its basis, and why nothing draws when the publication is held,
// updating or expired.
// Protected areas (FE-19) are always drawn (on the terrain too since FE-82): their row says what
// the drawing covers (MpaRow), links the official rules page and carries the
// ds582 credit in its basis. Where the region has reef marks for the target,
// the basis also says what the marks' run-time screen checked (#489,
// web/map/habitat.ts), and a stale or unavailable check adds a visible line
// saying the marks are withheld; the row stays one line while marks show.
// Currents (FE-15) follows the source choice `?current=`; its row carries the
// drawn source's basis sentence, or why nothing draws.
// The Clouds row labels the GOES frame on screen with its acquisition time and
// age and holds or resumes the loop (FE-22, web/map/clouds.ts).
// Water temp (FE-16) gives the drawn analysis's range in whole °F, its product,
// date and age, and the basis with its error, or why nothing draws.
// Temp contrast (CI6-03) gives its fixed scale in °F per nautical mile, its product,
// date and age, and the basis with its support rule, or why nothing draws.
// Swell (FE-17) gives the drawn hour's heights, periods and direction, its fixed
// colour scale, the model with its run, age and valid hour as a model forecast,
// and the basis, or why nothing draws.
// FE-20: the rows are the rail entries that are on, and a row shows its colour
// key only while its layer draws, so an inactive ramp never shows; otherwise it
// says why (Clouds in its rail note). In Terrain 2D and 3D an entry that draws only on the Chart reads
// "Chart only", and Currents gives the renderer's status (it keys its own).
// Charter fleet (FE-21) keys the charter grounds and, with its option on, the
// commercial AIS cells, with v1's basis sentences and status lines; for an
// admin (FE-24) each activity layer that is on, with v1's status line, which
// says the activity is inferred from movement.
// FE-82: protected areas, reef marks and charter grounds also drape on the
// terrain, so the protected areas' row and the Charter fleet row show there too;
// commercial AIS still draws on the Chart only and says so.
// Ranked trip spots (FE-51, #495): while the Chart draws a ranked trip plan's
// pins, a row keys them with the registry's label and basis (#422).
// FE-80: in 2D and 3D the Seafloor row is the terrain's: its depth ramp, the
// terrain basis, the screened candidates as "Chart only", and while Source
// coverage is on the renderer's colour key and its sources with their dates, verbatim.
// Depth contours (CI6-13) are always on, Chart only: while they draw, their row keys
// the contour and the dashed survey edge and names each survey, its date and datum;
// withheld or failed contours say so, and a region without any shows no row.
import {Button, IconButton} from '../ui/Button.tsx';
import {current, grade, layers, profile, region, species} from '../state.ts';
import {language, localeOf, t, type Language, type StringId} from '../i18n.ts';
import {EnglishDetail} from './EnglishDetail.tsx';
import {targetLabel} from '../species.ts';
import {PlanLink} from './PlanView.tsx';
import {chartFailed, chartMark, retryMpas, unavailable} from '../map/chart.ts';
import {NOTES, NOTE_COPY, groundsState} from '../map/charter-grounds.ts';
import {cloudHeld, cloudStamp} from '../map/clouds.ts';
import {statusText, type StatusPart} from '../map/status-copy.ts';
import {AIS_CREDIT, aisOn, aisState} from '../map/commercial-ais.ts';
import {ACTIVITY, ACTIVITY_ENTRY, activityAccess, activityOn, activityStatus} from '../map/fleet.ts';
import {currentsState} from '../map/currents.ts';
import {contourState} from '../map/depth-contours.ts';
import {chartOnly, drawsIn, layerCopy, layerEntry} from '../map/layers.ts';
import {densityShown, markNote, markScreen} from '../map/marks.ts';
import {CC_BY_4, CDFW_MPA_PAGE, DS582_METADATA, TRANSIENT_DETAILS, mpaState, shownMpaState} from '../map/mpa.ts';
import {legendKey, seafloorState, seafloorView, surveyList, surveySummary} from '../map/seafloor.ts';
import {waterTempState} from '../map/sst.ts';
import {chlorophyllState} from '../map/chlorophyll.ts';
import {PALETTE_TOKENS} from '../map/palette.ts';
import {CONTRAST_SCALE, contrastState} from '../map/contrast.ts';
import {frontsState} from '../map/fronts.ts';
import {HEIGHT_SCALE, frameSummary, nearshoreState, swellPartition, swellState} from '../map/swell.ts';
import {windState} from '../map/wind.ts';
import {ringBasis, ringSummary} from '../map/nearshore.ts';
import {stationState} from '../map/stations.ts';
import {shoreState} from '../map/shore.ts';
import {unreviewedNote} from '../brief/shore.ts';
import {WAVE_MODEL} from '../map/forecast-grid.ts';
import {currentStatus, shownPresentation, terrainCoarsened, terrainCoverage, terrainOptions} from '../map/stage.ts';
import {drawnSpots} from '../map/ranked.ts';
import {retrySavedSpots, savedSpotsOn, savedSpotsStatus, setSavedSpotsOn} from '../map/saved-spots.ts';
import {Segmented} from '../ui/Chip.tsx';
import {Fragment} from 'preact';
import {cadenceLine} from '../map/freshness.ts';
import {Popover} from '../ui/Popover.tsx';
import {railEntries, railOn} from './rail.ts';
import {PreviewLegendRows} from './PreviewLayers.tsx';

/** A basis popover body: English shows the producer's own basis as it is; Spanish leads with the registry sentence in Spanish, then the producer's full basis unchanged (labelled English) unless it is the registry's own English sentence. */
/** SC1352-02: a status the producer wrote in English, in the page's language when it attached catalogue parts; otherwise labelled English. */
function Status({lang, raw, parts}: {lang: Language; raw: string; parts?: readonly StatusPart[]}) {
  const r = statusText(raw, parts, lang);
  return r.translated ? <>{r.text}</> : <EnglishDetail lang={lang}>{raw}</EnglishDetail>;
}

function Basis({lang, id, runtime, extra, extraEs, copy}: {lang: Language; id: string; runtime: string; extra?: string; extraEs?: string; copy?: readonly StatusPart[]}) {
  if (lang !== 'es') return <>{runtime}{extra ? <> {extra}</> : null}</>;
  const full = statusText(runtime, copy, lang);
  if (full.translated) return <p>{full.text}</p>;
  const same = runtime === layerCopy(id, 'en').basis;
  return <>
    <p>{layerCopy(id, lang).basis}</p>
    {!same && runtime ? <p><EnglishDetail lang={lang}>{runtime}</EnglishDetail></p> : null}
    {extraEs ? <p>{extraEs}</p> : extra ? <p><EnglishDetail lang={lang}>{extra}</EnglishDetail></p> : null}
  </>;
}

function SeafloorRow() {
  const s = seafloorState.value, ready = s.status === 'ready' && s.drawn > 0, lang = language.value, c = layerCopy('seafloor', lang);
  return (
    <li class="app-legend-seafloor">
      {ready ? <span class="app-swatch" data-layer="seafloor" aria-hidden="true"></span> : null}{c.label}
      <Popover iconOnly summary={t('legend.bs.seafloor', lang)}>
        <p>{c.basis}</p>
        {[...s.credits, ...(s.surveys.length ? [surveyList(s.surveys)] : [])].map(line => <p key={line}><EnglishDetail lang={lang}>{line}</EnglishDetail></p>)}
      </Popover>
      {ready ? (
        <div class="app-legend-detail">
          {s.fit ? <Segmented label={t('legend.colourBy', lang)} value={s.view} onChange={v => { seafloorView.value = v; }}
            options={[{value: 'terrain', label: t('legend.terrainGrade', lang)}, {value: 'fit', label: t('legend.fit', lang, {species: `${s.fit[0]!.toUpperCase()}${s.fit.slice(1)}`})}]} /> : null}
          <p class="app-legend-title">{s.view === 'fit' ? t('legend.fitTitle', lang) : t('legend.terrainGrade', lang)}</p>
          <ul>{legendKey(s.view).map(([tone, label]) => <li key={tone}><span class="app-key" data-tone={tone} aria-hidden="true"></span><EnglishDetail lang={lang} prefix={false}>{label}</EnglishDetail></li>)}</ul>
          {s.surveys.length ? <p class="app-legend-note" data-surveys="seafloor"><EnglishDetail lang={lang}>{surveySummary(s.surveys)}</EnglishDetail></p> : null}
        </div>
      ) : null}
      {s.note ? <p class="app-legend-note" data-reason="seafloor"><EnglishDetail lang={lang}>{s.note}</EnglishDetail></p> : null}
    </li>
  );
}

/** The Seafloor row in 2D and 3D (FE-80): what the terrain draws, and the source key while Source coverage is on. */
function TerrainSeafloorRow() {
  const coverage = terrainCoverage.value, shown = terrainOptions.value.sourceCoverage, lang = language.value;
  return (
    <li class="app-legend-seafloor">
      <span class="app-swatch" data-layer="seafloor" aria-hidden="true"></span>{t('legend.seafloorTerrain', lang)}
      <Popover iconOnly summary={t('legend.bs.terrain', lang)}>
        <p>{layerCopy('relief', lang).basis}</p>
        {coverage?.sources.map(s => <p key={s.id}><a href={s.url} target="_blank" rel="noopener">{s.label} · {s.sourceDate}</a></p>)}
      </Popover>
      {shown && coverage?.key ? <p class="app-legend-note" data-key="source-coverage"><EnglishDetail lang={lang}>{coverage.key}</EnglishDetail></p> : null}
      <p class="app-legend-note" data-reason="seafloor">{t('legend.screened', lang, {reason: chartOnly(lang)})}</p>
    </li>
  );
}

const retryable: readonly string[] = Object.values(TRANSIENT_DETAILS);
/** The coarse-drape note (SC0452-04: renderer sampling only, nothing about the source boundary) for registry layer `id`, on the terrain only: the Chart never draws that fill. */
const coarseNote = (id: string, lang: Language) => shownPresentation.value !== 'chart' && terrainCoarsened.value.includes(id)
  ? <p class="app-legend-note" data-drape={id}>{t('legend.coarseDrape', lang)}</p> : null;
/**
 * The protected areas' row: the check date, or what the drawing lacks, so a missing outline never reads as
 * open water. "Loading boundaries." until they load, "Map unavailable." without a map, and unavailable when
 * MapLibre failed to draw the checked data. A failed read offers Try again (SC2007-02).
 */
export function MpaRow() {
  // The Chart's own failures say nothing about the terrain's drape (FE-82).
  const chart = shownPresentation.value === 'chart', lang = language.value, c = layerCopy('mpas', lang);
  const s = shownMpaState(mpaState.value, {sourceFailed: chart && unavailable.value.includes('mpas'), mapFailed: chart && chartFailed.value});
  const drawn = s.count > 0 && (s.status === 'complete' || s.status === 'partial' || s.status === 'incomplete');
  const marks = markNote.value, withheld = !!marks && (markScreen.value.status === 'stale' || markScreen.value.status === 'unavailable');
  return (
    <li class="app-legend-mpa" data-mpa={s.status}>
      <span class="app-legend-mpa-head">
        {drawn ? <span class="app-swatch" data-layer="mpas" aria-hidden="true"></span> : null}{c.label}
        <Popover iconOnly summary={t('legend.bs.mpa', lang)}>
          {c.basis} {s.detail ? <><Status lang={lang} raw={s.detail} parts={s.copy?.reason} /> </> : null}{t('legend.mpa.selection', lang)}<a href={DS582_METADATA} target="_blank" rel="noopener">{t('legend.mpa.dataset', lang)}</a>, <a href={CC_BY_4} target="_blank" rel="noopener">{t('legend.mpa.licence', lang)}</a>.
          {marks && !withheld ? <p data-reason="marks"><EnglishDetail lang={lang}>{marks}</EnglishDetail></p> : null}
        </Popover>
      </span>
      {s.note ? <p class="app-mpa-note"><Status lang={lang} raw={s.note} parts={s.copy?.note} /></p> : null}
      {coarseNote('mpas', lang)}
      {s.status === 'unavailable' && retryable.includes(s.detail) ? <Button variant="quiet" onClick={() => { retryMpas.value++; }}>{t('legend.tryAgain', lang)}</Button> : null}
      {withheld ? <p class="app-mpa-marks" data-reason="marks"><EnglishDetail lang={lang}>{marks}</EnglishDetail></p> : null}
      <a class="app-mpa-rules" href={CDFW_MPA_PAGE} target="_blank" rel="noopener">{t('legend.mpa.rules', lang)}</a>
    </li>
  );
}

function CurrentsRow() {
  const chart = shownPresentation.value === 'chart', state = currentsState.value, reason = chart ? state.reason : currentStatus.value, lang = language.value;
  return (
    <li class="app-legend-currents">
      {chart && state.drawn ? <>
        <span class="app-swatch" data-layer="currents" aria-hidden="true"></span>{layerCopy('currents', lang).label}
        <span class="app-swatch" data-layer="currents-fast" aria-hidden="true"></span>{t('legend.fastest', lang)}
      </> : layerCopy('currents', lang).label}
      <Popover iconOnly summary={t('legend.bs.currents', lang)}>{chart ? <Basis lang={lang} id="currents" runtime={state.basis} /> : layerCopy('currents', lang).basis}</Popover>
      {reason ? <p class="app-legend-note" data-reason="currents"><Status lang={lang} raw={reason} parts={chart ? state.copy?.reason : undefined} /></p> : null}
    </li>
  );
}

/** The observed native cells, logarithmic scale and original sample date. */
function ChlorophyllRow() {
  const s = chlorophyllState.value, lang = language.value, entry = layerCopy('chlorophyll', lang);
  return <li>{entry.label}
    <Popover iconOnly summary={t('legend.bs.chlorophyll', lang)}><Basis lang={lang} id="chlorophyll" runtime={s.basis} /></Popover>
    {s.drawn ? <p class="app-legend-note">{t('legend.logScale', lang)}{entry.legend.map(row => <span key={row.label}>
      <span class="app-swatch" style={{background: `var(--${PALETTE_TOKENS[row.swatch!]})`}} aria-hidden="true"></span>{row.label}{' '}
    </span>)}</p> : null}
    <p class="app-legend-note ui-mono" data-stamp="chlorophyll"><Status lang={lang} raw={s.note} parts={s.copy?.note} /></p>
    <p class="app-legend-note">{layerEntry('chlorophyll').attribution}</p>
  </li>;
}

function WaterTempRow() {
  const s = waterTempState.value, a = s.drawn, lang = language.value;
  return (
    <li class="app-legend-water-temp">
      {a ? <span class="app-swatch" data-layer="water-temp" aria-hidden="true"></span> : null}{layerCopy('water-temp', lang).label}
      {a ? <span class="app-legend-range ui-mono" data-range="water-temp">{a.range[0]}–{a.range[1]} °F</span> : null}
      <Popover iconOnly summary={t('legend.bs.waterTemp', lang)}><Basis lang={lang} id="water-temp" runtime={s.basis} /></Popover>
      {a ? <p class="app-legend-note ui-mono" data-stamp="water-temp"><Status lang={lang} raw={`${a.product} · ${a.stamp}`} parts={s.copy?.stamp} /></p> : null}
      {s.reason ? <p class="app-legend-note" data-reason="water-temp"><Status lang={lang} raw={s.reason} parts={s.copy?.reason} /></p> : null}
    </li>
  );
}

/** The Temp contrast row (on the Chart): the fixed scale in °F per nautical mile, product and age, or why nothing draws. */
function ContrastRow() {
  const s = contrastState.value, d = s.drawn, lang = language.value;
  return (
    <li class="app-legend-sst-contrast">
      {layerCopy('sst-contrast', lang).label}
      <Popover iconOnly summary={t('legend.bs.contrast', lang)}><Basis lang={lang} id="sst-contrast" runtime={s.basis} /></Popover>
      {d ? <p class="app-legend-note ui-mono app-legend-scale" data-scale="sst-contrast">{CONTRAST_SCALE[0]}<span class="app-swatch" data-layer="sst-contrast" aria-hidden="true"></span><span class="app-visually-hidden">{t('legend.to', lang)}</span>{CONTRAST_SCALE[1]}+{t('legend.perNm', lang)}</p> : null}
      {d ? <p class="app-legend-note ui-mono" data-stamp="sst-contrast"><Status lang={lang} raw={`${d.product} · ${d.stamp}`} parts={s.copy?.stamp} /></p> : null}
      {s.reason ? <p class="app-legend-note" data-reason="sst-contrast"><Status lang={lang} raw={s.reason} parts={s.copy?.reason} /></p> : null}
    </li>
  );
}

/** The Temp fronts row (on the Chart): the line and its band, product and age in words, or why nothing draws. */
function FrontsRow() {
  const s = frontsState.value, d = s.drawn, lang = language.value;
  return (
    <li class="app-legend-sst-fronts">
      {layerCopy('sst-fronts', lang).label}
      <Popover iconOnly summary={t('legend.bs.fronts', lang)}><Basis lang={lang} id="sst-fronts" runtime={s.basis} copy={s.copy?.basis} /></Popover>
      {d ? <p class="app-legend-note" data-band="sst-fronts">{t('legend.band', lang)}</p> : null}
      {d ? <p class="app-legend-note ui-mono" data-stamp="sst-fronts"><Status lang={lang} raw={`${d.product} · ${s.note}`} parts={s.copy?.stamp} /></p> : null}
      {s.reason ? <p class="app-legend-note" data-reason="sst-fronts"><Status lang={lang} raw={s.reason} parts={s.copy?.reason} /></p> : null}
    </li>
  );
}

/** The Wind row (on the Chart): the drawn hour's model stamp, or why nothing draws. */
function WindRow() {
  const s = windState.value, lang = language.value;
  return <li class="app-legend-wind">{t('legend.windRow', lang)}
    <Popover iconOnly summary={t('legend.bs.wind', lang)}><Basis lang={lang} id="wind" runtime={s.basis} /></Popover>
    {s.drawn ? <p class="app-legend-note ui-mono" data-stamp="wind"><Status lang={lang} raw={t('legend.windStamp', 'en', {stamp: s.drawn.stamp})} parts={s.copy?.stamp} /></p> : null}
    {s.reason ? <p class="app-legend-note" data-reason="wind"><Status lang={lang} raw={s.reason} parts={s.copy?.reason} /></p> : null}
  </li>;
}

function SwellRow() {
  const s = swellState.value, f = s.drawn, reason = s.reason, r = nearshoreState.value, lang = language.value;
  // The producer's own prefix is compared in English, from the catalogue, never in Spanish.
  const prefix = t('legend.swell.unavailable', 'en');
  const field = !f && r?.rings.length && reason.startsWith(prefix);
  const fieldReason = field ? `${t('legend.swell.fieldUnavailable', 'en')}${reason.slice(prefix.length)}${t('legend.swell.ringsRemain', 'en')}` : reason;
  const reasonParts = field ? s.copy?.fieldReason : s.copy?.reason;
  return (
    <li class="app-legend-swell">
      {f ? <span class="app-swatch" data-layer="swell" aria-hidden="true"></span> : null}{layerCopy('swell', lang).label}
      <Popover iconOnly summary={t('legend.bs.swell', lang)}><Basis lang={lang} id="swell" runtime={s.basis} extra={r ? ringBasis(r.product) : undefined} extraEs={r ? ringBasis(r.product, 'es') : undefined} /></Popover>
      <Segmented label={layerCopy('swell', lang).label} value={swellPartition.value} onChange={v => { swellPartition.value = v; }}
        options={[{value: 'primary', label: t('legend.swell.primary', lang)}, {value: 'wind', label: t('legend.swell.wind', lang)}, {value: 'secondary', label: t('legend.swell.secondary', lang)}]} />
      {f ? <p class="app-legend-note app-legend-range ui-mono" data-range="swell"><EnglishDetail lang={lang}>{frameSummary(f)}</EnglishDetail></p> : null}
      {f ? <p class="app-legend-note ui-mono app-legend-scale" data-scale="swell">{HEIGHT_SCALE[0]} ft<span class="app-swatch" data-layer="swell" aria-hidden="true"></span><span class="app-visually-hidden">{t('legend.to', lang)}</span>{HEIGHT_SCALE[1]}+ ft</p> : null}
      {f ? <p class="app-legend-note ui-mono" data-stamp="swell"><Status lang={lang} raw={t('legend.swell.stamp', 'en', {name: WAVE_MODEL.name, stamp: f.stamp})} parts={s.copy?.stamp} /></p> : null}
      {r ? <p class="app-legend-note ui-mono" data-nearshore="swell"><span class="app-ring" aria-hidden="true"></span>{ringSummary(r, new Date(), lang)}</p> : null}
      {fieldReason ? <p class="app-legend-note" data-reason="swell"><Status lang={lang} raw={fieldReason} parts={reasonParts} /></p> : null}
    </li>
  );
}

/** The Clouds row: the frame drawn now, and the loop toggle while more than one frame can play. */
export function CloudsRow({label}: {label: string}) {
  const stamp = cloudStamp.value, lang = language.value;
  return (
    <>
      <span class="app-legend-text">{label}{stamp ? <span class="app-legend-note ui-mono"><Status lang={lang} raw={stamp.label} parts={stamp.copy} /></span> : null}</span>
      {stamp?.canLoop ? <IconButton icon={cloudHeld.value ? 'play' : 'pause'} label={t('legend.cloudLoop', lang)} pressed={!cloudHeld.value} size="sm"
        onClick={() => { cloudHeld.value = !cloudHeld.value; }} /> : null}
    </>
  );
}

/** The Clouds row: the frame's key and label while one shows; the rail's note says why none does. */
function CloudsLegendRow({label}: {label: string}) {
  return (
    <li class="app-legend-clouds">
      {cloudStamp.value ? <span class="app-swatch" data-layer="clouds" aria-hidden="true"></span> : null}<CloudsRow label={label} />
    </li>
  );
}

// Match the charter card's date-only UTC display; omit malformed or rolled-over dates.
export function researchDate(value: string | null, lang: Language = 'en'): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T12:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) return null;
  return date.toLocaleDateString(localeOf(lang), {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
}

/**
 * The Charter fleet row (FE-21): the charter grounds' hatched key while they draw, else why not, and the
 * commercial AIS option's heat key and v1's status line while it is on; each with v1's basis sentences.
 */
function FleetRow() {
  const g = groundsState.value, lang = language.value, audit = researchDate(g.audit, lang), a = aisState.value, ais = aisOn.value && a.offered, chart = shownPresentation.value === 'chart';
  return (
    <li class="app-legend-fleet">
      {g.drawn ? <span class="app-swatch" data-layer="charter-grounds" aria-hidden="true"></span> : null}{layerCopy('charter-grounds', lang).label}
      <Popover iconOnly summary={t('legend.bs.charter', lang)}>{layerCopy('charter-grounds', lang).basis}{audit ? ` ${t('legend.fleet.checked', lang, {date: audit})}` : ''}</Popover>
      {g.drawn ? <p class="app-legend-note ui-mono" data-stamp="charter-grounds">{t(g.drawn === 1 ? 'legend.fleet.one' : 'legend.fleet.many', lang, {n: g.drawn})}</p> : null}
      {g.note || !g.drawn ? <p class="app-legend-note" data-reason="charter-grounds"><Status lang={lang} raw={g.note || NOTES.loading} parts={g.note ? g.copy?.note : NOTE_COPY.loading} /></p> : null}
      {coarseNote('charter-grounds', lang)}
      {ais ? <>
        <p class="app-legend-note app-legend-sub">{a.drawn && chart ? <span class="app-swatch" data-layer="commercial-ais" aria-hidden="true"></span> : null}{layerCopy('commercial-ais', lang).label}
          <Popover iconOnly summary={t('legend.bs.ais', lang)}>{layerCopy('commercial-ais', lang).basis} <EnglishDetail lang={lang}>{AIS_CREDIT}</EnglishDetail></Popover></p>
        {!chart ? <p class="app-legend-note" data-reason="commercial-ais">{chartOnly(lang)}</p> : a.note ? <p class="app-legend-note" data-reason="commercial-ais"><Status lang={lang} raw={a.note} parts={a.copy?.note} /></p> : null}
      </> : null}
      {activityAccess.value ? ACTIVITY.filter(name => activityOn.value.includes(name)).map(name => {
        const entry = layerCopy(ACTIVITY_ENTRY[name], lang);
        return <p key={name} class="app-legend-note app-legend-sub"><span class="app-swatch" data-layer={ACTIVITY_ENTRY[name]} aria-hidden="true"></span>{entry.legend[0]?.label ?? entry.label}</p>;
      }) : null}
      {activityAccess.value && activityStatus.value ? <p class="app-legend-note" data-reason="fleet-activity"><EnglishDetail lang={lang}>{activityStatus.value}</EnglishDetail></p> : null}
    </li>
  );
}

/** The ranked trip plan's pins, while the Chart draws any. */
export function RankedRow() {
  const n = drawnSpots.value.length, lang = language.value, entry = layerCopy('trip-ranked', lang);
  if (!n || shownPresentation.value !== 'chart') return null;
  return (
    <li class="app-legend-ranked">
      <span class="app-swatch" data-layer="trip-ranked" aria-hidden="true"></span>{entry.legend[0]?.label ?? entry.label}
      <Popover iconOnly summary={t('legend.bs.ranked', lang)}><p>{entry.basis}</p></Popover>
    </li>
  );
}

/** The owner's saved spots (SC0922-04): a native checkbox, off at the start, with why it cannot be turned on or what it shows, and Try again after a failed read. */
export function SavedSpotsRow() {
  const status = savedSpotsStatus.value, lang = language.value, entry = layerCopy('saved-spots', lang);
  return (
    <li class="app-legend-saved-spots">
      <label><input type="checkbox" style={{width: '24px', height: '24px'}} checked={savedSpotsOn.value} disabled={!status.canToggle} onChange={e => setSavedSpotsOn(e.currentTarget.checked)} /> {entry.label}</label>
      <Popover iconOnly summary={t('legend.bs.saved', lang)}><p>{entry.basis}</p></Popover>
      <p class="app-legend-note" data-reason="saved-spots" role="status"><Status lang={lang} raw={status.text} parts={status.copy} /></p>
      {status.retry ? <Button variant="quiet" onClick={retrySavedSpots}>{t('legend.tryAgain', lang)}</Button> : null}
    </li>
  );
}

/** The habitat-candidate density below zoom 10 (#620): what it shows, its grade filter and the zoom that resolves it; never a count of fish. */
export function DensityRow() {
  const n = densityShown.value;
  if (n === null) return null;
  const lang = language.value, label = targetLabel(profile.value, region.value, species.value), g = grade.value, gradeLabel = t(`rail.grade.${g}` as StringId, lang);
  return (
    <li class="app-legend-density">
      {n ? <span class="app-swatch" data-layer="marks-density" aria-hidden="true"></span> : null}
      {n ? t('legend.density.mapped', lang, {label}) : g === 'all' ? t('legend.density.none', lang, {label: label.toLowerCase()}) : t('legend.density.noneGrade', lang, {grade: gradeLabel, label: label.toLowerCase()})}
      <PlanLink />
      <Popover iconOnly summary={t('legend.bs.density', lang)}>
        <p>{layerCopy('marks', lang).basis} {t('rail.grade.meaning', lang)} {t('legend.density.note', lang)}</p>
      </Popover>
      {n ? <p class="app-legend-note" data-reason="marks-density">{g === 'all' ? '' : t('legend.density.grade', lang, {grade: gradeLabel})}{t('legend.density.zoomIn', lang)}</p> : null}
    </li>
  );
}

/** The depth contours (CI6-13): the key and surveys while they draw, or why they do not; nothing where none are published. */
export function DepthContoursRow() {
  const s = contourState.value, lang = language.value, entry = layerCopy('depth-contours', lang);
  if (shownPresentation.value !== 'chart' || !['drawn', 'withheld', 'failed'].includes(s.status)) return null;
  const drawn = s.status === 'drawn';
  const surveyed = (date: string) => t('legend.surveyed', lang, {date});
  return (
    <li class="app-legend-depth-contours">
      {drawn ? <span class="app-swatch" data-layer="depth-contours" aria-hidden="true"></span> : null}{entry.label}
      <Popover iconOnly summary={t('legend.bs.depth', lang)}>
        <p>{entry.basis}</p>
        {s.sources.map(x => <p key={x.source_id}>{x.name} · {surveyed(x.survey_date)} · {x.vertical_datum}</p>)}
      </Popover>
      {drawn ? <p class="app-legend-note" data-key="depth-contours">{entry.legend[0]?.label}</p> : null}
      {drawn ? <p class="app-legend-note" data-key="depth-contours-edge"><span class="app-swatch" data-layer="depth-contours-edge" aria-hidden="true"></span>{entry.legend[1]?.label}</p> : null}
      {drawn ? <p class="app-legend-note ui-mono" data-stamp="depth-contours">{[...new Set(s.sources.map(x => `${surveyed(x.survey_date)} · ${x.vertical_datum}`))].join('; ')} · {t('legend.notForNav', lang)}</p> : null}
      {s.note ? <p class="app-legend-note" data-reason="depth-contours"><EnglishDetail lang={lang}>{s.note}</EnglishDetail></p> : null}
    </li>
  );
}

/** A row with nothing drawn behind it: the entry's name and why, with no key. */
function StationsRow() {
  const s = stationState.value, rings = nearshoreState.value, lang = language.value, entry = layerCopy('stations', lang);
  return <li class="app-legend-stations">{entry.label}
    <Popover iconOnly summary={t('legend.bs.stations', lang)}>{entry.basis}<p>{layerEntry('stations').attribution}</p></Popover>
    <p class="app-legend-note"><Status lang={lang} raw={s.note} parts={s.copy} /></p>
    <ul>{entry.legend.map(row => <li key={row.label}><span class="app-key" aria-hidden="true" style={{background: `var(--${row.swatch})`}} />{row.label}</li>)}</ul>
    <p class="app-legend-note">{rings ? ringSummary(rings, new Date(), lang) : t('legend.ringsUnavailable', lang)}</p>
    <details><summary>{t('legend.stationList', lang)}</summary><ul>{s.pins.map(pin => <li key={pin.key}><Button variant="quiet" onClick={() => { chartMark.value = pin.mark; }}>{pin.mark.name}{pin.location ? '' : t('legend.locationUnavailable', lang)}</Button></li>)}</ul></details>
  </li>;
}

const PlainRow = ({id, label, reason}: {id: string; label: string; reason: string}) => (
  <li class="app-legend-plain">{label}<p class="app-legend-note" data-reason={id}>{reason}</p></li>
);

/** The Shore runs row: says that runs awaiting their first owner review are left off the Chart, never as expired or current. */
function ShoreRow() {
  const lang = language.value, note = shownPresentation.value === 'chart' ? unreviewedNote(shoreState.value.unreviewed) : '';
  return note ? <li class="app-legend-shore"><p class="app-legend-note" data-reason="shore-runs"><EnglishDetail lang={lang}>{note}</EnglishDetail></p></li> : null;
}

/** SCFEAT-FRESH-1: the layer's update cadence and age limit, one wording for every row (web/map/freshness.ts). */
const Cadence = ({id, lang}: {id: string; lang: Language}) => <li class="app-legend-cadence" data-cadence={id}><p class="app-legend-note">{cadenceLine(id, lang)}</p></li>;

function legendRow(e: ReturnType<typeof railEntries>[number], shown: ReturnType<typeof shownPresentation.peek>, lang: Language) {
  return !drawsIn(e.id, shown) ? <PlainRow key={e.id} id={e.id} label={e.label} reason={chartOnly(lang)} />
    : e.id === 'seafloor' ? shown === 'chart' ? <SeafloorRow key={e.id} /> : <TerrainSeafloorRow key={e.id} /> : e.id === 'currents' ? <CurrentsRow key={e.id} /> : e.id === 'water-temp' ? <WaterTempRow key={e.id} />
    : e.id === 'sst-contrast' ? <ContrastRow key={e.id} /> : e.id === 'sst-fronts' ? <FrontsRow key={e.id} /> : e.id === 'chlorophyll' ? <ChlorophyllRow key={e.id} />
    : e.id === 'swell' ? <><SwellRow key={e.id} /><WindRow /></> : e.id === 'clouds' ? <CloudsLegendRow key={e.id} label={e.label} />
    : e.id === 'fleet' ? <FleetRow key={e.id} />
    : e.id === 'stations' ? <StationsRow key={e.id} />
    : <PlainRow key={e.id} id={e.id} label={e.label} reason={t('rail.notDrawn', lang)} />;
}

export function Legend() {
  const shown = shownPresentation.value, lang = language.value;
  const on = railEntries(lang).filter(e => railOn(e.id, layers.value, current.value));
  return (
    <section class="app-legend" aria-label={t('legend.title', lang)}>
      <span class="ui-eyebrow">{t('legend.title', lang)}</span>
      <ul>
        {on.map(e => <Fragment key={e.id}>{legendRow(e, shown, lang)}{drawsIn(e.id, shown) ? <Cadence id={e.id} lang={lang} /> : null}</Fragment>)}
        <PreviewLegendRows />
        <RankedRow />
        <SavedSpotsRow />
        <ShoreRow />
        <DensityRow />
        <DepthContoursRow />
        <MpaRow />
        <Cadence id="mpas" lang={lang} />
      </ul>
      {unavailable.value.filter(id => id !== 'mpas' && !id.startsWith('preview-')).map(id => <p key={id} class="app-empty" data-unavailable={id}>{t('rail.unavailable', lang, {label: layerCopy(id, lang).label})}</p>)}
    </section>
  );
}

