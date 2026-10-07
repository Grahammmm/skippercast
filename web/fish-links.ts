// Fish link compatibility for the shared workspace. This selects a data
// package, never establishes local forecast coverage, legal access or depth.
import {isProfile} from './profile.ts';

export const FISH_REGIONS: Readonly<Record<string, string>> = {
  morro: 'morro-bay', avila: 'morro-bay', cambria: 'cambria-san-simeon',
  monterey: 'monterey-point-sur', carmel: 'monterey-point-sur', 'point-sur': 'monterey-point-sur',
  'big-sur': 'big-sur-coast', gorda: 'south-big-sur-san-simeon',
  arguello: 'point-arguello-conception', conception: 'point-arguello-conception',
};
const AREA_PLACES: Readonly<Record<string, string>> = {north: 'cambria', central: 'morro', south: 'avila'};
const FISH_LAYERS: Readonly<Record<string, string>> = {
  opportunity: 'seafloor', bathymetry: 'seafloor', currents: 'currents',
  temperature: 'water-temp', waves: 'swell', clouds: 'clouds', habitat: 'seafloor',
};
const own = (table: Readonly<Record<string, string>>, key: string): string | undefined => Object.hasOwn(table, key) ? table[key] : undefined;

/** Fish writes complete ISO timestamps; the shared store writes minutes. */
export function canonicalHour(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:00(?::00(?:\.000)?)?Z$/.test(value)) return null;
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return null;
  const canonical = new Date(ms).toISOString().slice(0, 16) + 'Z';
  return canonical.slice(0, 16) === value.slice(0, 16) ? canonical : null;
}

/**
 * Translate Fish aliases without changing explicit SkipperCast choices.
 * Unknown values stay in the link for a supported renderer to interpret;
 * they never silently become an unrelated target or geographic package.
 * No cookie/storage read or write; opening a shared link does not change home.
 */
export function fishLink(href: string, clearGeography = false): URL {
  const url = new URL(href), p = url.searchParams;
  const fish = ['mode', 'species', 'layer', 'place'].some(key => p.has(key));
  if (!fish) return url;
  const mode = p.get('mode');
  if (isProfile(mode)) {
    if (!p.has('profile')) p.set('profile', mode);
    p.delete('mode');
  }
  const target = p.get('species');
  if (target && /^[a-z][a-z0-9-]*$/.test(target)) {
    if (!p.has('target')) p.set('target', target);
    p.delete('species');
  }
  const layer = p.get('layer'), layers = layer ? own(FISH_LAYERS, layer) : undefined;
  if (layers) {
    if (!p.has('layers')) p.set('layers', layers);
    p.delete('layer');
  }
  if (clearGeography) {
    p.delete('place');
    if (own(AREA_PLACES, p.get('area') ?? '')) p.delete('area');
  } else if (!p.has('region') && !p.has('coast')) {
    const place = p.get('place') ?? own(AREA_PLACES, p.get('area') ?? '');
    if (place === 'coast') p.set('coast', 'central');
    else if (place && own(FISH_REGIONS, place)) p.set('region', own(FISH_REGIONS, place)!);
  }
  const hour = canonicalHour(p.get('hour'));
  if (hour) p.set('hour', hour);
  return url;
}
