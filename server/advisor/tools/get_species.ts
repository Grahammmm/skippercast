// get_species (docs/plans/text-advisor/04-advisor-engine.md § Tools): a stub with
// its final name, roles and input_schema until TA-E2 replaces this file. It
// answers {unavailable: true, reason: 'not built yet'} so the model says it
// can't check that yet instead of answering from memory.
import {stubTool} from './tool.ts';

export const getSpecies = stubTool({
  name: 'get_species',
  description: "What SkipperCast knows about a species: habitat, depth, season notes and look-alikes with how to tell them apart.",
  input_schema: {type: 'object', additionalProperties: false, required: ['species_key'], properties: {species_key: {type: 'string'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'species',
});
