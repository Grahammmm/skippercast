import { esc } from "./marine-charts.js?v=5.4";
import { loadDailyEvidence } from "./bite-evidence.js?v=5.6";

const HOUR = 3600000;
const IDS = ["lingcod", "rockfish", "halibut", "salmon", "albacore", "bluefin", "dungeness"];
const dateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit",
});
const dateOnly = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && Number.isFinite(Date.parse(s));
const age = (s, now) => (now - Date.parse(s)) / HOUR;
const time = (s) => Number.isFinite(Date.parse(s)) ? new Date(s).toLocaleString("en-US", {
  timeZone: "America/Los_Angeles", month: "short", day: "numeric", year: "numeric",
  hour: "numeric", minute: "2-digit",
}) + " PT" : "Unavailable";
export function officialURL(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && ["wildlife.ca.gov", "nrm.dfg.ca.gov"].includes(u.hostname) ? u.href : "https://wildlife.ca.gov/Fishing/Ocean";
  } catch { return "https://wildlife.ca.gov/Fishing/Ocean"; }
}
export function validRegulations(data) {
  return data?.schema_version === 1 && Number.isFinite(Date.parse(data.reviewed_at)) &&
    dateOnly(data.valid_from) && dateOnly(data.valid_through) && data.valid_from <= data.valid_through &&
    data.sources && data.checks && Array.isArray(data.common_notes) &&
    IDS.every((id) => {
      const p = data.species?.[id];
      return p && [p.name, p.season, p.bag, p.size].every((x) => typeof x === "string") &&
        Array.isArray(p.details) && p.details.every((s) => typeof s === "string") &&
        Array.isArray(p.source_ids) && p.source_ids.length > 0 && p.source_ids.every((s) => data.sources[s]?.url) &&
        Array.isArray(p.windows) && p.windows.every((w) => dateOnly(w.start) && dateOnly(w.end) && w.start <= w.end);
    });
}

export function regulationState(data, species, now = Date.now()) {
  const today = dateFormat.format(new Date(now));
  if (!validRegulations(data) || !IDS.includes(species))
    return { status: "unknown", label: "Check rules", today, reason: "Regulations unavailable. Open the official CDFW rules before fishing.", issues: [] };
  const p = data.species[species];
  const issues = p.source_ids.filter((id) => {
    const s = data.checks[id], approved = data.sources[id].approved_content_sha256;
    return !s || s.status !== "unchanged" || s.source_status !== "ok" ||
      !/^[a-f0-9]{64}$/.test(approved || "") || s.content_sha256 !== approved ||
      !Number.isFinite(age(s.data_retrieved_at, now)) || age(s.data_retrieved_at, now) < -1 || age(s.data_retrieved_at, now) > 36;
  });
  const reviewed = today >= data.valid_from && today <= data.valid_through && age(data.reviewed_at, now) >= -1;
  const window = p.windows.find((w) => today >= w.start && today <= w.end);
  let status = !window ? "closed" : window.requires_opening_review ? "scheduled" : "open";
  let reason = status === "closed" ? "Outside the reviewed local season." : status === "scheduled" ?
    "Scheduled opening only. A new review of season, health and trap restrictions is required before showing open." :
    "Local closures, MPAs and gear restrictions still apply.";
  if (!reviewed) {
    status = "unknown";
    reason = "This date is outside the reviewed rule period. Current-year rules need review.";
  } else if (issues.length) {
    status = "unknown";
    reason = issues.some((id) => data.checks[id]?.status === "changed") ?
      "An official source changed after review. The saved limits below may have changed; check CDFW." :
      "The daily source check is incomplete or over 36 hours old. Check CDFW; saved rules are shown below.";
  }
  return { status, label: { open: "Season open", closed: "Season closed", scheduled: "Opener unconfirmed", unknown: "Check rules" }[status], today, reason, issues, profile: p };
}

export function regulationsHTML(data, species, now = Date.now(), fallback = false) {
  const state = regulationState(data, species, now);
  const summary = `<summary><span>Regulations</span><span class="reg-badge reg-${state.status}" aria-live="polite">${esc(state.label)}</span><span class="reg-chevron" aria-hidden="true">⌄</span></summary>`;
  if (!state.profile) return summary + `<div class="reg-body"><p>${esc(state.reason)}</p><a href="https://wildlife.ca.gov/Fishing/Ocean" target="_blank" rel="noopener">Official CDFW rules ↗</a></div>`;
  const p = state.profile;
  const timestamps = p.source_ids.map((id) => data.checks[id]?.data_retrieved_at).filter((s) => Number.isFinite(Date.parse(s)));
  const checked = timestamps.length === p.source_ids.length ? timestamps.sort((a, b) => Date.parse(a) - Date.parse(b))[0] : null;
  const links = p.source_ids.map((id) => `<a href="${esc(officialURL(data.sources[id].url))}" target="_blank" rel="noopener">${esc(data.sources[id].name)} ↗</a>`).join("");
  return summary + `<div class="reg-body" tabindex="0" aria-label="${esc(p.name)} regulation details">
    <div class="reg-context">Today · ${esc(state.today)} · Pacific time</div>
    <h2>${esc(p.name)}</h2><p class="reg-area">${esc(data.area)}</p>
    <p class="reg-notice reg-${state.status}">${esc(state.reason)}</p>
    <dl class="reg-limits"><dt>Season</dt><dd>${esc(p.season)}</dd><dt>Daily / possession limit</dt><dd>${esc(p.bag)}</dd><dt>Minimum size</dt><dd>${esc(p.size)}</dd></dl>
    <details data-reg-section="gear"><summary>Gear, identification & other limits</summary><ul>${p.details.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></details>
    <details data-reg-section="area"><summary>Where these rules apply</summary><p>${esc(data.scope)}</p><ul>${data.common_notes.filter((s) => species !== "dungeness" || !s.startsWith("For finfish,")).map((s) => `<li>${esc(s)}</li>`).join("")}</ul><a href="${esc(officialURL(data.official_map_url))}" target="_blank" rel="noopener">CDFW map: check exact position & MPAs ↗</a></details>
    <div class="reg-freshness"><p>Rules reviewed: ${esc(time(data.reviewed_at))}<br>Oldest required source check: ${esc(time(checked))}${fallback ? " · saved snapshot" : ""}</p><p>Official sources are checked daily. Changes need review; a successful download does not approve new rules. Recheck before each trip.</p></div>
    <a class="reg-official" href="${esc(officialURL(data.sources[species === "salmon" ? "rules-salmon" : species === "dungeness" ? "rules-crab" : "rules-central"].url))}" target="_blank" rel="noopener">Read current official rules ↗</a>
    <details data-reg-section="sources"><summary>All official sources & check status</summary><div class="reg-links">${links}</div>${state.issues.length ? `<p>Needs review / fresh check: ${state.issues.map((id) => esc(data.sources[id].name)).join("; ")}.</p>` : "<p>Required sources match the reviewed versions.</p>"}</details>
  </div>`;
}

export function initRegulations(card, select) {
  let registry = null, fallback = true, species = select.value, lastRefresh = 0;
  function render(open = false) {
    const html = regulationsHTML(registry, species, Date.now(), fallback);
    if (card.innerHTML !== html) {
      const expanded = [...card.querySelectorAll("[data-reg-section][open]")].map((x) => x.dataset.regSection);
      card.innerHTML = html;
      if (!open) for (const section of card.querySelectorAll("[data-reg-section]")) section.open = expanded.includes(section.dataset.regSection);
    }
    if (open) card.open = true;
  }
  function selected() {
    const changed = species !== select.value;
    species = select.value;
    render(changed);
  }
  select.addEventListener("change", selected);
  document.addEventListener("skippercast:species", selected);
  async function refresh() {
    lastRefresh = Date.now();
    try {
      const result = await loadDailyEvidence();
      const candidate = result.data.regulations;
      if (validRegulations(candidate) && (!registry || Date.parse(candidate.reviewed_at) >= Date.parse(registry.reviewed_at))) {
        registry = candidate;
        fallback = result.fallback;
      }
    } catch { /* Keep the original check timestamps; stale is never current. */ }
    render();
  }
  render();
  (async () => {
    try {
      const response = await fetch("data/regulations.json", { cache: "no-cache", signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw Error("Rules unavailable");
      const candidate = await response.json();
      if (validRegulations(candidate)) registry = candidate;
    } catch { /* Official links remain available if both data paths fail. */ }
    render();
    await refresh();
  })();
  const tick = () => {
    render();
    if (Date.now() - lastRefresh >= HOUR) refresh();
  };
  setInterval(() => { if (document.visibilityState === "visible") tick(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") tick(); });
  // Leaflet must not pan or zoom when interacting with or scrolling the card.
  for (const type of ["pointerdown", "mousedown", "dblclick", "wheel", "touchstart", "touchmove"])
    card.addEventListener(type, (event) => event.stopPropagation(), { passive: true });
}
