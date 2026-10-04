// read_count_board (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const readCountBoard = stubTool({
  name: 'read_count_board',
  description: "Read a skipper's count-board photo into a draft report for them to confirm.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string'}}},
  roles: ['skipper', 'crew'],
  intent: 'report.count_board',
});
