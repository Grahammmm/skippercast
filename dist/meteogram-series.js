// Hourly meteogram columns from the marine bundle the Conditions view already
// loaded. Imported lazily by meteogram-ui.js after the app has set the region,
// because marine-data.js captures the region's forecast points on import.
import { pointBundle } from "./region.js";
import { readConditions, tideAt, HOUR } from "./marine-data.js";
import { rateHour } from "./morning-outlook.js";
import { agreementLevel, PROVISIONAL_HOUR } from "./meteogram-core.js";

const finite = Number.isFinite;

/**
 * Values come from the same readers as the rest of the Conditions view;
 * anything missing stays null. Gusts below sustained wind are inconsistent and
 * are left out, as the hourly score does. Hours from +72 h are flagged
 * provisional, matching the selected-hour label in weather-ui.js.
 */
export function buildSeries(bundle, point, species, family, start, now = Date.now(), length = 169) {
  const selected = pointBundle(bundle, point);
  const other = family === "gfs" ? "ecmwf" : "gfs";
  const s = { times: [], wind: [], gust: [], sea: [], period: [], tide: [], score: [], hazard: [], agreement: [], provisional: [] };
  for (let i = 0; i < length; i++) {
    const t = start + i * HOUR;
    const c = readConditions(selected, point, t, family), o = readConditions(selected, point, t, other);
    const rating = rateHour(selected, point, species, t, now);
    s.times.push(t);
    s.wind.push(finite(c.wind) ? c.wind : null);
    s.gust.push(finite(c.gust) && finite(c.wind) && c.gust >= c.wind ? c.gust : null);
    s.sea.push(finite(c.sea.height) ? c.sea.height : null);
    s.period.push(finite(c.sea.period) && c.sea.period > 0 ? c.sea.period : null);
    const tide = Array.isArray(selected?.tides) ? tideAt(selected.tides, t) : null;
    s.tide.push(finite(tide) ? tide : null);
    s.score.push(finite(rating.conditions) ? rating.conditions : null);
    s.hazard.push(!!rating.hazard);
    s.agreement.push(agreementLevel({ wind: c.wind, sea: c.sea.height }, { wind: o.wind, sea: o.sea.height }));
    s.provisional.push(i >= PROVISIONAL_HOUR);
  }
  return s;
}
