// The C2 release view (M9): web/map/terrain.js's loadC2 imports this only when
// web/map/c2-releases.ts lists the region, so MapLibre and the coast-MVP viewer
// stay out of the terrain module and never load while the flag is off.
import mapStyles from 'maplibre-gl/dist/maplibre-gl.css?url';
// A separate module id: packages/coast/src/coast3d/viewer.ts re-exports mvp.ts into the terrain module's
// graph, so the plain path would place the viewer, and a static MapLibre import, in the terrain chunk.
import {CoastMvpViewer} from '../../packages/coast/src/coast3d/mvp.ts?c2';
import placement from './c2.css?url';
import {lib, workerUrl} from './maplibre.js';

/** Mount the release at `url` in the host's shadow root; a refusal (or a throw) leaves nothing behind. */
export async function mountRelease(host, url) {
  lib.setWorkerUrl(workerUrl);
  const root = host.shadowRoot ?? host.attachShadow({mode: 'open'});
  const nodes = [mapStyles, placement].map(href => Object.assign(document.createElement('link'), {rel: 'stylesheet', href}));
  const div = Object.assign(document.createElement('div'), {className: 'coast-c2'});
  nodes.push(div);
  root.append(...nodes);
  const remove = () => { for (const node of nodes) node.remove(); };
  let result;
  try { result = await CoastMvpViewer.loadRelease(div, url, {lib}); } catch (error) { remove(); throw error; }
  if ('refused' in result) { remove(); return result; }
  return {
    destroy() { result.viewer.destroy(); remove(); },
    setVisible(visible) { div.hidden = !visible; },
  };
}
