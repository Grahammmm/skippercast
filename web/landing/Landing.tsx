// The landing (FE-07, design § 7, concept D · Open water, D4, D9). The
// eyebrow, the headline, the paragraph and the footer line are static in
// dist/landing.html, so the largest paint never waits for this module or
// for a re-render; main.tsx renders these parts into their hosts around
// them: the static shoreline, the minimal nav, the live readout (right under
// the paragraph, so the sourced readings show before any choice, D4), the
// profile pills and the port input (FE-08), and the layer dots. Choosing a
// port saves it under v1's key and opens the app there with the chosen
// profile. No map engine loads here (FE-25 adds the live map after first
// paint).
import {useEffect, useState} from 'preact/hooks';
import {exploreURL, loadPorts, portURL, savePort, type Port} from '../ports.ts';
import type {Profile} from '../profile.ts';
import {PortInput} from './PortInput.tsx';
import {ProfilePills} from './ProfilePills.tsx';
import {DEFAULT_REGION, loadReadout, type Readout as Data} from './readings.ts';
import {Readout} from './Readout.tsx';

/** The nav (§ 7): Fleet opens the app's fleet view, Reports the coast report (#395), How it's built the sources page (Q16). */
export const NAV = [
  {label: 'Fleet', href: `/map?region=${DEFAULT_REGION}&view=fleet`},
  {label: 'Reports', href: '/report'},
  {label: 'How it’s built', href: '/sources'},
] as const;

/** Keep the ui switch on a link into the v2 pages, so a preview stays in the new shell. */
export function keepUI(href: string, path: string): string {
  const ui = new URL(href).searchParams.get('ui');
  return ui ? `${path}${path.includes('?') ? '&' : '?'}ui=${encodeURIComponent(ui)}` : path;
}

export function LandingHead({href}: {href: string}) {
  return (
    <header class="landing-head">
      <a class="landing-brand" href={keepUI(href, '/')}>SkipperCast</a>
      <nav aria-label="Site">
        <ul class="landing-nav">
          {NAV.map(item => <li key={item.label}><a href={item.href.startsWith('/map') ? keepUI(href, item.href) : item.href}>{item.label}</a></li>)}
          <li><a href="/?ui=v1#account">Sign in</a></li>
        </ul>
      </nav>
    </header>
  );
}

export type LandingAppProps = {
  href: string;
  /** The stored profile, pressed at first; null leaves every pill up. */
  initialProfile?: Profile | null;
  /** The fleet line, passed only while the fleet flag is on. */
  fleet?: string | null;
  navigate?: (url: string) => void;
  /** Start loading the ports and readings (off for string rendering in tests). */
  load?: boolean;
};

export function LandingApp({href, initialProfile = null, fleet = null, navigate = url => location.assign(url), load = true}: LandingAppProps) {
  const [ports, setPorts] = useState<Port[] | null>(null);
  const [readout, setReadout] = useState<Data | null>(null);
  const [profile, setProfile] = useState<Profile | null>(initialProfile);
  useEffect(() => {
    if (!load) return;
    loadPorts().then(setPorts, () => setPorts([]));
    void loadReadout().then(setReadout);
  }, [load]);
  const choose = (port: Port) => { savePort(port.id); navigate(portURL(href, port, profile)); };
  const explore = () => {
    const url = new URL(exploreURL(href));
    if (profile) url.searchParams.set('profile', profile);
    navigate(url.href);
  };
  return (
    <>
      <Readout data={readout} fleet={fleet} conditions={keepUI(href, `/map?region=${DEFAULT_REGION}&view=conditions`)} />
      <ProfilePills value={profile} onChange={setProfile} />
      <PortInput ports={ports} onChoose={choose} onExplore={explore} />
    </>
  );
}
