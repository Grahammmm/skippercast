// Preact islands (P4-01b): components rendered into slots of the existing
// page. Loaded as a module script of index.html after boot.js and offline.js
// and before meteogram-ui.js, which draws into the card this renders.
import {render, type ComponentChild} from 'preact';
import {FreshnessBanner} from './components/FreshnessBanner.tsx';
import {MeteogramCard} from './components/MeteogramCard.tsx';
import {OutlookBadge} from './components/OutlookBadge.tsx';
import {followForecastHour} from './hour.ts';
import {startURLSync} from './state.ts';

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
followForecastHour();
