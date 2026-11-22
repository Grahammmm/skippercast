// MSKL-3 stub for kit layer 09 salinity (SAL-B): no salinity model source row (LAYERS-KIT-PLAN § 2; data follow-up D-HYCOM).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-5 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('salinity');
