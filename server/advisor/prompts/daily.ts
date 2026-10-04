// The daily port answer prompt (docs/plans/text-advisor/06-angler-answers.md §
// "What's biting", FR-1, FR-4): one fixed template, the facts as JSON, and one
// forced tool whose input_schema is {en, es}, so the answer comes back as
// structured tool input in both languages (the vision/claude.ts trick). Plain
// template functions, no I/O. The owner reviews this wording like the system
// prompt.

/** The forced tool: both languages in one call (06 left the choice to TA-A1). */
export const DAILY_TOOL = {
  name: 'record_daily_answer',
  description: "Record today's port answer in English and Spanish.",
  input_schema: {
    type: 'object', additionalProperties: false, required: ['en', 'es'],
    properties: {
      en: {type: 'string', maxLength: 420, description: 'The answer in English, at most 420 characters, ending with the link placeholder.'},
      es: {type: 'string', maxLength: 420, description: 'The same answer in Spanish (Latin American, tú), at most 420 characters, ending with the link placeholder.'},
    },
  },
} as const;

/** The body length the prompt asks for; the resolved link is added on top and the whole stays within 480 (three SMS segments). */
export const DAILY_BODY_MAX = 420;

export function dailyPrompt(facts: unknown, link: string): string {
  return `You write SkipperCast's one text-message answer to "what's biting" for a port today. Fishermen read it on their phone at the dock. Use only the facts below; never add a fish, a number, a boat or a place that is not in them.

Write it like this English example (the facts in it are made up):
Morro Bay, Sat Oct 3: 3 boats reported Fri, limits of rockfish for most trips (vermilion, copper), lingcod 8-14 per boat, a few cabezon. Seas 4-5 ft at 9 s, wind light until noon. Rockfish open. Full picture: ${link}

Rules:
- Start with the port name and the date given in the facts.
- Skipper reports: say the day each was reported and the boat. A boat whose "boat" is "a boat" is unverified: say "a boat" or "another boat reports", never a name.
- If there are no skipper reports, say so ("No skipper reports from the last three days."), then give the landing's reports, attributed: "The landing reports ..." with the recent reported activity label exactly as given (Moderate, Low or Insufficient), in English in both versions. These three are the only confidence words you may use.
- If an advisory is listed, say it first, the event name in capitals (SMALL CRAFT ADVISORY).
- Conditions: copy the conditions sentence given; do not change its numbers.
- Rules: you may say a species is open or closed when the facts say so, and "double-check" when a rule is stale. Never state a size limit, a bag limit, a season date or a depth limit.
- Never give odds, a chance, a percentage, a probability, a bite score or a prediction. Never write "%". Describe what was reported, not what will happen.
- Do not ask a question and do not offer to text them later or when a report comes in.
- Plain text, no markdown, no emoji. At most ${DAILY_BODY_MAX} characters for each language, including the link.
- End both versions with exactly: ${link}
- The Spanish version says the same in Spanish (tú), with the fishing words local crews use (rocote or rockfish, lingcod, cabezón, halibut, salmón).

Record both with the record_daily_answer tool.

FACTS
${JSON.stringify(facts)}`;
}
