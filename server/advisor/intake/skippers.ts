// Skipper onboarding (docs/plans/text-advisor/05-skipper-intake.md § Becoming a
// skipper, § Consent, § Crew, § Verification; 04 § stage 2): the registration
// state machine, the photo-consent question, the crew helpers and the
// verified/unverified contract the data tools share.
//
// State lives in job_state under advisor.flow.<contact_id> as JSON
// {flow: 'register' | 'consent', step, draft, asked_at}. The engine never
// writes it: the flow returns a flow_set action and the consumer applies it,
// like every other write (04 § "the engine never touches D1 for writes").
//
//   register  name -> port -> landing -> instagram -> booking, one question per
//             text; "skip" for the three optional ones; a port is matched by
//             catalog name or alias (answers/resolve.ts findPort), else the
//             three nearest ports are offered as a numbered list. On completion:
//             boat_create (the pending boat, the contact becomes its skipper),
//             a skipper review new_skipper (which texts the admin), the
//             completion text and the consent question.
//   consent   the question is pending for 24 h; yes/sí/ok records consent with
//             the message id; anything else declines once and falls through.
//             While consent is not active, a photo from the owner re-asks no
//             sooner than 7 days after the last ask.
//   revoke    "stop posting my photos" / "revoke" / "no publiques" at any time.
//
// A register flow older than 24 h is abandoned silently (deleted, the message
// goes on to the model). Three invalid answers to one question cancel it.
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import {t} from '../strings.ts';
import type {StringKey} from '../strings.ts';
import {resolveLinks, portRegion, portName, PORT_IDS} from '../links.ts';
import {findPort, fold} from '../answers/resolve.ts';
import {e164} from '../contacts.ts';
import {sha256} from '../ids.ts';
import type {Action, AdvisorContactRow, AdvisorSettings, EngineResult, FlowState, Language, NewBoat} from '../types.ts';
import type {Flow, FlowContext} from '../engine.ts';

export const FLOW_KEY_PREFIX = 'advisor.flow.';
export const FLOW_MAX_AGE_MS = 24 * 3600000;          // a pending question older than this is abandoned
export const CONSENT_REASK_MS = 7 * 24 * 3600000;     // the consent question at most once per 7 days
export const MAX_TRIES = 3;                           // invalid answers to one question before the flow is cancelled
export const NAME_MAX = 60, LANDING_MAX = 60, SLUG_MAX = 40, URL_MAX = 300;
export const VERIFIED = 'verified';

/** The job_state key of a contact's flow. */
export const flowKey = (contactId: string): string => FLOW_KEY_PREFIX + contactId;

export const REGISTER_STEPS = ['name', 'port', 'landing', 'instagram', 'booking'] as const;
export type RegisterStep = typeof REGISTER_STEPS[number];
const OPTIONAL: ReadonlySet<RegisterStep> = new Set(['landing', 'instagram', 'booking']);
const QUESTION: Record<RegisterStep, StringKey> = {name: 'register_ask_name', port: 'register_ask_port', landing: 'register_ask_landing', instagram: 'register_ask_instagram', booking: 'register_ask_booking'};
const INVALID: Record<RegisterStep, StringKey> = {name: 'register_bad_name', port: 'register_bad_port', landing: 'register_bad_landing', instagram: 'register_bad_instagram', booking: 'register_bad_booking'};

// ---- parsing (02 § advisor_boats column notes) -----------------------------------------

/** Lower-cased, trimmed, inner spaces collapsed, trailing . ! removed. */
const norm = (text: string): string => String(text ?? '').normalize('NFC').trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.!¡]+$/u, '').replace(/^¡/u, '').trim();

export const SKIP_WORDS: ReadonlySet<string> = new Set(['skip', 'none', 'no', 'n/a', 'na', 'nope', 'pass', 'no landing', 'no instagram', 'saltar', 'omitir', 'ninguno', 'ninguna', 'nada', 'no tengo', 'no hay', 'paso']);
export const CANCEL_WORDS: ReadonlySet<string> = new Set(['never mind', 'nevermind', 'forget it', 'cancel registration', 'olvídalo', 'olvidalo', 'déjalo', 'dejalo']);
export const YES_WORDS: ReadonlySet<string> = new Set(['yes', 'y', 'yep', 'yeah', 'yup', 'ok', 'okay', 'sure', 'sí', 'si', 'claro', 'dale', 'va', 'de acuerdo']);
export const isSkip = (text: string): boolean => SKIP_WORDS.has(norm(text));
export const isYes = (text: string): boolean => YES_WORDS.has(norm(text));

/** The pre-router's start phrases (04 § stage 2, 05 § Becoming a skipper); the Spanish ones answer in Spanish. */
const START_EN = /\b(?:register (?:my|a|our|the) boat|i'?m the (?:captain|skipper)|i am the (?:captain|skipper))\b/i;
const START_ES = /\b(?:registrar (?:mi|un|nuestro|el) barco|soy el capit[aá]n)\b/i;
/** "I'm the captain of the Rita G" / "soy el capitán del Rita G": the name after of/on/del/de. */
const NAME_AFTER = /\b(?:captain|skipper|capit[aá]n)\s+(?:of|on|del|de)\s+(?:the\s+|el\s+|la\s+)?(.+)$/i;
/** Revoking consent (05 § Consent), and granting it again after declining or revoking. */
const REVOKE = /^(?:revoke|stop posting (?:my )?(?:photos|pictures|pics|videos)|don'?t post (?:my )?(?:photos|pictures|pics)|no publiques(?: mis fotos)?|deja de publicar mis fotos)$/i;
const GRANT = /^(?:post my photos|you can post my photos|publica mis fotos|puedes publicar mis fotos)$/i;

/** Start phrase in this text: the reply language it implies ('es' for a Spanish phrase) and a boat name if one follows. */
export function startPhrase(text: string): {language: Language | null; name: string | null} | null {
  const value = String(text ?? '').trim();
  const es = START_ES.test(value);
  if (!es && !START_EN.test(value)) return null;
  const after = NAME_AFTER.exec(value);
  return {language: es ? 'es' : null, name: after ? parseName(after[1]!) : null};
}

/** A boat name: control characters and surrounding quotes stripped, 1-60 characters, case kept. */
export function parseName(text: string): string | null {
  const v = String(text ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().replace(/^["'“”‘’`]+|["'“”‘’`.!]+$/gu, '').replace(/\s+/g, ' ').trim();
  return v && v.length <= NAME_MAX && !isSkip(v) ? v : null;
}
/** A landing: free text up to 60 characters. */
export function parseLanding(text: string): string | null {
  const v = String(text ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
  return v && v.length <= LANDING_MAX ? v : null;
}
/** An Instagram handle `@?[a-z0-9._]{1,30}`, stored lower-case without the @. */
export function parseInstagram(text: string): string | null {
  const m = /^@?([a-z0-9._]{1,30})$/.exec(String(text ?? '').trim().toLowerCase());
  return m ? m[1]! : null;
}
/** A booking link (https only) or a public phone number (stored as phone_public, never as a contact). */
export function parseBooking(text: string): {booking_url: string | null; phone_public: string | null} | null {
  const v = String(text ?? '').trim();
  if (/^https:\/\/[^\s<>"]+\.[^\s<>"]+$/i.test(v) && v.length <= URL_MAX) {
    try { const url = new URL(v); if (url.protocol === 'https:' && !url.username && !url.password) return {booking_url: url.toString(), phone_public: null}; } catch { /* not a URL */ }
  }
  const phone = e164(v);
  return phone ? {booking_url: null, phone_public: phone} : null;
}

/** A URL slug from a boat name: ASCII, lower-case, hyphens, at most 40 characters ("boat" when nothing is left). */
export function slugify(name: string): string {
  const base = String(name ?? '').normalize('NFD').replace(/\p{M}+/gu, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const cut = base.length > SLUG_MAX ? base.slice(0, SLUG_MAX).replace(/-[^-]*$/, '') || base.slice(0, SLUG_MAX) : base;
  return cut.replace(/-+$/g, '') || 'boat';
}

/** A slug no boat has yet: the name's slug, else with -2, -3, ... (the base shortened to keep 40 characters). */
export async function uniqueSlug(db: D1Database, name: string): Promise<string> {
  const base = slugify(name);
  const taken = new Set((await db.prepare("SELECT slug FROM advisor_boats WHERE slug=? OR slug LIKE ?").bind(base, `${base.slice(0, SLUG_MAX - 3)}%`).all<{slug: string}>()).results.map(r => r.slug));
  if (!taken.has(base)) return base;
  for (let n = 2; n < 1000; n++) {
    const suffix = `-${n}`, slug = base.slice(0, SLUG_MAX - suffix.length).replace(/-+$/, '') + suffix;
    if (!taken.has(slug) && !await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE slug=?').bind(slug).first()) return slug;
  }
  throw Error('no free slug');
}

// ---- ports -------------------------------------------------------------------------------

const PORT_POINTS = ports.ports.map(p => ({id: p.id, region: p.region, lat: p.match[0]!, lon: p.match[1]!}));
const km = (a: {lat: number; lon: number}, b: {lat: number; lon: number}): number => {
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
};
/**
 * The three ports nearest the contact (05: "on no match list the three nearest
 * ports"): measured from the contact's home port, else from the first port of
 * ADVISOR_REGION_DEFAULT. The reference port comes first.
 */
export function nearestPorts(contact: Pick<AdvisorContactRow, 'home_port'>, settings: Pick<AdvisorSettings, 'regionDefault'>, n = 3): string[] {
  const from = PORT_POINTS.find(p => p.id === contact.home_port) ?? PORT_POINTS.find(p => p.region === settings.regionDefault) ?? PORT_POINTS[0]!;
  return [...PORT_POINTS].sort((a, b) => km(from, a) - km(from, b) || a.id.localeCompare(b.id)).slice(0, n).map(p => p.id);
}
/** A port answer: a number from the offered list, a catalog name or alias, or null. */
export function parsePort(text: string, options: readonly string[] = []): string | null {
  const v = norm(text);
  const pick = /^(?:#\s*)?([1-9])\)?$/.exec(v);
  if (pick) return options[Number(pick[1]) - 1] ?? null;
  const found = findPort(text);
  if (found) return found;
  const id = fold(text).replace(/ /g, '-');
  return PORT_IDS.has(id) ? id : null;
}

// ---- boats, the verified contract (05 § Verification) ------------------------------------

export interface BoatRow {
  id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null;
  booking_url: string | null; phone_public: string | null; owner_contact_id: string | null; status: string;
  verified_at: string | null; consent_photos_at: string | null; consent_message_id: string | null; consent_revoked_at: string | null; created_at: string;
  auto_publish: number; clean_reports: number;   // TA-I2 (SC-5)
}
export interface ContactBoat extends BoatRow {relation: 'owner' | 'crew'}

/** The boats a contact posts for: the ones it owns, then the one it is active crew on. */
export async function boatsForContact(db: D1Database, contactId: string): Promise<ContactBoat[]> {
  const rows = (await db.prepare(`SELECT b.*, CASE WHEN b.owner_contact_id=? THEN 'owner' ELSE 'crew' END AS relation FROM advisor_boats b
      WHERE b.owner_contact_id=? OR b.id IN (SELECT boat_id FROM advisor_crew WHERE contact_id=? AND removed_at IS NULL)
      ORDER BY relation DESC, b.created_at`).bind(contactId, contactId, contactId).all<ContactBoat>()).results;
  return rows;
}
/** The boat a skipper owns (null for anyone else). */
export async function ownedBoat(db: D1Database, contact: Pick<AdvisorContactRow, 'id' | 'boat_id'>): Promise<BoatRow | null> {
  if (!contact.boat_id) return null;
  return db.prepare('SELECT * FROM advisor_boats WHERE id=? AND owner_contact_id=?').bind(contact.boat_id, contact.id).first<BoatRow>();
}

/** True for a verified boat (05 § Verification): only these are named by the tools and listed by get_trips. */
export const isVerified = (status: string | null | undefined): boolean => status === VERIFIED;

/**
 * How a data tool shows a boat (05 § Verification, 06 § freshness): a
 * verified boat by name with its page link; an unverified one as "a boat",
 * no name, no link. Reports carry `verified` frozen at publish time.
 */
export function publicBoat(boat: {name: string; slug: string; verified: boolean}): {boat: string; verified: boolean; boat_link?: string} {
  return boat.verified ? {boat: boat.name, verified: true, boat_link: `{{link:boat:${boat.slug}}}`} : {boat: 'a boat', verified: false};
}

/** Photo consent is active: given, and not revoked since (05 § Consent). */
export function consentActive(boat: Pick<BoatRow, 'consent_photos_at' | 'consent_revoked_at'>): boolean {
  return Boolean(boat.consent_photos_at) && (!boat.consent_revoked_at || boat.consent_revoked_at < boat.consent_photos_at!);
}
/** The consent state for the contact brief. */
export const consentState = (boat: Pick<BoatRow, 'consent_photos_at' | 'consent_revoked_at'>): 'given' | 'revoked' | 'not given' =>
  consentActive(boat) ? 'given' : boat.consent_revoked_at ? 'revoked' : 'not given';

// ---- the flow state -------------------------------------------------------------------------

/** The stored flow for a contact, or null (unparseable rows count as none). */
export async function readFlow(db: D1Database, contactId: string): Promise<FlowState | null> {
  const row = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(flowKey(contactId)).first<{value: string}>();
  if (!row) return null;
  try {
    const v = JSON.parse(row.value);
    return v && (v.flow === 'register' || v.flow === 'consent') && typeof v.step === 'string' && typeof v.asked_at === 'string' && v.draft && typeof v.draft === 'object' ? v as FlowState : null;
  } catch { return null; }
}
const age = (state: FlowState, now: number): number => now - Date.parse(state.asked_at);

/** The next register step without an answer (a skipped field counts as answered), or null when complete. */
export function nextStep(draft: FlowState['draft']): RegisterStep | null {
  return REGISTER_STEPS.find(step => !Object.hasOwn(draft, step === 'booking' ? 'booking_url' : step)) ?? null;
}

// ---- texts ---------------------------------------------------------------------------------

const say = (settings: AdvisorSettings, language: Language, key: StringKey, vars: Record<string, string | number> = {}): Action =>
  ({type: 'send_text', text: resolveLinks(t(language, key, vars), settings.publicBase).text});
const portList = (ids: readonly string[]): string => ids.map((id, i) => `${i + 1}) ${portName(id) ?? id}`).join(', ');

/** The question for a step, with the numbered list for a port that did not match. */
export function question(settings: AdvisorSettings, language: Language, step: RegisterStep): Action { return say(settings, language, QUESTION[step]); }

const STRING = (v: unknown): string | null => typeof v === 'string' ? v : null;

/**
 * The completion of a registration: boat_create, the new_skipper review (the
 * consumer texts the admin), the completion text, the consent question and the
 * consent flow. `boatId` is derived from the message, so a retried message
 * creates the same boat.
 */
export async function completeRegistration(args: {db: D1Database; settings: AdvisorSettings; contact: AdvisorContactRow; messageId: string; draft: FlowState['draft']; language: Language; now: number}): Promise<Action[]> {
  const {db, settings, draft, language} = args;
  const name = STRING(draft.name)!, port = STRING(draft.port)!;
  const id = (await sha256(`boat:${args.messageId}`)).slice(0, 32);
  // A retried message re-runs this after the boat may already exist: keep its slug.
  const existing = await db.prepare('SELECT slug FROM advisor_boats WHERE id=?').bind(id).first<{slug: string}>();
  const boat: NewBoat = {
    id, slug: existing?.slug ?? await uniqueSlug(db, name), name, port, region: portRegion(port) ?? settings.regionDefault,
    landing: STRING(draft.landing), instagram: STRING(draft.instagram), booking_url: STRING(draft.booking_url), phone_public: STRING(draft.phone_public),
  };
  return [
    {type: 'boat_create', boat},
    // A whole registration in the other language counts as the switch FC-6 waits two messages for.
    ...(args.contact.language !== language ? [{type: 'contact_update' as const, fields: {language}}] : []),
    {type: 'review_open', kind: 'skipper', refId: boat.id, reason: 'new_skipper'},
    say(settings, language, 'register_done', {name, slug: boat.slug}),
    say(settings, language, 'consent_ask', {name}),
    {type: 'flow_set', state: {flow: 'consent', step: 'asked', draft: {boat_id: boat.id, lang: language}, asked_at: new Date(args.now).toISOString()}},
  ];
}

/** Answer one register step. Returns the actions and intent for the turn. */
async function registerStep(f: FlowContext, state: FlowState): Promise<EngineResult> {
  const language: Language = state.draft.lang === 'es' ? 'es' : state.draft.lang === 'en' ? 'en' : f.language;
  const step = (REGISTER_STEPS as readonly string[]).includes(state.step) ? state.step as RegisterStep : nextStep(state.draft) ?? 'name';
  const draft = {...state.draft};
  const text = f.text;
  let ok = false;
  if (OPTIONAL.has(step) && isSkip(text)) {
    if (step === 'booking') { draft.booking_url = null; draft.phone_public = null; } else draft[step] = null;
    ok = true;
  } else if (step === 'name') {
    const v = parseName(text); if (v) { draft.name = v; ok = true; }
  } else if (step === 'port') {
    const options = Array.isArray(draft.options) ? draft.options : [];
    const v = parsePort(text, options); if (v) { draft.port = v; delete draft.options; ok = true; }
  } else if (step === 'landing') {
    const v = parseLanding(text); if (v) { draft.landing = v; ok = true; }
  } else if (step === 'instagram') {
    const v = parseInstagram(text); if (v) { draft.instagram = v; ok = true; }
  } else {
    const v = parseBooking(text); if (v) { draft.booking_url = v.booking_url; draft.phone_public = v.phone_public; ok = true; }
  }
  const at = new Date(f.now).toISOString();
  if (!ok) {
    const tries = (state.tries ?? 0) + 1;
    if (tries >= MAX_TRIES) return {actions: [{type: 'flow_set', state: null}, say(f.settings, language, 'register_cancelled')], intent: 'skipper.register.cancelled'};
    if (step === 'port') {
      const options = nearestPorts(f.contact, f.settings);
      draft.options = options;
      return {actions: [say(f.settings, language, 'register_bad_port', {options: portList(options)}), {type: 'flow_set', state: {...state, step, draft, asked_at: at, tries}}],
        intent: 'skipper.register.port.invalid'};
    }
    return {actions: [say(f.settings, language, INVALID[step]), question(f.settings, language, step), {type: 'flow_set', state: {...state, step, draft, asked_at: at, tries}}],
      intent: `skipper.register.${step}.invalid`};
  }
  const next = nextStep(draft);
  if (!next) {
    const actions = await completeRegistration({db: f.db, settings: f.settings, contact: f.contact, messageId: f.message.id, draft, language, now: f.now});
    return {actions, intent: 'skipper.register.done'};
  }
  return {actions: [question(f.settings, language, next), {type: 'flow_set', state: {flow: 'register', step: next, draft, asked_at: at}}], intent: `skipper.register.${step}`};
}

/**
 * Start a registration with whatever is already known (the pre-router's name,
 * or the fields register_boat validated). Asks the first missing question, or
 * completes at once when nothing is missing.
 */
export async function startRegistration(args: {db: D1Database; settings: AdvisorSettings; contact: AdvisorContactRow; messageId: string; language: Language; now: number;
  draft?: FlowState['draft']; intro?: boolean}): Promise<{actions: Action[]; intent: string}> {
  const draft: FlowState['draft'] = {lang: args.language, ...(args.draft ?? {})};
  const next = nextStep(draft);
  if (!next) return {actions: await completeRegistration({...args, draft}), intent: 'skipper.register.done'};
  const ask = t(args.language, QUESTION[next]);
  const text = args.intro === false ? ask : `${t(args.language, 'register_intro')} ${ask}`;
  return {actions: [{type: 'send_text', text: resolveLinks(text, args.settings.publicBase).text},
    {type: 'flow_set', state: {flow: 'register', step: next, draft, asked_at: new Date(args.now).toISOString()}}], intent: 'skipper.register.start'};
}

/** Why this contact cannot register a boat now, as a reply, or null. */
export async function registrationBlocked(db: D1Database, settings: AdvisorSettings, contact: AdvisorContactRow, language: Language): Promise<Action | null> {
  const owned = await ownedBoat(db, contact);
  return owned ? say(settings, language, 'register_already', {name: owned.name}) : null;
}

// ---- the Stage 2 flow ---------------------------------------------------------------------

/**
 * TA-I1's Stage 2 flow (04 § stage 2): revoke and re-grant, a pending register
 * step, a pending consent answer, the pre-router's start phrases, and the
 * 7-day consent re-ask on a photo. Returns null to fall through; actions that
 * must happen either way (abandoning a stale flow, the decline note, a re-ask)
 * go to `f.carry`, which the engine appends to whatever answers the turn.
 */
export async function skipperFlow(f: FlowContext): Promise<EngineResult | null> {
  const web = !f.contact.phone_enc && Boolean(f.contact.web_session);
  if (web) return null;
  let state = await readFlow(f.db, f.contact.id);
  const fresh = state ? age(state, f.now) <= FLOW_MAX_AGE_MS : false;
  if (state?.flow === 'register' && !fresh) { f.carry.push({type: 'flow_set', state: null}); state = null; }

  // A start phrase restarts registration, even mid-flow.
  const start = f.text ? startPhrase(f.text) : null;
  if (start) {
    const language = start.language ?? f.language;
    const blocked = await registrationBlocked(f.db, f.settings, f.contact, language);
    if (blocked) return {actions: [blocked], intent: 'skipper.register.exists'};
    return startRegistration({db: f.db, settings: f.settings, contact: f.contact, messageId: f.message.id, language, now: f.now, draft: start.name ? {name: start.name} : {}});
  }

  if (state?.flow === 'register' && f.text) {
    if (CANCEL_WORDS.has(norm(f.text))) return {actions: [{type: 'flow_set', state: null}, say(f.settings, state.draft.lang === 'es' ? 'es' : f.language, 'register_cancelled')], intent: 'skipper.register.cancelled'};
    return registerStep(f, state);
  }

  // Consent belongs to the boat's owner.
  const boat = await ownedBoat(f.db, f.contact);
  if (!boat) {
    if (f.text && (REVOKE.test(norm(f.text)) || GRANT.test(norm(f.text))) && f.contact.boat_id) return {actions: [say(f.settings, f.language, 'owner_only')], intent: 'consent.not_owner'};
    return null;
  }
  const words = norm(f.text);
  if (words && REVOKE.test(words)) {
    return {actions: [{type: 'consent', boatId: boat.id, decision: 'revoke'}, {type: 'post_revoke', boatId: boat.id},
      {type: 'flow_set', state: {flow: 'consent', step: 'revoked', draft: {boat_id: boat.id}, asked_at: new Date(f.now).toISOString()}}, say(f.settings, f.language, 'consent_revoked')], intent: 'consent.revoke'};
  }
  if (words && GRANT.test(words)) {
    return {actions: [{type: 'consent', boatId: boat.id, decision: 'yes'}, {type: 'flow_set', state: null}, say(f.settings, f.language, 'consent_yes', {name: boat.name})], intent: 'consent.yes'};
  }
  if (state?.flow === 'consent' && state.step === 'asked' && fresh && !consentActive(boat)) {
    const language: Language = state.draft.lang === 'es' ? 'es' : f.language;
    if (f.text && isYes(f.text)) {
      return {actions: [{type: 'consent', boatId: boat.id, decision: 'yes'}, {type: 'flow_set', state: null}, say(f.settings, language, 'consent_yes', {name: boat.name})], intent: 'consent.yes'};
    }
    // Any other reply: consent stays null, said once; the message itself goes on (a question, a photo).
    f.carry.push({type: 'flow_set', state: {...state, step: 'declined'}}, say(f.settings, language, 'consent_declined'));
    if (f.text && /^(?:no|nope|nah|no thanks|not now|later|no gracias|ahora no|después|despues)$/.test(words)) {
      const carried = f.carry.splice(0);
      return {actions: carried, intent: 'consent.declined'};
    }
    return null;
  }
  // The 7-day re-ask: a photo from the owner while consent is not active.
  if (f.media.length && !consentActive(boat)) {
    const last = state?.flow === 'consent' ? Date.parse(state.asked_at) : Date.parse(boat.created_at);
    if (!(f.now - last < CONSENT_REASK_MS)) {
      f.carry.push(say(f.settings, f.language, 'consent_ask', {name: boat.name}),
        {type: 'flow_set', state: {flow: 'consent', step: 'asked', draft: {boat_id: boat.id, lang: f.language}, asked_at: new Date(f.now).toISOString()}});
    }
  }
  return null;
}

/** The flows TA-I1 registers in engine.ts STAGE_TWO_FLOWS. */
export const SKIPPER_FLOWS: readonly Flow[] = [{name: 'skipper', run: skipperFlow}];
