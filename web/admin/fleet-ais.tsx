// The fleet AIS health view (#fleet-ais, #fleet-ais?region=<id>; CF-35;
// docs/plans/charter-fleet/design.md § 13, US-O3): GET /api/admin/fleet/ais/health
// (server/fleet/admin/ais-health.ts). Per region: last message age, messages per
// minute, reconnects and drops in 24 h, gaps over 10 minutes and hours without
// messages over 7 days, 7- and 30-day uptime, the last processor run and the watch list.
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY} from '../advisor/copy.ts';
import {FLEET_COVERAGE_COPY as COPY, duration} from './fleet-coverage-copy.ts';
import {getFleet, when} from './api.ts';
import {fleetHref} from './route.ts';
import {Spark} from './funnel.tsx';

interface Uptime {pct: number | null; up_hours: number; hours: number}
export interface AisRegionHealth {
  region: string;
  heartbeat: {written_at: string | null; pushed_at: string; age_s: number | null; connected: boolean | null; source: string | null; git_sha: string | null} | null;
  heartbeat_unreadable: boolean;
  last_message_at: string | null; last_message_age_s: number | null; stale: boolean;
  messages_per_min: number | null; watched_messages_per_min: number | null;
  last_24h: {messages: number; reconnects: number; dropped: number; hours_reported: number};
  hours_24: {hour: string; messages: number; missing: boolean}[];
  gaps: {hour: string; max_gap_s: number}[];
  outages: {from: string; to: string; hours: number}[];
  uptime: {d7: Uptime; d30: Uptime};
  processor: {last_run_at: string; age_s: number} | null;
  watch: {watched: number; candidates: number; listener: number | null};
}
export interface AisHealthReport {checked_at: string; gap_s: number; stale_s: number; regions: AisRegionHealth[]}

function Row({label, value, tone}: {label: string; value: string | number; tone?: 'go' | 'rough' | 'caution'}) {
  return <><dt>{label}</dt><dd class={tone ? `is-${tone}` : undefined}>{value}</dd></>;
}
const STALE_S = 3 * 3600;   // the fleet-health alert threshold (server/fleet/admin/ais-health.ts STALE_S, CF-45)
const uptimeTone = (u: Uptime): 'go' | 'caution' | 'rough' | undefined => u.pct === null ? undefined : u.pct >= 99 ? 'go' : u.pct >= 90 ? 'caution' : 'rough';

export function FleetAisView({region}: {region: string}) {
  const [data, setData] = useState<AisHealthReport | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [regions, setRegions] = useState<string[]>([]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    setState('loading');
    getFleet<AisHealthReport>('ais/health', {region}).then(r => {
      if (!live) return;
      setData(r); setState('ready');
      setRegions(known => [...new Set([...known, ...r.regions.map(x => x.region), ...(region ? [region] : [])])].sort());
    }).catch(() => { if (live) setState('failed'); });
    return () => { live = false; };
  }, [region, tick]);

  return (
    <section class="admin-view" aria-labelledby="fleet-ais-heading">
      <h1 id="fleet-ais-heading" tabIndex={-1}>{COPY.aisHeading}</h1>
      <div class="admin-filters">
        <label>
          <span>{COPY.region}</span>
          <select value={region} onChange={e => { location.hash = fleetHref('fleet-ais', (e.currentTarget as HTMLSelectElement).value); }}>
            <option value="">{COPY.allRegions}</option>
            {regions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      </div>
      <p class="admin-meta">
        {data ? ADMIN_COPY.checkedAt(when(data.checked_at)) : ''}{' '}
        <button type="button" class="admin-button" onClick={() => setTick(t => t + 1)}>{ADMIN_COPY.refresh}</button>
      </p>
      <p class="admin-hint">{COPY.aisNote}</p>
      {state === 'loading' ? <p>{ADMIN_COPY.loading}</p> : state === 'failed' || !data ? <p class="admin-error" role="alert">{ADMIN_COPY.loadFailed}</p>
        : !data.regions.length ? <p>{COPY.noRegions}</p> : data.regions.map(h => <RegionHealth key={h.region} h={h} />)}
    </section>
  );
}

function RegionHealth({h}: {h: AisRegionHealth}) {
  const id = `fa-${h.region}`;
  return (
    <section class="admin-health" aria-labelledby={id}>
      <h2 id={id}>{h.region}</h2>
      {h.stale ? <p class="admin-banner" role="alert">{COPY.stale}</p> : null}
      {h.heartbeat_unreadable ? <p class="admin-error">{COPY.heartbeatUnreadable}</p> : null}
      <section aria-labelledby={`${id}-live`}>
        <h3 id={`${id}-live`}>{h.stale ? COPY.stale : COPY.receiving}</h3>
        <dl class="admin-fields">
          <Row label={COPY.lastMessage} value={when(h.last_message_at) || COPY.never} />
          <Row label={COPY.lastMessageAge} value={h.last_message_age_s === null ? COPY.never : duration(h.last_message_age_s)} tone={h.stale ? 'rough' : 'go'} />
          <Row label={COPY.messagesPerMin} value={h.messages_per_min ?? '—'} />
          <Row label={COPY.watchedPerMin} value={h.watched_messages_per_min ?? '—'} />
          <Row label={COPY.heartbeat} value={h.heartbeat ? COPY.ago(h.heartbeat.age_s) : COPY.never} />
          <Row label={COPY.connected} value={h.heartbeat?.connected === true ? COPY.yes : h.heartbeat?.connected === false ? COPY.no : '—'}
            tone={h.heartbeat?.connected === false ? 'rough' : undefined} />
        </dl>
      </section>
      <section aria-labelledby={`${id}-24`}>
        <h3 id={`${id}-24`}>{COPY.last24Heading}</h3>
        <p><Spark values={h.hours_24.map(x => x.messages)} label={COPY.messagesTrend} /></p>
        <dl class="admin-fields">
          <Row label={COPY.messages24} value={h.last_24h.messages} />
          <Row label={COPY.reconnects24} value={h.last_24h.reconnects} tone={h.last_24h.reconnects ? 'caution' : undefined} />
          <Row label={COPY.dropped24} value={h.last_24h.dropped} tone={h.last_24h.dropped ? 'caution' : undefined} />
          <Row label={COPY.hoursReported} value={`${h.last_24h.hours_reported} / 24`} tone={h.last_24h.hours_reported < 24 ? 'caution' : undefined} />
        </dl>
      </section>
      <section aria-labelledby={`${id}-up`}>
        <h3 id={`${id}-up`}>{COPY.uptimeHeading}</h3>
        <dl class="admin-fields">
          <Row label={COPY.uptime7} value={COPY.uptimeLine(h.uptime.d7.pct, h.uptime.d7.up_hours, h.uptime.d7.hours)} tone={uptimeTone(h.uptime.d7)} />
          <Row label={COPY.uptime30} value={COPY.uptimeLine(h.uptime.d30.pct, h.uptime.d30.up_hours, h.uptime.d30.hours)} tone={uptimeTone(h.uptime.d30)} />
        </dl>
      </section>
      <section aria-labelledby={`${id}-gaps`}>
        <h3 id={`${id}-gaps`}>{COPY.gapsHeading}</h3>
        {!h.gaps.length ? <p>{COPY.gapsEmpty}</p> : (
          <div class="admin-scroll" role="region" aria-labelledby={`${id}-gaps`} tabIndex={0}>
            <table class="admin-counts">
              <thead><tr><th scope="col">{COPY.hour}</th><th scope="col">{COPY.maxGap}</th></tr></thead>
              <tbody>{h.gaps.map(g => <tr key={g.hour}><th scope="row">{g.hour}:00</th><td>{duration(g.max_gap_s)}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>
      <section aria-labelledby={`${id}-out`}>
        <h3 id={`${id}-out`}>{COPY.outagesHeading}</h3>
        {!h.outages.length ? <p>{COPY.outagesEmpty}</p> : (
          <div class="admin-scroll" role="region" aria-labelledby={`${id}-out`} tabIndex={0}>
            <table class="admin-counts">
              <thead><tr><th scope="col">{COPY.from}</th><th scope="col">{COPY.to}</th><th scope="col">{COPY.hours}</th></tr></thead>
              <tbody>{h.outages.map(o => <tr key={o.from}><th scope="row">{o.from}:00</th><td>{o.to}:59</td><td>{o.hours}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>
      <section aria-labelledby={`${id}-proc`}>
        <h3 id={`${id}-proc`}>{COPY.processorHeading}</h3>
        <dl class="admin-fields">
          <Row label={COPY.processorLast} value={when(h.processor?.last_run_at) || COPY.never} />
          <Row label={COPY.processorAge} value={h.processor ? duration(h.processor.age_s) : '—'} tone={!h.processor || h.processor.age_s > STALE_S ? 'rough' : undefined} />
        </dl>
      </section>
      <section aria-labelledby={`${id}-watch`}>
        <h3 id={`${id}-watch`}>{COPY.watchHeading}</h3>
        <dl class="admin-fields">
          <Row label={COPY.watched} value={h.watch.watched} />
          <Row label={COPY.candidates} value={h.watch.candidates} />
          <Row label={COPY.listenerWatch} value={h.watch.listener ?? '—'} tone={h.watch.listener !== null && h.watch.listener !== h.watch.watched ? 'caution' : undefined} />
        </dl>
      </section>
    </section>
  );
}
