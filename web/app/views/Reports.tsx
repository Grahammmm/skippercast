// Reports view (FE-52, design § 6, ?view=reports): the dated evidence v1 kept
// in its Forecast and Guide panels, on one page over the map stage (the stage
// stays mounted, so the coast report it loads is the one the catch cards
// read). Sections: fleet catch cards (packages/coast `catchSheet` through
// CoastMarkup, eight at most, with v1's reported / retained / released
// labels), recent fishing evidence, recent discussions, the seasonal watch and
// charter evidence (web/reports.ts), then the coast report feed and page.
// Every row carries its date and source link; nothing ranks places, scores a
// catch or shows publisher prose or photos.
import type {ComponentChildren} from 'preact';
import {signal} from '@preact/signals';
import {useEffect} from 'preact/hooks';
import {counties} from '../../../packages/coast/src/counties.ts';
import type {CatchState} from '../../../packages/coast/src/ui/catches.ts';
import {coastReport} from '../../coast-data.ts';
import {PROFILE_TABLE} from '../../profile.ts';
import {profile, region, species} from '../../state.ts';
import type {Charters, Evidence, ReportsData, Watch} from '../../reports.ts';
import {regionInfo} from '../App.tsx';
import {DEFAULT_ZONE} from '../../zone.ts';
import {CoastMarkup, isSafeCatchState} from '../CoastMarkup.tsx';
import {language, t} from '../../i18n.ts';
import {catchCopy, countPhrase, evidenceCopy, reportDay, rowCopy} from '../../reports-copy.ts';
import {EnglishDetail} from '../EnglishDetail.tsx';

/** The loaded sections, the complete inputs they were loaded for and when (ms; a missing time counts as old). */
export const reportsData = signal<{key: string; data: ReportsData; loadedAt?: number} | null>(null);
let pending: {key: string} | null = null;
/** Settled sections older than this are read again when the view reopens. */
export const REPORTS_MAX_AGE_MS = 30 * 60_000;

/** True when settled sections are old or one of them failed (no charter source is not a failure). */
export function needsReload(entry: {data: ReportsData; loadedAt?: number}, charters: string | null, now: number): boolean {
  const {data, loadedAt} = entry;
  return !(now - (loadedAt ?? NaN) < REPORTS_MAX_AGE_MS) || data.discussions.status === 'unavailable'
    || data.evidence === null || data.watch === null || (charters !== null && data.charters === null);
}
// Preserve source-less keys used by existing preloaded Reports consumers.
const reportsKey = (id: string | null, target: string, charters: string | null): string =>
  charters === null ? `${id}:${target}` : JSON.stringify([id, target, charters]);

/** Load per region, target and charter source, again when `needsReload`; only the current request may publish. */
export async function openReports(id: string, target: string, charters: string | null, fetchFn: typeof fetch = fetch, now = Date.now()): Promise<void> {
  const key = reportsKey(id, target, charters);
  if (pending?.key === key) return;
  const settled = reportsData.peek();
  if (settled?.key === key && !needsReload(settled, charters, now)) {
    // Returning to settled data also supersedes a different pending load.
    pending = null;
    return;
  }
  const request = {key};
  pending = request;
  try {
    const {loadReports} = await import('../../reports.ts');
    const data = await loadReports({region: id, species: target, charters}, fetchFn);
    // The old value stays on screen until this read publishes.
    if (pending === request) reportsData.value = {key, data, loadedAt: now};
  } finally { if (pending === request) pending = null; }
}

const Out = ({href, children}: {href: string; children: ComponentChildren}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;

/** The catch cards, or why there are none; `state` is null outside a coast-report port. */
export function CatchCards({state}: {state: CatchState | null}) {
  const lang = language.value;
  if (!state) return <p>{t('reports.cards.pre', lang)}<a href="/report">{t('reports.cards.link', lang)}</a>{t('reports.cards.post', lang)}</p>;
  if (!isSafeCatchState(state)) return <p>{t('reports.cards.unsafe', lang)}</p>;
  // English passes no copy, so the renderer keeps its own text.
  return <CoastMarkup renderer="catchSheet" args={lang === 'en' ? [state] : [state, catchCopy(lang)]} class="app-reports-catches" />;
}

export function EvidenceSection({evidence, timeZone = DEFAULT_ZONE}: {evidence: Evidence | null; timeZone?: string}) {
  const lang = language.value;
  if (!evidence) return <p>{t('reports.evidence.unavailable', lang)}</p>;
  const text = evidenceCopy(evidence, lang);
  return (
    <>
      <p><span class="ui-eyebrow">{t('reports.evidence.eyebrow', lang)}</span> <strong>{text.confidence}</strong>. {text.reason ?? <EnglishDetail lang={lang}>{evidence.reason}</EnglishDetail>}</p>
      <p class="app-reports-small">{reportDay(evidence.start, lang, timeZone)}–{reportDay(evidence.end, lang, timeZone)} · {countPhrase('trips', evidence.trips, lang)} · {countPhrase('boats', evidence.boats, lang)} · {countPhrase('days', evidence.days, lang)}. {t('reports.evidence.caveat', lang, {date: reportDay(evidence.generatedAt, lang, timeZone)})}</p>
      {evidence.rows.length ? (
        <ul class="app-reports-list">
          {evidence.rows.map(r => {
            const row = rowCopy(r, lang);
            return (
              <li key={`${r.date}:${r.boat}`}>
                <span class="ui-mono">{reportDay(r.date, lang, timeZone)}</span> · {r.boat}: {row.translated ? row.catches : <EnglishDetail lang={lang}>{row.catches}</EnglishDetail>}
                <small>{row.translated ? row.where : <EnglishDetail lang={lang}>{row.where}</EnglishDetail>}{r.url ? <> · <Out href={r.url}>{t('reports.source', lang)}</Out></> : null}</small>
              </li>
            );
          })}
        </ul>
      ) : null}
    </>
  );
}

export function DiscussionsSection({discussions: d, timeZone = DEFAULT_ZONE}: {discussions: ReportsData['discussions']; timeZone?: string}) {
  const lang = language.value;
  if (d.status === 'unavailable') return <p>{t('reports.disc.unavailable', lang)}</p>;
  if (d.status === 'stale') return <p>{t('reports.disc.stale', lang, {date: reportDay(d.generatedAt, lang, timeZone)})}</p>;
  return (
    <>
      <p class="app-reports-small">{t('reports.disc.updated', lang, {date: reportDay(d.generatedAt, lang, timeZone), checked: d.checkedQueries, total: d.totalQueries, degraded: d.status === 'degraded' ? t('reports.disc.degraded', lang) : ''})}</p>
      {d.candidates.length ? (
        <ul class="app-reports-list">
          {d.candidates.map(c => <li key={c.url}><Out href={c.url}>{c.title}</Out><small>{t('reports.disc.published', lang, {date: reportDay(c.published_at, lang, timeZone), source: c.source ?? '', basis: c.location_basis || t('reports.disc.basis', lang)})}</small></li>)}
        </ul>
      ) : <p>{t('reports.disc.empty', lang)}</p>}
      <p class="app-reports-small">{t('reports.disc.caveat', lang)}</p>
    </>
  );
}

export function WatchSection({watch}: {watch: Watch | null}) {
  const lang = language.value;
  if (!watch) return <p>{t('reports.watch.unavailable', lang)}</p>;
  return (
    <>
      <p>{watch.coast}: {watch.items.length ? watch.items.map(w => `${w.name}${w.located ? t('reports.watch.located', lang) : ''}`).join('; ') : t('reports.watch.empty', lang)}.{watch.checked ? '' : t('reports.watch.unchecked', lang)}</p>
      {watch.items.filter(w => w.links.length).map(w => (
        <p key={w.name}>{w.name}: {w.links.map((l, i) => <span key={l.url}>{i ? ' · ' : ''}<Out href={l.url}>{l.date} · {l.publisher}</Out></span>)}</p>
      ))}
      <p class="app-reports-small">{t('reports.watch.caveat', lang)}</p>
    </>
  );
}

export function ChartersSection({charters, timeZone = DEFAULT_ZONE}: {charters: Charters | null; timeZone?: string}) {
  const lang = language.value;
  if (!charters) return <p>{t('reports.charters.none', lang)}</p>;
  return (
    <>
      {charters.rows.length ? (
        <ul class="app-reports-list">
          {charters.rows.map(r => (
            <li key={r.label}>{r.label}<small>{t('reports.charters.ground', lang, {ground: r.ground, trips: countPhrase('trips', r.trips, lang), boats: countPhrase('boats', r.boats, lang), date: reportDay(r.latest, lang, timeZone)})}</small>
              {r.sources.length ? <small>{r.sources.map((source, i) => <span key={`${source.url}:${source.date}:${source.boat}:${i}`}>{i ? ' · ' : t('reports.charters.sources', lang)}<Out href={source.url}>{reportDay(source.date, lang, timeZone)} · {source.boat}</Out></span>)}</small> : null}
            </li>
          ))}
        </ul>
      ) : <p>{t('reports.charters.empty', lang)}</p>}
      {charters.more ? <p class="app-reports-small">{t('reports.charters.more', lang, {n: charters.more})}</p> : null}
      <p class="app-reports-small">{t('reports.charters.caveat', lang, {date: reportDay(charters.audit, lang, timeZone)})}</p>
    </>
  );
}

const Section = ({id, title, children}: {id: string; title: string; children: ComponentChildren}) =>
  <section class="app-reports-section" aria-labelledby={`reports-${id}`}><h2 id={`reports-${id}`}>{title}</h2>{children}</section>;

/** The page body for loaded `data` (null while loading) and the catch state. */
export function ReportsBody({data, catches, timeZone = DEFAULT_ZONE}: {data: ReportsData | null; catches: CatchState | null; timeZone?: string}) {
  const lang = language.value;
  return (
    <>
      <section class="app-reports-section" aria-label={t('reports.catches.aria', lang)}><CatchCards state={catches} /></section>
      {data ? (
        <>
          <Section id="evidence" title={t('reports.section.evidence', lang)}><EvidenceSection evidence={data.evidence} timeZone={timeZone} /></Section>
          <Section id="discussions" title={t('reports.section.discussions', lang)}><DiscussionsSection discussions={data.discussions} timeZone={timeZone} /></Section>
          <Section id="watch" title={t('reports.section.watch', lang)}><WatchSection watch={data.watch} /></Section>
          <Section id="charters" title={t('reports.section.charters', lang)}><ChartersSection charters={data.charters} timeZone={timeZone} /></Section>
        </>
      ) : <p role="status">{t('reports.loading', lang)}</p>}
      <footer class="app-reports-footer">
        <a href="/feed.xml">{t('reports.feed.rss', lang)}</a>
        <a href="/report">{t('reports.feed.read', lang)}</a>
      </footer>
    </>
  );
}

export function Reports({now = new Date()}: {now?: Date} = {}) {
  const id = region.value, info = regionInfo.value, target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget, lang = language.value;
  const charters = info?.id === id ? info.charters ?? null : null, timeZone = info?.id === id ? info.timezone : DEFAULT_ZONE;
  useEffect(() => { if (id) void openReports(id, target, charters).catch(() => {}); }, [id, target, charters]);
  const loaded = reportsData.value, report = coastReport.value?.data, county = report ? counties[report.countyId] : undefined;
  return (
    <article class="app-reports" aria-labelledby="reports-title" data-view="reports">
      <span class="ui-eyebrow">{t('reports.eyebrow', lang)}</span>
      <h1 id="reports-title">{t('reports.title', lang)}</h1>
      <p class="app-deck">{t('reports.deck', lang)}</p>
      <ReportsBody timeZone={timeZone} data={loaded?.key === reportsKey(id, target, charters) ? loaded.data : null} catches={report && county ? {report, county, now} : null} />
    </article>
  );
}
