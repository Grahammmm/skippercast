// The fleet Coverage view (#fleet-coverage, #fleet-coverage?region=<id>; CF-35;
// docs/plans/charter-fleet/design.md § 13, US-O2): GET /api/admin/fleet/coverage
// (server/fleet/admin/coverage.ts). Plain tables: boats by port and class, % with an
// MMSI, AIS seen or not seen in 30 days, single-source boats, completeness by field
// group, sources per boat and recent pipeline runs. A boat with no AIS is "not seen".
import {Fragment} from 'preact';
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY} from '../advisor/copy.ts';
import {FLEET_COVERAGE_COPY as COPY, percent} from './fleet-coverage-copy.ts';
import {getFleet, when} from './api.ts';
import {fleetHref, fleetVesselHref} from './route.ts';

type Group = 'identity' | 'registry' | 'specs' | 'contact';
export interface CoverageCell {
  boats: number;
  mmsi: {n: number; pct: number | null};
  ais: {seen: number; not_seen: number; seen_pct: number | null};
  single_source: number;
  completeness: {mean_pct: number | null; groups: Record<Group, number | null>};
}
export interface CoverageReport {
  generated_at: string; region: string | null; seen_days: number;
  groups: Record<Group, string[]>;
  totals: CoverageCell;
  ports: (CoverageCell & {region: string; port_id: string | null; classes: (CoverageCell & {vessel_class: string | null})[]})[];
  sources_per_boat: Record<'0' | '1' | '2' | '3+', number>;
  single_source: {id: string; slug: string; name: string; region: string; port_id: string | null; vessel_class: string | null; source_id: string; ais: 'seen' | 'not-seen'}[];
  truncated: boolean;
  runs: {id: string; region: string; step: string; sink: string; started_at: string; finished_at: string | null; status: string; counts: unknown; error: string | null}[];
}
const GROUPS: readonly Group[] = ['identity', 'registry', 'specs', 'contact'];

/** The AIS presence label: "Seen" or "Not seen", nothing stronger. */
export const presence = (ais: 'seen' | 'not-seen'): string => ais === 'seen' ? COPY.aisSeen : COPY.aisNotSeen;

function Cells({c}: {c: CoverageCell}) {
  return (
    <>
      <td>{c.boats}</td>
      <td>{COPY.countOf(c.mmsi.n, c.mmsi.pct)}</td>
      <td>{COPY.countOf(c.ais.seen, c.ais.seen_pct)}</td>
      <td>{c.ais.not_seen}</td>
      <td>{c.single_source}</td>
      <td>{percent(c.completeness.mean_pct)}</td>
      {GROUPS.map(g => <td key={g}>{percent(c.completeness.groups[g])}</td>)}
    </>
  );
}

export function FleetCoverageView({region}: {region: string}) {
  const [data, setData] = useState<CoverageReport | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [regions, setRegions] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    setState('loading');
    getFleet<CoverageReport>('coverage', {region}).then(r => {
      if (!live) return;
      setData(r); setState('ready');
      setRegions(known => [...new Set([...known, ...r.ports.map(p => p.region), ...(region ? [region] : [])])].sort());
    }).catch(() => { if (live) setState('failed'); });
    return () => { live = false; };
  }, [region]);

  return (
    <section class="admin-view" aria-labelledby="fleet-coverage-heading">
      <h1 id="fleet-coverage-heading" tabIndex={-1}>{COPY.coverageHeading}</h1>
      <div class="admin-filters">
        <label>
          <span>{COPY.region}</span>
          <select value={region} onChange={e => { location.hash = fleetHref('fleet-coverage', (e.currentTarget as HTMLSelectElement).value); }}>
            <option value="">{COPY.allRegions}</option>
            {regions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      </div>
      <p class="admin-hint">{COPY.coverageNote}</p>
      {state === 'loading' ? <p>{ADMIN_COPY.loading}</p> : state === 'failed' || !data ? <p class="admin-error" role="alert">{ADMIN_COPY.loadFailed}</p> : <CoverageBody r={data} />}
    </section>
  );
}

function CoverageBody({r}: {r: CoverageReport}) {
  if (!r.totals.boats && !r.runs.length) return <p>{COPY.noBoats}</p>;
  const head = (
    <tr>
      <th scope="col">{COPY.port}</th><th scope="col">{COPY.vesselClass}</th><th scope="col">{COPY.boats}</th><th scope="col">{COPY.mmsi}</th>
      <th scope="col">{COPY.seen}</th><th scope="col">{COPY.notSeen}</th><th scope="col">{COPY.singleSource}</th><th scope="col">{COPY.completeness}</th>
      {GROUPS.map(g => <th key={g} scope="col" title={COPY.groups[g]}>{COPY.groupShort[g]}</th>)}
    </tr>
  );
  return (
    <div class="admin-coverage">
      {r.truncated ? <p class="admin-hint">{COPY.truncated}</p> : null}
      <section aria-labelledby="fc-ports">
        <h2 id="fc-ports">{COPY.byPortHeading}</h2>
        <div class="admin-scroll" role="region" aria-labelledby="fc-ports" tabIndex={0}>
          <table class="admin-counts">
            <thead>{head}</thead>
            <tbody>
              <tr><th scope="row">{COPY.totalsHeading}</th><td>{COPY.portTotal}</td><Cells c={r.totals} /></tr>
              {r.ports.flatMap(p => {
                const port = `${r.region ? '' : p.region + ' · '}${p.port_id ?? COPY.noPort}`;
                return [
                  <tr key={`${p.region}/${p.port_id}`}><th scope="row">{port}</th><td>{COPY.portTotal}</td><Cells c={p} /></tr>,
                  ...p.classes.map(c => <tr key={`${p.region}/${p.port_id}/${c.vessel_class}`}><th scope="row">{port}</th><td>{c.vessel_class ?? COPY.unclassified}</td><Cells c={c} /></tr>),
                ];
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section aria-labelledby="fc-groups">
        <h2 id="fc-groups">{COPY.groupsHeading}</h2>
        <dl class="admin-fields">
          {GROUPS.map(g => <Fragment key={g}><dt>{COPY.groups[g]}</dt><dd>{percent(r.totals.completeness.groups[g])}</dd></Fragment>)}
        </dl>
      </section>
      <section aria-labelledby="fc-sources">
        <h2 id="fc-sources">{COPY.sourcesHeading}</h2>
        <p class="admin-hint">{COPY.sourcesNote}</p>
        <dl class="admin-fields">
          {(['0', '1', '2', '3+'] as const).map(k => <Fragment key={k}><dt>{COPY.sourcesCount(k)}</dt><dd>{r.sources_per_boat[k]}</dd></Fragment>)}
        </dl>
      </section>
      <section aria-labelledby="fc-single">
        <h2 id="fc-single">{COPY.singleHeading}</h2>
        {!r.single_source.length ? <p>{COPY.singleEmpty}</p> : (
          <div class="admin-scroll" role="region" aria-labelledby="fc-single" tabIndex={0}>
            <table class="admin-counts">
              <thead><tr><th scope="col">{COPY.name}</th><th scope="col">{COPY.port}</th><th scope="col">{COPY.vesselClass}</th><th scope="col">{COPY.source}</th><th scope="col">{COPY.ais}</th></tr></thead>
              <tbody>
                {r.single_source.map(s => (
                  <tr key={s.id}>
                    <th scope="row"><a href={fleetVesselHref(s.id)}>{s.name}</a></th>
                    <td>{s.port_id ?? COPY.noPort}</td><td>{s.vessel_class ?? COPY.unclassified}</td><td>{s.source_id}</td><td>{presence(s.ais)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section aria-labelledby="fc-runs">
        <h2 id="fc-runs">{COPY.runsHeading}</h2>
        {!r.runs.length ? <p>{COPY.runsEmpty}</p> : (
          <div class="admin-scroll" role="region" aria-labelledby="fc-runs" tabIndex={0}>
            <table class="admin-counts">
              <thead><tr><th scope="col">{COPY.step}</th><th scope="col">{COPY.region}</th><th scope="col">{COPY.status}</th><th scope="col">{COPY.started}</th>
                <th scope="col">{COPY.finished}</th><th scope="col">{COPY.counts}</th><th scope="col">{COPY.error}</th></tr></thead>
              <tbody>
                {r.runs.map(run => (
                  <tr key={run.id}>
                    <th scope="row">{run.step}</th><td>{run.region}</td>
                    <td class={run.status === 'failed' ? 'is-rough' : run.status === 'ok' ? 'is-go' : 'is-caution'}>{run.status}</td>
                    <td>{when(run.started_at)}</td><td>{when(run.finished_at) || '—'}</td>
                    <td>{run.counts && typeof run.counts === 'object' ? Object.entries(run.counts as Record<string, unknown>).map(([k, v]) => `${k} ${String(v)}`).join(', ') : '—'}</td>
                    <td>{run.error ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
