// The model's tools (docs/plans/text-advisor/04-advisor-engine.md § Tools).
// Each file exports one AdvisorTool: {name, description, input_schema, roles,
// run(input, ctx)}. run() returns a compact JSON result for the model and,
// optionally, actions for the consumer to apply; a tool never writes to D1
// itself (except rate counters in request_limits), so a crash before the apply
// step leaves nothing half-done. Admin actions (verify, approve, publish,
// change a rule) have no tool: the engine proposes, routes/admin.ts decides.
//
// TA-E2 replaces the data-tool stubs (get_port_report, get_conditions,
// get_rules, get_species, get_strategy, get_trips; identify_fish with TA-I3);
// TA-I1/I2/I3 replace the skipper-tool stubs. Each stub already has its final
// name, roles and input_schema, so the prompt and tests do not change when the
// file does.
import type {AdvisorContactRow} from '../types.ts';
import type {AdvisorTool, ToolAudience, ToolContext, ToolOutput} from './tool.ts';
export {NOT_BUILT, stubTool} from './tool.ts';
export type {AdvisorTool, ToolAudience, ToolContext, ToolOutput} from './tool.ts';
import {updateProfile} from './update_profile.ts';
import {escalate} from './escalate.ts';
import {sendUploadLink} from './send_upload_link.ts';
import {sendContactCard} from './send_contact_card.ts';
import {offerTextLink} from './offer_text_link.ts';
import {getPortReport} from './get_port_report.ts';
import {getConditions} from './get_conditions.ts';
import {getRules} from './get_rules.ts';
import {getSpecies} from './get_species.ts';
import {getStrategy} from './get_strategy.ts';
import {getTrips} from './get_trips.ts';
import {identifyFish} from './identify_fish.ts';
import {readCountBoard} from './read_count_board.ts';
import {proposeReport} from './propose_report.ts';
import {editReport} from './edit_report.ts';
import {proposePost} from './propose_post.ts';
import {registerBoat} from './register_boat.ts';
import {addCrew} from './add_crew.ts';
import {removeCrew} from './remove_crew.ts';
import {shareAnglerPhoto} from './share_angler_photo.ts';

const ALL: readonly ToolAudience[] = ['angler', 'skipper', 'crew'];
export const ANYONE = ALL;

/** Every tool, in the order the model sees them. */
export const TOOLS: readonly AdvisorTool[] = [
  updateProfile, getPortReport, getConditions, getRules, getSpecies, getStrategy, getTrips, identifyFish,
  readCountBoard, proposeReport, editReport, proposePost, registerBoat, addCrew, removeCrew, shareAnglerPhoto,
  sendUploadLink, sendContactCard, offerTextLink, escalate,
];
export const TOOL_BY_NAME: ReadonlyMap<string, AdvisorTool> = new Map(TOOLS.map(tool => [tool.name, tool]));

/** True for a web chat visitor not linked to a number (03 § web). */
export const isWebOnly = (contact: Pick<AdvisorContactRow, 'phone_enc' | 'web_session'>): boolean => !contact.phone_enc && Boolean(contact.web_session);

/**
 * The tools this contact may use: by role (anglers never see skipper tools;
 * the admin-test role sees what an angler sees), and web-only tools only on
 * the web chat. Nobody sees an admin tool: there is none.
 */
export function toolsForRole(contact: Pick<AdvisorContactRow, 'role' | 'phone_enc' | 'web_session'>): AdvisorTool[] {
  const role: ToolAudience = contact.role === 'skipper' || contact.role === 'crew' ? contact.role : 'angler';
  const web = isWebOnly(contact);
  return TOOLS.filter(tool => tool.roles.includes('web') ? web : tool.roles.includes(role));
}

/** The Messages API `tools` array; the last definition carries cache_control so the whole list is cached with the system prompt. */
export function claudeTools(tools: readonly AdvisorTool[]): Record<string, unknown>[] {
  return tools.map((tool, i) => ({name: tool.name, description: tool.description, input_schema: tool.input_schema,
    ...(i === tools.length - 1 ? {cache_control: {type: 'ephemeral'}} : {})}));
}

/**
 * Run one tool_use block. A tool the contact may not use, an unknown name or
 * a throwing executor becomes an error result for the model (is_error), never
 * an exception out of the turn.
 */
export async function dispatchTool(name: string, input: unknown, ctx: ToolContext, allowed: readonly AdvisorTool[]): Promise<ToolOutput & {isError: boolean}> {
  const tool = allowed.find(t => t.name === name);
  if (!tool) return {result: {error: 'unknown tool'}, isError: true};
  const args = input && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, unknown> : {};
  try {
    const out = await tool.run(args, ctx);
    return {...out, isError: false};
  } catch (error) {
    return {result: {error: String((error as Error)?.message ?? error).slice(0, 120)}, isError: true};
  }
}
