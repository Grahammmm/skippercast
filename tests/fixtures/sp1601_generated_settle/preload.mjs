// Used only in the dedicated unchanged-regression child process.
import {installOffline} from './offline.mjs';
const guard = installOffline();
process.once('exit', () => guard.restore());
