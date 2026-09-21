import {
  STATIONS,
  WIND_MODELS,
  WAVE_MODELS,
  TIMEZONE,
  futureDates,
  forecastURLs,
  valueAt,
  compass,
  range,
  evidenceFlags,
  coverageNote,
  fetchJSON,
} from "./forecast.js";
const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (v, suffix = "", digits = 1) =>
  Number.isFinite(v) ? `${v.toFixed(digits)}${suffix}` : "Unavailable";
const dateLabel = (d) =>
  new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${d}T12:00:00Z`));
const dateTime = (v) => {
  const date = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: TIMEZONE,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      }).format(date)
    : "Unavailable";
};
const goodList = (result) =>
  result.status === "fulfilled" &&
  Array.isArray(result.value) &&
  result.value.length === STATIONS.length
    ? result.value
    : null;

export function initWeather(map, forecastLayer, onSelectStation = () => {}) {
  let data,
    loading = false,
    dates = futureDates(),
    stationIndex = 1,
    day = dates[0],
    hour = "08";
  const urls = forecastURLs();
  const status = () => {
    if (!data) return;
    const stale = Date.now() - data.retrievedAt > 60 * 60 * 1000;
    $("forecast-status").textContent =
      `${stale ? "Refresh needed. " : ""}Retrieved ${dateTime(new Date(data.retrievedAt).toISOString())}. All forecast times are Pacific. ${data.wind && data.wave ? "Wind and wave responses loaded." : "Some forecast sources are unavailable."}`;
  };
  async function load() {
    if (loading) return;
    loading = true;
    $("load-forecast").disabled = true;
    $("load-forecast").textContent = "Loading…";
    $("forecast-status").textContent =
      "Fetching wind, waves, model metadata, and current NWS advisories…";
    try {
      const result = await Promise.allSettled([
        fetchJSON(urls.wind),
        fetchJSON(urls.wave),
        ...WIND_MODELS.concat(WAVE_MODELS).map((m) => fetchJSON(m.meta)),
        fetchJSON("https://api.weather.gov/alerts/active/zone/PZZ645"),
      ]);
      data = {
        wind: goodList(result[0]),
        wave: goodList(result[1]),
        metadata: result
          .slice(2, 6)
          .map((r) => (r.status === "fulfilled" ? r.value : null)),
        alerts: result[6].status === "fulfilled" ? result[6].value : null,
        retrievedAt: Date.now(),
      };
      dates = futureDates();
      if (!dates.includes(day)) day = dates[0];
      $("layer-forecast").checked = true;
      forecastLayer.addTo(map);
      render();
      status();
    } catch {
      $("forecast-status").textContent =
        "Forecasts could not load. Try again or use the official NWS forecast.";
    } finally {
      loading = false;
      $("load-forecast").disabled = false;
      $("load-forecast").textContent = "Refresh forecast";
    }
  }
  function render() {
    const time = `${day}T${hour}:00`,
      wind = data.wind?.[stationIndex],
      wave = data.wave?.[stationIndex];
    const val = (kind, m, key, unit) =>
      valueAt(kind === "wind" ? wind : wave, m, key, time, unit);
    const windCards = WIND_MODELS.map((m) => {
      const direction = val("wind", m.id, "wind_direction_10m", "°");
      return `<article class="weather-card"><h3>${m.name} · wind</h3><strong>${fmt(val("wind", m.id, "wind_speed_10m", "kn"), " kt")}</strong><p>Gusts ${fmt(val("wind", m.id, "wind_gusts_10m", "kn"), " kt")} · from ${compass(direction)}</p></article>`;
    }).join("");
    const waveCards = WAVE_MODELS.map(
      (m) =>
        `<article class="weather-card"><h3>${m.name} · combined seas</h3><strong>${fmt(val("wave", m.id, "wave_height", "ft"), " ft")}</strong><p>${fmt(val("wave", m.id, "wave_period", "s"), " s")} mean period · from ${compass(val("wave", m.id, "wave_direction", "°"))}</p></article>`,
    ).join("");
    const flags = evidenceFlags(wind, wave, time);
    WIND_MODELS.concat(WAVE_MODELS).forEach((m, i) => {
      const selected = coverageNote(data.metadata[i], time),
        window = coverageNote(data.metadata[i], `${day}T13:00`);
      if (selected || window)
        flags.push(
          `${m.name}: ${selected || "Part of the 06:00–13:00 window is beyond latest published model coverage."}`,
        );
    });
    const windowHours = Array.from(
      { length: 8 },
      (_, i) => `${day}T${String(i + 6).padStart(2, "0")}:00`,
    );
    const windowRows = [
      ...WIND_MODELS.map((m) => {
        const speeds = windowHours.map((t) =>
            valueAt(wind, m.id, "wind_speed_10m", t, "kn"),
          ),
          gusts = windowHours.map((t) =>
            valueAt(wind, m.id, "wind_gusts_10m", t, "kn"),
          );
        const conflict = speeds.some(
          (v, i) =>
            Number.isFinite(v) && Number.isFinite(gusts[i]) && gusts[i] < v,
        );
        return `<tr><th>${m.name}</th><td>${range(speeds) ? range(speeds) + " kt" : "Incomplete"}</td><td>${range(gusts) ? range(gusts) + " kt" : "Incomplete"}${conflict ? " · inconsistent" : ""}</td></tr>`;
      }),
      ...WAVE_MODELS.map((m) => {
        const heights = windowHours.map((t) =>
          valueAt(wave, m.id, "wave_height", t, "ft"),
        );
        return `<tr><th>${m.name}</th><td>${range(heights) ? range(heights) + " ft" : "Incomplete"}</td><td>Combined seas</td></tr>`;
      }),
    ].join("");
    const components = ["wind_wave", "swell_wave", "secondary_swell_wave"]
      .map(
        (k, i) =>
          `<tr><th>${["Wind chop", "Primary swell", "Secondary swell"][i]}</th>${WAVE_MODELS.map(
            (m) => {
              const h = val("wave", m.id, `${k}_height`, "ft"),
                p = val("wave", m.id, `${k}_period`, "s"),
                d = val("wave", m.id, `${k}_direction`, "°");
              return `<td>${h === null ? "Unavailable" : h === 0 ? "0.0 ft" : `${fmt(h, " ft")} / ${fmt(p, " s")} / ${compass(d)}`}</td>`;
            },
          ).join("")}</tr>`,
      )
      .join("");
    const alerts = Array.isArray(data.alerts?.features)
      ? data.alerts.features
      : null;
    const alertText =
      alerts === null
        ? "NWS advisory access unavailable — open the official forecast."
        : alerts.length
          ? alerts
              .map(
                (a) =>
                  `${a.properties?.event || "Marine alert"}: ${a.properties?.headline || "See NWS for details"}`,
              )
              .join(" | ")
          : "No active PZZ645 alerts returned at retrieval. This does not clear future trips or the harbor entrance.";
    const metadataRows = WIND_MODELS.concat(WAVE_MODELS)
      .map((m, i) => {
        const meta = data.metadata[i];
        return `<tr><th>${m.name}</th><td>${meta?.last_run_initialisation_time ? dateTime(meta.last_run_initialisation_time) : "Unavailable"}</td><td>${meta?.last_run_availability_time ? dateTime(meta.last_run_availability_time) : "Unavailable"}</td><td>${meta?.data_end_time ? dateTime(meta.data_end_time) : "Unavailable"}</td></tr>`;
      })
      .join("");
    const grid = (d) =>
      Number.isFinite(d?.latitude) && Number.isFinite(d?.longitude)
        ? `${d.latitude.toFixed(3)}, ${d.longitude.toFixed(3)}`
        : "Unavailable";
    const requested = STATIONS[stationIndex];
    const visibility = val("wind", "gfs_global", "visibility", "m"),
      rain = val("wind", "gfs_global", "precipitation", "mm");
    $("forecast-content").innerHTML =
      `<div class="forecast-controls"><label>Offshore sample<select id="weather-station">${STATIONS.map((s, i) => `<option value="${i}" ${i === stationIndex ? "selected" : ""}>${s.name}</option>`).join("")}</select></label><label>Date<select id="weather-day">${dates.map((d, i) => `<option value="${d}" ${d === day ? "selected" : ""}>${dateLabel(d)}${i >= 3 ? " · provisional" : ""}</option>`).join("")}</select></label><label>Hour (Pacific)<select id="weather-hour">${Array.from(
        { length: 8 },
        (_, i) => String(i + 6).padStart(2, "0"),
      )
        .map(
          (h) =>
            `<option value="${h}" ${h === hour ? "selected" : ""}>${Number(h) > 12 ? Number(h) - 12 : Number(h)}:00 ${Number(h) >= 12 ? "PM" : "AM"}</option>`,
        )
        .join(
          "",
        )}</select></label></div><div class="weather-cards">${windCards}${waveCards}</div>${flags.length ? `<div class="forecast-notice">${flags.map(esc).join("<br>")}</div>` : ""}<div class="forecast-table-wrap" tabindex="0" role="region" aria-label="Forecast comparison table; scroll horizontally for more columns"><table><caption>Selected hour · component height / period / from</caption><thead><tr><th>Component</th><th>ECMWF WAM</th><th>NOAA GFS Wave</th></tr></thead><tbody>${components}</tbody></table></div><div class="forecast-table-wrap" tabindex="0" role="region" aria-label="Forecast comparison table; scroll horizontally for more columns"><table><caption>06:00–13:00 Pacific · full-window ranges</caption><thead><tr><th>Model</th><th>Wind / seas</th><th>Gusts / metric</th></tr></thead><tbody>${windowRows}</tbody></table></div><p class="small">NOAA GFS at the selected hour: visibility ${visibility === null ? "unavailable" : (visibility / 1609.344).toFixed(1) + " mi"} · precipitation ${rain === null ? "unavailable" : (rain / 25.4).toFixed(2) + " in"}. ECMWF visibility may be unavailable.</p><div class="forecast-notice">${esc(alertText)}</div><p class="small">${dates.indexOf(day) >= 3 ? "This date is provisional. " : ""}No trip rating is assigned. Check current observations, visibility, advisories, entrance conditions, daylight, and the entire route before departure. A 06:00–13:00 screen does not establish four fishing hours.</p><details class="forecast-metadata"><summary>Source times &amp; grid locations</summary><p class="small">Requested: ${requested.latitude}, ${requested.longitude}. Response grid: wind ${grid(wind)}; waves ${grid(wave)}. Coarse offshore samples cannot resolve individual reefs or the harbor entrance.</p><div class="forecast-table-wrap" tabindex="0" role="region" aria-label="Forecast comparison table; scroll horizontally for more columns"><table><thead><tr><th>Model</th><th>Latest initialization</th><th>Available via provider</th><th>Latest coverage end</th></tr></thead><tbody>${metadataRows}</tbody></table></div><p class="small">Latest-run metadata describes provider availability. It is not a guaranteed run attribution for every rolling forecast value. Retrieval time is not forecast issue time. Unpopulated forecast hours remain unavailable.</p><a href="${urls.wind}" target="_blank" rel="noopener">Raw wind response ↗</a> · <a href="${urls.wave}" target="_blank" rel="noopener">Raw wave response ↗</a></details><div class="forecast-links"><a href="https://forecast.weather.gov/MapClick.php?TextType=2&amp;zoneid=PZZ645" target="_blank" rel="noopener">NWS marine forecast ↗</a><a href="https://www.ndbc.noaa.gov/station_page.php?station=46215" target="_blank" rel="noopener">Diablo Canyon buoy ↗</a><a href="https://www.morrobayca.gov/144/Harbor" target="_blank" rel="noopener">Harbor information ↗</a><a href="https://open-meteo.com/" target="_blank" rel="noopener">Data: Open-Meteo · CC BY 4.0 ↗</a></div>`;
    $("weather-station").addEventListener("change", (e) => {
      stationIndex = Number(e.target.value);
      render();
      $("weather-station").focus({ preventScroll: true });
    });
    $("weather-day").addEventListener("change", (e) => {
      day = e.target.value;
      render();
      $("weather-day").focus({ preventScroll: true });
    });
    $("weather-hour").addEventListener("change", (e) => {
      hour = e.target.value;
      render();
      $("weather-hour").focus({ preventScroll: true });
    });
    drawStations(time);
  }
  function drawStations(time) {
    forecastLayer.clearLayers();
    STATIONS.forEach((s, i) => {
      const wind = data.wind?.[i],
        wave = data.wave?.[i];
      const speed = valueAt(wind, "gfs_global", "wind_speed_10m", time, "kn"),
        direction = valueAt(
          wind,
          "gfs_global",
          "wind_direction_10m",
          time,
          "°",
        ),
        sea = valueAt(wave, "ncep_gfswave025", "wave_height", time, "ft");
      const arrow =
        direction !== null
          ? `<span class="wind-arrow" style="transform:rotate(${(direction + 180) % 360}deg)">↑</span>`
          : "";
      const html = `${arrow} ${fmt(speed, " kt")} · ${fmt(sea, " ft")}`;
      L.marker([s.latitude, s.longitude], {
        icon: L.divIcon({
          className: "station-marker",
          html,
          iconSize: [160, 34],
          iconAnchor: [80, 17],
        }),
        title: `${s.name}: NOAA GFS wind and wave model values at ${time} Pacific`,
      })
        .bindTooltip(
          `${s.name} · NOAA GFS wind / GFS Wave · ${time.replace("T", " ")} Pacific`,
        )
        .on("click", () => {
          stationIndex = i;
          render();
          onSelectStation();
        })
        .addTo(forecastLayer);
    });
  }
  $("load-forecast").addEventListener("click", load);
  $("layer-forecast").addEventListener("change", (e) => {
    if (e.target.checked && !data) load();
  });
  const timer = setInterval(status, 60000);
  window.addEventListener("pagehide", () => clearInterval(timer), {
    once: true,
  });
}
