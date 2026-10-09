// Entry of dist/landing.html (FE-07, design § 7): a returning visitor with a
// saved port and no parameters (besides the ui switch) goes straight to the
// app there, with the stored profile; the CSP allows no inline script, so
// this first module does it and the hero shows for the moment before. Every
// other visit renders the landing's parts into their hosts beside the
// static hero. FE-25: once the page has loaded and painted, and only where
// WebGL2 works (MapLibre 6 needs it) and the visitor has not asked to save
// data (save-data.ts), the live night map (NightMap.tsx) loads
// by dynamic import, so neither MapLibre nor the map's modules count against
// the first paint (design § 13); the static shoreline stays until it draws.
import {render, type ComponentChild} from 'preact';
import {isProfile, type Profile} from '../profile.ts';
import {loadPorts, portURL, savedPortId, type Port} from '../ports.ts';
import {LandingApp, LandingHead} from './Landing.tsx';
import {LayerDots} from './LayerDots.tsx';
import {DEFAULT_REGION} from './readings.ts';
import {saveData} from './save-data.ts';
import {Shoreline, ShorelineCredit} from './Shoreline.tsx';

/** web/state.ts STORAGE_KEYS.profile (equal by test); the store itself is the app's and loads there. */
export const PROFILE_KEY = 'skippercast-profile-v1';

function storedProfile(): Profile | null {
  try { const value = localStorage.getItem(PROFILE_KEY); return isProfile(value) ? value : null; } catch { return null; }
}

/** The app address for a saved port when `href` carries no parameter but ui; null to stay. */
export async function savedPortTarget(href: string, saved: string | null, profile: Profile | null, ports: () => Promise<readonly Port[]> = loadPorts): Promise<string | null> {
  const keys = [...new URL(href).searchParams.keys()];
  if (!saved || keys.some(key => key !== 'ui')) return null;
  const port = await ports().then(list => list.find(p => p.id === saved) ?? null, () => null);
  return port ? portURL(href, port, profile) : null;
}

/** True where a WebGL2 context can be made; the probe's context is released at once. */
export function webgl2(doc: Pick<Document, 'createElement'> = document): boolean {
  try {
    const gl = doc.createElement('canvas').getContext('webgl2');
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return !!gl;
  } catch { return false; }
}

/** Run `next` after the load event and the frame after it, so nothing it loads competes with the first paint. */
export function afterFirstPaint(next: () => void): void {
  const go = () => requestAnimationFrame(() => setTimeout(next, 0));
  if (document.readyState === 'complete') go(); else addEventListener('load', go, {once: true});
}

const mount = (id: string, part: ComponentChild) => {
  const host = document.getElementById(id);
  if (host) { host.replaceChildren(); render(part, host); }
};
const landing = document.querySelector<HTMLElement>('.landing');
/** `data-night` (the night map's state) and `data-preview` (the hovered layer dot) on the page, for landing.css. */
const mark = (key: 'night' | 'preview', value: string | null) => { if (landing) { if (value) landing.dataset[key] = value; else delete landing.dataset[key]; } };
function nightMap(): void {
  if (saveData(navigator) || !webgl2()) return;
  import('./NightMap.tsx').then(({NightMap, NightCredit}) => {
    mount('landing-night', <NightMap page={location.href} region={DEFAULT_REGION} onState={state => mark('night', state)} />);
    mount('landing-credit', <><ShorelineCredit /><NightCredit /></>);
  }, error => console.warn('Night map unavailable; the static shoreline stays.', error));
}

const profile = storedProfile();
// A returning visitor goes on to the app; everyone else gets the night map after first paint.
void savedPortTarget(location.href, savedPortId(), profile).then(next => { if (next) location.replace(next); else afterFirstPaint(nightMap); });
mount('landing-shore', <Shoreline />);
mount('landing-credit', <ShorelineCredit />);
mount('landing-head', <LandingHead href={location.href} />);
mount('landing-app', <LandingApp href={location.href} initialProfile={profile} />);
mount('landing-dots', <LayerDots href={location.href} region={DEFAULT_REGION} onPreview={layer => mark('preview', layer)} />);
