// The shape every Text Advisor tool file exports (docs/plans/text-advisor/04-advisor-engine.md
// § Tools), kept apart from the registry (index.ts) so tool files never import
// the registry that imports them.
import type {Env} from '../../env.ts';
import type {Action, AdvisorContactRow, AdvisorMessageRow, AdvisorSettings, EngineDeps, Language} from '../types.ts';

/** Who may see a tool: contact roles, plus 'web' for tools offered only on the web chat. */
export type ToolAudience = 'angler' | 'skipper' | 'crew' | 'web';

/** What a tool may read. `db` is the same D1 handle; tools treat it as read-only. */
export interface ToolContext {
  env: Env; contact: AdvisorContactRow; message: AdvisorMessageRow; deps: EngineDeps; db: D1Database;
  language: Language; settings: AdvisorSettings; now: number;
}
export interface ToolOutput {result: unknown; actions?: Action[]}
export interface AdvisorTool {
  name: string;
  description: string;
  input_schema: {type: 'object'; properties: Record<string, unknown>; required?: string[]; additionalProperties?: boolean};
  /** Roles that see the tool. 'web' alone means web contacts only, whatever their role. */
  roles: readonly ToolAudience[];
  /** The intent label a turn records when this is its first tool (04 § intent recording). */
  intent: string;
  run(input: Record<string, unknown>, ctx: ToolContext): Promise<ToolOutput>;
}

/** The result every not-yet-built tool returns, so the model says it can't check that yet. */
/** The characters of a tool result the model sees (engine.ts cuts longer JSON, which would no longer parse). */
export const TOOL_RESULT_MAX = 4000;

export const NOT_BUILT = Object.freeze({unavailable: true, reason: 'not built yet'});
/** A stub with its final schema: answers NOT_BUILT until its task replaces the file. */
export function stubTool(def: Omit<AdvisorTool, 'run'>): AdvisorTool {
  return {...def, run: async () => ({result: NOT_BUILT})};
}

