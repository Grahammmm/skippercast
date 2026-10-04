// get_strategy (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 §
// rigging and area advice; AD-1, AD-2, principle 7): how to fish a species in a
// region (answers/advice.ts): rig, bait or lure, depth band, season note, and
// only allowlisted public grounds (catalog/advisor/public-grounds.json) with
// broad descriptions. The region's search-plans.json spot names (read from the
// built site through ASSETS when it is bound) go through the same allowlist, so
// a search-plan name that is not a public ground never comes out. Never a
// coordinate. `first_time` is true when this contact has not asked a strategy
// question before; the prompt then ends the reply with the AD-2 line.
import type {AdvisorTool, ToolContext} from './tool.ts';
import {strategyFor} from '../answers/advice.ts';
import {contactRegion, resolveSpecies} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';
import {t} from '../strings.ts';

/** The AD-2 line in English (the prompt quotes it); the note gives it in the reply language (TA-A6). */
export const AD2_LINE = t('en', 'ad2_line');

/** The spot names in a region's published search plans (dist/regions/<id>/search-plans.json), or [] when ASSETS is not bound or the file is missing. */
export async function searchPlanNames(ctx: Pick<ToolContext, 'env'>, region: string, species: string): Promise<string[]> {
  const assets = ctx.env?.ASSETS;
  if (!assets || !/^[a-z0-9-]{1,64}$/.test(region)) return [];
  try {
    const response = await assets.fetch(new Request(`https://assets.local/regions/${region}/search-plans.json`));
    if (!response.ok) return [];
    const plans = await response.json() as {features?: {properties?: {name?: unknown; species?: unknown}}[]};
    return (plans.features ?? []).map(f => f.properties).filter(p => typeof p?.name === 'string' && (!Array.isArray(p.species) || p.species.includes(species) || (species !== 'reef' && p.species.includes('reef'))))
      .map(p => p!.name as string);
  } catch { return []; }
}

export const getStrategy: AdvisorTool = {
  name: 'get_strategy',
  description: "How to fish for a species in a region: rig, bait or lure, line, weight, depth band, and general areas or named public grounds. Never a coordinate or anyone's spot.",
  input_schema: {type: 'object', additionalProperties: false, required: ['species_key'], properties: {species_key: {type: 'string'}, region: {type: 'string'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'strategy',
  async run(input, ctx) {
    const key = resolveSpecies(String(input.species_key ?? ''))?.key ?? String(input.species_key ?? '').trim().toLowerCase();
    const region = typeof input.region === 'string' && regionConfig(input.region) ? input.region : contactRegion(ctx.contact, ctx.settings);
    const names = await searchPlanNames(ctx, region, key);
    const strategy = strategyFor(key, region, names);
    if (!strategy) return {result: {error: 'no method notes for this species', species_key: key.slice(0, 40)}};
    const earlier = await ctx.db.prepare("SELECT 1 AS x FROM advisor_messages WHERE contact_id=? AND direction='in' AND intent='strategy' AND id<>? LIMIT 1")
      .bind(ctx.contact.id, ctx.message.id).first();
    return {result: {
      ...strategy,
      first_time: !earlier,
      note: `General areas and depth bands only. Missing fields are not in our notes: do not fill them in.${earlier ? '' : ` This is the first time they asked: end the reply with "${t(ctx.language, 'ad2_line')}"`}`,
      link: `{{link:species:${strategy.species_key}}}`,
    }};
  },
};
