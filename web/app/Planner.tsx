// The day planner inside the trip dialog (FE-51, #602): spots, layers and the
// GPX hand-off, rendered from web/planner.ts's signals. It replaces v1's
// dist/export-ui.js markup with the same controls, ids and copy, so a plan reads
// and exports as before. Loaded with the planner on first open. Styles:
// web/app/trip.css.
import {useEffect} from 'preact/hooks';
import {signal} from '@preact/signals';
import {coordinates} from '../state.ts';
import {formatCoordinates} from '../../dist/coordinates.js';
import {exportEvidenceLabel, USER_WAYPOINT_CATEGORIES} from '../../dist/trip-export.js';
import {fitLabel} from '../../dist/spot-ranking.js';
import type {Filters, LayerKey, Planner as Model, Preset, ProtectedHit, Target, TripSpecies} from '../planner.ts';

const DEVICE_HELP: Readonly<Record<string, readonly [string, string, string]>> = {
  generic: ['Chartplotter model not selected', 'Download GPX, copy it to storage supported by your model, then use its Import menu. Most reviewed plotters use SD/microSD; USB support varies. Inserting media alone does not import a plan.', 'https://www8.garmin.com/manuals/webhelp/GUID-3E67C80C-0812-4EEC-BC60-699751B9CF6F/EN-US/GPSMAP_x3_OM_EN-US.pdf'],
  garmin: ['Garmin GPSMAP / ECHOMAP', 'Use a compatible SD/microSD card. Select GPX as the data-transfer file type, then Manage User Data → Data Transfer → Merge from Card. Avoid Replace from Card if you want to retain existing data. Menu names depend on model.', 'https://support.garmin.com/en-US/?faq=zFDPlv7AnK2eNWRp2AgMkA'],
  lowrance: ['Lowrance HDS', 'Copy GPX to a compatible memory card. In Storage / Files, select the file and Import. Verify the instructions for your model and software. HDS PRO total capacity: 3,000 waypoints, 100 trails, 10,000 points per trail.', 'https://www.lowrance.com/hds-pro/specs/'],
  simrad: ['Simrad NSS / NSX', 'Use a compatible memory card; USB is model-specific. Use Files or the waypoint/route/track import controls to import GPX. NSX total capacity: 6,000 waypoints, 50 tracks, 12,000 points per track. Other Simrad models differ.', 'https://www.simrad-yachting.com/en-eu/nsx/specifications/'],
  raymarine: ['Raymarine Axiom', 'Copy GPX to compatible storage. In LightHouse 4, use My data → Import/export → Import from card, or select the file in Files. Axiom 2 total capacity: 10,000 waypoints and 15 tracks (10,000 points per track).', 'https://docs.raymarine.com/81406/en-US/latest/index.html'],
  inavx: ['iNavX on iPad / iPhone', 'Use Share / Save file to open GPX in iNavX. Or download, open the file from Files → Downloads, then Share → iNavX. Display imported waypoints and tracks. No USB or memory card is required.', 'https://inavx.com/h/inavx/waypoints.htm'],
};
const LAYERS: readonly (readonly [LayerKey, string, string])[] = [
  ['waypoints', 'Fishing waypoints', 'Selected positions with terrain, depth and source notes.'],
  ['outlines', 'Linked reef outlines', 'Partial habitat boundaries as tracks, included once per area.'],
  ['alignments', 'Structure alignment lines', 'Fixed survey alignments as tracks. Not forecast drifts or routes.'],
  ['exclusions', 'Protected-area outlines', 'AVOID tracks for MPAs and mapped groundfish exclusions; whole outlines that intersect your chosen coverage.'],
];
const PRESETS: readonly (readonly [Preset, string])[] = [['map', 'Current map'], ['filtered', 'Filtered research references'], ['region', 'Whole region'], ['none', 'Clear selection']];

/** The spot's checkbox title and lines, as v1 listed them. */
function SpotRow({t, checked, hit, onToggle}: {t: Target; checked: boolean; hit?: ProtectedHit; onToggle: (on: boolean) => void}) {
  const depth = t.canonical_habitat ? (t.neighborhood_depth_ft ?? []).map(n => Math.round(n)).join('–') : t.center_depth_ft;
  return (
    <label class="export-check">
      <input type="checkbox" data-spot={t.id} checked={checked} onChange={e => onToggle(e.currentTarget.checked)} />
      <span>
        <strong>{t.trip_rank ? `#${t.trip_rank} · ${fitLabel(t.trip_fit)} · ${t.evidence_confidence?.percent}% confidence` : t.label}</strong>
        <small>{exportEvidenceLabel(t)}</small>
        <small>{formatCoordinates(t.latitude, t.longitude, coordinates.value)}</small>
        <small>{t.trip_rank ? t.name : t.id} · grade {t.habitat_grade} · {depth} ft</small>
        {t.trip_rank ? <small>{t.terrain_interpretation}</small> : null}
        {hit ? <small>Inside a protected-area boundary; excluded as a fishing target by SkipperCast. Boundaries are context; current rules are on the agency page. {hit.matches.map(m => <span key={m.url + m.name}>{m.name} · <a href={m.url} target="_blank" rel="noopener">{m.agency} boundary and rules</a> </span>)}</small> : null}
      </span>
    </label>
  );
}

function BoundaryNote({hit}: {hit?: ProtectedHit}) {
  return hit ? <p>Inside a protected-area boundary; excluded as a fishing target by SkipperCast. Boundaries are context; current rules are on the agency page. {hit.matches.map(m => <span key={m.url + m.name}>{m.name} · <a href={m.url} target="_blank" rel="noopener">{m.agency} boundary and rules</a> </span>)}</p> : null;
}

export function Planner({model: m, open}: {model: Model; open: boolean}) {
  // While the dialog shows: the screen's age each minute and new boundaries refresh the counts; opening restores a saved ranked plan.
  useEffect(() => {
    if (!open) return;
    m.tick.value++;
    void m.restore();
    const bump = () => { m.tick.value++; };
    document.addEventListener('skippercast:boundaries', bump);
    const timer = setInterval(bump, 60000);
    return () => { document.removeEventListener('skippercast:boundaries', bump); clearInterval(timer); };
  }, [open, m]);

  const d = m.draft.value, f = m.filters.value, s = m.summary.value, ranked = m.ranked.value, research = m.allowResearch.value;
  const blocked = !ranked || m.filtersDirty.value || !d.ids.length;
  const filter = <K extends keyof Filters>(key: K, parse: (v: string) => Filters[K]) => (e: Event) => m.setFilter(key, parse((e.currentTarget as HTMLInputElement).value));
  const device = DEVICE_HELP[deviceChoice.value] ?? DEVICE_HELP.generic!;
  const spots = m.spots.value;

  return (
    <div id="export-content">
      <div class="export-card export-plan">
        <div class="export-fields">
          <label>Plan name<input id="export-name" maxLength={80} value={d.name} onInput={e => m.edit({name: e.currentTarget.value})} /></label>
          <label>Fishing date<input type="date" id="export-date" value={d.date} onInput={e => m.edit({date: e.currentTarget.value})} /></label>
        </div>
        <p class="export-note" id="export-storage">{m.storageNote.value}</p>
      </div>
      <section class="export-card" aria-label="Your waypoints">
        <h2>Your waypoints</h2>
        <p>User labels, not verified habitat, depth or navigation guidance. Saved in this browser’s region draft, separate from account trip alerts.</p>
        <button id="waypoint-place" onClick={m.chooseWaypoint}>Place a waypoint on the Chart</button>
        {m.waypointPosition.value ? <form onSubmit={e => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          m.saveWaypoint(String(data.get('name')), String(data.get('category')));
        }}>
          <p>{formatCoordinates(m.waypointPosition.value.latitude, m.waypointPosition.value.longitude, coordinates.value)}</p>
          <label>Waypoint name<input name="name" maxLength={80} required /></label>
          <label for="waypoint-category">Category</label><select id="waypoint-category" name="category">{USER_WAYPOINT_CATEGORIES.map(category => <option key={category} value={category}>{category}</option>)}</select>
          <button type="submit">Save waypoint</button> <button type="button" onClick={() => { m.waypointPosition.value = null; }}>Cancel</button>
        </form> : null}
        {(d.userWaypoints ?? []).map(t => <article key={t.id}>
          <label class="export-check"><input type="checkbox" checked={d.ids.includes(t.id)} onChange={e => m.toggleSpot(t.id, e.currentTarget.checked)} /><span>{t.name} · {t.category}</span></label>
          <p>{formatCoordinates(t.latitude, t.longitude, coordinates.value)}</p>
          {d.ids.includes(t.id) ? <BoundaryNote hit={m.protectedHits.value.find(h => h.id === t.id)} /> : null}
          <button onClick={() => m.removeWaypoint(t.id)} aria-label={`Remove waypoint ${t.name}`}>Remove waypoint</button>
        </article>)}
      </section>
      <details class="export-card" id="export-spots" open>
        <summary><span>1. Choose your spots</span><strong id="export-selection-count">{d.ids.length} selected</strong></summary>
        <div class="export-card-body">
          <button class="primary export-best" id="export-best" disabled={!m.portsReady.value || m.loading.value} onClick={() => void m.selectBest()}>Best available · up to {f.limit} reef spots</button>
          <p class="export-note">Ranked reef habitat. Confidence % describes habitat evidence.</p>
          <details class="export-trip-filters">
            <summary>Trip filters</summary>
            <div class="export-fields">
              <label>Target<select id="export-species" value={f.species} onChange={filter('species', v => v as TripSpecies)}>
                <option value="reef">Lingcod + rockfish</option><option value="lingcod">Lingcod</option><option value="rockfish">Rockfish</option></select></label>
              <label>Maximum spots<select id="export-limit" value={String(f.limit)} onChange={filter('limit', Number)}>
                {[10, 20, 30, 50].map(n => <option key={n} value={String(n)}>{n}</option>)}</select></label>
              <label>Maximum depth (ft)<input id="export-depth" type="number" min="25" max="300" defaultValue={String(f.depth)} onChange={filter('depth', Number)} /></label>
              <label>Search area<select id="export-best-scope" value={f.scope} onChange={filter('scope', v => v as Filters['scope'])}>
                <option value="region">Selected region</option><option value="map">Current map view</option></select></label>
              <label>From port<select id="export-port" value={f.port} onChange={filter('port', String)}>
                <option value="">No distance limit</option>{m.ports.value.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
              <label>Maximum one-way distance (nm)<input id="export-distance" type="number" min="1" max="100" defaultValue={String(f.distance)} onChange={filter('distance', Number)} /></label>
            </div>
            <p class="export-note">Distance is straight-line reference only. Habitat ranks stay fixed; check the selected day’s conditions separately.</p>
          </details>
          <p><button id="export-map" disabled={blocked} onClick={m.showOnMap}>Show ranked spots on map</button> <button id="export-conditions" disabled={blocked} onClick={m.checkConditions}>Check trip conditions</button></p>
          <details>
            <summary>How ranking and confidence work</summary>
            <p>3/3 Strong, 2/3 Good, 1/3 Secondary habitat fit. The combined target uses the weaker of the two fits. We select distinct reefs at least 0.15 nm apart; fewer than your limit may qualify.</p>
            <p>Confidence index: original survey 25 points, valid metric support up to 25, fine resolution up to 20, interpreted substrate coverage up to 20, known survey year 5, documented independent support 5. Unknown interpolation flags cap it at 90%. This is an evidence rubric, not a statistical probability of catching fish. Reef depths are nominal; verify them on your sounder.</p>
          </details>
          <label class="export-check"><input id="export-research" type="checkbox" checked={research} onChange={e => m.setResearch(e.currentTarget.checked)} />
            <span><strong>Research-coordinate export · opt in</strong><small>Include historical research references that are not chart-depth qualified. Verify the bottom and depth on your chart and sounder. This choice does not bypass protected-area checks.</small></span></label>
          <p class="export-note">The default picker contains measured reefs from a current publication. Their survey depths remain nominal. Research-coordinate export is a separate capability from qualified fishing targets; saved research selections are retained but need this session’s opt-in before download.</p>
          <p>Start with a set, then check only the spots you want. Current map selects loaded measured reefs in view plus opted-in research references. Filtered research uses the map’s species and depth filters; Best available uses the trip filters above.</p>
          <div class="export-presets">
            {PRESETS.map(([scope, label]) => <button key={scope} data-scope={scope} id={scope === 'filtered' ? 'export-filtered-research' : undefined} disabled={scope === 'filtered' && !research} onClick={() => m.preset(scope)}>{label}</button>)}
          </div>
          <p id="export-scope-status" role="status">{m.scopeStatus.value}</p>
          <label>Find a spot<input id="export-search" type="search" placeholder="Name, ID or grade" autoComplete="off" value={m.search.value} onInput={e => { m.search.value = e.currentTarget.value; }} /></label>
          <div id="export-spot-list" class="export-spot-list" role="group" aria-label="Choose fishing spots">
            {spots.length ? spots.map(t => <SpotRow key={t.id} t={t} checked={d.ids.includes(t.id)} hit={m.protectedHits.value.find(h => h.id === t.id)} onToggle={on => m.toggleSpot(t.id, on)} />)
              : <p>No matching measured reefs loaded. Select Best available to load the current screened publication, or deliberately opt in to research references. Your existing selection is retained.</p>}
          </div>
        </div>
      </details>
      <details class="export-card" id="export-layers">
        <summary><span>2. What to include</span><strong id="export-layer-count">{Object.values(d.layers).filter(Boolean).length + (m.contourTracks.value ? 1 : 0)} layers</strong></summary>
        <div class="export-card-body export-checks">
          {LAYERS.map(([id, name, description]) => (
            <label key={id} class="export-check"><input type="checkbox" data-layer={id} checked={d.layers[id]} onChange={e => m.setLayer(id, e.currentTarget.checked)} />
              <span><strong>{name}</strong><small>{description}</small></span></label>
          ))}
          <label class="export-check"><input type="checkbox" data-export="contours" checked={m.contourTracks.value} onChange={e => m.setContourTracks(e.currentTarget.checked)} />
            <span><strong>Depth contour tracks</strong><small>Published index contours (every 150 ft) as tracks, with survey, date and datum. Not for navigation.</small></span></label>
          <label>Protected-area coverage<select id="export-avoid-scope" value={d.avoidScope} onChange={e => m.edit({avoidScope: e.currentTarget.value === 'region' ? 'region' : 'map'})}>
            <option value="map">Current map view</option><option value="region">Whole selected region</option></select></label>
          <p class="export-note">GPX carries coordinates and text. Chart imagery, bathymetry, live forecasts and predicted drift guides remain in the app. Static outlines do not replace official charts or current rules.</p>
        </div>
      </details>
      <section class="export-card export-transfer" aria-labelledby="export-transfer-title">
        <h2 id="export-transfer-title">3. Take your plan aboard</h2>
        <div id="export-counts" class="export-counts" aria-live="polite">
          {s.ok ? <><strong>{s.counts.waypoints} <span>waypoints</span></strong><strong>{s.counts.tracks} <span>tracks</span></strong></> : `${d.ids.length} spots in your plan`}
        </div>
        <p id="export-validation" role="status">{s.ok
          ? `${s.counts.outlines} reef outlines · ${s.counts.alignments} alignments · ${s.counts.exclusions} AVOID outlines${s.counts.contours === undefined ? '' : ` · ${s.counts.contours} depth contour tracks`}. ${s.counts.trackPoints.toLocaleString()} track points; largest track ${s.counts.largestTrack.toLocaleString()}.${s.counts.tracks > 15 ? ' More than 15 tracks: check your device’s free track capacity or reduce outlines.' : ''} Boundaries checked again when you export.`
          : s.message}</p>
        <div class="export-actions">
          <button class="primary" id="export-download" disabled={!s.ok} onClick={() => void m.deliver('gpx')}>Download GPX</button>
          <button id="export-share" disabled={!s.ok} onClick={() => void m.deliver('share')}>Share / Save file</button>
          <button id="export-notes" disabled={!m.notesReady.value} onClick={() => void m.deliver('notes')}>Download offline notes</button>
        </div>
        <p id="export-action-status" role="status">{m.actionStatus.value}</p>
        {!s.ok && m.notesReady.value ? <p>GPX withheld. Offline notes contain boundary context only, not fishing coordinates or guidance for the selected spots.</p> : null}
        <details class="export-help">
          <summary>USB, memory card &amp; iNavX help</summary>
          <label>Your chartplotter<select id="export-device" value={deviceChoice.value} onChange={e => { deviceChoice.value = e.currentTarget.value; }}>
            {Object.entries(DEVICE_HELP).map(([id, [name]]) => <option key={id} value={id}>{name}</option>)}</select></label>
          <p id="export-device-help">{device[1]}</p>
          <a id="export-device-source" href={device[2]} target="_blank" rel="noopener">Official device reference ↗</a>
          <ol><li>Back up your existing waypoints and tracks.</li><li>Download the GPX. Copy it to the USB drive or SD/microSD card your model supports, or share it to iNavX.</li><li>Import using the device’s menu. Enable waypoints and tracks, then compare a name and coordinate with SkipperCast.</li></ol>
          <p>GPX interchange is not a guarantee for every device. Total device capacities include existing data; check free space and your model’s limits. Many plotters store far fewer tracks than waypoints. Start with a small waypoint-only set. Reimporting can create duplicates.</p>
          <p>Offline notes are a separate HTML file to read on a phone, tablet or computer, not to import into a plotter. A saved file keeps the data as downloaded, so recheck rules and conditions before departure.</p>
        </details>
      </section>
    </div>
  );
}

/** The chartplotter whose import help shows; this page session only, as in v1. */
const deviceChoice = signal('generic');
