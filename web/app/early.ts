// /map's early script (SCB-11), linked async at the top of the page by vite.config.mjs EARLY_SCRIPTS. The app's code (./main.tsx
// and everything it imports) is a few hundred KB, which takes seconds on a slow phone; the reads the first verdict waits on start
// here, as soon as this small file arrives, and the app takes their answers when it runs (web/early-reads.ts). It imports nothing
// the app shares, so it is a file of its own. Should the app already be running (it marks the page before its first read), the
// app has asked for those files itself and this does nothing.
import {startEarlyReads} from '../early-reads.ts';

if (!(globalThis as {skippercastApp?: boolean}).skippercastApp) startEarlyReads();
