// propose_post (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const proposePost = stubTool({
  name: 'propose_post',
  description: "Draft a social post from a skipper's catch or action photo for the team to review.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string'}, hint: {type: 'string', maxLength: 200}}},
  roles: ['skipper', 'crew'],
  intent: 'post.draft',
});
