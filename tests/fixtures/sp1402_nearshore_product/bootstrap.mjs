// Node's installed native type stripping; no extracted functions or source rewriting.
import {installOffline} from './offline.mjs';
const restore = installOffline();
process.on('exit', () => {
  try { restore(); } catch (error) { console.error(error); process.exitCode = 1; }
});
