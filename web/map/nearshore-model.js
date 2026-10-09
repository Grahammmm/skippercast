// packages/coast's nearshore model gates for the Chart's Swell rings (FE-27,
// design § 9): re-exported, never copied. Plain JavaScript with its types in
// nearshore-model.d.ts (the web/map/surface-field.js pattern): presentation.ts
// and its imports fail web/tsconfig.json's noUncheckedIndexedAccess, so the
// web program must not load them.
export {freshNearshore, nearshoreAt, nearshoreSampleLabel} from '../../packages/coast/src/presentation.ts';
