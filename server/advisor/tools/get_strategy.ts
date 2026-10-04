// get_strategy (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-E2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const getStrategy = stubTool({
  name: 'get_strategy',
  description: "How to fish for a species in a region: rig, bait or lure, line, weight, depth band, and general areas or named public grounds. Never a coordinate or anyone's spot.",
  input_schema: {type: 'object', additionalProperties: false, required: ['species_key'], properties: {species_key: {type: 'string'}, region: {type: 'string'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'strategy',
});
