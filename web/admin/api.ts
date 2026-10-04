// The admin app's API client and shared shapes (server/routes/admin.ts; TA-W2).
// Same-origin fetches with the session cookie; the browser sends Origin on
// every POST, which requireUser checks.

export type ReviewKind = 'media' | 'report' | 'post' | 'skipper' | 'conversation' | 'rule';
export type ReviewStatus = 'open' | 'approved' | 'edited' | 'rejected';
export type Decision = 'approve' | 'edit' | 'reject';
export const KINDS: readonly ReviewKind[] = ['media', 'report', 'skipper', 'conversation', 'post', 'rule'];
export const STATUSES: readonly (ReviewStatus | 'all')[] = ['open', 'approved', 'edited', 'rejected', 'all'];

export interface Count {species_key: string; label: string; kept: number | null; released: number | null; uncertain?: boolean}
export interface QueueItem {
  id: string; kind: ReviewKind; ref_id: string; reason: string; status: ReviewStatus; note: string | null; opened_at: string; decided_at: string | null;
  detail: Record<string, any> | null;   // the kind's detail (server/advisor/admin/queue.ts reviewDetail)
}
export interface QueuePage {items: QueueItem[]; next: string | null}
export interface DecisionBody {decision: Decision; patch?: Record<string, unknown>; note?: string; reply?: string}
export interface DecisionResult {review: QueueItem; sends?: number; held?: string; repeated?: boolean}
export interface Health {
  checked_at: string; enabled: boolean; replies_enabled: boolean; channel: string;
  relay: {state: 'up' | 'down'; failures: number; checked_at: string; last_ok_at: string | null} | null;
  queue: {stale_queued: number; oldest_queued_at: string | null; held_outbound: number; failed_today: number};
  vision: {name: string; down_until: string | null}[];
  caps: {day: string; llm: {used: number; limit: number}; vision: {used: number; limit: number}};
  media_jobs: {pending: number | null};
  reviews: {open: number};
  meta: null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {credentials: 'same-origin', ...init});
  const data = await response.json().catch(() => ({})) as {error?: string};
  if (!response.ok) throw new ApiError(response.status, data.error ?? `HTTP ${response.status}`);
  return data as T;
}

/** The query string for a queue page. */
export function queuePath(status: string, kind: string, cursor?: string | null): string {
  const q = new URLSearchParams({status});
  if (kind) q.set('kind', kind);
  if (cursor) q.set('cursor', cursor);
  return `/api/admin/reviews?${q}`;
}

export const getQueue = (status: string, kind: string, cursor?: string | null): Promise<QueuePage> => call(queuePath(status, kind, cursor));
export const getHealth = (): Promise<Health> => call('/api/admin/health');
export const decide = (id: string, body: DecisionBody): Promise<DecisionResult> =>
  call(`/api/admin/reviews/${encodeURIComponent(id)}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

/** A short local time for an ISO timestamp. */
export const when = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
};
