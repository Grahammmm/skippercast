// edit_report (04 § Tools, 05 § Corrections, SC-4): a correction the
// deterministic parser (parseCorrection) did not take ("make the reds 40 and
// drop the cabezon"). The model passes the report id from the brief and a
// patch list; each entry sets a line ({label, kept?, released?}), removes one
// ({label, remove: true}) or sets anglers, trip_type, report_date or notes.
// The edit is the same report_edit action the deterministic path uses: an
// advisor_report_edits row, version + 1, and the corrected lines texted back.
import type {AdvisorTool} from './tool.ts';
import {boatToday, cleanFields, contactBoat, correctionActions, fieldsOf, normalizeTrip, parseDateWords, patchOf, speciesKeyFor, CORRECTION_DAYS} from '../intake/reports.ts';
import type {Change, ReportRow} from '../intake/reports.ts';
import type {ReportCount, ReportEditFields} from '../types.ts';
import {fold} from '../answers/resolve.ts';

const MAX_PATCH = 12;

export const editReport: AdvisorTool = {
  name: 'edit_report',
  description: "Correct a skipper's report (\"lings were 14\", \"drop the cabezon\", \"it was yesterday\"). report_id is in the contact brief. Each patch entry is one change: {label, kept?, released?} sets or adds a species line, {label, remove: true} removes it, or {field: 'anglers'|'trip_type'|'report_date'|'notes', value}. The system texts the corrected lines; reply with one short line at most.",
  input_schema: {type: 'object', additionalProperties: false, required: ['report_id', 'patch'], properties: {report_id: {type: 'string'}, patch: {type: 'array', maxItems: MAX_PATCH, items: {type: 'object', additionalProperties: false, properties: {
    label: {type: 'string', maxLength: 40}, kept: {type: 'integer', minimum: 0}, released: {type: 'integer', minimum: 0}, remove: {type: 'boolean'},
    field: {type: 'string', enum: ['anglers', 'trip_type', 'report_date', 'notes']}, value: {type: 'string', description: 'The new value: a number for anglers, YYYY-MM-DD or "yesterday" for report_date'},
  }}}}},
  roles: ['skipper', 'crew'],
  intent: 'report.edit',
  async run(input, ctx) {
    const boat = await contactBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {edited: false, reason: 'this contact is not linked to a boat'}};
    const today = boatToday(boat, ctx.now);
    const row = await ctx.db.prepare("SELECT * FROM advisor_reports WHERE id=? AND boat_id=? AND status IN ('pending_confirm','published') AND report_date>=?")
      .bind(String(input.report_id ?? ''), boat.id, new Date(Date.parse(`${today}T12:00:00Z`) - CORRECTION_DAYS * 86400000).toISOString().slice(0, 10)).first<ReportRow>();
    if (!row) return {result: {edited: false, reason: 'no report with that id for this boat in the last 7 days'}};
    const entries = (Array.isArray(input.patch) ? input.patch : []).slice(0, MAX_PATCH).filter((p): p is Record<string, unknown> => Boolean(p) && typeof p === 'object');
    const before = fieldsOf(row), counts = before.counts.map(c => ({...c}));
    const fields: ReportEditFields = {}, changes: Change[] = [], rejected: number[] = [];
    entries.forEach((p, i) => {
      if (typeof p.field === 'string') {
        if (p.field === 'anglers' && Number.isInteger(Number(p.value)) && Number(p.value) >= 0) { fields.anglers = Number(p.value); changes.push({kind: 'anglers', n: fields.anglers}); return; }
        if (p.field === 'trip_type' && typeof p.value === 'string' && normalizeTrip(p.value)) { fields.trip_type = normalizeTrip(p.value); changes.push({kind: 'trip', trip: fields.trip_type!}); return; }
        if (p.field === 'report_date' && typeof p.value === 'string') { const d = parseDateWords(p.value, today); if (d) { fields.report_date = d; changes.push({kind: 'date', date: d}); return; } }
        if (p.field === 'notes' && typeof p.value === 'string') { fields.notes = p.value; return; }
        rejected.push(i); return;
      }
      const label = typeof p.label === 'string' ? p.label.trim() : '';
      if (!label) { rejected.push(i); return; }
      const at = counts.findIndex(c => fold(c.label) === fold(label) || (c.species_key !== 'other' && c.species_key === speciesKeyFor(label) && fold(c.label).startsWith(fold(label).slice(0, 4))));
      if (p.remove === true) { if (at < 0) { rejected.push(i); return; } const [gone] = counts.splice(at, 1); changes.push({kind: 'removed', label: gone!.label}); return; }
      const kept = Number.isInteger(p.kept) ? p.kept as number : undefined, released = Number.isInteger(p.released) ? p.released as number : undefined;
      if (kept === undefined && released === undefined) { rejected.push(i); return; }
      const line: ReportCount = at >= 0 ? counts[at]! : {species_key: speciesKeyFor(label), label, kept: null, released: null};
      if (kept !== undefined) line.kept = kept;
      if (released !== undefined) line.released = released;
      delete line.uncertain;
      if (at < 0) counts.push(line);
      changes.push({kind: 'count', line});
    });
    if (changes.some(c => c.kind === 'count' || c.kind === 'removed')) fields.counts = counts;
    const clean = cleanFields(fields);
    const patch = patchOf(before, clean);
    if (!patch.length) return {result: {edited: false, reason: 'nothing to change', rejected}};
    const actions = await correctionActions(ctx.db, ctx.settings, ctx.language, row, {fields: clean, patch, changes});
    const ok = actions.some(a => a.type === 'report_edit');
    return {result: {edited: ok, ...(ok ? {} : {reason: 'another report of this boat already has that date'}), rejected, note: 'The system has texted the corrected lines. Add one short line at most.'}, actions};
  },
};
