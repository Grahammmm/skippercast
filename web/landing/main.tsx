// Entry of dist/landing.html (FE-07, design § 7): a returning visitor with a
// saved port and no parameters (besides the ui switch) goes straight to the
// app there, with the stored profile; the CSP allows no inline script, so
// this first module does it and the hero shows for the moment before. Every
// other visit renders the landing's parts into their hosts beside the
// static hero.
import {render, type ComponentChild} from 'preact';
import {isProfile, type Profile} from '../profile.ts';
import {loadPorts, portURL, savedPortId, type Port} from '../ports.ts';
import {LandingApp, LandingHead} from './Landing.tsx';
import {LayerDots} from './LayerDots.tsx';
import {DEFAULT_REGION} from './readings.ts';
import {Shoreline} from './Shoreline.tsx';

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

const profile = storedProfile();
void savedPortTarget(location.href, savedPortId(), profile).then(next => { if (next) location.replace(next); });
const mount = (id: string, part: ComponentChild) => {
  const host = document.getElementById(id);
  if (host) { host.replaceChildren(); render(part, host); }
};
mount('landing-shore', <Shoreline />);
mount('landing-head', <LandingHead href={location.href} />);
mount('landing-app', <LandingApp href={location.href} initialProfile={profile} />);
mount('landing-dots', <LayerDots href={location.href} region={DEFAULT_REGION} />);
