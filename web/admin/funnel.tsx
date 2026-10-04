// The admin Funnel view (08 § Admin, Funnel; OP-5; TA-W4): GET /api/admin/funnel
// for the last 7 or 30 days. Plain tables and small inline SVG bars (no chart
// library); every number is also in a table cell, so the bars are decoration
// with a text label. Counts only: the API carries no contact, message or boat id.
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {getFunnel} from './api.ts';
import type {Funnel} from './api.ts';

const BAR_W = 6, BAR_GAP = 2, SPARK_H = 32;

/** Bars for a series (one per value), scaled to the largest; an empty series draws nothing. */
export function Spark({values, label}: {values: number[]; label: string}) {
  const max = Math.max(1, ...values), width = values.length * (BAR_W + BAR_GAP);
  return (
    <svg class="admin-spark" role="img" aria-label={label} width={width} height={SPARK_H} viewBox={`0 0 ${width} ${SPARK_H}`}>
      {values.map((v, i) => {
        const h = v ? Math.max(2, Math.round((v / max) * SPARK_H)) : 0;
        return <rect key={i} x={i * (BAR_W + BAR_GAP)} y={SPARK_H - h} width={BAR_W} height={h} />;
      })}
    </svg>
  );
}

/** One horizontal bar for a table row, proportional to `max`; hidden from assistive tech (the cell holds the number). */
function Bar({value, max}: {value: number; max: number}) {
  const w = max ? Math.round((value / max) * 120) : 0;
  return <svg class="admin-bar" aria-hidden="true" width={120} height={10} viewBox="0 0 120 10"><rect x={0} y={0} width={w} height={10} /></svg>;
}

function Stat({label, value}: {label: string; value: string | number}) {
  return <><dt>{label}</dt><dd>{value}</dd></>;
}

export function FunnelView() {
  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<Funnel | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');

  useEffect(() => {
    let live = true;
    setState('loading');
    getFunnel(days).then(f => { if (live) { setData(f); setState('ready'); } }).catch(() => { if (live) setState('failed'); });
    return () => { live = false; };
  }, [days]);

  return (
    <section class="admin-view" aria-labelledby="funnel-heading">
      <h1 id="funnel-heading" tabIndex={-1}>{COPY.funnelHeading}</h1>
      <div class="admin-filters">
        <label>
          <span>{COPY.funnelWindow}</span>
          <select value={String(days)} onChange={e => setDays((e.currentTarget as HTMLSelectElement).value === '30' ? 30 : 7)}>
            <option value="7">{COPY.funnelDays(7)}</option>
            <option value="30">{COPY.funnelDays(30)}</option>
          </select>
        </label>
      </div>
      <p class="admin-hint">{COPY.funnelNote}</p>
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'failed' || !data ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : <FunnelBody f={data} />}
    </section>
  );
}

function FunnelBody({f}: {f: Funnel}) {
  const intentMax = Math.max(0, ...f.messages.by_intent.map(i => i.count));
  const llmMax = Math.max(0, ...f.analytics.llm.map(l => l.calls));
  const pageMax = Math.max(0, ...f.analytics.pages.map(p => p.count));
  return (
    <div class="admin-funnel">
      <section aria-labelledby="f-contacts">
        <h2 id="f-contacts">{COPY.newContacts}</h2>
        <p class="admin-funnel-total"><strong>{f.contacts.new}</strong> <Spark values={f.contacts.by_day.map(d => d.total)} label={COPY.trendLabel(COPY.newContacts)} /></p>
        <div class="admin-scroll" role="region" aria-label={COPY.contactsTable} tabIndex={0}>
          <table class="admin-counts">
            <thead><tr><th scope="col">{COPY.day}</th><th scope="col">{COPY.total}</th>{f.contacts.sources.map(s => <th key={s} scope="col">{s}</th>)}</tr></thead>
            <tbody>
              {[...f.contacts.by_day].reverse().map(d => (
                <tr key={d.day}><th scope="row">{d.day}</th><td>{d.total}</td>{f.contacts.sources.map(s => <td key={s}>{d.by_source[s] ?? 0}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="f-engagement">
        <h2 id="f-engagement">{COPY.engagement}</h2>
        <dl class="admin-fields">
          <Stat label={COPY.inbound} value={f.messages.inbound} />
          <Stat label={COPY.repliesSent} value={f.replies.outbound} />
          <Stat label={COPY.repliesPerContact} value={COPY.decimal(f.replies.per_contact)} />
          <Stat label={COPY.returnRate} value={`${COPY.percent(f.return_rate.rate)} (${f.return_rate.returning} / ${f.return_rate.active})`} />
        </dl>
      </section>

      <section aria-labelledby="f-intents">
        <h2 id="f-intents">{COPY.messagesByIntent}</h2>
        {f.messages.by_intent.length === 0 ? <p>{COPY.none}</p> : (
          <table class="admin-counts">
            <thead><tr><th scope="col">{COPY.intent}</th><th scope="col">{COPY.count}</th><th scope="col"><span class="admin-visually-hidden">{COPY.trend}</span></th></tr></thead>
            <tbody>{f.messages.by_intent.map(i => <tr key={i.intent}><th scope="row">{i.intent}</th><td>{i.count}</td><td><Bar value={i.count} max={intentMax} /></td></tr>)}</tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="f-boats">
        <h2 id="f-boats">{COPY.boatsSection}</h2>
        <dl class="admin-fields">
          <Stat label={COPY.boatsVerified} value={f.boats.verified} />
          <Stat label={COPY.boatsVerifiedTotal} value={f.boats.verified_total} />
          <Stat label={COPY.boatsPending} value={f.boats.pending} />
          <Stat label={COPY.reportsPublished} value={f.boats.reports_published} />
          <Stat label={COPY.reportsPerBoat} value={COPY.decimal(f.boats.reports_per_boat)} />
          <Stat label={COPY.photosSubmitted} value={f.photos.submitted} />
          <Stat label={COPY.photosApproved} value={f.photos.approved} />
          <Stat label={COPY.consentRate} value={`${COPY.percent(f.consent.rate)} (${f.consent.given} / ${f.consent.boats})`} />
        </dl>
      </section>

      <section aria-labelledby="f-analytics">
        <h2 id="f-analytics">{COPY.analyticsHeading}</h2>
        {!f.analytics.available ? <p class="admin-muted">{COPY.analyticsMissing[f.analytics.reason ?? 'error']}</p> : (
          <>
            <h3>{COPY.turnLatency}</h3>
            <dl class="admin-fields">
              <Stat label={COPY.turns} value={f.analytics.turns.count} />
              <Stat label={COPY.p50} value={COPY.ms(f.analytics.turns.p50_ms)} />
              <Stat label={COPY.p95} value={COPY.ms(f.analytics.turns.p95_ms)} />
            </dl>
            <h3>{COPY.llmByFeature}</h3>
            {f.analytics.llm.length === 0 ? <p>{COPY.none}</p> : (
              <div class="admin-scroll" role="region" aria-label={COPY.llmByFeature} tabIndex={0}>
                <table class="admin-counts">
                  <thead><tr><th scope="col">{COPY.feature}</th><th scope="col">{COPY.calls}</th><th scope="col">{COPY.inputTokens}</th><th scope="col">{COPY.outputTokens}</th><th scope="col"><span class="admin-visually-hidden">{COPY.trend}</span></th></tr></thead>
                  <tbody>{f.analytics.llm.map(l => (
                    <tr key={l.feature}><th scope="row">{l.feature}</th><td>{l.calls}</td><td>{l.input_tokens}</td><td>{l.output_tokens}</td><td><Bar value={l.calls} max={llmMax} /></td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <h3>{COPY.pageTraffic}</h3>
            {f.analytics.pages.length === 0 ? <p>{COPY.none}</p> : (
              <table class="admin-counts">
                <thead><tr><th scope="col">{COPY.event}</th><th scope="col">{COPY.visitSource}</th><th scope="col">{COPY.count}</th><th scope="col"><span class="admin-visually-hidden">{COPY.trend}</span></th></tr></thead>
                <tbody>{f.analytics.pages.map(p => (
                  <tr key={`${p.event}:${p.source}`}>
                    <th scope="row">{COPY.pageEvents[p.event as keyof typeof COPY.pageEvents] ?? p.event}</th>
                    <td>{COPY.visitSources[p.source as keyof typeof COPY.visitSources] ?? p.source}</td><td>{p.count}</td><td><Bar value={p.count} max={pageMax} /></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </>
        )}
      </section>
    </div>
  );
}
