// add_crew (04 § Tools, 05 § Crew, SK-3): the boat's owner adds a crew member
// by phone number. The number goes straight to hashing and encryption; the
// result is {added: true} only, so the model never sees it echoed. The
// consumer (crew_add) finds or creates the crew contact (role crew, the boat),
// records advisor_crew with added_by, and texts the invite to the crew number
// through that contact's channel. Only the boat's owner_contact_id may add.
import type {AdvisorTool} from './tool.ts';
import {deriveKeys, e164, encryptPhone, phoneHash} from '../contacts.ts';
import {ownedBoat} from '../intake/skippers.ts';

export const MAX_CREW = 20;

export const addCrew: AdvisorTool = {
  name: 'add_crew',
  description: "Add a crew member to the skipper's boat by their US mobile number; they get a text inviting them to send count boards and photos for the boat. Only the boat's owner can do this. Never repeat the number back.",
  input_schema: {type: 'object', additionalProperties: false, required: ['phone'], properties: {phone: {type: 'string', description: 'The number exactly as the skipper typed it'}}},
  roles: ['skipper'],
  intent: 'skipper.crew',
  async run(input, ctx) {
    const boat = await ownedBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {added: false, reason: "only the boat's owner can add crew"}};
    const number = e164(input.phone);
    if (!number) return {result: {added: false, reason: 'not a US mobile number'}};
    if (!ctx.env.ADVISOR_PHONE_KEY) return {result: {added: false, reason: 'texting is not set up yet'}};
    const keys = await deriveKeys(ctx.env.ADVISOR_PHONE_KEY);
    const hash = await phoneHash(keys, number);
    if (hash === ctx.contact.phone_hash) return {result: {added: false, reason: "that is the skipper's own number"}};
    const existing = await ctx.db.prepare('SELECT id,status FROM advisor_contacts WHERE phone_hash=?').bind(hash).first<{id: string; status: string}>();
    if (existing && existing.status !== 'active') return {result: {added: false, reason: 'that number cannot be texted'}};
    if (existing && await ctx.db.prepare('SELECT 1 AS x FROM advisor_boats WHERE owner_contact_id=?').bind(existing.id).first()) return {result: {added: false, reason: 'that number runs its own boat'}};
    const crew = await ctx.db.prepare('SELECT COUNT(*) AS n FROM advisor_crew WHERE boat_id=? AND removed_at IS NULL').bind(boat.id).first<{n: number}>();
    if ((crew?.n ?? 0) >= MAX_CREW) return {result: {added: false, reason: `a boat has at most ${MAX_CREW} crew`}};
    return {result: {added: true}, actions: [{type: 'crew_add', boatId: boat.id, phoneHash: hash, phoneEnc: await encryptPhone(keys, number)}]};
  },
};
