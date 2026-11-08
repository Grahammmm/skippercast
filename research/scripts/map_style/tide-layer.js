// MAPLAYER-TIDE-1: tide layer for the map test page (style "tide 1" of the map style study).
//
// Reference: reports/skippercast-map-style-study/layers.py tide(1), flood/ebb arrows, green = flood, red = ebb.
// The study drew illustrative current arrows. CO-OPS publishes no tidal-current predictions for the
// central coast, so this layer draws the same symbol from the one thing that is published at stations:
// the predicted water level. An arrow UP and green = the water is rising (flood), DOWN and red = falling
// (ebb). It is NOT a current direction. Length follows the rate of rise or fall.
//
// Pure functions first (tested by tests/test_tide_layer.mjs), then the DOM part.

export const FLOOD = '#2e9e5b';   // study colours
export const EBB = '#d6452d';
export const STAND = '#7a8794';   // near high or low water: the level is barely moving
export const STAND_FT_PER_H = 0.15;
export const MAX_FT_PER_H = 1.6;  // arrow size saturates here

const HOUR = 3600e3;

/** Level (ft above MLLW) and rate (ft/h, + rising) at ms epoch `t`, half-cosine between predicted extremes. */
export function tideState(extremes, t) {
  const ts = extremes.map((e) => Date.parse(e.t));
  if (!(t >= ts[0] && t <= ts[ts.length - 1])) return {state: 'outside'};
  let i = 0;
  while (i < ts.length - 2 && t > ts[i + 1]) i++;
  const [a, b] = [extremes[i], extremes[i + 1]];
  const f = (t - ts[i]) / (ts[i + 1] - ts[i]);
  const dh = (ts[i + 1] - ts[i]) / HOUR;
  const level = a.v + (b.v - a.v) * (1 - Math.cos(Math.PI * f)) / 2;
  const rate = (b.v - a.v) * (Math.PI / 2) * Math.sin(Math.PI * f) / dh;
  const state = Math.abs(rate) < STAND_FT_PER_H ? 'stand' : rate > 0 ? 'rising' : 'falling';
  return {state, level, rate, next: b, prev: a};
}

export function colorFor(state) {
  return state === 'rising' ? FLOOD : state === 'falling' ? EBB : STAND;
}

/** Arrow size in px: 20 at the stand, 46 at MAX_FT_PER_H and above. */
export function sizeFor(rate) {
  return Math.round(20 + 26 * Math.min(1, Math.abs(rate) / MAX_FT_PER_H));
}

const PT = {timeZone: 'America/Los_Angeles', hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short'};
const PT_DAY = {...PT, weekday: 'short', month: 'short', day: 'numeric'};
export const fmtPT = (ms) => new Intl.DateTimeFormat('en-US', PT).format(ms);
export const fmtPTDay = (ms) => new Intl.DateTimeFormat('en-US', PT_DAY).format(ms);

/** Plain-words label lines for one station at time t. */
export function describe(station, t) {
  const s = tideState(station.extremes, t);
  if (s.state === 'outside') {
    const last = Date.parse(station.extremes[station.extremes.length - 1].t);
    return {state: 'outside', title: station.name,
            lines: [t > last ? `Predictions end ${fmtPTDay(last)}` : 'Before the predicted window']};
  }
  const near = (t - Date.parse(s.prev.t)) < (Date.parse(s.next.t) - t) ? s.prev : s.next;   // the extreme the level is closest to
  const word = s.state === 'rising' ? 'Rising' : s.state === 'falling' ? 'Falling' : 'Near ' + (near.type === 'H' ? 'high' : 'low');
  const rate = s.state === 'stand' ? '' : ` ${Math.abs(s.rate).toFixed(1)} ft/h`;
  const nextWord = s.next.type === 'H' ? 'high' : 'low';
  return {state: s.state, rate: s.rate, title: station.name,
          lines: [`${word}${rate} · ${s.level.toFixed(1)} ft`,
                  `next ${nextWord} ${s.next.v.toFixed(1)} ft, ${fmtPT(Date.parse(s.next.t))}`]};
}

/** Declutter: keep the first station of any group closer than `minPx`; `order` ranks them (harmonic first). */
export function declutter(stations, project, minPx) {
  const kept = [];
  for (const st of stations) {
    const p = project(st);
    if (kept.every((k) => Math.hypot(k.p.x - p.x, k.p.y - p.y) >= minPx)) kept.push({st, p});
  }
  return kept.map((k) => k.st);
}

export const rank = (st) => (st.kind === 'harmonic' ? 0 : 1);

function arrowSvg(color, px, down) {
  const rot = down ? ' transform="rotate(180 32 32)"' : '';
  return `<svg width="${px}" height="${px}" viewBox="0 0 64 64"><polygon${rot} points="32,3 56,31 41,31 41,61 23,61 23,31 8,31" ` +
         `fill="${color}" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/></svg>`;
}

/**
 * Add the layer to a MapLibre map. Returns {setTime(ms), setVisible(bool), data, summary()}.
 * `maplibregl` is passed in so this module stays loadable by node tests.
 */
export function addTideLayer(map, maplibregl, data, container) {
  const stations = [...data.stations].sort((a, b) => rank(a) - rank(b) || b.lat - a.lat);
  const markers = new Map();
  let time = Date.now();
  let visible = true;
  const mk = (st) => {
    const el = document.createElement('div');
    el.className = 'tide-mark';
    const m = new maplibregl.Marker({element: el, anchor: 'center'}).setLngLat([st.lon, st.lat]).addTo(map);
    markers.set(st.id, {st, el, m});
  };
  stations.forEach(mk);
  const paint = () => {
    const proj = (st) => map.project([st.lon, st.lat]);
    const z = map.getZoom();
    const shown = new Set(visible ? declutter(stations, proj, z >= 12 ? 0 : z >= 10 ? 34 : 60).map((s) => s.id) : []);
    for (const {st, el} of markers.values()) {
      el.style.display = shown.has(st.id) ? '' : 'none';
      if (!shown.has(st.id)) continue;
      const d = describe(st, time);
      const color = d.state === 'outside' ? '#b8b8b8' : colorFor(d.state);
      const px = d.state === 'outside' ? 20 : sizeFor(d.rate);
      el.innerHTML = `<div class="tide-arrow">${arrowSvg(color, px, d.state === 'falling')}</div>` +
        (z >= 9.5 ? `<div class="tide-label"><b></b><span></span><span></span></div>` : '');
      el.title = [d.title, ...d.lines, 'Prediction, not an observation. Not for navigation.'].join('\n');
      const lab = el.querySelector('.tide-label');
      if (lab) {
        lab.querySelector('b').textContent = d.title;
        const sp = lab.querySelectorAll('span');
        sp[0].textContent = d.lines[0];
        sp[1].textContent = d.lines[1] || '';
      }
    }
  };
  map.on('zoomend', paint);
  paint();
  return {
    data,
    setTime(ms) { time = ms; paint(); },
    setVisible(v) { visible = v; paint(); },
    count: () => stations.length,
    shownCount: () => [...markers.values()].filter((x) => x.el.style.display !== 'none').length,
  };
}
