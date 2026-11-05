// Mock-only boundary for the chart-pack delete tests: the SP-15 boundary, with savePack able to wait on a per-test gate (or on Cancel).
import {runtime} from '../sp1502_pack_inventory/runtime.mjs';
export * from '../sp1502_pack_inventory/boundary.mjs';
export const savePack = async (_id, signal) => {
  runtime.saves++;
  if (runtime.saveGate) await Promise.race([runtime.saveGate.promise, new Promise((_, no) => signal?.addEventListener('abort', () => no(new Error('aborted'))))]);
  return runtime.saveMeta ?? {region_name: 'Fixture Harbor', bytes: 128, missing: []};
};
