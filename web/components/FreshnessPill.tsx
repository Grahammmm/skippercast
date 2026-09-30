// Freshness pill (guide §5.5): how old one source's latest reading is, in
// relative time ("Buoy 4 min ago", "Buoy stale 2 h", "Buoy unavailable").
// It keeps the reading time and the feed state, never a label: freshnessPill()
// (web/confidence.ts, over live-conditions.js freshness()) judges them at
// render time and again every minute while the pill is on screen.
import {useEffect, useState} from 'preact/hooks';
import {freshnessPill, type Observation} from '../confidence.ts';

export const FRESHNESS_TICK_MS = 60_000;

export function FreshnessPill({observation, source = 'Buoy'}: {observation: Observation | null; source?: string}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), FRESHNESS_TICK_MS);
    return () => clearInterval(timer);
  }, []);
  // A new observation is judged at once, not at the next tick.
  const {state, label} = freshnessPill(observation, Math.max(now, Date.now()), source);
  return (
    <span class="freshness-pill" data-state={state}>
      <span class="freshness-dot" aria-hidden="true"></span>{label}
    </span>
  );
}
