// edit_report (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const editReport = stubTool({
  name: 'edit_report',
  description: "Correct a skipper's report (\"lings were 14\").",
  input_schema: {type: 'object', additionalProperties: false, required: ['report_id', 'patch'], properties: {report_id: {type: 'string'}, patch: {type: 'object'}}},
  roles: ['skipper', 'crew'],
  intent: 'report.edit',
});
