// register_boat (04 § Tools, 05 § Becoming a skipper, SK-1): the model heard
// someone say they run a boat ("I run the Sea Example") and passes whatever fields
// it already has. This starts the deterministic registration flow
// (intake/skippers.ts): the system texts the next missing question itself and
// every later answer is parsed by the flow, not the model. With every field
// given it completes at once (boat_create, the new_skipper review, the
// completion text and the consent question). Invalid fields are dropped and
// asked again by the flow.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';
import {parseName, parsePort, parseLanding, parseInstagram, parseBooking, registrationBlocked, startRegistration} from '../intake/skippers.ts';
import type {FlowState} from '../types.ts';

export const registerBoat: AdvisorTool = {
  name: 'register_boat',
  description: "Start setting up a boat page for a person who says they run a charter or party boat (\"I'm the captain of the Sea Example\", \"I run a six-pack out of Morro\"). Pass only what they already told you; leave the rest out. The system then texts them the remaining questions one at a time and the photo-consent question, so after calling it reply with one short line at most and do not ask those questions yourself.",
  input_schema: {type: 'object', additionalProperties: false, properties: {
    name: {type: 'string', maxLength: 60, description: 'The boat name as they wrote it'},
    port: {type: 'string', enum: [...PORT_IDS], description: 'Home port id'},
    landing: {type: 'string', maxLength: 60},
    instagram: {type: 'string', maxLength: 31},
    booking_url: {type: 'string', maxLength: 300, description: 'An https booking link or a public phone for the boat page'},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'skipper.register',
  async run(input, ctx) {
    if (!ctx.contact.phone_enc) return {result: {started: false, reason: 'boats register by text message, not on the web chat'}};
    const blocked = await registrationBlocked(ctx.db, ctx.settings, ctx.contact, ctx.language);
    if (blocked) return {result: {started: false, reason: 'this contact already owns a boat; registration is done'}};
    const draft: FlowState['draft'] = {}, dropped: string[] = [];
    const take = <T>(key: string, value: unknown, parse: (v: string) => T | null, set: (v: T) => void) => {
      if (value === undefined || value === null || value === '') return;
      const v = typeof value === 'string' ? parse(value) : null;
      if (v === null) dropped.push(key); else set(v);
    };
    take('name', input.name, parseName, v => { draft.name = v; });
    take('port', input.port, v => parsePort(v), v => { draft.port = v; });
    take('landing', input.landing, parseLanding, v => { draft.landing = v; });
    take('instagram', input.instagram, parseInstagram, v => { draft.instagram = v; });
    take('booking_url', input.booking_url, parseBooking, v => { draft.booking_url = v.booking_url; draft.phone_public = v.phone_public; });
    const out = await startRegistration({db: ctx.db, settings: ctx.settings, contact: ctx.contact, messageId: ctx.message.id, language: ctx.language, now: ctx.now, draft, intro: false});
    const done = out.intent === 'skipper.register.done';
    return {result: {started: true, registered: done, ignored: dropped,
      note: done ? 'The boat is set up; the system has texted the confirmation and the consent question. Add nothing.' : 'The system has texted the next question. Reply with one short line at most; do not ask it yourself.'}, actions: out.actions};
  },
};
