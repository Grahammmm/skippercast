// Renderer colours as data (docs/plans/front-end/design.md § 3A.4 item 3).
// The only file in packages/coast where colour literals are allowed
// (scripts/check_tokens.mjs); CSS and SVG strings use var(--coast-…, literal)
// instead. These are the CoastViewer's v1 values, unchanged; a v2 host will
// pass values read through web/map/palette.ts to mountCoast (src/embed.ts).
export type CoastPalette={
 /** Clear colour and 3D fog. */
 ground:string;
 /** Hemisphere light: sky and ground. */
 sky:string;groundLight:string;
 /** Directional sun light. */
 sun:string;
 /** Base colour of terrain, water and imagery materials (vertex colours and shaders tint it). */
 surface:string;
 /** Habitat fill by terrain grade (A, B, other) and the reef outline (grade A). */
 gradeA:string;gradeB:string;gradeOther:string;
 /** Blend colour of habitat areas at broad zoom. */
 habitatArea:string;
 /** Surface-current arrows. */
 current:string;
};
export const DEFAULT_COAST_PALETTE:Readonly<CoastPalette>=Object.freeze({
 ground:'#dce8e7',sky:'#effbff',groundLight:'#4b655d',sun:'#fff2d4',surface:'#ffffff',
 gradeA:'#f8d69a',gradeB:'#afd7ba',gradeOther:'#abcad8',habitatArea:'#69e6c3',current:'#fcfaf0',
});

// Host overlay colours (FE-81, src/coast3d/overlays.ts). An overlay style names
// one of these roles, never a colour, and the host supplies the values at mount
// (`overlayPalette`). The names are v2's web/map/palette.ts keys, so v2 passes
// the Palette it read from web/tokens.css as is. There are no defaults here:
// an overlay draws only in colours its host read from the tokens.
export const COAST_OVERLAY_COLORS=['bg','line','text','muted','mint','blue','coral','amber','mpaFill','mpaLine'] as const;
export type CoastOverlayColor=typeof COAST_OVERLAY_COLORS[number];
export type CoastOverlayPalette=Readonly<Record<CoastOverlayColor,string>>;
