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
import {CoastMarkup, isSafeCatchState} from '../CoastMarkup.tsx';

/** The loaded sections and the region and target they were loaded for. */
export const reportsData = signal<{key: string; data: ReportsData} | null>(null);
let pending = '';

/** Load the sections once per region and target (web/reports.ts comes in with a dynamic import, outside the app entry). */
export async function openReports(id: string, target: string, charters: string | null, fetchFn: typeof fetch = fetch): Promise<void> {
  const key = `${id}:${target}`;
  if (reportsData.peek()?.key === key || pending === key) return;
  pending = key;
  try {
    const {loadReports} = await import('../../reports.ts');
    const data = await loadReports({region: id, species: target, charters}, fetchFn);
    if (pending === key) reportsData.value = {key, data};
  } finally { if (pending === key) pending = ''; }
}

const day = (iso: string | null | undefined): string => {
  const at = iso ? Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00Z` : iso) : NaN;
  return Number.isFinite(at) ? new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: /^\d{4}-\d{2}-\d{2}$/.test(iso ?? '') ? 'UTC' : 'America/Los_Angeles'}).format(at) : 'date unavailable';
};
const Out = ({href, children}: {href: string; children: ComponentChildren}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;

/** The catch cards, or why there are none; `state` is null outside a coast-report port. */
export function CatchCards({state}: {state: CatchState | null}) {
  if (!state) return <p>Dated fleet catch cards show for ports the coast report covers. Choose such a port on the map, or read the <a href="/report">coast report</a>.</p>;
  if (!isSafeCatchState(state)) return <p>The fleet catch counts in this report failed a check and are not shown.</p>;
  return <CoastMarkup renderer="catchSheet" args={[state]} class="app-reports-catches" />;
}

export function EvidenceSection({evidence}: {evidence: Evidence | null}) {
  if (!evidence) return <p>The daily evidence feed for this region is unavailable. No catch score is assumed.</p>;
  return (
    <>
      <p><span class="ui-eyebrow">Evidence for recent activity</span> <strong>{evidence.confidence}</strong>. {evidence.reason}</p>
      <p class="app-reports-small">{day(evidence.start)}–{day(evidence.end)} · {evidence.trips} reported trip{evidence.trips === 1 ? '' : 's'} · {evidence.boats} boat{evidence.boats === 1 ? '' : 's'} · {evidence.days} reporting date{evidence.days === 1 ? '' : 's'}. Confidence describes the evidence for recent activity, not a forecast of your catch or a seven-day prediction. Feed collected {day(evidence.generatedAt)}.</p>
      {evidence.rows.length ? (
        <ul class="app-reports-list">
          {evidence.rows.map(r => (
            <li key={`${r.date}:${r.boat}`}>
              <span class="ui-mono">{day(r.date)}</span> · {r.boat}: {r.catches}
              <small>{r.where}{r.url ? <> · <Out href={r.url}>Source</Out></> : null}</small>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

export function DiscussionsSection({discussions: d}: {discussions: ReportsData['discussions']}) {
  if (d.status === 'unavailable') return <p>Recent discussion search is unavailable. Check the public data job for its source status.</p>;
  if (d.status === 'stale') return <p>The last research snapshot is dated {day(d.generatedAt)}. Current local discussion coverage is unverified.</p>;
  return (
    <>
      <p class="app-reports-small">Updated {day(d.generatedAt)} · {d.checkedQueries}/{d.totalQueries} rotating searches checked in this update{d.status === 'degraded' ? ' · some sources failed or returned partial results' : ''}. Search coverage rotates across regions; an empty result does not mean fish are absent.</p>
      {d.candidates.length ? (
        <ul class="app-reports-list">
          {d.candidates.map(c => <li key={c.url}><Out href={c.url}>{c.title}</Out><small>Published {day(c.published_at)} · {c.source} · {c.location_basis || 'regional search'}</small></li>)}
        </ul>
      ) : <p>No dated local discussion links passed the search filter for this region yet.</p>}
      <p class="app-reports-small">These are unreviewed links. Posting date is not fishing date; the search does not verify a catch, species or boat position.</p>
    </>
  );
}

export function WatchSection({watch}: {watch: Watch | null}) {
  if (!watch) return <p>The seasonal watch for this coast is unavailable.</p>;
  return (
    <>
      <p>{watch.coast}: {watch.items.length ? watch.items.map(w => `${w.name}${w.located ? ' · recent located reports' : ''}`).join('; ') : 'no species on watch'}.{watch.checked ? '' : ' Current source check unavailable.'}</p>
      {watch.items.filter(w => w.links.length).map(w => (
        <p key={w.name}>{w.name}: {w.links.map((l, i) => <span key={l.url}>{i ? ' · ' : ''}<Out href={l.url}>{l.date} · {l.publisher}</Out></span>)}</p>
      ))}
      <p class="app-reports-small">A watch is a reason to check local water and reports; it does not establish fish presence.</p>
    </>
  );
}

export function ChartersSection({charters}: {charters: Charters | null}) {
  if (!charters) return <p>No geographically specific charter evidence is published for this region and target.</p>;
  return (
    <>
      {charters.rows.length ? (
        <ul class="app-reports-list">
          {charters.rows.map(r => (
            <li key={r.label}>{r.label}<small>Captains named “{r.ground}” · {r.trips} reported trip{r.trips === 1 ? '' : 's'} · {r.boats} boat{r.boats === 1 ? '' : 's'} · latest report {day(r.latest)}</small>
              {r.sources.length ? <small>{r.sources.map((source, i) => <span key={`${source.url}:${source.date}:${source.boat}:${i}`}>{i ? ' · ' : 'Source reports: '}<Out href={source.url}>{day(source.date)} · {source.boat}</Out></span>)}</small> : null}
            </li>
          ))}
        </ul>
      ) : <p>No charter grounds have reports for this target.</p>}
      {charters.more ? <p class="app-reports-small">{charters.more} more on the map's Fleet layer.</p> : null}
      <p class="app-reports-small">Newest report first. Reported areas from published trip records; exact stops unknown. Report counts are not catch rates or a popularity ranking. Research checked {day(charters.audit)}.</p>
    </>
  );
}

const Section = ({id, title, children}: {id: string; title: string; children: ComponentChildren}) =>
  <section class="app-reports-section" aria-labelledby={`reports-${id}`}><h2 id={`reports-${id}`}>{title}</h2>{children}</section>;

/** The page body for loaded `data` (null while loading) and the catch state. */
export function ReportsBody({data, catches}: {data: ReportsData | null; catches: CatchState | null}) {
  return (
    <>
      <section class="app-reports-section" aria-label="Fleet catch counts"><CatchCards state={catches} /></section>
      {data ? (
        <>
          <Section id="evidence" title="Recent fishing evidence"><EvidenceSection evidence={data.evidence} /></Section>
          <Section id="discussions" title="Recent discussions"><DiscussionsSection discussions={data.discussions} /></Section>
          <Section id="watch" title="Seasonal watch"><WatchSection watch={data.watch} /></Section>
          <Section id="charters" title="Where local charters report fishing"><ChartersSection charters={data.charters} /></Section>
        </>
      ) : <p role="status">Loading dated reports…</p>}
      <footer class="app-reports-footer">
        <a href="/feed.xml">Follow the coast report (RSS)</a>
        <a href="/report">Readable coast report</a>
      </footer>
    </>
  );
}

export function Reports({now = new Date()}: {now?: Date} = {}) {
  const id = region.value, info = regionInfo.value, target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  const charters = info?.id === id ? info.charters ?? null : null;
  useEffect(() => { if (id) void openReports(id, target, charters).catch(() => {}); }, [id, target, charters]);
  const loaded = reportsData.value, report = coastReport.value?.data, county = report ? counties[report.countyId] : undefined;
  return (
    <article class="app-reports" aria-labelledby="reports-title" data-view="reports">
      <span class="ui-eyebrow">Dated evidence</span>
      <h1 id="reports-title">Reports</h1>
      <p class="app-deck">Trip counts, discussions and charter records with their dates and sources. Missing reports do not mean zero catch.</p>
      <ReportsBody data={loaded?.key === `${id}:${target}` ? loaded.data : null} catches={report && county ? {report, county, now} : null} />
    </article>
  );
}
