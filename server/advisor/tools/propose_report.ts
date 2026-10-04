// propose_report (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const proposeReport = stubTool({
  name: 'propose_report',
  description: "Turn a skipper's typed counts into a draft report for them to confirm.",
  input_schema: {type: 'object', additionalProperties: false, required: ['counts'], properties: {report_date: {type: 'string', description: 'YYYY-MM-DD; default today'}, anglers: {type: 'integer', minimum: 0}, trip_type: {type: 'string', maxLength: 30}, counts: {type: 'array', items: {type: 'object', additionalProperties: false, required: ['label'], properties: {species_key: {type: 'string'}, label: {type: 'string'}, kept: {type: 'integer', minimum: 0}, released: {type: 'integer', minimum: 0}}}}, notes: {type: 'string', maxLength: 280}}},
  roles: ['skipper', 'crew'],
  intent: 'report.text',
});
