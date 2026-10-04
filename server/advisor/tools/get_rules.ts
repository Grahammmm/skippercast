// get_rules (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 § fish ID
// step 3, ID-2, OP-6): the reviewed rules table for a species in a region. Each
// rule carries its source, the date a person last checked it and `stale`; the
// model must say "double-check" for a stale rule and give the rules link. An
// empty list is still a real answer (the engine's rules guard counts any call
// that is not an error or `unavailable`): the model then says to check CDFW.
import type {AdvisorTool} from './tool.ts';
import {lookupRules} from '../answers/rules.ts';
import {contactRegion, resolveSpecies} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';

const MAX_RULES = 6, NOTE = 280;
const clip = (s: string | null): string | null => s && s.length > NOTE ? `${s.slice(0, NOTE - 1).replace(/\s+\S*$/, '')}…` : s;

export const getRules: AdvisorTool = {
  name: 'get_rules',
  description: "The current fishing rules for a species in a region from SkipperCast's reviewed rules table, with the source and the date a person last checked it. The only source of size limits, bag limits, seasons, closures and depth limits: never state one without calling this. A row with stale: true must be quoted with \"double-check\".",
  input_schema: {type: 'object', additionalProperties: false, required: ['species_key'], properties: {species_key: {type: 'string'}, region: {type: 'string', description: 'Region id; default: the contact region'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'rules',
  async run(input, ctx) {
    const asked = String(input.species_key ?? '');
    const species = resolveSpecies(asked)?.key ?? asked.trim().toLowerCase();
    const wanted = typeof input.region === 'string' && regionConfig(input.region) ? input.region : contactRegion(ctx.contact, ctx.settings);
    const rules = (await lookupRules(ctx.db, {region: wanted, speciesKey: species, now: ctx.now})).slice(0, MAX_RULES);
    return {result: {
      species_key: species, region: wanted,
      rules: rules.map(r => ({
        species_key: r.species_key, label: r.species_label, applies_as: r.applies_as,
        size_min_in: r.size_min_in, size_max_in: r.size_max_in, bag_limit: r.bag_limit, bag_notes: clip(r.bag_notes),
        season_open: r.season_open, season_close: r.season_close, depth_limit_ft: r.depth_limit_ft,
        area_notes: clip(r.area_notes), gear_notes: clip(r.gear_notes),
        source_name: r.source_name, source_url: r.source_url, checked: r.reviewed_at.slice(0, 10), review_due: r.review_due, stale: r.stale,
      })),
      any_stale: rules.some(r => r.stale),
      link: `{{link:rules:${species}}}`,
      note: rules.length ? 'Quote only these rows, with the source and checked date. A stale row: say "double-check" and give the link.' : 'No reviewed rule for this species here: say to check the current CDFW rules and give the link. Do not state a number.',
    }};
  },
};
