// add_crew (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I1 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const addCrew = stubTool({
  name: 'add_crew',
  description: "Add a crew member to the skipper's boat by their phone number.",
  input_schema: {type: 'object', additionalProperties: false, required: ['phone'], properties: {phone: {type: 'string'}}},
  roles: ['skipper'],
  intent: 'skipper.crew',
});
