// MSKL-3 stub for kit layer 17 visibility-fog (VIS-B): no visibility grid (point visibility only) (LAYERS-KIT-PLAN § 2; data follow-up D-VIS).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-9 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('visibility-fog');
