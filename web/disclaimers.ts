// Limitation and disclaimer strings the app shows, kept in one place (P4-04).
//
// Every string here was moved, word for word, from the screen that used to
// show it inline; the screens now show it inside a confidence badge's "why"
// or a disclosure. Change the wording here only together with the owner:
// the information in a caveat must survive; only where it appears changes.
// The legally required caveats (C1-C4) are defined in docs/legal/disclaimers.md.
//
// Erasable TypeScript only: the Node tests and dist/*.js modules import it.

/** A limitation: an optional bold lead-in, the text, and an optional link. */
export interface Limitation {
  lead?: string;
  text: string;
  link?: {href: string; text: string};
}

/**
 * Spot sheet, historical Morro Bay-Avila targets (`research_only`). Was the
 * paragraph above the spot's name (dist/app.js); now the depth badge's why.
 */
export const RESEARCH_ONLY_LOCATION: Limitation = {
  lead: 'Research-only location.',
  text: 'Source raster output vertical datum and product uncertainty are unverified. The displayed depths are not chart depths or a verified 200-foot fishing screen. Check your official chart and sounder.',
};

/** Spot sheet "Mapped habitat candidate" note, first half: now the terrain badge's why. */
export const MAPPED_HABITAT_CANDIDATE = 'Mapped habitat candidate';
export const terrainConfidence = (confidence: string): string =>
  `Terrain interpretation confidence: ${confidence}.`;

/** Spot sheet "Mapped habitat candidate" note, second half: now the fish badge's why. */
export const FISH_UNVERIFIED: Limitation = {
  text: 'Fish presence is unverified; no verified charter AIS visits at this target.',
  link: {href: '#charter-evidence', text: 'See the AIS research coverage.'},
};
