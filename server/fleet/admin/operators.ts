// The fleet admin's operators and outreach (docs/plans/charter-fleet/design.md § 12, § 13;
// D14, US-S1..S4; CF-32). Mounted in routes/admin.ts behind requireUser and requireAdmin;
// the FLEET_ENABLED gate (routes/fleet.ts) runs first.
//
//   GET  /api/admin/fleet/operators              ?region= &outreach_status= &consent_status=   by lead score, 500 at most
//   GET  /api/admin/fleet/operators/:id          operator, vessels, lead score with parts, outreach log
//   POST /api/admin/fleet/operators/:id          {outreach_status?, outreach_note?, consent_status?, consent_scope?, consent_note?, revoke_consent?: true}
//   GET  /api/admin/fleet/operators/:id/outreach the outreach log, newest first
//   POST /api/admin/fleet/operators/:id/outreach {kind: note|draft|reply, channel?, body}
//   POST /api/admin/fleet/outreach/:id           {action: approve|discard|log-sent}
//
// Nothing here sends a message (D14, US-S4): no channel, fetch or sender is imported, and a
// test checks that. A draft stays a draft until the owner sends it themselves; the only
// transitions are draft -> approved -> logged ("log as sent by owner", kind sent-by-owner)
// and draft or approved -> discarded. An operator marked do-not-contact gets no new draft
// and no approval or log of an old one. A consent change records who and when on
// fleet_operators (consent_recorded_by, consent_recorded_at; consent_revoked_at on
// withdrawal, read as no consent from the next request) and a logged note with the
// before, after and how it was given, so the history survives the next change. An
// outreach status set by hand (do-not-contact included) and a draft logged as sent each
// add a logged note too: its created_by and created_at say who and when.
import {leadInputs, leadScore} from '../leadscore.ts';
import type {AdminOutcome} from '../../advisor/admin/skippers.ts';

type SqlValue = string | number | null;
const OPERATOR_ID = /^[A-Za-z0-9_-]{16,64}$/;
const HEX32 = /^[0-9a-f]{32}$/;
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
export const OPERATOR_LIMIT = 500;
export const OUTREACH_LIMIT = 200;
export const CONSENT_STATUSES = ['unknown', 'contacted', 'declined', 'content-sharing', 'partner'] as const;
export const OUTREACH_STATUSES = ['none', 'drafted', 'contacted', 'declined', 'replied', 'partner', 'do-not-contact'] as const;
export const CONSENT_SCOPES = ['profile', 'photos', 'catch-logs', 'offerings', 'social-posts'] as const;
export const OUTREACH_KINDS = ['note', 'draft', 'reply'] as const;   // sent-by-owner only through log-sent
export const CHANNELS = ['email', 'phone', 'instagram', 'facebook', 'in-person', 'other'] as const;
export const OUTREACH_ACTIONS = ['approve', 'discard', 'log-sent'] as const;
/** status -> the statuses each action may move it to. */
const TRANSITIONS: Record<typeof OUTREACH_ACTIONS[number], {from: string[]; to: string}> = {
  'approve': {from: ['draft'], to: 'approved'},
  'discard': {from: ['draft', 'approved'], to: 'discarded'},
  'log-sent': {from: ['approved'], to: 'logged'},
};
const MAX_BODY = 8000, MAX_NOTE = 2000;
const DNC = 'do-not-contact';

const oneOf = (list: readonly string[], v: unknown): v is string => typeof v === 'string' && list.includes(v);
const parse = (text: string | null): unknown => { if (text === null) return null; try { return JSON.parse(text); } catch { return null; } };
const newId = (): string => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');

interface OperatorRow {id: string; region: string; consent_status: string; consent_scope_json: string | null; consent_revoked_at: string | null; outreach_status: string; [k: string]: unknown}
const operatorRow = (db: D1Database, id: string): Promise<OperatorRow | null> =>
  OPERATOR_ID.test(id) ? db.prepare('SELECT * FROM fleet_operators WHERE id=?').bind(id).first<OperatorRow>() : Promise.resolve(null);

/** GET /api/admin/fleet/operators: highest lead score first, then name. */
export async function listOperators(db: D1Database, q: {region?: string; outreach_status?: string; consent_status?: string}, now: string):
  Promise<{operators: unknown[]; truncated: boolean} | {error: string}> {
  const where: string[] = [], args: string[] = [];
  if (q.region) { if (!REGION.test(q.region)) return {error: 'invalid region'}; where.push('o.region=?'); args.push(q.region); }
  if (q.outreach_status) { if (!oneOf(OUTREACH_STATUSES, q.outreach_status)) return {error: 'unknown outreach_status'}; where.push('o.outreach_status=?'); args.push(q.outreach_status); }
  if (q.consent_status) { if (!oneOf(CONSENT_STATUSES, q.consent_status)) return {error: 'unknown consent_status'}; where.push('o.consent_status=?'); args.push(q.consent_status); }
  const cond = where.length ? where.join(' AND ') : '1';
  const [rows, inputs] = await Promise.all([
    db.prepare(`SELECT o.id,o.region,o.slug,o.name,o.website,o.consent_status,o.consent_recorded_at,o.consent_revoked_at,o.outreach_status,o.updated_at,
        (SELECT COUNT(*) FROM fleet_vessels v WHERE v.operator_id=o.id) AS vessels,
        (SELECT MAX(created_at) FROM fleet_outreach x WHERE x.operator_id=o.id AND x.status<>'discarded') AS last_touch,
        (SELECT COUNT(*) FROM fleet_outreach x WHERE x.operator_id=o.id AND x.status IN ('draft','approved')) AS open_drafts
      FROM fleet_operators o WHERE ${cond} ORDER BY o.name,o.id LIMIT ?`).bind(...args, OPERATOR_LIMIT + 1).all<{id: string; name: string; outreach_status: string}>(),
    leadInputs(db, {sql: cond, args}, now),
  ]);
  const operators = rows.results.slice(0, OPERATOR_LIMIT).map(o => ({...o, lead_score: leadScore(inputs.get(o.id)!)}))
    .sort((a, b) => Number(a.outreach_status === DNC) - Number(b.outreach_status === DNC)   // do-not-contact last
      || b.lead_score.score - a.lead_score.score || a.name.localeCompare(b.name));
  return {operators, truncated: rows.results.length > OPERATOR_LIMIT};
}

/** The outreach log of one operator, newest first. */
async function outreachLog(db: D1Database, id: string): Promise<unknown[]> {
  return (await db.prepare('SELECT * FROM fleet_outreach WHERE operator_id=? ORDER BY created_at DESC,id LIMIT ?').bind(id, OUTREACH_LIMIT).all()).results;
}

/** GET /api/admin/fleet/operators/:id. */
export async function operatorDetail(db: D1Database, id: string, now: string): Promise<Record<string, unknown> | null> {
  const row = await operatorRow(db, id);
  if (!row) return null;
  const [vessels, inputs, outreach] = await Promise.all([
    db.prepare('SELECT id,slug,name,port_id,vessel_class,status,profile_status,mmsi FROM fleet_vessels WHERE operator_id=? ORDER BY name_norm,id').bind(id).all(),
    leadInputs(db, {sql: 'o.id=?', args: [id]}, now),
    outreachLog(db, id),
  ]);
  const {consent_scope_json, ...operator} = row;
  return {operator: {...operator, consent_scope: parse(consent_scope_json)}, vessels: vessels.results, lead_score: leadScore(inputs.get(id)!), outreach};
}

/** GET /api/admin/fleet/operators/:id/outreach. */
export async function listOutreach(db: D1Database, id: string): Promise<{outreach: unknown[]} | null> {
  return await operatorRow(db, id) ? {outreach: await outreachLog(db, id)} : null;
}

const note = (db: D1Database, operator: string, body: string, by: string, now: string): D1PreparedStatement =>
  db.prepare(`INSERT INTO fleet_outreach(id,operator_id,kind,channel,body,status,created_by,created_at) VALUES(?,?,'note',NULL,?,'logged',?,?)`)
    .bind(newId(), operator, body.slice(0, MAX_BODY), by, now);

/** POST /api/admin/fleet/operators/:id: outreach status and consent. */
export async function editOperator(db: D1Database, id: string, input: Record<string, unknown>, by: string, now: string): Promise<AdminOutcome<Record<string, unknown>>> {
  const row = await operatorRow(db, id);
  if (!row) return {status: 'not-found'};
  for (const key of Object.keys(input))
    if (!['outreach_status', 'outreach_note', 'consent_status', 'consent_scope', 'consent_note', 'revoke_consent'].includes(key)) return {status: 'invalid', error: `unknown field: ${key}`};
  const sets: string[] = [], args: SqlValue[] = [], statements: D1PreparedStatement[] = [];
  if (input.outreach_status !== undefined) {
    if (!oneOf(OUTREACH_STATUSES, input.outreach_status)) return {status: 'invalid', error: `outreach_status: not one of ${OUTREACH_STATUSES.join(', ')}`};
    const why = typeof input.outreach_note === 'string' ? input.outreach_note.trim() : '';
    if (input.outreach_note !== undefined && (typeof input.outreach_note !== 'string' || why.length > MAX_NOTE)) return {status: 'invalid', error: `outreach_note: at most ${MAX_NOTE} characters`};
    if (input.outreach_status !== row.outreach_status) {
      sets.push('outreach_status=?'); args.push(input.outreach_status);
      statements.push(note(db, id, `Outreach status ${row.outreach_status} -> ${input.outreach_status}.${why ? ' ' + why : ''}`, by, now));
    }
  } else if (input.outreach_note !== undefined) return {status: 'invalid', error: 'outreach_note goes with an outreach_status'};
  const grant = input.consent_status !== undefined || input.consent_scope !== undefined, revoke = input.revoke_consent !== undefined;
  if (revoke && input.revoke_consent !== true) return {status: 'invalid', error: 'revoke_consent must be true'};
  if (grant && revoke) return {status: 'invalid', error: 'record consent or revoke it, not both'};
  if (grant || revoke) {
    const how = typeof input.consent_note === 'string' ? input.consent_note.trim() : '';
    if (!how || how.length > MAX_NOTE) return {status: 'invalid', error: `consent_note: say how consent was given or withdrawn (1-${MAX_NOTE} characters)`};
    if (revoke) {
      if (row.consent_revoked_at) return {status: 'conflict', error: 'consent is already revoked'};
      sets.push('consent_revoked_at=?'); args.push(now);
      statements.push(note(db, id, `Consent revoked (was ${row.consent_status}). ${how}`, by, now));
    } else {
      const status = input.consent_status ?? row.consent_status;
      if (!oneOf(CONSENT_STATUSES, status)) return {status: 'invalid', error: `consent_status: not one of ${CONSENT_STATUSES.join(', ')}`};
      const scope = input.consent_scope ?? (parse(row.consent_scope_json) as {scope?: unknown} | null)?.scope ?? [];
      if (!Array.isArray(scope) || !scope.every(s => oneOf(CONSENT_SCOPES, s)) || new Set(scope).size !== scope.length)
        return {status: 'invalid', error: `consent_scope: a list of ${CONSENT_SCOPES.join(', ')}`};
      sets.push('consent_status=?', 'consent_scope_json=?', 'consent_revoked_at=NULL'); args.push(status, JSON.stringify({scope, note: how}));
      statements.push(note(db, id, `Consent ${row.consent_status} -> ${status}; scope: ${scope.join(', ') || 'none'}. ${how}`, by, now));
    }
    sets.push('consent_recorded_at=?', 'consent_recorded_by=?'); args.push(now, by);
  } else if (input.consent_note !== undefined) return {status: 'invalid', error: 'consent_note goes with a consent change'};
  if (!sets.length) return {status: 'invalid', error: 'nothing to change'};
  await db.batch([db.prepare(`UPDATE fleet_operators SET ${sets.join(',')},updated_at=? WHERE id=?`).bind(...args, now, id), ...statements]);
  return {status: 'ok', value: (await operatorDetail(db, id, now))!};
}

/** POST /api/admin/fleet/operators/:id/outreach: a note, a reply received, or a draft (never sent). */
export async function addOutreach(db: D1Database, id: string, input: Record<string, unknown>, by: string, now: string): Promise<AdminOutcome<Record<string, unknown>>> {
  const row = await operatorRow(db, id);
  if (!row) return {status: 'not-found'};
  for (const key of Object.keys(input)) if (!['kind', 'channel', 'body'].includes(key)) return {status: 'invalid', error: `unknown field: ${key}`};
  if (!oneOf(OUTREACH_KINDS, input.kind)) return {status: 'invalid', error: `kind: not one of ${OUTREACH_KINDS.join(', ')}`};
  if (input.channel !== undefined && input.channel !== null && !oneOf(CHANNELS, input.channel)) return {status: 'invalid', error: `channel: not one of ${CHANNELS.join(', ')}`};
  const text = typeof input.body === 'string' ? input.body.trim() : '';
  if (!text || text.length > MAX_BODY) return {status: 'invalid', error: `body: 1-${MAX_BODY} characters`};
  const draft = input.kind === 'draft';
  if (draft && row.outreach_status === DNC) return {status: 'conflict', error: 'the operator is do-not-contact: no new drafts'};
  const outId = newId();
  // The do-not-contact check is repeated in the insert, so a status change between the read and the write still blocks the draft.
  const insert = db.prepare(`INSERT INTO fleet_outreach(id,operator_id,kind,channel,body,status,created_by,created_at)
    SELECT ?,?,?,?,?,?,?,? WHERE ? OR EXISTS (SELECT 1 FROM fleet_operators WHERE id=? AND outreach_status<>'${DNC}')`)
    .bind(outId, id, input.kind, (input.channel as string | undefined) ?? null, text, draft ? 'draft' : 'logged', by, now, draft ? 0 : 1, id);
  const statements = [insert];
  if (draft) statements.push(db.prepare(`UPDATE fleet_operators SET outreach_status='drafted',updated_at=? WHERE id=? AND outreach_status='none'`).bind(now, id));
  const [result] = await db.batch(statements);
  if (!result?.meta.changes) return {status: 'conflict', error: 'the operator is do-not-contact: no new drafts'};
  return {status: 'ok', value: {outreach: await db.prepare('SELECT * FROM fleet_outreach WHERE id=?').bind(outId).first()}};
}

/** POST /api/admin/fleet/outreach/:id {action}: approve, discard, or log as sent by the owner. */
export async function decideOutreach(db: D1Database, id: string, input: Record<string, unknown>, by: string, now: string): Promise<AdminOutcome<Record<string, unknown>>> {
  if (!HEX32.test(id)) return {status: 'not-found'};
  const entry = await db.prepare('SELECT o.*,f.outreach_status FROM fleet_outreach o JOIN fleet_operators f ON f.id=o.operator_id WHERE o.id=?')
    .bind(id).first<{operator_id: string; kind: string; status: string; outreach_status: string}>();
  if (!entry || !['draft', 'sent-by-owner'].includes(entry.kind)) return {status: 'not-found'};
  for (const key of Object.keys(input)) if (key !== 'action') return {status: 'invalid', error: `unknown field: ${key}`};
  if (!oneOf(OUTREACH_ACTIONS, input.action)) return {status: 'invalid', error: `action: not one of ${OUTREACH_ACTIONS.join(', ')}`};
  const move = TRANSITIONS[input.action as typeof OUTREACH_ACTIONS[number]];
  if (!move.from.includes(entry.status)) return {status: 'conflict', error: `a ${entry.status} draft cannot be ${input.action === 'log-sent' ? 'logged as sent' : input.action + 'd'}`};
  if (input.action !== 'discard' && entry.outreach_status === DNC) return {status: 'conflict', error: 'the operator is do-not-contact: discard the draft'};
  // Conditional on the status read and, except for discard, on the operator still not being do-not-contact.
  const cond = `id=? AND status IN (${move.from.map(() => '?').join(',')})` +
    (input.action === 'discard' ? '' : ` AND NOT EXISTS (SELECT 1 FROM fleet_operators WHERE id=? AND outreach_status='${DNC}')`);
  const where = [id, ...move.from, ...(input.action === 'discard' ? [] : [entry.operator_id])];
  const statements = [input.action === 'log-sent'
    ? db.prepare(`UPDATE fleet_outreach SET kind='sent-by-owner',status='logged' WHERE ${cond}`).bind(...where)
    : db.prepare(`UPDATE fleet_outreach SET status=?${input.action === 'approve' ? ',approved_by=?,approved_at=?' : ''} WHERE ${cond}`)
      .bind(move.to, ...(input.action === 'approve' ? [by, now] : []), ...where)];
  if (input.action === 'log-sent') {
    // Who logged it and when: a note, written only if this request made the transition (never twice for one draft).
    const text = `Logged as sent by the owner: draft ${id}.`;
    statements.push(db.prepare(`INSERT INTO fleet_outreach(id,operator_id,kind,channel,body,status,created_by,created_at)
      SELECT ?,?,'note',NULL,?,'logged',?,? WHERE EXISTS (SELECT 1 FROM fleet_outreach WHERE id=? AND status='logged')
        AND NOT EXISTS (SELECT 1 FROM fleet_outreach WHERE operator_id=? AND kind='note' AND body=?)`)
      .bind(newId(), entry.operator_id, text, by, now, id, entry.operator_id, text));
    statements.push(db.prepare(`UPDATE fleet_operators SET outreach_status='contacted',updated_at=? WHERE id=? AND outreach_status IN ('none','drafted')
      AND EXISTS (SELECT 1 FROM fleet_outreach WHERE id=? AND status='logged')`).bind(now, entry.operator_id, id));
  }
  const [result] = await db.batch(statements);
  if (!result?.meta.changes) return {status: 'conflict', error: 'the draft changed while saving; reload and retry'};
  return {status: 'ok', value: {outreach: await db.prepare('SELECT * FROM fleet_outreach WHERE id=?').bind(id).first()}};
}
