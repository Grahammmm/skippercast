// Boat profile sheet: enter a boat, optionally look it up with AI, confirm the
// numbers, and save them in this browser. Saved profiles scale the conditions
// ratings (boat-handling.js). Nothing here is sent anywhere except the name
// typed for an AI lookup, and only when the person asks for one.
import {BOAT_KEY, HULLS, LAYOUTS, REFERENCE, boatFactors, describeFactors, normalizeBoat, savedBoat} from './boat-handling.js';

const FIELDS = [
  ['loa_ft', 'Length overall', 'ft', 0.1], ['beam_ft', 'Beam', 'ft', 0.1],
  ['displacement_lb', 'Loaded weight', 'lb', 50], ['deadrise_deg', 'Deadrise at transom', '°', 1],
  ['cruise_kn', 'Cruise speed', 'kn', 1],
];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

function store(profile) {
  try { localStorage.setItem(BOAT_KEY, JSON.stringify(profile)); return true; } catch { return false; }
}
function clear() { try { localStorage.removeItem(BOAT_KEY); } catch { /* nothing saved */ } }

export function shortName(boat) {
  if (!boat) return 'Boat';
  return boat.loa_ft ? `${Math.round(boat.loa_ft)} ft` : 'Boat';
}

function thresholdsHTML(boat) {
  const f = boatFactors(boat), d = describeFactors(f), ref = describeFactors(boatFactors(null));
  return `<p class="boat-effect"><strong>How ratings change:</strong> seas start to count above <b>${d.seas} ft</b> (reference ${ref.seas} ft),
    short chop above <b>${d.chop} ft</b> under ${d.chopPeriod} s, wind above <b>${d.wind} kn</b>, gusts above <b>${d.gust} kn</b>.
    Penalties per foot and per knot shrink or grow in proportion.</p>`;
}

function sheet() {
  const previous = document.activeElement, saved = savedBoat();
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim boat-scrim';
  scrim.innerHTML = `<section class="home-port-card boat-card" role="dialog" aria-modal="true" aria-labelledby="boat-title">
    <div class="home-port-kicker">YOUR BOAT</div>
    <h1 id="boat-title">Rate conditions for your boat</h1>
    <p class="home-port-intro">Enter your boat and SkipperCast scales its comfort and drift-control ratings to its size and hull.
      Without a boat, ratings use a 23 ft, 20° deep-V walkaround.</p>
    <label for="boat-query">Make, model and year</label>
    <div class="boat-query-row"><input id="boat-query" type="text" autocomplete="off" maxlength="120" placeholder="e.g. Boston Whaler 230 Vantage" value="${esc(saved?.query || saved?.boat?.name || '')}" />
      <button type="button" id="boat-lookup">Look up with AI</button></div>
    <p id="boat-status" class="home-port-feedback" role="status"></p>
    <div id="boat-sources"></div>
    <form id="boat-form" class="boat-form">
      ${FIELDS.map(([key, label, unit, step]) => `<label><span>${label} <span class="boat-unit">(${unit})</span></span>
        <input name="${key}" type="number" inputmode="decimal" step="${step}" min="0" value="${esc(saved?.boat?.[key] ?? '')}" />
        <span class="boat-ai" data-ai="${key}" hidden>AI estimate</span></label>`).join('')}
      <label><span>Hull</span> <select name="hull"><option value="">Choose…</option>${Object.entries(HULLS).map(([k, v]) => `<option value="${k}"${saved?.boat?.hull === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>
        <span class="boat-ai" data-ai="hull" hidden>AI estimate</span></label>
      <label><span>Layout</span> <select name="layout"><option value="">Choose…</option>${Object.entries(LAYOUTS).map(([k, v]) => `<option value="${k}"${saved?.boat?.layout === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>
        <span class="boat-ai" data-ai="layout" hidden>AI estimate</span></label>
    </form>
    <div id="boat-effect">${thresholdsHTML(saved?.boat || null)}</div>
    <div class="home-port-actions"><button type="button" id="boat-save">Save boat</button>${saved ? '<button type="button" id="boat-clear">Use reference boat</button>' : ''}</div>
    <p class="home-port-fine">Check every number against your boat's documents; AI lookups can be wrong. Loaded weight includes fuel, crew and gear
      (about 1.3× dry weight if you don't know it). This is a comfort heuristic, not a seaworthiness or safety rating. Saved in this browser only.</p>
    <button type="button" class="home-port-close" aria-label="Close boat profile">×</button>
  </section>`;
  document.body.append(scrim);
  document.body.classList.add('choosing-home-port');
  const $ = sel => scrim.querySelector(sel);
  const form = $('#boat-form'), status = $('#boat-status');
  let lookup = saved?.lookup || null;

  const read = () => normalizeBoat({...Object.fromEntries(new FormData(form)), name: lookup?.boat?.name || $('#boat-query').value});
  const refresh = () => { $('#boat-effect').innerHTML = thresholdsHTML(read()); };
  form.addEventListener('input', event => {
    const marker = scrim.querySelector(`[data-ai="${event.target.name}"]`);
    if (marker) marker.hidden = true;  // edited by the person: no longer an AI estimate
    refresh();
  });
  const showSources = result => {
    const box = $('#boat-sources');
    if (!result) { box.replaceChildren(); return; }
    box.innerHTML = `<div class="boat-match"><strong>${esc(result.boat.name || 'Best match')}</strong>
      <span>AI confidence: ${esc(result.confidence)}</span>${result.notes ? `<p>${esc(result.notes)}</p>` : ''}
      ${result.sources?.length ? `<p class="boat-sources">Sources: ${result.sources.map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>`).join(' · ')}</p>` : ''}</div>`;
  };
  if (lookup) showSources(lookup);

  $('#boat-lookup').addEventListener('click', async () => {
    const query = $('#boat-query').value.trim();
    if (query.length < 3) { status.textContent = 'Enter the make and model first.'; return; }
    status.textContent = 'Looking up published specifications… this can take up to a minute.';
    $('#boat-lookup').disabled = true;
    try {
      const response = await fetch('/api/boat/lookup', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}), signal: AbortSignal.timeout(90000)});
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) {
        const signIn = typeof data.signIn === 'string' ? data.signIn : '';
        status.innerHTML = signIn && signIn.startsWith('/') ? `Sign in to use AI lookup, or enter the numbers below by hand. <a href="${signIn.replace('%2F%23forecast', '%2F%23map')}">Sign in</a>` : 'AI lookup needs an account, which is coming soon. Enter the numbers below by hand.';
        return;
      }
      if (!response.ok) { status.textContent = data.error || 'Lookup failed. Enter the numbers below by hand.'; return; }
      lookup = data;
      for (const [key] of FIELDS) {
        const value = data.boat[key] ?? (key === 'displacement_lb' ? data.boat.displacement_lb : null);
        form.elements[key].value = value ?? '';
        scrim.querySelector(`[data-ai="${key}"]`).hidden = value == null;
      }
      for (const key of ['hull', 'layout']) {
        form.elements[key].value = data.boat[key] || '';
        scrim.querySelector(`[data-ai="${key}"]`).hidden = !data.boat[key];
      }
      showSources(data);
      status.textContent = 'Found it. Check each number, then save.';
      refresh();
    } catch {
      status.textContent = 'Lookup failed. Enter the numbers below by hand.';
    } finally { $('#boat-lookup').disabled = false; }
  });

  $('#boat-save').addEventListener('click', () => {
    const boat = read();
    if (!boat.loa_ft) { status.textContent = 'Length overall is needed to rate conditions for your boat.'; return; }
    const ok = store({schema_version: 1, boat, query: $('#boat-query').value.trim(), saved_at: new Date().toISOString(),
      lookup: lookup ? {boat: lookup.boat, confidence: lookup.confidence, notes: lookup.notes, sources: lookup.sources} : null});
    if (!ok) { status.textContent = 'This browser blocked saving. Ratings keep the reference boat.'; return; }
    location.reload();  // ratings are computed on load
  });
  $('#boat-clear')?.addEventListener('click', () => { clear(); location.reload(); });

  const close = () => { scrim.remove(); document.body.classList.remove('choosing-home-port'); previous?.focus?.(); };
  $('.home-port-close').addEventListener('click', close);
  scrim.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); close(); } });
  $('#boat-query').focus();
}

export function initBoatProfile() {
  const button = document.getElementById('boat-button');
  if (!button) return;
  const saved = savedBoat();
  button.textContent = shortName(saved?.boat);
  button.setAttribute('aria-label', saved?.boat ? `Boat profile: ${saved.boat.name || shortName(saved.boat)}` : 'Set your boat');
  button.addEventListener('click', sheet);
}

export {REFERENCE};
