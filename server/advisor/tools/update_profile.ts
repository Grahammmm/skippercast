// update_profile (04 § Tools, FC-2): what the person told us about
// themselves, as a contact_update action. Only known ports and species keys
// are kept; anything else is reported back so the model can ask again.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';
import {ALL_SPECIES_KEYS, canonicalSpecies} from '../vision/species.ts';
import type {ContactFields} from '../types.ts';

export const updateProfile: AdvisorTool = {
  name: 'update_profile',
  description: "Save what the person told you about themselves: the name they want to be called, their home port, the species they fish for, or the language they want. Ask for home port and targets once, naturally, after answering their first real question; never ask again once saved. home_port must be one of the port ids; targets are species keys.",
  input_schema: {type: 'object', additionalProperties: false, properties: {
    display_name: {type: 'string', maxLength: 60},
    home_port: {type: 'string', enum: [...PORT_IDS]},
    targets: {type: 'array', items: {type: 'string'}, maxItems: 8},
    language: {type: 'string', enum: ['en', 'es']},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'profile',
  async run(input) {
    const fields: ContactFields = {}, rejected: string[] = [];
    if (typeof input.display_name === 'string') {
      const name = input.display_name.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 60);
      if (name) fields.display_name = name; else rejected.push('display_name');
    }
    if (input.home_port !== undefined) {
      if (typeof input.home_port === 'string' && PORT_IDS.has(input.home_port)) fields.home_port = input.home_port; else rejected.push('home_port');
    }
    if (input.targets !== undefined) {
      const keys = Array.isArray(input.targets) ? [...new Set(input.targets.filter((k): k is string => typeof k === 'string').map(k => canonicalSpecies(k.trim().toLowerCase())).filter(k => ALL_SPECIES_KEYS.has(k)))].slice(0, 8) : [];
      if (keys.length) fields.targets_json = JSON.stringify(keys); else rejected.push('targets');
    }
    if (input.language === 'en' || input.language === 'es') fields.language = input.language;
    else if (input.language !== undefined) rejected.push('language');
    const saved = Object.keys(fields).map(k => k === 'targets_json' ? 'targets' : k);
    return {result: {saved, rejected}, actions: saved.length ? [{type: 'contact_update', fields}] : []};
  },
};
