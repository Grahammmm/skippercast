// packages/coast's surface-field mathematics for the Chart (FE-15, FE-16, design
// § 9): re-exported, never copied. Plain JavaScript with its types in
// surface-field.d.ts, as web/map/terrain.js does: the source is checked by
// packages/coast/tsconfig.json, and web/tsconfig.json's noUncheckedIndexedAccess
// would reject it, so the web program must not load it.
export {fieldColor, fieldContours, surfaceField, temperatureRange, vectorReading} from '../../packages/coast/src/map/surface-field.ts';
