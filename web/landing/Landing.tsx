// The landing (FE-07, design § 7, concept D · Open water, D4, D9). The
// eyebrow, the headline, the paragraph and the footer line are static in
// dist/landing.html, so the largest paint never waits for this module or
// for a re-render; main.tsx renders these parts into their hosts around
// them: the static shoreline, the minimal nav, the live readout (right under
// the paragraph, so the sourced readings show before any choice, D4), the
// guided first run, and the layer dots. #622 (walkthrough slice 4): the first
// run asks for the port first (FE-08's input), starts warming that region
// (region-warm.ts) and then asks how they fish (ProfileStep.tsx); choosing a
// profile saves the port under v1's key and opens the app there with it.
// "Explore the coast" takes the same second step with nothing to warm. No map
// engine loads here (FE-25 adds the live map after first paint).
import {useEffect, useRef, useState} from 'preact/hooks';
import {exploreURL, loadPorts, portURL, savePort, type Port} from '../ports.ts';
import type {Profile} from '../profile.ts';
import {PortInput} from './PortInput.tsx';
import {ProfileStep} from './ProfileStep.tsx';
import {warmRegion, type WarmState} from './region-warm.ts';
import {DEFAULT_REGION, loadReadout, type Readout as Data} from './readings.ts';
import {Readout} from './Readout.tsx';

/** The nav (§ 7): Fleet and Reports open the app's views (Reports, FE-52), How it's built the sources page (Q16). */
export const NAV = [
  {label: 'Fleet', href: `/map?region=${DEFAULT_REGION}&view=fleet`},
  {label: 'Reports', href: `/map?region=${DEFAULT_REGION}&view=reports`},
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
          <li><a href="/map#account">Sign in</a></li>
        </ul>
      </nav>
    </header>
  );
}

export type LandingAppProps = {
  href: string;
  /** The stored profile, shown pressed in the profile step; null leaves every choice up. */
  initialProfile?: Profile | null;
  /** The fleet line, passed only while the fleet flag is on. */
  fleet?: string | null;
  navigate?: (url: string) => void;
  /** Start loading the ports and readings, and warm a chosen region (off for string rendering in tests). */
  load?: boolean;
  /** The region warm-up (region-warm.ts by default; tests pass stand-ins). */
  warm?: (region: string) => Promise<{state: WarmState}>;
};

/** Where the profile step leads: a port (warmed) or the central coast (nothing to warm). */
type Choice = {place: string; port: Port | null};
const EXPLORE_PLACE = 'Central coast';

export function LandingApp({href, initialProfile = null, fleet = null, navigate = url => location.assign(url), load = true, warm = region => warmRegion(region, href)}: LandingAppProps) {
  const [ports, setPorts] = useState<Port[] | null>(null);
  const [readout, setReadout] = useState<Data | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [warmth, setWarmth] = useState<WarmState | null>(null);
  /** The region being warmed, so an answer for an earlier choice is ignored; and whether the visitor came back from step 2. */
  const warming = useRef<string | null>(null);
  const [back, setBack] = useState(false);
  useEffect(() => {
    if (!load) return;
    loadPorts().then(setPorts, () => setPorts([]));
    void loadReadout().then(setReadout);
  }, [load]);
  // Step 1 → 2: remember the choice and warm its region while they pick a profile; a later choice ignores an earlier warm-up's answer.
  const choose = (port: Port) => {
    setChoice({place: port.name, port});
    if (!load) return;
    const region = port.region;
    warming.current = region;
    setWarmth('loading');
    void warm(region).then(r => { if (warming.current === region) setWarmth(r.state); }, () => { if (warming.current === region) setWarmth('failed'); });
  };
  const explore = () => { warming.current = null; setChoice({place: EXPLORE_PLACE, port: null}); setWarmth(null); };
  const restart = () => { warming.current = null; setChoice(null); setWarmth(null); setBack(true); };
  // Step 2: the profile opens the app; only now is the port saved as home.
  const finish = (profile: Profile) => {
    if (!choice) return;
    if (choice.port) { savePort(choice.port.id); navigate(portURL(href, choice.port, profile)); return; }
    const url = new URL(exploreURL(href));
    url.searchParams.set('profile', profile);
    navigate(url.href);
  };
  return (
    <>
      <Readout data={readout} fleet={fleet} conditions={keepUI(href, `/map?region=${DEFAULT_REGION}&view=conditions`)} />
      {choice
        ? <ProfileStep place={choice.place} warm={choice.port ? warmth : null} current={initialProfile} onChoose={finish} onBack={restart} />
        : <PortInput ports={ports} onChoose={choose} onExplore={explore} autoFocus={back} />}
    </>
  );
}
