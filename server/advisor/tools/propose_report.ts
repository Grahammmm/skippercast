// propose_report (04 § Tools, 05 § Plain-text report, SC-2): the model passes
// the structure it parsed from a skipper's typed counts that the deterministic
// parser (parseCountText) did not take. Labels are mapped to species keys here
// (species-synonyms.json), not by the model; the system texts the same
// confirmation as the deterministic path, or posts at once with auto_publish.
import type {AdvisorTool} from './tool.ts';
import {boatToday, cleanFields, contactBoat, draftActions, normalizeTrip, parseDateWords, speciesKeyFor} from '../intake/reports.ts';
import type {ReportCount, ReportFields} from '../types.ts';

export const proposeReport: AdvisorTool = {
  name: 'propose_report',
  description: "Turn a skipper's typed counts into a draft report for them to confirm (\"22 people, limits of rockfish, 12 lings, 2 released\"). Pass each species as they wrote it in label, with kept and released numbers. The system texts the draft and asks them to confirm; reply with one short line at most.",
  input_schema: {type: 'object', additionalProperties: false, required: ['counts'], properties: {report_date: {type: 'string', description: 'YYYY-MM-DD; default today'}, anglers: {type: 'integer', minimum: 0}, trip_type: {type: 'string', maxLength: 30}, counts: {type: 'array', items: {type: 'object', additionalProperties: false, required: ['label'], properties: {species_key: {type: 'string'}, label: {type: 'string'}, kept: {type: 'integer', minimum: 0}, released: {type: 'integer', minimum: 0}}}}, notes: {type: 'string', maxLength: 280}}},
  roles: ['skipper', 'crew'],
  intent: 'report.text',
  async run(input, ctx) {
    const boat = await contactBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {proposed: false, reason: 'this contact is not linked to a boat'}};
    const today = boatToday(boat, ctx.now);
    const date = typeof input.report_date === 'string' ? (parseDateWords(input.report_date, today) ?? null) : today;
    if (!date) return {result: {proposed: false, reason: 'report_date must be today or within the last 7 days'}};
    const raw = Array.isArray(input.counts) ? input.counts : [];
    const counts: ReportCount[] = raw.filter((c): c is Record<string, unknown> => Boolean(c) && typeof c === 'object').map(c => ({
      species_key: speciesKeyFor(String(c.label ?? '')), label: String(c.label ?? '').trim(), kept: (c.kept as number | null) ?? null, released: (c.released as number | null) ?? null,
    })).filter(c => c.label);
    const clean = cleanFields({counts, anglers: (input.anglers as number | undefined) ?? null, trip_type: typeof input.trip_type === 'string' ? normalizeTrip(input.trip_type) : null,
      notes: typeof input.notes === 'string' ? input.notes : null});
    const fields: ReportFields = {report_date: date, trip_type: clean.trip_type ?? null, anglers: clean.anglers ?? null, counts: clean.counts ?? [], notes: clean.notes ?? null};
    if (!fields.counts.length && fields.anglers === null) return {result: {proposed: false, reason: 'no counts'}};
    const draft = await draftActions({db: ctx.db, settings: ctx.settings, contact: ctx.contact, boat, messageId: ctx.message.id, language: ctx.language, now: ctx.now, fields, source: 'text', mediaId: null});
    return {result: {proposed: true, report_id: draft.reportId, updated_existing: draft.edited, note: 'The system has texted the draft and the confirmation question. Add one short line at most.'}, actions: draft.actions};
  },
};
