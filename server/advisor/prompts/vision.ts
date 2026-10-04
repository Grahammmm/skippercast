// Vision prompts (docs/plans/text-advisor/07-vision.md § Claude provider). The
// answer shape is not described here: each request forces one tool whose
// input_schema is the result schema (vision/claude.ts), so the prompts say only
// what to look for and how to judge it. Plain template functions, no I/O.
import type {VisionSpecies} from '../vision/species.ts';

/** classify: the kind definitions and the has_person rule. */
export function classifyPrompt(): string {
  return `Classify this photo for a fishing-report service. Report what you see with the record_classification tool.

Kinds (pick one):
- count_board: a whiteboard, chalkboard, printed sheet or screen listing catch counts, usually with a boat name and a date.
- fish: a single fish or a few fish shown for identification.
- action: people fishing, a boat deck, a fish being landed.
- scenery: the ocean, a harbor, a sunset, a boat with no fishing in progress.
- video: a still from a video or a video player screenshot.
- document: a receipt, license, ticket, map or other paper or screen that is not a count board.
- unknown: none of the above, or you cannot tell.

Rules:
- kind_confidence is your honest probability (0 to 1) that the kind is right.
- has_person is true for any recognisable face or body. A hand or arm holding a fish is has_person=false unless a face is visible. person_confidence is your probability that a person is visible.
- has_fish is true when any fish, crab or other catch is visible.
- text_present is true when there is legible handwriting or print, however little.
- nsfw is true for nudity, gore beyond normal fish cleaning, or anything unsuitable for a public fishing page.`;
}

/** count board: transcription rules. */
export function countBoardPrompt(): string {
  return `This photo is a fishing count board from a sport-fishing boat or landing. Transcribe it with the record_count_board tool.

Rules:
- Transcribe every catch line, top to bottom, one entry per species or group.
- label: the text as written ("Lings", "Verm", "Reds"). Expand only obvious abbreviations in your head; keep the original label in the output.
- count: the number kept. released: a released count when the board shows one (often "rel", "R" or a number in brackets), else null.
- A number you cannot read is null, with low confidence for that line. Never guess a digit.
- boat_name and date_text exactly as written, or null when not on the board. Never invent a boat name or a date.
- date_iso (YYYY-MM-DD) only when the written date is unambiguous; otherwise null. date_confidence is your probability the date is right.
- trip_type as written ("3/4 day", "full day", "overnight") or null. anglers: the angler or passenger count when shown, else null.
- notes: any other short remark on the board (limits, "lim of rock", weather), or null.
- confidence values are honest probabilities from 0 to 1. overall_confidence covers the whole reading: low when the board is blurry, cropped or partly hidden.`;
}

const line = (s: VisionSpecies): string => `- ${s.key}: ${s.name}${s.cues.length ? ' — ' + s.cues.slice(0, 3).join('; ') : ''}${s.lookalikes.length ? ` (often confused with ${s.lookalikes.join(', ')})` : ''}`;

/** fish ID: the region's species list with 2-3 cues each (catalog/advisor/lookalikes.json). */
export function fishIdPrompt(species: readonly VisionSpecies[]): string {
  return `Identify the fish (or crab) in this photo for an angler off the California coast. Answer with the record_fish_id tool.

Species this service knows, with field marks:
${species.map(line).join('\n')}

Rules:
- Give up to three candidates, most likely first. species_key must be one of the keys above, or null when it is none of them; label is always the common name you would say out loud.
- confidence is your honest probability (0 to 1) that the candidate is right; the three should not add up to more than 1.
- cues: the visible features that support the candidate (short phrases, at most three).
- Set needs_better_photo when the fish is partly out of frame, blurry, too far away, or several different fish are shown; give the reason as one of blurry, partial, multiple_fish, no_fish, too_far, other.
- If no fish is visible, return no candidates, needs_better_photo=true and reason no_fish.`;
}
