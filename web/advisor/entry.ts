// The Text Advisor's entry point for the v2 masthead (FE-55). Kept apart from
// copy.ts so web/app/ imports two strings, not the whole advisor copy chunk;
// copy.ts re-exports both, so the advisor pages keep one source of truth.

/** The masthead's link to the web chat (the same words as the pages' PAGES_COPY.ctaChat). */
export const CHAT_ENTRY = 'Ask SkipperCast';
/** The web chat page, which the advisor gate answers 404 while TEXT_ADVISOR_ENABLED is off. */
export const CHAT_PATH = '/chat.html';
