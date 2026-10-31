// Unit factors for the Worker forecast sampler (server/model-api.js), which the
// Python pipeline also runs under plain node via scripts/model_api.mjs.
// Factors the Worker sampler has always used; changing a value changes published
// answers — needs its own PR.
export const KN_PER_MS = 1.9438444924, MPH_PER_MS = 2.2369362921, KMH_PER_MS = 3.6, FT_PER_M = 3.28084;
