// get_conditions (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-E2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';

export const getConditions = stubTool({
  name: 'get_conditions',
  description: "Wind, gusts, seas, swell period and direction for a port's fishing window on a date, and any small craft advisory, gale warning or hazardous seas statement. Call it before any trip-planning answer; lead with an advisory when there is one.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {port: {type: 'string', enum: [...PORT_IDS]}, date: {type: 'string', description: 'YYYY-MM-DD, or a word the person used such as Saturday or tomorrow'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'conditions',
});
