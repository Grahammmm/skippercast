// update_profile (04 § Tools, FC-2): what the person told us about
// themselves, as a contact_update action. Only known ports and species keys
// are kept; anything else is reported back so the model can ask again.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';
import {ALL_SPECIES_KEYS, canonicalSpecies} from '../vision/species.ts';
import type {ContactFields} from '../types.ts';
import {cleanDisplayName} from '../display-name.ts';

export const updateProfile: AdvisorTool = {
  name: 'update_profile',
  description: "Save what the person told you about themselves: the name they want to be called, their home port, the species they fish for, or the language they want. Ask for home port and targets once, naturally, after answering their first real question; never ask again once saved. home_port must be one of the port ids; targets are species keys. If unknown_targets is returned, ask what they meant by those.",
  input_schema: {type: 'object', additionalProperties: false, properties: {
    display_name: {type: 'string', maxLength: 60},
    home_port: {type: 'string', enum: [...PORT_IDS]},
    targets: {type: 'array', items: {type: 'string'}, maxItems: 8},
    language: {type: 'string', enum: ['en', 'es']},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'profile',
  async run(input) {
    const fields: ContactFields = {}, rejected: string[] = [], unknown = new Set<string>();
    if (typeof input.display_name === 'string') {
      const name = cleanDisplayName(input.display_name);
      if (name) fields.display_name = name; else rejected.push('display_name');
    }
    if (input.home_port !== undefined) {
      if (typeof input.home_port === 'string' && PORT_IDS.has(input.home_port)) fields.home_port = input.home_port; else rejected.push('home_port');
    }
    if (input.targets !== undefined) {
      const known = new Set<string>();
      // RF1300-5: unknown entries are named back (cleaned, input order) so the model can ask what they meant.
      for (const k of Array.isArray(input.targets) ? input.targets : []) {
        if (typeof k !== 'string') { unknown.add('(not text)'); continue; }
        const raw = k.trim().toLowerCase(), key = canonicalSpecies(raw);
        if (ALL_SPECIES_KEYS.has(key)) known.add(key);
        else unknown.add([...raw.replace(/[\u0000-\u001f\u007f-\u009f]/gu, '')].slice(0, 40).join('') || '(blank)');
      }
      const keys = [...known].slice(0, 8);
      if (keys.length) fields.targets_json = JSON.stringify(keys); else rejected.push('targets');
    }
    if (input.language === 'en' || input.language === 'es') fields.language = input.language;
    else if (input.language !== undefined) rejected.push('language');
    const saved = Object.keys(fields).map(k => k === 'targets_json' ? 'targets' : k);
    const result = unknown.size ? {saved, rejected, unknown_targets: [...unknown].slice(0, 8)} : {saved, rejected};
    return {result, actions: saved.length ? [{type: 'contact_update', fields}] : []};
  },
};
