// Telemetry for the server-rendered advisor pages (TA-W1; docs/plans/text-advisor/08-website.md
// § Telemetry): one view event per page load for the port, species and boat
// pages, and `advisor_cta` when the "Text SkipperCast" link is followed. The
// page says which family it is (<body data-advisor-page>) and its region
// (data-region); web/telemetry.ts adds the visit source from the URL's `s`
// (txt, ig, fb, qr) and sends nothing when the browser opts out.
import {initTelemetry, track} from '../telemetry.ts';
import type {FunnelEvent} from '../telemetry.ts';

export const PAGE_VIEWS: Readonly<Record<string, FunnelEvent>> = {port: 'advisor_port_view', species: 'advisor_species_view', boat: 'advisor_boat_view'};

/** Start page telemetry on an advisor page; false on any other page or when telemetry is off. */
export function startPageTelemetry(doc: Document): boolean {
  const body = doc.body, view = body ? PAGE_VIEWS[body.dataset.advisorPage ?? ''] : undefined;
  if (!body || !view) return false;
  if (!initTelemetry()) return false;
  const region = body.dataset.region ?? '';
  track(view, {region});
  doc.addEventListener('click', event => {
    const target = event.target as Element | null;
    if (target?.closest?.('[data-advisor-cta]')) track('advisor_cta', {region, flush: true});
  });
  return true;
}

if (typeof document !== 'undefined') startPageTelemetry(document);
