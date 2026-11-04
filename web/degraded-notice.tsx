// SC-LAUNCH-4 / SC1322-06: the cost-ceiling notice, shared by /map's masthead and mobile sheet
// (re-exported from web/app/Masthead.tsx) and the landing (web/landing/Landing.tsx), so both pages
// say the same words. Its own module, so the landing does not pull the map shell (App.tsx) in.
import {degraded, degradedText} from './degraded.ts';

/** SC-LAUNCH-4: says so while the Worker is past its daily cost ceiling and answering with saved copies (web/degraded.ts). */
export function DegradedNotice() {
  const text = degradedText(degraded.value);
  // Existing note paint (app.css .app-limits-note), so the pinned contrast proof of app.css is untouched.
  return text ? <p class="app-limits-note app-degraded" role="status" data-degraded="cost-ceiling">{text}</p> : null;
}
