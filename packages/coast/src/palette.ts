// Renderer colours as data (docs/plans/front-end/design.md § 3A.4 item 3).
// The only file in packages/coast where colour literals are allowed
// (scripts/check_tokens.mjs); CSS and SVG strings use var(--coast-…, literal)
// instead. These are the CoastViewer's v1 values (the shader's former literals for the ramp, land, water and contours); a v2 host will
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
 /** 3D sky gradient top; it fades to `ground` (the fog colour) at the horizon. */
 skyTop:string;
 // sRGB hex like every role; three hands the shader linear values, which for the
 // defaults below equal v1's former shader constants to within hex rounding.
 /** Depth ramp, shallow to deep. The fixed ramp uses shallow, channel and deep at v1's 8 m, 100 m and 1800 m; the view ramp spans all four across the depths in view. */
 depthShallow:string;depthMid:string;depthChannel:string;depthDeep:string;
 /** Land without imagery, low to high (by 600 m), and the illustrative water surface's tint. */
 landLow:string;landHigh:string;waterTint:string;
 /** Depth contour lines. */
 contour:string;
};
export const DEFAULT_COAST_PALETTE:Readonly<CoastPalette>=Object.freeze({
 ground:'#dce8e7',sky:'#effbff',groundLight:'#4b655d',sun:'#fff2d4',surface:'#ffffff',
 gradeA:'#f8d69a',gradeB:'#afd7ba',gradeOther:'#abcad8',habitatArea:'#69e6c3',current:'#fcfaf0',
 skyTop:'#8fb3bd',depthShallow:'#99d8d0',depthMid:'#4b9baf',depthChannel:'#3590a8',depthDeep:'#215779',
 landLow:'#bdc5a6',landHigh:'#dddbc0',waterTint:'#73c7d4',contour:'#3f8190',
});

// Host overlay colours (FE-81, src/coast3d/overlays.ts). An overlay style names
// one of these roles, never a colour, and the host supplies the values at mount
// (`overlayPalette`). The names are v2's web/map/palette.ts keys, so v2 passes
// the Palette it read from web/tokens.css as is. There are no defaults here:
// an overlay draws only in colours its host read from the tokens.
/** The v1 printable report's series on light paper (presentation.ts trendChart, reportPanel), as data (#711). */
export const REPORT_COLORS=Object.freeze({wind:'#147a83',seas:'#338bab',tide:'#b68648',grid:'#d9e5e5',window:'#38a490',pointer:'#183e4d',
 windSpark:'#18848d',waveSpark:'#3b88ac',nearshoreSpark:'#437b87',tideSpark:'#b58c54'});
/** Surface-temperature ramp, cold to warm: web/tokens.css --sst-0…5 (map/surface-field.ts fieldColor takes hex). */
export const temperatureColors=['#244f9d','#188eb5','#39c6c2','#a6dda0','#efd477','#f18a65'];
/** Surface-current speed ramp, slow to fast: web/tokens.css --current-0…5, panel.css .current-gradient. */
export const currentColors=['#245893','#228fab','#4bcbbb','#d2e59a','#f6c876','#ec8e68'];
export const COAST_OVERLAY_COLORS=['bg','line','text','muted','mint','blue','coral','amber','mpaFill','mpaLine'] as const;
export type CoastOverlayColor=typeof COAST_OVERLAY_COLORS[number];
export type CoastOverlayPalette=Readonly<Record<CoastOverlayColor,string>>;
