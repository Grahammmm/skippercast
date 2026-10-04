// Link placeholders in replies (docs/plans/text-advisor/06-angler-answers.md
// § Links in replies, WH-1). The model never writes a URL: it writes
// {{link:port:morro-bay}} and this module turns the first valid placeholder
// into a real ADVISOR_PUBLIC_BASE URL carrying ?s=txt (so site visits are
// attributed to the advisor), drops every other placeholder, and drops any
// unknown one. The pages behind /ports, /species and /boats are server/advisor/pages/
// (TA-W1); while the advisor is dark they answer the gate's 404 like every advisor path.
import ports from '../../catalog/home-ports.json' with {type: 'json'};
import {ALL_SPECIES_KEYS, canonicalSpecies} from './vision/species.ts';

const PORTS = new Map(ports.ports.map(p => [p.id, p] as const));
/** Every home-port id (catalog/home-ports.json). */
export const PORT_IDS: ReadonlySet<string> = new Set(PORTS.keys());
/** The region a home port belongs to, or null. */
export const portRegion = (port: string | null | undefined): string | null => (port && PORTS.get(port)?.region) || null;
/** The port's display name, or null. */
export const portName = (port: string | null | undefined): string | null => (port && PORTS.get(port)?.name) || null;

const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;   // 02 § advisor_boats.slug: ASCII, max 40
export const PLACEHOLDER = /\{\{\s*link:([a-z0-9:_-]{1,80})\s*\}\}/gi;
// A placeholder with its lead-in (", or see", "see:", ":"), so a dropped link takes its lead-in with it.
const WITH_LEAD = /((?:,?[ \t]*(?:or see|see)\b)?[ \t]*:?[ \t]*)\{\{\s*link:([a-z0-9:_-]{1,80})\s*\}\}/gi;
export const SOURCE = 'txt';

/** The site path (with ?s=txt and any fragment) for one placeholder body ("port:morro-bay"), or null when it is unknown or invalid. */
export function linkPath(spec: string): string | null {
  const [kind, value, ...rest] = spec.toLowerCase().split(':');
  if (rest.length) return null;
  const q = `?s=${SOURCE}`;
  switch (kind) {
    case 'home': return value === undefined ? `/${q}` : null;
    case 'port': return value && PORT_IDS.has(value) ? `/ports/${value}${q}` : null;
    case 'species': { const key = value && canonicalSpecies(value); return key && ALL_SPECIES_KEYS.has(key) ? `/species/${key}${q}` : null; }
    case 'boat': return value && SLUG.test(value) ? `/boats/${value}${q}` : null;
    case 'rules': {
      if (value === undefined) return `/${q}#species-regulations`;   // the app's regulations card
      const key = canonicalSpecies(value);
      return ALL_SPECIES_KEYS.has(key) ? `/species/${key}${q}#rules` : null;
    }
    case 'map': { const region = value ? portRegion(value) : null; return region ? `/?region=${region}&s=${SOURCE}` : null; }
    default: return null;
  }
}

export interface ResolvedLinks {text: string; links: string[]}

/**
 * Replace placeholders in `text`: the first valid one becomes `base + path`
 * (at most `max`, default one link per reply, 04), every other placeholder is
 * removed, and the spacing around a removed one is tidied.
 */
export function resolveLinks(text: string, base: string, max = 1): ResolvedLinks {
  const links: string[] = [];
  const out = String(text ?? '').replace(WITH_LEAD, (_whole, lead: string, spec: string) => {
    const path = linkPath(spec);
    if (!path || links.length >= max) return '';
    const url = base.replace(/\/+$/, '') + path;
    links.push(url);
    return lead + url;
  });
  const tidy = out.replace(/[ \t]+([.,;!?])/g, '$1').replace(/[ \t]{2,}/g, ' ').replace(/[ \t]+$/gm, '').trim();
  return {text: tidy, links};
}
