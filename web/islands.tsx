// Preact islands (P4-01b): components rendered into slots of the existing
// page. Loaded as a module script of index.html after boot.js and offline.js
// and before meteogram-ui.js, which draws into the card this renders.
import {render, type ComponentChild} from 'preact';
import {effect, untracked} from '@preact/signals';
import {FreshnessBanner} from './components/FreshnessBanner.tsx';
import {MapLegend} from './components/MapLegend.tsx';
import {MeteogramCard} from './components/MeteogramCard.tsx';
import {OutlookBadge} from './components/OutlookBadge.tsx';
import {SpotConfidence} from './components/SpotConfidence.tsx';
import {followForecastHour} from './hour.ts';
import {startURLSync} from './state.ts';
import {spotConfidence} from './views.ts';

/** Render `node` as the only content of `host`; false when the slot is missing. */
export function mount(host: Element | null, node: ComponentChild): boolean {
  if (!host) return false;
  host.replaceChildren();
  render(node, host);
  return true;
}

startURLSync();
const badge = document.getElementById('best-day-banner');
mount(badge, <OutlookBadge host={badge} />);
mount(document.getElementById('meteogram-card'), <MeteogramCard />);
const banner = document.getElementById('offline-banner');
mount(banner, <FreshnessBanner host={banner} />);
mount(document.getElementById('map-legend'), <MapLegend />);
followForecastHour();

// The spot sheet is redrawn (innerHTML) on every selection, so its badge slot
// is new each time: unmount the previous row, then mount into the new slot.
let spotSlot: Element | null = null;
effect(() => {
  const spot = spotConfidence.value;
  untracked(() => {
    if (spotSlot) render(null, spotSlot);
    spotSlot = spot ? document.getElementById('spot-confidence') : null;
    if (spot) mount(spotSlot, <SpotConfidence badges={spot.badges} buoy={spot.buoy} />);
  });
});
