// MSKL-3 stub for kit layer 15 precip-radar (RADAR-C): no MRMS source row (LAYERS-KIT-PLAN § 2; data follow-up D-MRMS).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-9 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('precip-radar');
