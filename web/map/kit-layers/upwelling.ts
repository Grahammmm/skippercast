// MSKL-3 stub for kit layer 06 upwelling (UPW-A): no CUTI/BEUTI source row (LAYERS-KIT-PLAN § 2; data follow-up D-CUTI).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-11 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('upwelling');
