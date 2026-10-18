// FE79 / COVER-05: compile only; never import renderer code at runtime.
import type {CoastTerrainSource} from '../../../packages/coast/src/embed-types.ts';
import type {TerrainSource} from '../../../packages/coast/src/coast3d/regional.ts';

declare const regional: Readonly<TerrainSource>;
declare const embedded: Readonly<CoastTerrainSource>;

export const embedFromRegional: Readonly<CoastTerrainSource> = regional;
export const regionalFromEmbed: Readonly<TerrainSource> = embedded;

// Both required-field controls must be rejected. If either target becomes
// permissive (including any), its unused @ts-expect-error fails compilation.
declare const regionalWithoutId: Omit<Readonly<TerrainSource>, 'id'>;
declare const embeddedWithoutId: Omit<Readonly<CoastTerrainSource>, 'id'>;

// @ts-expect-error -- the embed source requires id.
export const invalidEmbed: Readonly<CoastTerrainSource> = regionalWithoutId;
// @ts-expect-error -- the regional source requires id.
export const invalidRegional: Readonly<TerrainSource> = embeddedWithoutId;
