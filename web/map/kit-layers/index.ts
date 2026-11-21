// MSKL-3: the kit layers that have their own module here, by kit id. A layer card replaces its own module, never this list.
// Erasable syntax only: tests/test_stacking.mjs imports it by type stripping.
import type {KitLayerModule} from './no-data.ts';
import kd490 from './kd490.ts';
import ssh from './ssh.ts';
import upwelling from './upwelling.ts';
import subsurface_temp from './subsurface-temp.ts';
import salinity from './salinity.ts';
import sea_ice from './sea-ice.ts';
import pressure from './pressure.ts';
import precip_radar from './precip-radar.ts';
import visibility_fog from './visibility-fog.ts';

export const KIT_LAYER_MODULES: Readonly<Record<string, KitLayerModule>> = Object.freeze({
  kd490, ssh, upwelling, 'subsurface-temp': subsurface_temp, salinity, 'sea-ice': sea_ice, pressure, 'precip-radar': precip_radar, 'visibility-fog': visibility_fog,
});
