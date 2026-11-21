// MSKL-3 stub for kit layer 12 pressure (PRES-A): no sea-level pressure grid in the forecast tiles (LAYERS-KIT-PLAN § 2; data follow-up D-MSLP).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-6 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('pressure');
