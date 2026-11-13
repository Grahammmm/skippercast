// Entry of dist/app.html (SCB-11). The app's code (./main.tsx and everything it imports) is a few hundred KB, which takes seconds
// on a slow phone; the reads the first verdict waits on start here, before that code is asked for, and the app takes their answers
// when it runs (web/early-reads.ts). This entry imports nothing else, so it runs as soon as the page has it.
import {startEarlyReads} from '../early-reads.ts';

startEarlyReads();
void import('./main.tsx');
