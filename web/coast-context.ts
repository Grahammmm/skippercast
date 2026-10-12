import {FISH_REGIONS} from './fish-links.ts';
/** The surface-current choices of `?current=` (FE-73): web/state.ts reads them from here. */
export {currentLayers, isCurrentLayer, type CurrentLayer} from '../packages/coast/src/state/current-layer.ts';

const TARGETS: Readonly<Record<string, string>> = {
 reef: 'all', all: 'all', lingcod: 'lingcod', rockfish: 'rockfish-reef',
 'rockfish-reef': 'rockfish-reef', 'gopher-rockfish': 'gopher-rockfish',
 cabezon: 'cabezon-shallow-reef', 'cabezon-shallow-reef': 'cabezon-shallow-reef',
 halibut: 'halibut', surfperch: 'surfperch',
};
export const coastTarget = (target: string): string | null => Object.hasOwn(TARGETS, target) ? TARGETS[target]! : null;
export const hasCoastTerrain = (region: string): boolean => Object.values(FISH_REGIONS).includes(region);
export type Presentation = 'chart' | '2d' | '3d';
export function presentationFromURL(href: string): Presentation {
 const value = new URL(href).searchParams.get('presentation');
 return value === '2d' || value === '3d' ? value : 'chart';
}
/** Change display only; geographic, target, forecast and account routes survive. */
export function presentationURL(href: string, mode: Presentation): URL {
 const url = new URL(href);
 if (mode === 'chart') url.searchParams.delete('presentation');
 else url.searchParams.set('presentation', mode);
 return url;
}
/** Public habitat identity is independent of the historical atlas spot id. */
export function habitatURL(href: string, id: string | null): URL {
 const url = new URL(href);
 if (id && /^[A-Za-z0-9._:-]{1,160}$/.test(id)) url.searchParams.set('habitat', id);
 else url.searchParams.delete('habitat');
 return url;
}
