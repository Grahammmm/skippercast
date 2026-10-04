// get_port_report (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-E2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';

export const getPortReport = stubTool({
  name: 'get_port_report',
  description: "Recent fish reports for a port: the day's summary, the latest skipper reports (date, boat, counts, whether the boat is verified) and the landing's reports labelled as such, with how fresh they are. Use it for \"what's biting\" and before mentioning any catch. Never turn it into odds.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {port: {type: 'string', enum: [...PORT_IDS], description: 'Port id'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'reports',
});
