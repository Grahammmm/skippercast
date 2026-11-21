// MSKL-3 stub for kit layer 05 ssh (SSH-B): no blended sea-surface-height source row (LAYERS-KIT-PLAN § 2; data follow-up D-SSH).
// Draws nothing, never switches itself on; its legend row says "no data yet". MSKL-6 replaces this file with the layer.
import {noDataLayer} from './no-data.ts';

export default noDataLayer('ssh');
