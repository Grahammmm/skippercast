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
import {carryAsk} from '../boat-entry.ts';
import {exploreURL, loadPorts, portURL, savePort, type Port} from '../ports.ts';
import type {Profile} from '../profile.ts';
import {PortInput} from './PortInput.tsx';
import {ProfileStep} from './ProfileStep.tsx';
import {warmRegion, type WarmState} from './region-warm.ts';
import {DEFAULT_REGION, loadReadout, type Readout as Data} from './readings.ts';
import {Readout} from './Readout.tsx';
import type {LandingVerdict} from './live-verdict.ts';
import {degraded} from '../degraded.ts';
import {DegradedNotice} from '../degraded-notice.tsx';
import {language, t} from '../i18n.ts';

/** The nav (§ 7): Fleet and Reports open the app's views (Reports, FE-52), How it's built the sources page (Q16). */
export const NAV = [
  {label: t('landing.link.fleet', 'en'), href: `/map?region=${DEFAULT_REGION}&view=fleet`},
  {label: t('landing.link.reports', 'en'), href: `/map?region=${DEFAULT_REGION}&view=reports`},
  {label: t('landing.link.sources', 'en'), href: '/sources'},
] as const;
/** NAV's labels in the page language, in NAV's order (NAV itself keeps the English metadata). */
const NAV_IDS = ['landing.link.fleet', 'landing.link.reports', 'landing.link.sources'] as const;

export function LandingHead(_props: {href: string}) {
  const lang = language.value;
  return (
    <header class="landing-head">
      <a class="landing-brand" href="/">SkipperCast</a>
      <nav aria-label={t('landing.aria.site', lang)}>
        <ul class="landing-nav">
          {NAV.map((item, i) => <li key={item.href}><a href={item.href}>{t(NAV_IDS[i]!, lang)}</a></li>)}
          <li><a href="/map#account">{t('landing.link.signin', lang)}</a></li>
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
  /** The region warm-up (region-warm.ts by default; tests pass stand-ins). `signal` aborts a warm-up the visitor has left. */
  warm?: (region: string, signal?: AbortSignal) => Promise<{state: WarmState}>;
  /** BF-landing-live: tomorrow's verdict, loaded after the readout (main.tsx passes live-verdict.ts by dynamic import, as it does the night map; none by default). */
  verdict?: () => Promise<LandingVerdict | null>;
};

/**
 * Tomorrow's answer for the boat saved on this device (else the reference boat), named, as the app's lead gives it; below the funnel, so nothing above the port input moves.
 * SC1322-06: `saved` (the Worker is past its cost ceiling, web/degraded.ts) labels it as from saved copies, not current.
 */
export const LiveVerdict = ({v, saved = false}: {v: LandingVerdict; saved?: boolean}) => {
  const lang = language.value;
  return (
  <section class="landing-verdict" aria-live="polite" aria-label={t(saved ? 'landing.verdict.ariaSaved' : 'landing.verdict.aria', lang)} data-day={v.date} data-degraded={saved ? 'cost-ceiling' : undefined}>
    <p class="landing-verdict-head">{saved ? t('landing.verdict.saved', lang) : null}{t('landing.verdict.head', lang, {day: v.day, place: v.place, boat: v.boatName})}<strong class="landing-verdict-word" data-verdict={v.verdict}>{v.word}</strong></p>
    <p class="landing-verdict-limit">{v.sentence}</p>
    {v.boatNote ? <p class="landing-verdict-note">{v.boatNote}</p> : null}
    <a class="landing-verdict-link" href={v.href}>{t('landing.verdict.link', lang)}</a>
  </section>
  );
};

/** Where the profile step leads: a port (warmed) or the central coast (nothing to warm). */
type Choice = {place: string; port: Port | null};

export function LandingApp({href, initialProfile = null, fleet = null, navigate = url => location.assign(url), load = true,
  warm = (region, signal) => warmRegion(region, href, undefined, undefined, {signal}), verdict = () => Promise.resolve(null)}: LandingAppProps) {
  const [ports, setPorts] = useState<Port[] | null>(null);
  const [readout, setReadout] = useState<Data | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [warmth, setWarmth] = useState<WarmState | null>(null);
  /**
   * The warm-up of the port on screen. Leaving that port — Change port, Explore the coast, or another
   * port — aborts it, so a port the visitor cancelled stops fetching its region's startup files, and its
   * answer, early or late, never replaces the state of the choice that is live. The check is on the
   * selection, not the region id, so a port chosen, left and chosen again is not answered by the run it
   * abandoned (region-warm.ts createRegionWarmup states the same boundary for the coast startup).
   */
  const warming = useRef<AbortController | null>(null);
  const leaveWarm = (): void => { warming.current?.abort(); warming.current = null; };
  /** Whether the visitor came back from step 2. */
  const [back, setBack] = useState(false);
  /** Whether the last port list failed (step 1 then offers "Try again"), and the newest attempt, so an earlier answer is ignored. */
  const [failed, setFailed] = useState(false);
  const attempt = useRef(0);
  // A retry shows "Loading ports…" again; loadPorts forgets a failure, so it fetches again.
  const loadList = () => {
    const mine = ++attempt.current;
    setPorts(null);
    loadPorts().then(list => { if (attempt.current === mine) { setFailed(false); setPorts(list); } },
      () => { if (attempt.current === mine) { setFailed(true); setPorts([]); } });
  };
  const [answer, setAnswer] = useState<LandingVerdict | null>(null);
  useEffect(() => {
    if (!load) return;
    let alive = true;
    loadList();
    // The verdict's modules load only once the readout is in, and nothing is set after unmount.
    void loadReadout(undefined, undefined, undefined, language.value).then(r => { setReadout(r); return alive ? verdict() : null; }).then(v => { if (alive) setAnswer(v); }, () => {});
    return () => { alive = false; leaveWarm(); };
  }, [load]);
  // Step 1 → 2: remember the choice and warm its region while they pick a profile; a later choice ignores an earlier warm-up's answer.
  const choose = (port: Port) => {
    setChoice({place: port.name, port});
    if (!load) return;
    leaveWarm();
    const selection = new AbortController();
    warming.current = selection;
    setWarmth('loading');
    void warm(port.region, selection.signal).then(r => { if (warming.current === selection) setWarmth(r.state); },
      () => { if (warming.current === selection) setWarmth('failed'); });
  };
  const explore = () => { leaveWarm(); setChoice({place: t('landing.place.central', language.value), port: null}); setWarmth(null); };
  const restart = () => { leaveWarm(); setChoice(null); setWarmth(null); setBack(true); };
  // Step 2: accept once, synchronously, even before navigation unmounts us.
  const finished = useRef(false);
  // SC-LANDING-ORDER: a Boat choice opens the map asking for the boat (MYB-1's fields, after the choice; boat-entry.ts carryAsk).
  const finish = (profile: Profile) => {
    if (!choice || finished.current) return;
    finished.current = true;
    const open = (url: string) => navigate(profile === 'boat' ? carryAsk(url) : url);
    if (choice.port) { savePort(choice.port.id); open(portURL(href, choice.port, profile)); return; }
    const url = new URL(exploreURL(href));
    url.searchParams.set('profile', profile);
    open(url.href);
  };
  return (
    <>
      <Readout data={readout} fleet={fleet} conditions={`/map?region=${DEFAULT_REGION}&view=conditions`} />
      {choice
        ? <ProfileStep place={choice.place} warm={choice.port ? warmth : null} current={initialProfile} onChoose={finish} onBack={restart} />
        : <PortInput ports={ports} onChoose={choose} onExplore={explore} onRetry={failed ? loadList : undefined} autoFocus={back} />}
      {/* SC1322-06: /map's cost-ceiling notice, above the verdict, which then reads as saved copies; nothing while live. */}
      <DegradedNotice />
      {answer ? <LiveVerdict v={answer} saved={degraded.value !== null} /> : null}
    </>
  );
}
