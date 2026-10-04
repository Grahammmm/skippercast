// remove_crew (04 § Tools, 05 § Crew, SK-3): the boat's owner removes a crew
// member by phone number. The consumer (crew_remove) sets advisor_crew.removed_at
// (the row stays for audit) and clears the contact's boat_id, so its later
// photos are an angler's. Only the boat's owner_contact_id may remove; the
// result never echoes the number.
import type {AdvisorTool} from './tool.ts';
import {deriveKeys, e164, phoneHash} from '../contacts.ts';
import {ownedBoat} from '../intake/skippers.ts';

export const removeCrew: AdvisorTool = {
  name: 'remove_crew',
  description: "Remove a crew member from the skipper's boat by their phone number. Only the boat's owner can do this. Never repeat the number back.",
  input_schema: {type: 'object', additionalProperties: false, required: ['phone'], properties: {phone: {type: 'string'}}},
  roles: ['skipper'],
  intent: 'skipper.crew',
  async run(input, ctx) {
    const boat = await ownedBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {removed: false, reason: "only the boat's owner can remove crew"}};
    const number = e164(input.phone);
    if (!number) return {result: {removed: false, reason: 'not a US mobile number'}};
    if (!ctx.env.ADVISOR_PHONE_KEY) return {result: {removed: false, reason: 'texting is not set up yet'}};
    const hash = await phoneHash(await deriveKeys(ctx.env.ADVISOR_PHONE_KEY), number);
    const row = await ctx.db.prepare(`SELECT c.id FROM advisor_contacts c JOIN advisor_crew w ON w.contact_id=c.id
        WHERE c.phone_hash=? AND w.boat_id=? AND w.removed_at IS NULL`).bind(hash, boat.id).first<{id: string}>();
    if (!row) return {result: {removed: false, reason: 'that number is not crew on this boat'}};
    return {result: {removed: true}, actions: [{type: 'crew_remove', boatId: boat.id, contactId: row.id}]};
  },
};
