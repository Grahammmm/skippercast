// MSKL-3 stub for kit layer 10 sea-ice (ICE-B): no sea-ice source row, and no sea ice on this coast (LAYERS-KIT-PLAN § 2; data follow-up D-ICE).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-11 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('sea-ice');
