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

// TA-S6: the visit source a reply's links carry: 'txt' for the advisor's replies, 'ig' for an Instagram comment's.
const VISIT_SOURCE = /^[a-z]{2,8}$/;
// TA-S6: a /text deep-link source (routes/advisor.ts textBody keeps it as the first message's `[via <source>]`).
const TEXT_SOURCE = /^[a-z0-9_-]{1,16}$/;

/**
 * The site path (with ?s=<source> and any fragment) for one placeholder body ("port:morro-bay"), or null when it is unknown or invalid.
 * TA-S6 adds `text:<source>` (the /text deep link, `/text?s=<source>`: "continue by text" in an Instagram DM is `text:igdm`),
 * `chat` (the web chat, which takes photos) and `boats:<port>` (the port page's boats section).
 */
export function linkPath(spec: string, source: string = SOURCE): string | null {
  const [kind, value, ...rest] = spec.toLowerCase().split(':');
  if (rest.length) return null;
  const q = `?s=${VISIT_SOURCE.test(source) ? source : SOURCE}`;
  switch (kind) {
    case 'home': return value === undefined ? `/${q}` : null;
    case 'port': return value && PORT_IDS.has(value) ? `/ports/${value}${q}` : null;
    case 'boats': return value && PORT_IDS.has(value) ? `/ports/${value}${q}#boats-title` : null;
    case 'text': return value && TEXT_SOURCE.test(value) ? `/text?s=${value}` : null;
    case 'chat': return value === undefined ? `/chat.html${q}` : null;
    case 'species': { const key = value && canonicalSpecies(value); return key && ALL_SPECIES_KEYS.has(key) ? `/species/${key}${q}` : null; }
    case 'boat': return value && SLUG.test(value) ? `/boats/${value}${q}` : null;
    case 'rules': {
      if (value === undefined) return `/${q}#species-regulations`;   // the app's regulations card
      const key = canonicalSpecies(value);
      return ALL_SPECIES_KEYS.has(key) ? `/species/${key}${q}#rules` : null;
    }
    case 'map': { const region = value ? portRegion(value) : null; return region ? `/?region=${region}&${q.slice(1)}` : null; }
    default: return null;
  }
}

export interface ResolvedLinks {text: string; links: string[]}

/**
 * Replace placeholders in `text`: the first valid one becomes `base + path`
 * (at most `max`, default one link per reply, 04), every other placeholder is
 * removed, and the spacing around a removed one is tidied. `source` is the
 * pages' visit source (default 'txt'; TA-S6: 'ig' in a comment's reply).
 */
export function resolveLinks(text: string, base: string, max = 1, source: string = SOURCE): ResolvedLinks {
  const links: string[] = [];
  const out = String(text ?? '').replace(WITH_LEAD, (_whole, lead: string, spec: string) => {
    const path = linkPath(spec, source);
    if (!path || links.length >= max) return '';
    const url = base.replace(/\/+$/, '') + path;
    links.push(url);
    return lead + url;
  });
  const tidy = out.replace(/[ \t]+([.,;!?])/g, '$1').replace(/[ \t]{2,}/g, ' ').replace(/[ \t]+$/gm, '').trim();
  return {text: tidy, links};
}
