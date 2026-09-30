// Freshness pill (guide §5.5): how old one source's latest reading is, in
// relative time ("Buoy 4 min ago", "Buoy stale 2 h", "Buoy unavailable").
// The wording and state come from freshnessPill() in web/confidence.ts.
import type {Pill} from '../confidence.ts';

export function FreshnessPill({state, label}: Pill) {
  return (
    <span class="freshness-pill" data-state={state}>
      <span class="freshness-dot" aria-hidden="true"></span>{label}
    </span>
  );
}
