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
  media_jobs: {pending: number};
  reviews: {open: number};
  meta: null;
}

// ---- TA-W3: Skippers and Contacts (server/advisor/admin/skippers.ts) ----
export interface ContactRef {id: string; channel: string; language: string; display_name: string | null; role: string; status: string}
export interface Crew {contact_id: string; display_name: string | null; channel: string; status: string; added_at: string}
export interface Boat {
  id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null;
  booking_url: string | null; phone_public: string | null; status: 'pending' | 'verified' | 'rejected'; verified_at: string | null; created_at: string;
  owner: ContactRef | null; last_report_date: string | null; reports_30d: number; posts: number;
  consent: 'given' | 'revoked' | 'not given'; consent_photos_at: string | null; consent_revoked_at: string | null;
  consent_note: {note: string; at: string} | null; crew: Crew[]; review_open: boolean;
}
export type BoatFields = Partial<Record<'name' | 'port' | 'landing' | 'instagram' | 'booking_url' | 'phone_public', string | null>>;
export interface BoatEdit {fields?: BoatFields; status?: 'verified' | 'rejected'; consent_note?: string | null}
export interface BoatResult {boat: Boat; sends?: number; held?: string}
export interface InviteResult {contact_id: string; sends: number; created: boolean}
export interface ContactDetail {
  contact: ContactRef & {source: string | null; home_port: string | null; created_at: string; last_seen_at: string; messages_today: number; blocked_from: string | null};
  boats: {id: string; name: string; slug: string; status: string; relation: 'owner' | 'crew'}[];
  messages: {direction: 'in' | 'out'; body: string | null; intent: string | null; status: string; created_at: string; team: boolean; media: number}[];
  export: string;
}

// ---- TA-W4: the Funnel (server/advisor/admin/funnel.ts) ----
export interface Funnel {
  days: 7 | 30; since: string; generated_at: string;
  contacts: {new: number; sources: string[]; by_day: {day: string; total: number; by_source: Record<string, number>}[]};
  messages: {inbound: number; by_intent: {intent: string; count: number}[]};
  replies: {outbound: number; contacts: number; per_contact: number | null};
  return_rate: {active: number; returning: number; rate: number | null};
  boats: {verified: number; verified_total: number; pending: number; reports_published: number; boats_reporting: number; reports_per_boat: number | null};
  photos: {submitted: number; approved: number};
  consent: {boats: number; given: number; rate: number | null};
  analytics: {available: boolean; reason: 'not-configured' | 'no-data' | 'error' | null;
    llm: {feature: string; calls: number; input_tokens: number; output_tokens: number}[];
    turns: {count: number; p50_ms: number | null; p95_ms: number | null};
    pages: {event: string; source: string; count: number}[]};
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

const postJson = <T>(path: string, data: unknown): Promise<T> =>
  call(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});

export const getBoats = (): Promise<{boats: Boat[]}> => call('/api/admin/boats');
export const editBoat = (id: string, edit: BoatEdit): Promise<BoatResult> => postJson(`/api/admin/boats/${encodeURIComponent(id)}`, edit);
export const removeCrew = (boat: string, contact: string): Promise<{boat: Boat}> =>
  postJson(`/api/admin/boats/${encodeURIComponent(boat)}/crew/${encodeURIComponent(contact)}/remove`, {});
export const invite = (phone: string, boatName: string, language: 'en' | 'es'): Promise<InviteResult> =>
  postJson('/api/admin/boats/invite', {phone, ...(boatName.trim() ? {boat_name: boatName.trim()} : {}), language});
export const getContact = (id: string): Promise<ContactDetail> => call(`/api/admin/contacts/${encodeURIComponent(id)}`);
export const setBlocked = (id: string, blocked: boolean): Promise<{status: string}> => postJson(`/api/admin/contacts/${encodeURIComponent(id)}/block`, {blocked});
export const getFunnel = (days: 7 | 30): Promise<Funnel> => call(`/api/admin/funnel?days=${days}`);
/** The admin app's link to a contact (08: reached by id from a review or a boat only). */
export const contactHref = (id: string): string => `#contact/${encodeURIComponent(id)}`;

/** A short local time for an ISO timestamp. */
export const when = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
};
