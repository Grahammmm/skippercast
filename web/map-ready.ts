// SC-PERF-LAZY-1: whether the map has first painted. Its own file so the chart can set it without importing the ranking code.
import {signal} from '@preact/signals';

/** True once the map has drawn its first idle frame, or could not start (so nothing waits for a map that will not come). */
export const mapFirstIdle = signal(false);
export const markMapIdle = (): void => { if (!mapFirstIdle.peek()) mapFirstIdle.value = true; };
