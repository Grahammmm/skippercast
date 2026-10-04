// share_angler_photo (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-I3 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const shareAnglerPhoto = stubTool({
  name: 'share_angler_photo',
  description: "Record whether an angler agrees to SkipperCast sharing their photo with credit.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id', 'consent'], properties: {media_id: {type: 'string'}, consent: {type: 'boolean'}}},
  roles: ['angler'],
  intent: 'photo.share',
});
