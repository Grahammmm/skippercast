// One cleaner for a contact's display name (update_profile and the consumer's
// contact_update). The name goes into other people's texts (crew_invite) and
// into the model prompt, so invisible, control and direction-changing
// characters are removed and the cut is by whole characters, never mid-pair.
export const DISPLAY_NAME_MAX = 60;

// C0, DEL and C1 controls; zero-width space/joiners and LRM/RLM; bidi
// embeddings and overrides; word joiner and invisible operators; bidi
// isolates; BOM / zero-width no-break space.
const INVISIBLE = /[\p{Cc}\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF]/gu;

/** NFC, whitespace runs to one space, invisible/control/bidi removed, trimmed, 60 code points; null when nothing visible is left. */
export function cleanDisplayName(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const s = value.normalize('NFC').replace(/\s+/gu, ' ').replace(INVISIBLE, '').trim();
  const cut = Array.from(s).slice(0, DISPLAY_NAME_MAX).join('').trim();
  return cut || null;
}
