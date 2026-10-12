// Layer dots (FE-07, design § 7): one dot per layer rail entry on the right
// edge, each a link into the app with that layer on (/map?region=…&layers=…;
// Currents also names the rail's default source, `current=wcofs`, FE-20).
// The name shows on hover and focus; it is the link text, so it is also the
// accessible name. Hover and focus also report the layer (`onPreview`), so the
// live night map (FE-25) can preview the one layer it draws, Currents. The labels
// are the rail's (web/app/LayerRail.tsx RAIL_ENTRIES, equal by test): the
// landing does not import the app's rail, its store or their chunks before
// first paint.
import {RAIL_IDS, type RailId} from '../profile.ts';

/** web/state.ts DEFAULT_CURRENT (equal by test): the source the rail's Currents entry turns on. */
export const DOT_CURRENT = 'wcofs';

export const DOT_LABELS: Readonly<Record<RailId, string>> = {
  seafloor: 'Seafloor', currents: 'Currents', 'water-temp': 'Water temp', swell: 'Swell', fleet: 'Charter fleet', clouds: 'Clouds',
};

/** The app at `region` with only `layer` on (Currents with the rail's default source); the ui switch of `href` stays. */
export function layerURL(href: string, region: string, layer: string): string {
  const url = new URL(href);
  const ui = url.searchParams.get('ui');
  url.pathname = '/map'; url.hash = ''; url.search = '';
  url.searchParams.set('region', region);
  url.searchParams.set('layers', layer);
  if (layer === 'currents') url.searchParams.set('current', DOT_CURRENT);
  if (ui) url.searchParams.set('ui', ui);
  return url.href;
}

/** `onPreview` gets the hovered or focused layer, and null when the pointer or focus leaves it. */
export function LayerDots({href, region, onPreview}: {href: string; region: string; onPreview?: (layer: RailId | null) => void}) {
  return (
    <nav class="landing-dots" aria-label="Map layers">
      <ul>
        {RAIL_IDS.map(id => (
          <li key={id}>
            <a href={layerURL(href, region, id)} data-layer={id} onPointerEnter={() => onPreview?.(id)} onPointerLeave={() => onPreview?.(null)}
              onFocus={() => onPreview?.(id)} onBlur={() => onPreview?.(null)}>
              <span class="landing-dot" aria-hidden="true"></span>
              <span class="landing-dot-name">{DOT_LABELS[id]}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
