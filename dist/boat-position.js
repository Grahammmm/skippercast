// The phone's position is transient. This module never stores or sends a track.
const RAD = Math.PI / 180;
export function targetVector(from, to) {
  const a = Number(from.latitude), b = Number(from.longitude);
  const c = Number(to.latitude), d = Number(to.longitude);
  if (![a, b, c, d].every(Number.isFinite) || Math.abs(a) > 90 || Math.abs(c) > 90 || Math.abs(b) > 180 || Math.abs(d) > 180) return null;
  const lat1 = a * RAD, lat2 = c * RAD, deltaLat = (c - a) * RAD, deltaLon = (d - b) * RAD;
  const h = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
  const distanceNm = 3440.065 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
  const y = Math.sin(deltaLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLon);
  return { distanceNm, bearingTrue: (Math.atan2(y, x) / RAD + 360) % 360 };
}

export function initBoatPosition(map, {onMapRequested = () => {}} = {}) {
  const button = document.getElementById('boat-position-toggle');
  const card = document.getElementById('boat-position-card');
  const status = document.getElementById('boat-position-status');
  const center = document.getElementById('boat-position-center');
  let watchId = null, fix = null, target = null, marker = null, accuracyRing = null, bearingLine = null, firstFix = false;
  const geo = navigator.geolocation;
  const cleanLayers = () => {
    for (const layer of [marker, accuracyRing, bearingLine]) if (layer) map.removeLayer(layer);
    marker = accuracyRing = bearingLine = null;
  };
  const show = () => {
    if (!fix) return;
    const age = Math.max(0, Date.now() - fix.time);
    if (age > 30000) {
      status.textContent = 'GPS fix is stale. Wait for a fresh fix before using the bearing.';
      if (bearingLine) { map.removeLayer(bearingLine); bearingLine = null; }
      return;
    }
    const accuracy = Math.round(fix.accuracy);
    const vector = target && targetVector(fix, target);
    const staleWarning = accuracy > 100 ? 'Low GPS accuracy; do not use for close approach. ' : '';
    status.textContent = vector
      ? `${target.label}: ${vector.distanceNm < 1 ? vector.distanceNm.toFixed(2) : vector.distanceNm.toFixed(1)} nm straight line · ${Math.round(vector.bearingTrue)}° true bearing. GPS ±${accuracy} m. ${staleWarning}`
      : `Position found · GPS ±${accuracy} m. Pick a mapped fishing mark for distance and bearing.`;
    if (bearingLine) { map.removeLayer(bearingLine); bearingLine = null; }
    if (vector) bearingLine = L.polyline([[fix.latitude, fix.longitude], [target.latitude, target.longitude]], {color:'#176a7d',weight:2,dashArray:'5 7',opacity:.8,interactive:false}).addTo(map);
  };
  const stop = (message = 'Location off. Your position was not saved.') => {
    if (watchId !== null) geo?.clearWatch(watchId);
    watchId = null; fix = null; firstFix = false;
    cleanLayers();
    button.setAttribute('aria-pressed', 'false');
    button.textContent = '⌖ Locate me';
    card.hidden = true;
    status.textContent = message;
  };
  const start = () => {
    if (watchId !== null) { onMapRequested(); return; }
    if (!geo || !window.isSecureContext) {
      card.hidden = false;
      status.textContent = 'Phone location needs a secure browser with location access.';
      return;
    }
    card.hidden = false;
    status.textContent = 'Waiting for a fresh GPS fix…';
    button.textContent = '● GPS on';
    button.setAttribute('aria-pressed', 'true');
    watchId = geo.watchPosition(position => {
      const {latitude, longitude, accuracy} = position.coords;
      if (![latitude, longitude, accuracy].every(Number.isFinite) || accuracy < 0) return;
      // Browsers may return an old cached fix while the receiver starts.
      if (Date.now() - position.timestamp > 30000) return;
      fix = {latitude, longitude, accuracy, time:position.timestamp};
      if (marker) marker.setLatLng([latitude, longitude]);
      else marker = L.circleMarker([latitude, longitude], {radius:8,color:'#fff',weight:3,fillColor:'#0967bd',fillOpacity:1,interactive:false}).addTo(map);
      if (accuracyRing) accuracyRing.setLatLng([latitude, longitude]).setRadius(accuracy);
      else accuracyRing = L.circle([latitude, longitude], {radius:accuracy,color:'#0967bd',weight:1,fillOpacity:.08,interactive:false}).addTo(map);
      show();
      if (!firstFix) { firstFix = true; onMapRequested(); map.setView([latitude, longitude], Math.max(map.getZoom(), 13)); }
    }, error => {
      stop();
      card.hidden = false;
      status.textContent = error.code === 1 ? 'Location permission denied. Enable location for SkipperCast in your browser settings.' : 'GPS position unavailable. Try an open-sky location or use your chartplotter.';
    }, {enableHighAccuracy:true, maximumAge:0, timeout:15000});
  };
  button.addEventListener('click', () => watchId === null ? start() : stop());
  center.addEventListener('click', () => { if (fix) map.setView([fix.latitude, fix.longitude], Math.max(map.getZoom(), 13)); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && watchId !== null) stop('Location paused while this page was in the background. Tap Locate me to resume.'); });
  window.addEventListener('pagehide', () => stop());
  const freshTimer = setInterval(() => { if (watchId !== null && fix) show(); }, 5000);
  window.addEventListener('pagehide', () => clearInterval(freshTimer));
  return {setTarget(value) { target = value && Number.isFinite(value.latitude) && Number.isFinite(value.longitude) ? value : null; if (watchId !== null) show(); }, start, stop};
}
