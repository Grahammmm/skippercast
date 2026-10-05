// The admin app's API client and shared shapes (server/routes/admin.ts; TA-W2).
// Same-origin fetches with the session cookie; the browser sends Origin on
// every POST, which requireUser checks.
import {ADMIN_COPY} from '../advisor/copy.ts';

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
  vision: {name: string; configured: boolean; down_until: string | null; last_ok_at: string | null}[];   // TA-V2: configured and last_ok_at
  caps: {day: string; llm: {used: number; limit: number}; vision: {used: number; limit: number}};
  media_jobs: {pending: number};
  reviews: {open: number};
  meta: {configured: boolean; quota_usage: number | null; quota_total: number | null; checked_at: string | null; error: 'unavailable' | null};
  inbox: {enabled: boolean; public_replies: boolean; webhook_ready: boolean};   // TA-S6
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

// ---- TA-S7: post insights (server/advisor/social/insights.ts) ----
export const SOCIAL_COLUMNS = ['views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits'] as const;
export type SocialTotals = Record<typeof SOCIAL_COLUMNS[number], number>;
export type SurfaceStats = SocialTotals & {link_taps: number; day: string; fetched_at: string; notes: string[]};
export interface PostStats {instagram: SurfaceStats | null; facebook: SurfaceStats | null; chats: number}

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
  social: {posts: number; instagram: SocialTotals; facebook: SocialTotals; by_kind: ({kind: string; posts: number; chats: number} & SocialTotals)[];   // TA-S7
    chats_from_posts: number; chats_from_instagram: number; site_visits_per_post: null};
  analytics: {available: boolean; reason: 'not-configured' | 'no-data' | 'error' | null;
    llm: {feature: string; calls: number; input_tokens: number; output_tokens: number}[];
    turns: {count: number; p50_ms: number | null; p95_ms: number | null};
    pages: {event: string; source: string; count: number}[]};
}

// ---- TA-A4: Rules (server/advisor/admin/rules.ts) ----
export interface Rule {
  id: string; region: string; jurisdiction: string; species_key: string; species_label: string;
  size_min_in: number | null; size_max_in: number | null; bag_limit: number | null; bag_notes: string | null;
  season_open: string | null; season_close: string | null; depth_limit_ft: number | null; area_notes: string | null; gear_notes: string | null;
  source_name: string; source_url: string; reviewed_at: string; review_due: string; status: 'active' | 'review' | 'retired';
  updated_by: string; updated_at: string; due: boolean;
}
export interface RulesList {rules: Rule[]; today: string; jurisdictions: string[]; regions: {id: string; jurisdiction: string}[]; species: {key: string; name: string}[]}
export type RuleFields = Partial<Record<'species_label' | 'size_min_in' | 'size_max_in' | 'bag_limit' | 'bag_notes' | 'season_open' | 'season_close' |
  'depth_limit_ft' | 'area_notes' | 'gear_notes' | 'source_name' | 'source_url', string | number | null>>;
export interface NewRule extends RuleFields {jurisdiction: string; region: string; species_key: string}

// ---- TA-S1: social posts (server/advisor/admin/posts.ts postView) ----
export interface PostMedia {id: string; kind: string; has_person: boolean | null; publish_state: string; credit: string | null; review_open: boolean; thumb: string | null; original: string | null}
export interface Post {
  id: string; kind: string; region: string; status: string; caption: string; caption_stats: {length: number; hashtags: number; mentions: number};
  targets: string[]; allowed_targets: string[]; collaborators: string[]; user_tags: {username: string; x: number; y: number}[];
  scheduled_for: string | null; error: string | null; created_by: string; approved_by: string | null; approved_at: string | null; posted_at: string | null;
  created_at: string; updated_at: string; boat: {id: string; name: string; slug: string; status: string; instagram: string | null} | null;
  media: PostMedia[]; review_id: string | null; hold: string | null;
  ig_media_id: string | null; fb_post_id: string | null; fb_story_id: string | null; collab_status: string | null;   // TA-S2
  graphics?: string[];   // TA-S4: admin preview URLs of a daily card, roundup slides or Story card
  stats?: PostStats | null;   // TA-S7: a posted post's latest insights and the chats it started
}
/** GET /api/admin/posts/calendar (TA-S4, server/advisor/social/calendar.ts calendarWeek). */
export interface WeekPost {id: string; kind: string; region: string; status: string; at: string; scheduled_for: string | null; posted_at: string | null; boat: string | null; summary: string}
export interface WeekSlot {slot: string; kind: string; region: string; time: string; at: string; capacity: number; posts: WeekPost[]; empty: boolean; past: boolean}
export interface WeekDay {date: string; weekday: string; slots: WeekSlot[]; others: WeekPost[]}
export interface CalendarWeek {tz: string; start: string; end: string; days: WeekDay[]}
/** POST /api/admin/posts/:id/{publish,schedule,retry} (TA-S2). */
export interface PostActionResult {post: Post; outcome?: string; error?: string}
export interface PostsPage {posts: Post[]; next: string | null}
export const POST_STATUSES: readonly string[] = ['all', 'draft', 'approved', 'scheduled', 'publishing', 'posted', 'partial', 'failed', 'rejected'];
export const POST_KINDS: readonly string[] = ['photo', 'carousel', 'reel', 'story', 'daily', 'roundup'];
/** The query string for a Posts page. */
export function postsPath(status: string, kind: string, cursor?: string | null): string {
  const q = new URLSearchParams({status: status || 'all'});
  if (kind) q.set('kind', kind);
  if (cursor) q.set('cursor', cursor);
  return `/api/admin/posts?${q}`;
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
export const subscribeWebhooks = (): Promise<{subscribed: boolean; fields: string}> => postJson('/api/admin/meta/subscribe', {});   // TA-S6
export const getPosts = (status: string, kind: string, cursor?: string | null): Promise<PostsPage> => call(postsPath(status, kind, cursor));
export const publishPost = (id: string): Promise<PostActionResult> => postJson(`/api/admin/posts/${encodeURIComponent(id)}/publish`, {});
export const schedulePost = (id: string, scheduledFor: string | null): Promise<PostActionResult> => postJson(`/api/admin/posts/${encodeURIComponent(id)}/schedule`, {scheduled_for: scheduledFor});
export const retryPost = (id: string): Promise<PostActionResult> => postJson(`/api/admin/posts/${encodeURIComponent(id)}/retry`, {});
export const getCalendar = (start: string | null): Promise<CalendarWeek> => call(`/api/admin/posts/calendar${start ? `?start=${encodeURIComponent(start)}` : ''}`);
export function rulesPath(jurisdiction: string, status: string): string {
  const q = new URLSearchParams();
  if (jurisdiction) q.set('jurisdiction', jurisdiction);
  if (status) q.set('status', status);
  const query = q.toString();
  return `/api/admin/rules${query ? `?${query}` : ''}`;
}
export const getRules = (jurisdiction: string, status: string): Promise<RulesList> => call(rulesPath(jurisdiction, status));
export const createRule = (rule: NewRule): Promise<{rule: Rule}> => postJson('/api/admin/rules', rule);
export const editRule = (id: string, fields: RuleFields): Promise<{rule: Rule}> => postJson(`/api/admin/rules/${encodeURIComponent(id)}`, fields);
export const retireRule = (id: string): Promise<{rule: Rule}> => postJson(`/api/admin/rules/${encodeURIComponent(id)}/retire`, {});
/** The admin app's link to a contact (08: reached by id from a review or a boat only). */
export const contactHref = (id: string): string => `#contact/${encodeURIComponent(id)}`;

/** A short local time for an ISO timestamp. */
export const when = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
};

/** TA-V2: a vision provider's Health line: not configured, or skipped until / available, with its last answer. */
export function visionLine(v: Health['vision'][number]): string {
  if (!v.configured) return ADMIN_COPY.providerNotConfigured;
  const state = v.down_until ? ADMIN_COPY.providerDown(when(v.down_until)) : ADMIN_COPY.providerUp;
  return `${state} · ${ADMIN_COPY.providerLastOk(when(v.last_ok_at) || ADMIN_COPY.providerNever)}`;
}

// ---- Charter fleet (/api/admin/fleet/*; charter-fleet design § 12, § 13) ----
/** A fleet admin API path: '/api/admin/fleet/<path>' with the non-empty query values. */
export function fleetPath(path: string, query: Record<string, string | null | undefined> = {}): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value) q.set(key, value);
  const text = q.toString();
  return `/api/admin/fleet/${path}${text ? `?${text}` : ''}`;
}
export const getFleet = <T>(path: string, query?: Record<string, string | null | undefined>): Promise<T> => call(fleetPath(path, query));
export const postFleet = <T>(path: string, data: unknown): Promise<T> => postJson(fleetPath(path), data);
/**
 * Whether the fleet admin is on (CF-31). Every /api/admin/fleet/* path answers 404 while
 * FLEET_ENABLED is off (server/routes/fleet.ts), so the open-review list answering is the flag.
 */
export async function getFleetEnabled(): Promise<boolean> {
  try { await getFleet('reviews', {status: 'open'}); return true; }
  catch (e) { if (e instanceof ApiError && (e.status === 404 || e.status === 401)) return false; throw e; }
}

// ---- CF-31: fleet reviews and vessels (server/fleet/admin/reviews.ts, vessels.ts) ----
export const FLEET_REVIEW_KINDS = ['merge', 'mmsi', 'class', 'fact-conflict', 'change', 'vanished', 'advisor-link', 'scope'] as const;
export type FleetReviewKind = typeof FLEET_REVIEW_KINDS[number];
export const FLEET_REVIEW_STATUSES = ['open', 'decided', 'dismissed', 'all'] as const;
export type FleetAction = 'same-vessel' | 'new-vessel' | 'set-mmsi' | 'reject-mmsi' | 'set-class' | 'set-status' | 'confirm' | 'dismiss';
export const VESSEL_CLASSES = ['six-pack', 'inspected-party', 'long-range'] as const;
export const VESSEL_STATUSES = ['active', 'inactive', 'sold', 'excluded'] as const;
export const PROFILE_STATUSES = ['listed', 'hidden'] as const;
export const MAP_CONSENTS = ['none', 'aggregate', 'named'] as const;
export const WATERS = ['ocean', 'bay', 'delta', 'inland'] as const;
export interface FleetReview {
  id: string; region: string; kind: FleetReviewKind; subject_id: string | null; subject_name?: string | null; subject_slug?: string | null;
  candidate: unknown; proposal: unknown; decision: unknown; score: number | null; status: 'open' | 'decided' | 'dismissed';
  decided_by: string | null; decided_at: string | null; opened_at: string; run_id: string | null; actions?: FleetAction[];
}
export interface FleetDecision {action: FleetAction; vessel_id?: string; mmsi?: string; vessel_class?: string; status?: string; note?: string}
/** A vessel in the list (vessels.ts listVessels). `pinned` is ['*'] when the pin record is unreadable. */
export interface FleetVesselRow {
  id: string; region: string; slug: string; name: string; operator_id: string | null; port_id: string | null; landing_id: string | null;
  vessel_class: string | null; mmsi: string | null; uscg_doc: string | null; status: string; profile_status: string;
  completeness: number | null; last_seen_at: string | null; updated_at: string; ais_watched: boolean; open_reviews: number; pinned: string[];
}
/** A column's pin: who set it and when; true when pinned_json is unreadable (everything is pinned); null when unpinned. */
export type FleetPin = {by: string; at: string; fact_id: string} | true | null;
export interface FleetFact {
  id: string; field: string; value: unknown; source_id: string; source_url: string; method: string; confidence: number; rights: string;
  retrieved_at: string; first_seen_at: string; last_seen_at: string; superseded_at: string | null; superseded_by: string | null; run_id: string | null;
}
/** GET /api/admin/fleet/vessels/:id (vessels.ts vesselDetail). */
export interface FleetVesselDetail {
  vessel: Record<string, unknown> & {id: string; region: string; slug: string; name: string; status: string; profile_status: string;
    map_display_consent: string; removal_requested_at: string | null; completeness: number | null; pinned: string[]};
  fields: Record<string, {value: unknown; pinned: FleetPin; fact_id: string | null}>;
  facts: FleetFact[];
  aliases: {alias: string; alias_norm: string; kind: string; source_url: string | null; first_seen_at: string; last_seen_at: string}[];
  offerings: (Record<string, unknown> & {id: string; name: string; trip_type: string | null; status: string; price_cents: number | null; departs_local: string | null;
    season_from: string | null; season_to: string | null})[];
  changes: {id: string; kind: string; before: unknown; after: unknown; detected_at: string; run_id: string | null; review_id: string | null}[];
  watch: {region: string; mmsi: string; match_method: string; confidence: number | null; status: string; ais_name: string | null; last_seen_at: string | null; positions_30d: number | null}[];
  trips: {id: string; mmsi: string; departed_at: string; returned_at: string | null; local_date: string; status: string; trip_type_inferred: string | null;
    distance_nm: number | null; fishing_min: number | null}[];
  advisor_boats: {id: string; slug: string; name: string; port: string; status: string}[];
  open_reviews: {id: string; kind: FleetReviewKind; score: number | null; opened_at: string}[];
  operator: {id: string; slug: string; name: string; consent_status: string; outreach_status: string} | null;
}
export type FleetFieldValue = string | number | string[] | null;
export interface FleetVesselEdit {fields?: Record<string, FleetFieldValue>; unpin?: string[]; removal_requested?: true}
export interface FleetVesselQuery {region?: string; port?: string; class?: string; status?: string; profile_status?: string; ais?: string; completeness_max?: string}

export const getFleetReviews = (status: string, kind: string, region: string, cursor?: string | null): Promise<{reviews: FleetReview[]; next: string | null}> =>
  getFleet('reviews', {status: status || 'open', kind, region, cursor});
export const decideFleetReview = (id: string, decision: FleetDecision): Promise<{review: FleetReview; repeated?: true}> =>
  postFleet(`reviews/${encodeURIComponent(id)}`, decision);
export const getFleetVessels = (filters: FleetVesselQuery, cursor?: string | null): Promise<{vessels: FleetVesselRow[]; next: string | null}> =>
  getFleet('vessels', {...filters, cursor});
export const getFleetVessel = (id: string): Promise<FleetVesselDetail> => getFleet(`vessels/${encodeURIComponent(id)}`);
export const editFleetVessel = (id: string, edit: FleetVesselEdit): Promise<FleetVesselDetail> => postFleet(`vessels/${encodeURIComponent(id)}`, edit);

/** True when a vessel can appear on public pages (server/fleet/display.ts): active, listed and no removal request (Q15). */
export const vesselIsPublic = (v: {status: string; profile_status: string; removal_requested_at: string | null}): boolean =>
  v.status === 'active' && v.profile_status === 'listed' && !v.removal_requested_at;
/** A source URL as a link target: plain https only (an admin:<id> source is never a link). */
export function httpsUrl(url: unknown): string | null {
  if (typeof url !== 'string' || !url.startsWith('https://')) return null;
  try { return new URL(url).protocol === 'https:' ? url : null; } catch { return null; }
}
/** A JSON value as one short line for the admin's tables. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value) && value.every(v => v === null || typeof v !== 'object')) return value.map(v => String(v)).join(', ');
  return JSON.stringify(value);
}
// ---- end CF-31 ----
