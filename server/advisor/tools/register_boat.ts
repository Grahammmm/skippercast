// register_boat (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I1 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';

export const registerBoat = stubTool({
  name: 'register_boat',
  description: "Register the boat of a person who says they run a charter or party boat.",
  input_schema: {type: 'object', additionalProperties: false, required: ['name', 'port'], properties: {name: {type: 'string', maxLength: 60}, landing: {type: 'string', maxLength: 60}, port: {type: 'string', enum: [...PORT_IDS]}, instagram: {type: 'string', maxLength: 31}, booking_url: {type: 'string', maxLength: 300}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'skipper.register',
});
