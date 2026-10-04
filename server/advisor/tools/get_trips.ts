// get_trips (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-E2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';

export const getTrips = stubTool({
  name: 'get_trips',
  description: "Verified charter and party boats for a port, with their landing, trip types, booking link and boat page. Never rank one boat over another.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {port: {type: 'string', enum: [...PORT_IDS]}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'trips',
});
