// add_crew (04 § Tools, 05 § Crew, SK-3): the boat's owner invites a crew
// member by phone number. The number goes straight to hashing and encryption;
// the result never echoes it. The consumer (crew_add) finds or creates the
// contact, records a pending invitation (job_state advisor.crewinvite.<id>)
// and texts it through that contact's channel; the contact becomes crew only
// after replying YES within 72 hours (intake/skippers.ts crewInviteFlow,
// consumer crew_accept). Only the owner of a verified boat may invite.
//
// The result is the same whether or not the invitation can go out (a stopped
// number, a recent NO to this boat, another boat's owner): it never says
// whether the number is known to us.
import type {AdvisorTool} from './tool.ts';
import {deriveKeys, e164, encryptPhone, phoneHash} from '../contacts.ts';
import {isVerified, ownedBoat} from '../intake/skippers.ts';

export const MAX_CREW = 20;
/** What the model hears for an invitation, whether it goes out or is quietly dropped. */
export const INVITED = Object.freeze({invited: true, note: 'An invitation is texted to that number if it can receive one. They join the crew only after they reply YES within 72 hours.'});

export const addCrew: AdvisorTool = {
  name: 'add_crew',
  description: "Invite a crew member to the skipper's boat by their US mobile number. They get a text and join the crew only when they reply YES (within 72 hours); until then nothing they send is credited to the boat. Only the owner of a verified boat can do this. Never repeat the number back.",
  input_schema: {type: 'object', additionalProperties: false, required: ['phone'], properties: {phone: {type: 'string', description: 'The number exactly as the skipper typed it'}}},
  roles: ['skipper'],
  intent: 'skipper.crew',
  async run(input, ctx) {
    const boat = await ownedBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {added: false, reason: "only the boat's owner can add crew"}};
    if (!isVerified(boat.status)) return {result: {added: false, reason: 'crew can be added once the SkipperCast team has verified the boat'}};
    const number = e164(input.phone);
    if (!number) return {result: {added: false, reason: 'not a US mobile number'}};
    if (!ctx.env.ADVISOR_PHONE_KEY) return {result: {added: false, reason: 'texting is not set up yet'}};
    const keys = await deriveKeys(ctx.env.ADVISOR_PHONE_KEY);
    const hash = await phoneHash(keys, number);
    if (hash === ctx.contact.phone_hash) return {result: {added: false, reason: "that is the skipper's own number"}};
    const crew = await ctx.db.prepare('SELECT COUNT(*) AS n FROM advisor_crew WHERE boat_id=? AND removed_at IS NULL').bind(boat.id).first<{n: number}>();
    if ((crew?.n ?? 0) >= MAX_CREW) return {result: {added: false, reason: `a boat has at most ${MAX_CREW} crew`}};
    return {result: {...INVITED}, actions: [{type: 'crew_add', boatId: boat.id, phoneHash: hash, phoneEnc: await encryptPhone(keys, number)}]};
  },
};
