// ?hour= follows the forecast hour (P4-01b). weather-ui.js announces every
// render with a "skippercast:forecast" event (detail.time: the selected hour,
// epoch seconds) and owns the hour through the #detail-hour range input, so
// this reads that input and writes the URL, and on the first forecast selects
// the hour a shared link asks for, if it is inside the timeline.
import {hour, hourParam, parseHour, setParams} from './state.ts';

const HOUR = 3600;

/** The timeline index for `wanted` given the selected time and index, or null outside 0..max. */
export function indexForHour(wanted: number | null, selectedTime: number, selectedIndex: number, max = 168): number | null {
  if (wanted === null || !Number.isFinite(selectedTime)) return null;
  const i = Math.round((wanted - (selectedTime - selectedIndex * HOUR)) / HOUR);
  return i >= 0 && i <= max ? i : null;
}

export function followForecastHour(doc: Document = document): void {
  let applied = false;
  const follow = (event: Event) => {
    const detail = (event as CustomEvent<{time?: number; epoch?: number}>).detail || {};
    const selectedTime = detail.epoch ?? detail.time;
    const input = doc.getElementById('detail-hour') as HTMLInputElement | null;
    if (!input || typeof selectedTime !== 'number' || !Number.isFinite(selectedTime)) return;
    const index = Number(input.value) || 0;
    if (!applied) {
      applied = true;
      const i = indexForHour(parseHour(hour.value), selectedTime, index, Number(input.max) || 168);
      if (i !== null && i !== index) {
        input.value = String(i);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        return;
      }
    }
    // "Now" (index 0) is the default and is not written.
    const next = index === 0 ? null : hourParam(selectedTime);
    if (next !== hour.value) setParams({hour: next});
  };
  // The clock publishes even when neither model can load.
  doc.addEventListener('skippercast:time', follow);
  doc.addEventListener('skippercast:forecast', follow);
}
