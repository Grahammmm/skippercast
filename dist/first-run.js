// First run: harbor → boat → tomorrow's answer, in under a minute.
// Step 1 is the home-port chooser (home-port.js). Choosing a port there on a
// first visit sets the next step here; each step survives the reload that
// applies it. Nothing leaves the browser.
import { BOAT_KEY, normalizeBoat, savedBoat } from './boat-handling.js';
import { latestTomorrow, clock } from './tomorrow.js';

export const FIRST_RUN_KEY = 'skippercast-first-run-v1';
const STEPS = ['boat', 'answer'];

export const PRESETS = [
  { id: 'skiff', label: 'Skiff or small center console', detail: '16–18 ft', boat: { name: 'Skiff (16–18 ft)', loa_ft: 17, hull: 'modified-v', layout: 'skiff' } },
  { id: 'console', label: 'Center console', detail: '20–24 ft', boat: { name: 'Center console (20–24 ft)', loa_ft: 22, hull: 'modified-v', layout: 'center-console' } },
  { id: 'walkaround', label: 'Walkaround or cuddy', detail: '22–26 ft', boat: { name: 'Walkaround (22–26 ft)', loa_ft: 24, hull: 'deep-v', layout: 'walkaround' } },
  { id: 'cabin', label: 'Cabin or sportfisher', detail: '28–35 ft', boat: { name: 'Cabin boat (28–35 ft)', loa_ft: 31, hull: 'deep-v', layout: 'pilothouse' } },
];

const read = (storage) => { try { return storage?.getItem(FIRST_RUN_KEY) || null; } catch { return null; } };
const write = (storage, value) => { try { value ? storage.setItem(FIRST_RUN_KEY, value) : storage.removeItem(FIRST_RUN_KEY); return true; } catch { return false; } };

/** The pending first-run step ('boat', 'answer') or null when there is none. */
export function pendingStep(storage = globalThis.localStorage) {
  const step = read(storage);
  return STEPS.includes(step) ? step : null;
}
/** Called by the port chooser on a first visit. */
export function startFirstRun(storage = globalThis.localStorage) { return write(storage, 'boat'); }
export function advance(storage = globalThis.localStorage) {
  const i = STEPS.indexOf(pendingStep(storage));
  return write(storage, i >= 0 && i + 1 < STEPS.length ? STEPS[i + 1] : null);
}
export function finish(storage = globalThis.localStorage) { return write(storage, null); }

/** Save a preset boat the same way the boat sheet does (boat-profile.js). */
export function savePreset(id, storage = globalThis.localStorage, now = new Date()) {
  const preset = PRESETS.find((p) => p.id === id);
  if (!preset) return false;
  try {
    storage.setItem(BOAT_KEY, JSON.stringify({ schema_version: 1, boat: normalizeBoat(preset.boat), query: '', preset: id, saved_at: now.toISOString(), lookup: null }));
    return true;
  } catch { return false; }
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** Step 3 text: the single answer for tomorrow, with caveats kept for "Why?". */
export function answerHTML(day, { pointName = '', boatName = '' } = {}) {
  if (!day) return '';
  const word = { go: 'Go', marginal: 'Marginal', 'no-go': 'No-go', unknown: 'No usable forecast yet' }[day.verdict] || 'Check conditions';
  const detail = day.verdict === 'go' && day.backBy
    ? `Comfortable from ${clock(day.departFrom)}; be back by ${clock(day.backBy)}.`
    : day.verdict === 'unknown' ? 'The forecast is not available right now.' : day.limit ? `Limit: ${day.limit.text}.` : '';
  return `<div class="home-port-kicker">STEP 3 OF 3 · TOMORROW${pointName ? ' · ' + esc(pointName).toUpperCase() : ''}</div>
    <h1 id="first-run-title" class="first-run-verdict tw-${esc(day.verdict)}">${esc(word)}</h1>
    <p class="first-run-detail">${esc(detail)}</p>
    <p class="first-run-meta">Confidence ${esc(day.confidence)} (${esc(day.agreement)})${boatName ? ' · for ' + esc(boatName) : ''}</p>
    <details class="first-run-why"><summary>Why?</summary><p>Two-hour windows from 5 a.m. to 7 p.m. are rated go at 7/10 or better for your boat, marginal from 4, and no-go below 4 or under any marine advisory. Confidence is how often NOAA GFS and ECMWF agree. This is a planning heuristic from model forecasts: it is not a routed trip, a harbor-bar clearance or a safety certification, and it does not predict fish. Check the latest marine forecast, the bar and your own judgment before you go.</p></details>`;
}

function card(inner, labelledby) {
  const previous = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim first-run-scrim';
  scrim.innerHTML = `<section class="home-port-card first-run-card" role="dialog" aria-modal="true" aria-labelledby="${labelledby}">${inner}</section>`;
  document.body.append(scrim);
  document.body.classList.add('choosing-home-port');
  const close = () => { scrim.remove(); document.body.classList.remove('choosing-home-port'); previous?.focus?.(); };
  scrim.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  return { scrim, close };
}

function boatStep(storage) {
  const { scrim, close } = card(`<div class="home-port-kicker">STEP 2 OF 3 · YOUR BOAT</div>
    <h1 id="first-run-title">What do you fish from?</h1>
    <p class="home-port-intro">Ratings scale to your boat's size and hull. Pick the closest; you can enter your exact boat later.</p>
    <div class="home-port-results first-run-boats">${PRESETS.map((p) => `<button type="button" class="home-port-option" data-preset="${p.id}"><strong>${esc(p.label)}</strong><span>${esc(p.detail)}</span></button>`).join('')}</div>
    <div class="home-port-actions"><button type="button" id="first-run-exact">Enter my exact boat</button><button type="button" id="first-run-skip">Skip · use a 23 ft deep-V</button></div>`, 'first-run-title');
  scrim.addEventListener('click', (e) => {
    const preset = e.target.closest('[data-preset]');
    if (preset) {
      if (!savePreset(preset.dataset.preset, storage)) { close(); finish(storage); return; }
      advance(storage); location.reload();   // ratings read the boat on load
    }
  });
  scrim.querySelector('#first-run-skip').addEventListener('click', () => { advance(storage); close(); showAnswer(storage); });
  scrim.querySelector('#first-run-exact').addEventListener('click', () => {
    advance(storage); close();
    document.getElementById('boat-button')?.click();   // the full boat sheet saves and reloads
  });
  scrim.querySelector('[data-preset]')?.focus();
}

function showAnswer(storage) {
  const render = (plan) => {
    const day = plan?.days?.[0];
    if (!day) return false;
    finish(storage);
    const boat = savedBoat()?.boat;
    const { scrim, close } = card(`${answerHTML(day, { pointName: plan.pointName, boatName: boat?.name || '' })}
      <div class="home-port-actions"><button type="button" id="first-run-forecast" class="primary">See the 3-day plan</button><button type="button" id="first-run-map">Open the map</button></div>`, 'first-run-title');
    scrim.querySelector('#first-run-forecast').addEventListener('click', () => { close(); location.hash = 'forecast'; });
    scrim.querySelector('#first-run-map').addEventListener('click', () => { close(); location.hash = 'map'; });
    scrim.querySelector('#first-run-forecast').focus();
    return true;
  };
  if (render(latestTomorrow())) return;
  const listener = (event) => { if (render(event.detail)) document.removeEventListener('skippercast:tomorrow', listener); };
  document.addEventListener('skippercast:tomorrow', listener);
}

/** Run the pending first-run step, if any. */
export function initFirstRun(storage = globalThis.localStorage) {
  const step = pendingStep(storage);
  if (step === 'boat') boatStep(storage);
  else if (step === 'answer') showAnswer(storage);
  return step;
}
