// identify_fish (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I3 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const identifyFish = stubTool({
  name: 'identify_fish',
  description: "Identify the fish in a photo the person sent: species candidates with confidence, the cues that tell them apart, and whether a better photo is needed.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'fishid',
});
