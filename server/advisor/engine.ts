// The Text Advisor engine (docs/plans/text-advisor/04-advisor-engine.md): one
// stored inbound message in, actions out. The consumer (consumer.ts) applies
// the actions; the engine reads D1 but writes only two counters (the daily
// message count on the contact and the LLM caps in request_limits, both
// counted before any reply, like routes/boat.ts), so a crash before the apply
// step leaves nothing half-done.
//
//   Stage 0  guards: replies switched off, blocked, stopped, the daily message cap
//   Stage 1  commands (STOP, START, HELP, forget me / DELETE, send me my data) and language
//   Stage 2  deterministic flows: the text admin fallback, the web phone-link
//            code, the upload link, then the flows later tasks register in
//            STAGE_TWO_FLOWS (TA-I1 registration and consent; TA-I2 report
//            confirmation, count text, corrections and a skipper's media), then
//            the acknowledgement of any other media-only message
//   Stage 3  the model turn: caps, Claude with tools (at most 4 tool rounds, 30 s),
//            then markdown stripped, the rules guard, links, the 3-segment cap
//
// Deviations from 04, each deliberate: STOP, START, HELP and the data commands
// are answered even past the daily cap (carriers require STOP and HELP to
// work); the global LLM cap is checked just before the model call rather than
// before the commands, since only the model call spends it; group chats never
// reach the engine (the adapters drop them, 03 § BlueBubbles "As built"), so
// 04's stage 0 step 4 has nothing to do here.
import type {Env} from '../env.ts';
import type {LlmUsage} from '../analytics.ts';
import {recordLlm} from '../analytics.ts';
import {advisorSettings} from './settings.ts';
import {advisorLog} from './log.ts';
import {localClock, DEFAULT_TZ} from './cron.ts';
import {parseCommand, normalizeCommand, detectLanguage, chooseLanguage} from './intents.ts';
import type {Command} from './intents.ts';
import {t, both} from './strings.ts';
import type {StringKey} from './strings.ts';
import {resolveLinks, portRegion, portName} from './links.ts';
import {resolvePort} from './answers/resolve.ts';
import {systemPrompt, REFUSAL_EN, ABUSE_EN} from './prompts/system.ts';
import {toolsForRole, claudeTools, dispatchTool, isWebOnly} from './tools/index.ts';
import {TOOL_RESULT_MAX} from './tools/tool.ts';
import type {AdvisorTool, ToolContext} from './tools/index.ts';
import {uploadLinkText} from './tools/send_upload_link.ts';
import {contactCardAction} from './tools/send_contact_card.ts';
import {linkKey, takeDaily, LINK_GUESSES_PER_DAY} from './tools/offer_text_link.ts';
import type {PendingLink} from './tools/offer_text_link.ts';
import {sha256} from './ids.ts';
import type {Action, AdvisorContactRow, AdvisorMessageRow, AdvisorSettings, EngineDeps, EngineResult, Handler, Language} from './types.ts';
// TA-I1: skipper registration, consent and crew (05), and the contact brief's boat lines.
import {SKIPPER_FLOWS, boatsForContact, consentState, readFlow, FLOW_MAX_AGE_MS} from './intake/skippers.ts';
// TA-I2: reports (pending confirmation, count text, corrections, the media-only skipper path) and their brief lines.
import {REPORT_FLOWS, reportBrief} from './intake/reports.ts';
// TA-I3: an angler's photos (fish ID, the AC-1 share offer and credit).
import {ANGLER_FLOWS} from './intake/anglers.ts';
// TA-A1: the plain "what's biting" pre-router and the day's answer in the situation brief.
import {DAILY_FLOWS, storedDaily} from './answers/reports.ts';
import {capReply, rulesGuard, stripMarkdown} from './reply.ts';
// TA-A2: the advisory backstop on planning turns.
import {leadsWithAdvisory} from './answers/planning.ts';

export const API = 'https://api.anthropic.com/v1/messages';
export const MAX_TOKENS = 700;
export const TEMPERATURE = 0.3;
export const MAX_TOOL_ROUNDS = 4;
export const MAX_PAUSES = 3;
export const TURN_BUDGET_MS = 30_000;
export const HISTORY_TURNS = 12;
export const HISTORY_MS = 48 * 3600000;
// REPLY_MAX, capReply and the rules guard live in reply.ts (TA-I3, TA-A1: the fish-ID and daily answers use them too); re-exported here.
export {REPLY_MAX, capReply, rulesGuard, statesRuleNumber, stripMarkdown} from './reply.ts';
export const RETRY_DELAY_MS = 2_000;          // one retry on 429/529, as the vision provider
export const FORGET_WINDOW_MS = 24 * 3600000; // DELETE confirms a "forget me" asked within a day
/** Intents whose reply may run past three segments: lists the person asked for (04). */
export const LIST_INTENTS: ReadonlySet<string> = new Set(['trips']);

export interface EngineInput {env: Env; contact: AdvisorContactRow; message: AdvisorMessageRow; now: number; deps?: EngineDeps; signal?: AbortSignal}

/** The pieces a Stage 2 flow sees. */
export interface FlowContext {
  env: Env; contact: AdvisorContactRow; message: AdvisorMessageRow; now: number; deps: EngineDeps; signal?: AbortSignal;
  settings: AdvisorSettings; language: Language; text: string; media: string[]; db: D1Database;
  /**
   * TA-I1: actions a flow needs whatever answers the turn (abandoning a stale
   * flow, the one-time "no social posts" note, a consent re-ask on a photo).
   * They go before a flow's own result, after the languageUpdate on the model
   * path, and after the acknowledgement of a media-only message.
   */
  carry: Action[];
}
/**
 * A deterministic Stage 2 flow (04 § stage 2): returns a result to end the
 * turn, or null to fall through. TA-I1 (registration, consent) and TA-I2
 * (pending report confirmation, corrections, count text) push theirs into
 * STAGE_TWO_FLOWS; they run after the built-in flows below, in order.
 */
export interface Flow {name: string; run(ctx: FlowContext): Promise<EngineResult | null>}
export const STAGE_TWO_FLOWS: Flow[] = [...SKIPPER_FLOWS, ...REPORT_FLOWS, ...ANGLER_FLOWS, ...DAILY_FLOWS];   // TA-I1: registration, consent (intake/skippers.ts); TA-I2: reports (intake/reports.ts); TA-I3: angler photos (intake/anglers.ts); TA-A1: what's biting (answers/reports.ts)

const ADMIN = /^(ok|no)\s+([0-9a-f]{6})$/i;
const SIX_DIGITS = /^\d{6}$/;

/** A JSON array of ids from a media_json column, or []. */
function mediaIds(json: string | null): string[] {
  if (!json) return [];
  try { const v = JSON.parse(json); return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []; } catch { return []; }
}

/** A text action with every {{link:...}} placeholder resolved (at most one link). */
function textAction(settings: AdvisorSettings, text: string): Action {
  return {type: 'send_text', text: resolveLinks(text, settings.publicBase).text};
}

// ---- Stage 0 helpers ---------------------------------------------------------------

/**
 * Inbound messages from this contact today (America/Los_Angeles), this one
 * included, read from advisor_messages so a retried message counts once.
 * advisor_contacts.messages_today/messages_day are set to the same value
 * (02 § advisor_contacts) for the admin view.
 */
export async function messagesToday(db: D1Database, contact: Pick<AdvisorContactRow, 'id'>, now: number): Promise<number> {
  const today = localClock(now, DEFAULT_TZ).date;
  const since = new Date(now - 27 * 3600000).toISOString();
  const rows = (await db.prepare("SELECT created_at FROM advisor_messages WHERE contact_id=? AND direction='in' AND created_at>=? LIMIT 2000").bind(contact.id, since).all<{created_at: string}>()).results;
  const n = rows.filter(r => localClock(Date.parse(r.created_at), DEFAULT_TZ).date === today).length;
  await db.prepare('UPDATE advisor_contacts SET messages_today=?,messages_day=? WHERE id=?').bind(n, today, contact.id).run();
  return n;
}

/** One use of a day counter in request_limits (UTC day, the routes/boat.ts idiom). Returns the new count. */
export async function countToday(db: D1Database, key: string, now: number): Promise<number> {
  const day = Math.floor(now / 86400000);
  const row = await db.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count')
    .bind(`${key}:${day}`, (day + 2) * 86400).first<{count: number}>();
  return row?.count ?? Infinity;
}

// ---- conversation history (04 § stage 3) ---------------------------------------------

interface HistoryRow {id: string; direction: 'in' | 'out'; body: string | null; media_json: string | null; intent: string | null; status: string; created_at: string}

/** The contact's earlier messages: the last 12 or the last 48 hours, whichever is fewer, oldest first. */
export async function history(db: D1Database, contactId: string, messageId: string, now: number): Promise<HistoryRow[]> {
  const since = new Date(now - HISTORY_MS).toISOString();
  const rows = (await db.prepare("SELECT id,direction,body,media_json,intent,status,created_at FROM advisor_messages WHERE contact_id=? AND id<>? AND created_at>=? AND NOT (direction='out' AND status='failed') ORDER BY created_at DESC, id DESC LIMIT ?")
    .bind(contactId, messageId, since, HISTORY_TURNS).all<HistoryRow>()).results;
  return rows.reverse();
}

/** The user-turn text of an inbound message: its body plus "[photo]" notes (images are never replayed). */
function inboundText(body: string | null, media: number): string {
  const notes = media ? (media === 1 ? '[photo]' : `[${media} photos]`) : '';
  return [String(body ?? '').trim(), notes].filter(Boolean).join(' ') || '[empty message]';
}

type ApiMessage = {role: 'user' | 'assistant'; content: string | unknown[]};

/** Alternating user/assistant messages ending with the current one; consecutive same-role rows are joined. */
export function buildMessages(rows: readonly HistoryRow[], current: string): ApiMessage[] {
  const out: {role: 'user' | 'assistant'; text: string}[] = [];
  for (const row of rows) {
    const role = row.direction === 'in' ? 'user' : 'assistant';
    const text = role === 'user' ? inboundText(row.body, mediaIds(row.media_json).length) : String(row.body ?? '').trim();
    if (!text) continue;
    const last = out[out.length - 1];
    if (last && last.role === role) last.text += '\n' + text; else out.push({role, text});
  }
  while (out.length && out[0]!.role === 'assistant') out.shift();
  const last = out[out.length - 1];
  if (last && last.role === 'user') last.text += '\n' + current; else out.push({role: 'user', text: current});
  return out.map(m => ({role: m.role, content: m.text}));
}

// ---- briefs ---------------------------------------------------------------------------

const WEEKDAYS: Record<string, string> = {Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday'};

/** The contact brief and the situation brief (04 § stage 3), as one uncached system block. */
export async function briefs(db: D1Database, contact: AdvisorContactRow, settings: AdvisorSettings, language: Language, isNew: boolean, now: number, messageCreatedAt: string = new Date(now).toISOString()): Promise<string> {
  // TA-I1 (04 § stage 3): the boat's name, its verification status and the photo consent for skippers and crew.
  const boats = contact.boat_id ? (await boatsForContact(db, contact.id)).filter(b => b.id === contact.boat_id) : [];
  const boat = boats[0] ?? null;
  // TA-I2 (04 § stage 2): the pending report itself, with its id for edit_report, or the latest one.
  const reportLines = boat ? await reportBrief(db, boat, messageCreatedAt, now) : ['- report waiting for confirmation: no'];
  const flow = await readFlow(db, contact.id);
  const registering = flow?.flow === 'register' && now - Date.parse(flow.asked_at) <= FLOW_MAX_AGE_MS ? flow.step : null;
  const boatLines = boat ? [
    `- boat: ${boat.name} (${boat.relation === 'owner' ? 'they own it' : 'they are crew'}); status: ${boat.status}${boat.status === 'verified' ? '' : ' (reports publish but tools show it as "a boat" until the team verifies it)'}`,
    `- photo consent for social posts: ${consentState(boat)}`,
  ] : [];
  let targets: string[] = [];
  try { const v = contact.targets_json ? JSON.parse(contact.targets_json) : []; if (Array.isArray(v)) targets = v.filter((x): x is string => typeof x === 'string'); } catch { targets = []; }
  const local = localClock(now, DEFAULT_TZ);
  const region = portRegion(contact.home_port) ?? settings.regionDefault;
  // TA-A1 (04 § stage 3): the home port's (else the region's first port's) answer for today, when one is stored.
  const briefPort = contact.home_port && portRegion(contact.home_port) ? contact.home_port : resolvePort(null, null, settings)?.port ?? null;
  const daily = briefPort ? await storedDaily(db, briefPort, now) : null;
  const channel = isWebOnly(contact) ? 'web chat (no SMS limits, but keep it short)' : contact.channel === 'imessage' ? 'iMessage' : 'SMS (3 segments, 480 characters)';
  return [
    'CONTACT BRIEF',
    `- role: ${contact.role}`,
    ...boatLines,
    ...(registering ? [`- boat registration in progress: the next answer is the ${registering} (the system asks; do not ask it yourself)`] : []),
    `- reply language: ${language === 'es' ? 'Spanish' : 'English'}`,
    `- display name: ${contact.display_name ?? 'not given'}`,
    `- home port: ${contact.home_port ? `${portName(contact.home_port)} (${contact.home_port})` : 'not given yet'}`,
    `- targets: ${targets.length ? targets.join(', ') : 'not given yet'}`,
    ...reportLines,
    `- new contact: ${isNew ? 'yes (this is their first message)' : 'no'}`,
    '',
    'SITUATION BRIEF',
    `- today: ${WEEKDAYS[local.weekday] ?? local.weekday} ${local.date}, ${local.time} Pacific time`,
    `- region: ${region}`,
    daily ? `- today's answer for ${portName(briefPort)}: ${language === 'es' ? daily.text_es : daily.text_en}` : "- today's port answer: not generated yet (use get_port_report)",
    '- advisories: call get_conditions for the port and date before any trip advice',
    `- channel: ${channel}`,
  ].join('\n');
}

// ---- reply post-processing ---------------------------------------------------------------

// ---- the Messages API loop --------------------------------------------------------------

interface ContentBlock {type: string; text?: string; id?: string; name?: string; input?: unknown}
interface ApiResponse {content?: ContentBlock[]; stop_reason?: string; usage?: Record<string, unknown>}

const count = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0;
class BudgetSpent extends Error { constructor() { super('advisor turn budget spent'); this.name = 'BudgetSpent'; } }

export interface ModelTurn {
  text: string; toolsCalled: string[]; usableRules: boolean; actions: Action[]; outcome: 'ok' | 'tool_loop' | 'budget';
  /** TA-A2: the first get_conditions result with an advisory: its line (reply language) and events, for the advisory backstop. */
  advisory?: {line: string; events: string[]} | null;
}

/**
 * Claude with tools: at most MAX_TOOL_ROUNDS executed tool rounds; a fifth
 * tool_use is not executed (outcome 'tool_loop'). pause_turn continues the
 * assistant turn (as lookupBoat does) up to MAX_PAUSES times. 429/529 are
 * retried once after 2 s; any other HTTP error throws (the consumer retries
 * the message). The 30 s budget ends the loop with outcome 'budget'; the
 * consumer's hard-stop signal aborts it with an error.
 */
export async function modelTurn(args: {env: Env; settings: AdvisorSettings; system: unknown[]; messages: ApiMessage[]; tools: readonly AdvisorTool[];
  ctx: ToolContext; deps: EngineDeps; signal?: AbortSignal; usage: LlmUsage}): Promise<ModelTurn> {
  const {env, settings, tools, ctx, deps, signal, usage} = args;
  const fetcher = deps.fetcher ?? ((url: string, init: RequestInit) => fetch(url, init));
  const clock = deps.clock ?? Date.now;
  const sleep = deps.sleep ?? ((ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)));
  const started = clock();
  const messages = [...args.messages];
  const request = {model: settings.model, max_tokens: MAX_TOKENS, temperature: TEMPERATURE, system: args.system, tools: claudeTools(tools), messages};
  const toolsCalled: string[] = [], actions: Action[] = [];
  let usableRules = false, rounds = 0, pauses = 0, lastText = '', carry = '';
  let advisory: ModelTurn['advisory'] = null;

  async function call(): Promise<ApiResponse> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const left = TURN_BUDGET_MS - (clock() - started);
      if (left <= 0) throw new BudgetSpent();
      signal?.throwIfAborted();
      if (attempt) await sleep(RETRY_DELAY_MS);
      const timeout = AbortSignal.timeout(Math.max(1, left));
      const response = await fetcher(API, {method: 'POST', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: {'x-api-key': env.ANTHROPIC_API_KEY!, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
        body: JSON.stringify(request)}).catch((error: unknown) => {
        if (signal?.aborted) throw error;
        if ((error as Error)?.name === 'TimeoutError') throw new BudgetSpent();
        throw error;
      });
      usage.turns = (usage.turns ?? 0) + 1;
      if ((response.status === 429 || response.status === 529) && attempt === 0) continue;
      if (!response.ok) throw Error(`advisor model HTTP ${response.status}`);
      const data = await response.json() as ApiResponse;
      usage.input_tokens = (usage.input_tokens ?? 0) + count(data.usage?.input_tokens) + count(data.usage?.cache_creation_input_tokens) + count(data.usage?.cache_read_input_tokens);
      usage.output_tokens = (usage.output_tokens ?? 0) + count(data.usage?.output_tokens);
      return data;
    }
    throw Error('advisor model unavailable');
  }

  try {
    for (;;) {
      const data = await call();
      const content = Array.isArray(data.content) ? data.content : [];
      // Text continued after a pause_turn belongs to the same assistant turn.
      const raw = carry + content.filter(b => b.type === 'text' && typeof b.text === 'string').map(b => b.text).join('');
      carry = '';
      if (raw.trim()) lastText = raw.trim();
      if (data.stop_reason === 'pause_turn' && pauses < MAX_PAUSES) {
        pauses++; carry = raw;
        messages.push({role: 'assistant', content});
        continue;
      }
      const uses = content.filter(b => b.type === 'tool_use' && typeof b.id === 'string' && typeof b.name === 'string');
      if (data.stop_reason !== 'tool_use' || !uses.length) return {text: lastText, toolsCalled, usableRules, actions, outcome: 'ok', advisory};
      if (rounds >= MAX_TOOL_ROUNDS) return {text: lastText, toolsCalled, usableRules, actions, outcome: 'tool_loop', advisory};
      rounds++;
      const results: unknown[] = [];
      for (const use of uses) {
        const out = await dispatchTool(use.name!, use.input, ctx, tools);
        toolsCalled.push(use.name!);
        if (use.name === 'get_rules' && !out.isError && !(out.result as {unavailable?: unknown})?.unavailable) usableRules = true;
        // TA-I3: identify_fish quotes the rules table too (06 § fish ID step 3); a current row counts, a stale one does not.
        if (use.name === 'identify_fish' && !out.isError && (out.result as {rules?: {stale?: boolean} | null})?.rules?.stale === false) usableRules = true;
        // TA-A2: a planning turn whose conditions carry an advisory must lead with it (AD-4); runTurn checks the reply.
        if (use.name === 'get_conditions' && !out.isError && !advisory) advisory = advisoryOf(out.result);
        if (out.actions) actions.push(...out.actions);
        results.push({type: 'tool_result', tool_use_id: use.id, content: JSON.stringify(out.result ?? null).slice(0, TOOL_RESULT_MAX), ...(out.isError ? {is_error: true} : {})});
      }
      messages.push({role: 'assistant', content}, {role: 'user', content: results});
    }
  } catch (error) {
    if (error instanceof BudgetSpent) return {text: lastText, toolsCalled, usableRules, actions, outcome: 'budget', advisory};
    throw error;
  }
}

/** A get_conditions result's advisory line and events, when it says to lead with one. */
function advisoryOf(result: unknown): {line: string; events: string[]} | null {
  const r = result as {lead_with_advisory?: unknown; advisory_line?: unknown; advisories?: {event?: unknown}[]} | null;
  if (r?.lead_with_advisory !== true || typeof r.advisory_line !== 'string' || !Array.isArray(r.advisories)) return null;
  const events = r.advisories.map(a => a?.event).filter((e): e is string => typeof e === 'string' && e.length > 0);
  return events.length ? {line: r.advisory_line, events} : null;
}

// ---- the turn ----------------------------------------------------------------------------

const SPANISH_COMMANDS = new Set(['alto', 'parar', 'empezar', 'ayuda', 'olvídame', 'olvidame', 'borra mis datos', 'borrar', 'mis datos', 'mándame un enlace', 'mandame un enlace', 'enlace']);

/** The engine. See the file header for the stages. */
export async function runTurn(input: EngineInput): Promise<EngineResult> {
  const {env, contact, message, now, signal} = input;
  const deps = input.deps ?? {};
  const settings = advisorSettings(env);
  const db = env.DB!;
  const text = String(message.body ?? '').trim();
  const media = mediaIds(message.media_json);
  const done = (actions: Action[], intent: string, extra: Partial<EngineResult> = {}): EngineResult => ({actions, intent, ...extra});

  // Stage 0: the soft switch, blocked and stopped contacts.
  if (!settings.repliesEnabled) return done([], 'held');
  if (contact.status === 'blocked') return done([], 'blocked');
  const command = parseCommand(text);
  if (contact.status === 'stopped') {
    // No outbound of any kind until START (02 § STOP).
    if (command !== 'start') return done([], 'stopped');
  }

  // Language (FC-6): the reply follows this message; the stored language follows two in a row.
  const rows = await history(db, contact.id, message.id, now);
  const previousIn = [...rows].reverse().find(r => r.direction === 'in');
  const isNew = !(await db.prepare('SELECT 1 AS x FROM advisor_messages WHERE contact_id=? AND id<>? LIMIT 1').bind(contact.id, message.id).first());
  const commandLanguage: Language | null = command ? (SPANISH_COMMANDS.has(normalizeCommand(text)) ? 'es' : null) : null;
  const detected = commandLanguage ?? detectLanguage(text);
  const choice = chooseLanguage(contact.language, detected, previousIn ? detectLanguage(previousIn.body ?? '') : null);
  const language: Language = choice.reply;
  const languageUpdate: Action[] = choice.store ? [{type: 'contact_update', fields: {language: choice.store}}] : [];
  const say = (key: StringKey, vars: Record<string, string | number> = {}): Action => textAction(settings, t(language, key, vars));
  // The first reply to a brand-new phone contact says who we are, rates and HELP/STOP (the 10DLC promise), once.
  const welcomeFirst = (): Action[] => {
    if (!isNew || isWebOnly(contact)) return [];
    const card = contactCardAction({contact, language, settings});
    return [say('welcome'), ...(card ? [card] : [])];
  };

  // Stage 1: commands. STOP, START, HELP and the data commands work even past the daily cap.
  if (command && command !== 'upload_link') {
    const result = await commandTurn(command, {env, contact, settings, language, say, welcomeFirst, db, message, now, languageUpdate});
    if (result) return result;
  }

  // Stage 0: the daily message cap (OP-3): one "limit" text a day, on the first message over it.
  const sent = await messagesToday(db, contact, now);
  if (sent > settings.dailyMessagesPerContact) {
    const target = contact.home_port ? `port:${contact.home_port}` : 'home';
    return done(sent === settings.dailyMessagesPerContact + 1 ? [say('capped', {target})] : [], 'capped');
  }

  // Stage 2: the upload-link request (04 § stage 2).
  if (command === 'upload_link') {
    const {text: link} = await uploadLinkText({env, contact, language, settings, now});
    return done([...welcomeFirst(), ...languageUpdate, textAction(settings, link)], 'upload_link');
  }

  // Stage 2: deterministic flows.
  const flow: FlowContext = {env, contact, message, now, deps, signal, settings, language, text, media, db, carry: []};
  const admin = await adminFlow(flow);
  if (admin) return admin;
  const link = await linkCodeFlow(flow);
  if (link) return link;
  for (const f of STAGE_TWO_FLOWS) {
    const r = await f.run(flow);
    if (r) return {...r, actions: [...welcomeFirst(), ...languageUpdate, ...flow.carry.splice(0), ...r.actions]};
  }
  if (!text && media.length) {
    // A skipper's or crew's media went through TA-I2's flow above and an angler's through TA-I3's; this answers
    // what neither could read (no stored row, a boatless skipper).
    return done([...welcomeFirst(), say('media_ack'), ...flow.carry], 'media');
  }
  if (!text) return done([...flow.carry], 'empty');
  // TA-I1: whatever a flow carried goes out before any Stage 3 answer.
  languageUpdate.push(...flow.carry.splice(0));

  // Stage 3: the model turn.
  if (!env.ANTHROPIC_API_KEY) {
    // Not configured yet: the warm-up text alone, as before the engine (no model, no welcome).
    advisorLog('warn', 'advisor_model_not_configured', {});
    return done([...languageUpdate, say('warming_up')], 'unconfigured');
  }
  if (await countToday(db, `advisor-llm:${contact.id}`, now) > settings.dailyLlmPerContact) {
    const n = await countToday(db, `advisor-llm-capped:${contact.id}`, now);
    const target = contact.home_port ? `port:${contact.home_port}` : 'home';
    return done(n === 1 ? [say('capped', {target})] : [], 'capped');
  }
  if (await countToday(db, 'global:advisor-llm', now) > settings.globalDailyLlm) {
    advisorLog('warn', 'advisor_global_cap', {limit: settings.globalDailyLlm});
    return done([say('global_cap')], 'global_cap');
  }

  const tools = toolsForRole(contact);
  const ctx: ToolContext = {env, contact, message, deps, db, language, settings, now};
  const system = [{type: 'text', text: systemPrompt(language), cache_control: {type: 'ephemeral'}},
    {type: 'text', text: await briefs(db, contact, settings, language, isNew, now, message.created_at)}];
  const usage: LlmUsage = {model: settings.model, turns: 0, input_tokens: 0, output_tokens: 0, web_search_requests: 0};
  let turn: ModelTurn | null = null, outcome = 'error';
  try {
    // TA-I2/I3: a photo with a caption reaches the model with its ids, so read_count_board (skippers, crew) or
    // identify_fish and share_angler_photo (anglers) can read it.
    const current = media.length
      ? `${String(text).trim()} [${media.length === 1 ? 'photo' : `${media.length} photos`}, media_id ${media.slice(0, 10).join(', ')}]`.trim() : inboundText(text, media.length);
    turn = await modelTurn({env, settings, system, messages: buildMessages(rows, current), tools, ctx, deps, signal, usage});
    outcome = turn.outcome;
  } finally {
    const intentNow = turn ? intentOf(turn, tools) : 'chat';
    recordLlm(env, `advisor:${intentNow}`, outcome, usage);
    advisorLog(outcome === 'ok' ? 'info' : 'warn', 'advisor_model_turn', {intent: intentNow, outcome, model: usage.model, turns: usage.turns, input_tokens: usage.input_tokens, output_tokens: usage.output_tokens});
  }

  const actions: Action[] = [...welcomeFirst(), ...languageUpdate];
  let intent = intentOf(turn, tools);
  let reply = stripMarkdown(turn.text);
  if (turn.outcome !== 'ok') {
    // A fifth tool_use, or the 30 s budget: the last text if any, else "let me check" and a review (04).
    if (!reply) reply = t(language, 'tool_loop');
    actions.push({type: 'review_open', kind: 'conversation', refId: message.id, reason: turn.outcome === 'tool_loop' ? 'tool_loop' : 'model_timeout'});
  }
  // TA-I1: a tool that texted for itself (register_boat's question) needs no filler when the model added nothing.
  if (!reply && turn.outcome === 'ok' && turn.actions.some(a => a.type === 'send_text')) {
    actions.push(...turn.actions);
    return done(actions, intent, {usage, model: settings.model});
  }
  if (!reply) reply = t(language, 'not_understood');
  if (!turn.usableRules) {
    const guarded = rulesGuard(reply, language);
    if (guarded.fired) {
      reply = guarded.text;
      actions.push({type: 'review_open', kind: 'conversation', refId: message.id, reason: 'rules_without_tool'});
      advisorLog('warn', 'advisor_rules_guard', {intent});
    }
  }
  // TA-A2 (AD-4): a deterministic backstop like the rules guard: when the turn's conditions had an advisory and the
  // reply does not lead with it, the advisory line goes first.
  if (turn.advisory && !leadsWithAdvisory(reply, turn.advisory.events)) {
    reply = `${turn.advisory.line} ${reply}`;
    advisorLog('warn', 'advisor_advisory_backstop', {intent, events: turn.advisory.events.length});
  }
  const resolved = resolveLinks(reply, settings.publicBase);
  reply = LIST_INTENTS.has(intent) ? resolved.text : capReply(resolved.text, resolved.links);
  if ([REFUSAL_EN, ABUSE_EN, ...both('refusal'), ...both('abuse_stop')].some(line => reply.startsWith(line))) intent = 'refused';
  actions.push({type: 'send_text', text: reply}, ...turn.actions);
  return done(actions, intent, {usage, model: settings.model});
}

/** 04 § intent recording: the first tool's intent, else 'chat'. */
function intentOf(turn: ModelTurn | null, tools: readonly AdvisorTool[]): string {
  const first = turn?.toolsCalled[0];
  return (first && tools.find(tool => tool.name === first)?.intent) || 'chat';
}

interface CommandContext {
  env: Env; contact: AdvisorContactRow; settings: AdvisorSettings; language: Language; db: D1Database; message: AdvisorMessageRow; now: number;
  say: (key: StringKey, vars?: Record<string, string | number>) => Action; welcomeFirst: () => Action[]; languageUpdate: Action[];
}

/** Stage 1 (04 table). Returns null for a word that is only a command in context ("delete" without a pending "forget me", "yes" when active). */
async function commandTurn(command: Command, c: CommandContext): Promise<EngineResult | null> {
  const {contact, settings, language, say} = c;
  switch (command) {
    case 'stop': {
      // Twilio answers STOP on SMS itself and refuses our confirmation (21610), so it is skipped there (03 § Twilio "As built").
      const twilioSms = settings.channel === 'twilio' && contact.channel === 'sms';
      return {actions: [...(twilioSms ? [] : [say('stop_done')]), {type: 'set_status', status: 'stopped'}], intent: 'stop'};
    }
    case 'start':
      if (contact.status === 'stopped') return {actions: [{type: 'set_status', status: 'active'}, ...c.languageUpdate, say('welcome')], intent: 'start'};
      if (normalizeCommand(c.message.body ?? '') === 'yes') return null;
      return {actions: [...c.languageUpdate, say('welcome')], intent: 'start'};
    case 'help':
      return {actions: [...c.welcomeFirst(), ...c.languageUpdate, say('help')], intent: 'help'};
    case 'forget':
      return {actions: [...c.languageUpdate, say('forget_ask')], intent: 'forget.ask'};
    case 'delete': {
      const since = new Date(c.now - FORGET_WINDOW_MS).toISOString();
      const last = await c.db.prepare("SELECT intent FROM advisor_messages WHERE contact_id=? AND direction='in' AND id<>? AND created_at>=? ORDER BY created_at DESC, id DESC LIMIT 1")
        .bind(contact.id, c.message.id, since).first<{intent: string | null}>();
      if (last?.intent !== 'forget.ask') return null;
      return {actions: [{type: 'forget', language}], intent: 'forget'};
    }
    case 'export':
      return {actions: [...c.languageUpdate, {type: 'export', language}], intent: 'export'};
    case 'upload_link':
      return null;   // handled after the daily cap, in runTurn
  }
}

// ---- Stage 2 built-in flows --------------------------------------------------------------

/**
 * The text admin fallback (08 § text-based admin): only the contact whose id
 * is ADVISOR_ADMIN_CONTACT_ID and whose role is admin-test, only "ok <code>" /
 * "no <code>", only open skipper and media reviews whose id starts with code.
 */
async function adminFlow(f: FlowContext): Promise<EngineResult | null> {
  const match = ADMIN.exec(f.text);
  if (!match || !f.settings.adminContactId || f.contact.id !== f.settings.adminContactId || f.contact.role !== 'admin-test') return null;
  const decision = match[1]!.toLowerCase() === 'ok' ? 'approved' : 'rejected', code = match[2]!.toLowerCase();
  const rows = (await f.db.prepare("SELECT id,kind FROM advisor_reviews WHERE id LIKE ? AND status='open' AND kind IN ('skipper','media') LIMIT 2").bind(`${code}%`).all<{id: string; kind: string}>()).results;
  const say = (key: StringKey, vars: Record<string, string>) => textAction(f.settings, t(f.language, key, vars));
  if (rows.length !== 1) return {actions: [say('admin_not_found', {code})], intent: 'admin.not_found'};
  const review = rows[0]!;
  return {actions: [{type: 'admin_review', reviewId: review.id, decision}, say('admin_done', {decision, kind: review.kind, code})], intent: `admin.${decision}`};
}

/**
 * The web phone-link code (03 § web, WH-2): a web-only contact with a pending
 * code (job_state advisor.link.<id>) who types six digits. A match merges the
 * web conversation into the phone contact; at most 5 guesses a day.
 */
async function linkCodeFlow(f: FlowContext): Promise<EngineResult | null> {
  if (!isWebOnly(f.contact) || !SIX_DIGITS.test(f.text)) return null;
  const row = await f.db.prepare('SELECT value FROM job_state WHERE key=?').bind(linkKey(f.contact.id)).first<{value: string}>();
  if (!row) return null;
  let pending: PendingLink & {phone_contact_id?: string};
  try { pending = JSON.parse(row.value); } catch { return null; }
  const say = (key: StringKey) => textAction(f.settings, t(f.language, key));
  if (!await takeDaily(f.db, `advisor-link-guess:${f.contact.id}`, LINK_GUESSES_PER_DAY, f.now)) return {actions: [say('link_expired')], intent: 'link.limited'};
  if (!(pending.expires_at > f.now) || !pending.phone_contact_id) return {actions: [say('link_expired')], intent: 'link.expired'};
  if (await sha256(f.text) !== pending.code_hash) return {actions: [say('link_wrong')], intent: 'link.wrong'};
  return {actions: [say('link_done'), {type: 'link_merge', phoneContactId: pending.phone_contact_id}], intent: 'link.done'};
}

/** The consumer's handler (server/index.ts, inbound.ts, the web chat route): the engine with deps.engine. */
export const engineHandler: Handler = async ({env, contact, message, now, deps, signal}) => runTurn({env, contact, message, now, deps: deps.engine ?? {}, signal});
