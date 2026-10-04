// The admin Health view (08 § Admin, Health; TA-W2): relay state, the message
// queue, vision providers, today's caps and the media job, from
// GET /api/admin/health. Meta's token and quota arrive with TA-S0.
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {when} from './api.ts';
import type {Health} from './api.ts';

function Row({label, value, tone}: {label: string; value: string | number; tone?: 'go' | 'rough' | 'caution'}) {
  return <><dt>{label}</dt><dd class={tone ? `is-${tone}` : undefined}>{value}</dd></>;
}

export function HealthView({health, failed, onRefresh}: {health: Health | null; failed: boolean; onRefresh: () => void}) {
  return (
    <section class="admin-view" aria-labelledby="health-heading">
      <h1 id="health-heading" tabIndex={-1}>{COPY.healthHeading}</h1>
      <p class="admin-meta">
        {health ? COPY.checkedAt(when(health.checked_at)) : ''}{' '}
        <button type="button" class="admin-button" onClick={onRefresh}>{COPY.refresh}</button>
      </p>
      {failed ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : !health ? <p>{COPY.loading}</p> : (
        <div class="admin-health">
          <section aria-labelledby="h-relay">
            <h2 id="h-relay">{COPY.relay}</h2>
            <dl class="admin-fields">
              <Row label={COPY.relayState} value={!health.relay ? COPY.relayUnknown : health.relay.state === 'up' ? COPY.relayUp : COPY.relayDownWord}
                tone={!health.relay ? undefined : health.relay.state === 'up' ? 'go' : 'rough'} />
              <Row label={COPY.lastOk} value={when(health.relay?.last_ok_at) || COPY.relayNever} />
              <Row label={COPY.failures} value={health.relay?.failures ?? 0} />
              <Row label={COPY.outbound} value={health.channel} />
              <Row label={COPY.advisor} value={health.enabled ? COPY.enabled : COPY.disabled} />
              <Row label={COPY.replies} value={health.replies_enabled ? COPY.enabled : COPY.disabled} tone={health.replies_enabled ? undefined : 'caution'} />
            </dl>
          </section>
          <section aria-labelledby="h-queue">
            <h2 id="h-queue">{COPY.queue}</h2>
            <dl class="admin-fields">
              <Row label={COPY.staleQueued} value={health.queue.stale_queued} tone={health.queue.stale_queued ? 'rough' : 'go'} />
              <Row label={COPY.oldestQueued} value={when(health.queue.oldest_queued_at) || '—'} />
              <Row label={COPY.heldOutbound} value={health.queue.held_outbound} tone={health.queue.held_outbound ? 'caution' : undefined} />
              <Row label={COPY.failedToday} value={health.queue.failed_today} tone={health.queue.failed_today ? 'caution' : undefined} />
              <Row label={COPY.openReviews} value={health.reviews.open} />
            </dl>
          </section>
          <section aria-labelledby="h-vision">
            <h2 id="h-vision">{COPY.vision}</h2>
            <dl class="admin-fields">
              {health.vision.map(v => <Row key={v.name} label={v.name} value={v.down_until ? COPY.providerDown(when(v.down_until)) : COPY.providerUp} tone={v.down_until ? 'rough' : 'go'} />)}
            </dl>
          </section>
          <section aria-labelledby="h-caps">
            <h2 id="h-caps">{COPY.caps}</h2>
            <dl class="admin-fields">
              <Row label={COPY.llmCalls} value={`${health.caps.llm.used} / ${health.caps.llm.limit}`} tone={health.caps.llm.used >= health.caps.llm.limit ? 'rough' : undefined} />
              <Row label={COPY.visionCalls} value={`${health.caps.vision.used} / ${health.caps.vision.limit}`} tone={health.caps.vision.used >= health.caps.vision.limit ? 'rough' : undefined} />
            </dl>
          </section>
          <section aria-labelledby="h-media">
            <h2 id="h-media">{COPY.mediaJobs}</h2>
            <dl class="admin-fields">
              <Row label={COPY.mediaPending} value={health.media_jobs.pending ?? COPY.mediaUnknown} />
            </dl>
          </section>
          <section aria-labelledby="h-meta">
            <h2 id="h-meta">{COPY.meta}</h2>
            <p class="admin-muted">{COPY.metaLater}</p>
          </section>
        </div>
      )}
    </section>
  );
}
