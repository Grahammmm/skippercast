// The charter fleet's vessels (docs/plans/charter-fleet/design.md § 13, Vessels;
// CF-31). #fleet-vessels (?region=<id>) lists registry vessels by name with filters
// (port, class, status, profile, AIS, completeness) from GET /api/admin/fleet/vessels;
// #fleet-vessel/<id> shows one: whether it can appear on public pages (a removal
// request keeps it off even when listed, open-questions.md Q15), each resolved field
// with its pin and winning fact, every fact with its source link, method, confidence
// and history, then offerings, aliases, changes, AIS watch, trips, linked advisor
// boats and open reviews. Saving a field posts an admin fact that pins it
// (server/fleet/admin/vessels.ts); Unpin releases it. The name stays with the
// resolver, which owns name normalisation (design § 7). Strings: ./fleet-copy.ts.
import {useEffect, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {ADMIN_COPY} from '../advisor/copy.ts';
import {FLEET_COPY as COPY} from './fleet-copy.ts';
import {ApiError, MAP_CONSENTS, PROFILE_STATUSES, VESSEL_CLASSES, VESSEL_STATUSES, WATERS, editFleetVessel, getFleetVessel, getFleetVessels, httpsUrl,
  valueText, vesselIsPublic, when} from './api.ts';
import type {FleetFact, FleetFieldValue, FleetPin, FleetVesselDetail, FleetVesselEdit, FleetVesselQuery, FleetVesselRow} from './api.ts';
import {fleetHref, fleetVesselHref} from './route.ts';
import {JsonValue, Pair, RegionFilter} from './fleet-review.tsx';

const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : ADMIN_COPY.decisionFailed);
const percent = (n: number | null | undefined): string => (typeof n === 'number' ? `${Math.round(n * 100)}%` : '—');
const label = (col: string): string => (col === '*' ? COPY.allPinned : COPY.fieldLabels[col] ?? col);

// ---- list -------------------------------------------------------------------------
export function FleetVessels({region}: {region: string}) {
  const [filters, setFilters] = useState<Omit<FleetVesselQuery, 'region'>>({});
  const [rows, setRows] = useState<FleetVesselRow[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');

  async function load(cursor: string | null = null): Promise<void> {
    if (!cursor) setState('loading');
    try {
      const page = await getFleetVessels({...filters, region}, cursor);
      setRows(all => (cursor ? [...all, ...page.vessels] : page.vessels));
      setNext(page.next);
      setState('ready');
    } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, [filters, region]);
  const set = (key: keyof typeof filters) => (e: Event): void => {
    const value = (e.currentTarget as HTMLInputElement | HTMLSelectElement).value.trim();
    setFilters(all => ({...all, [key]: value}));
  };
  const select = (key: keyof typeof filters, text: string, options: [string, string][]) => (
    <label>
      <span>{text}</span>
      <select value={filters[key] ?? ''} onChange={set(key)}>
        <option value="">{COPY.anyValue}</option>
        {options.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
      </select>
    </label>
  );

  return (
    <section class="admin-view" aria-labelledby="fleet-vessels-heading">
      <h1 id="fleet-vessels-heading" tabIndex={-1}>{COPY.vesselsHeading}</h1>
      <div class="admin-filters">
        <RegionFilter region={region} onChange={r => { location.hash = fleetHref('fleet-vessels', r); }} />
        <label>
          <span>{COPY.port}</span>
          <input type="text" maxLength={64} value={filters.port ?? ''} onChange={set('port')} />
        </label>
        {select('class', COPY.fieldLabels.vessel_class!, [...VESSEL_CLASSES.map(c => [c, COPY.classes[c]!] as [string, string]), ['none', COPY.notClassified]])}
        {select('status', COPY.statusLabel, VESSEL_STATUSES.map(s => [s, COPY.vesselStatuses[s]!]))}
        {select('profile_status', COPY.profileLabel, PROFILE_STATUSES.map(s => [s, COPY.profileStatuses[s]!]))}
        {select('ais', COPY.aisLabel, [['watched', COPY.aisWatched], ['unwatched', COPY.aisUnwatched]])}
        {select('completeness_max', COPY.completenessLabel, [25, 50, 75].map(n => [String(n / 100), COPY.completenessAtMost(n)]))}
      </div>
      {state === 'loading' ? <p>{ADMIN_COPY.loading}</p> : state === 'failed' ? <p class="admin-error" role="alert">{ADMIN_COPY.loadFailed}</p> : rows.length === 0 ? <p>{COPY.vesselsNone}</p> : (
        <div class="admin-scroll" role="region" aria-label={COPY.vesselsCaption} tabIndex={0}>
          <table class="admin-counts">
            <caption class="admin-visually-hidden">{COPY.vesselsCaption}</caption>
            <thead>
              <tr>{Object.values(COPY.columns).map(c => <th key={c} scope="col">{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map(v => (
                <tr key={v.id}>
                  <th scope="row"><a href={fleetVesselHref(v.id)}>{v.name}</a> <span class="admin-cell-note">{v.region}</span></th>
                  <td>{v.port_id ?? '—'}</td>
                  <td>{v.vessel_class ? COPY.classes[v.vessel_class] ?? v.vessel_class : COPY.notClassified}</td>
                  <td>{COPY.vesselStatuses[v.status] ?? v.status}</td>
                  <td>{COPY.profileStatuses[v.profile_status] ?? v.profile_status}</td>
                  <td>{percent(v.completeness)}</td>
                  <td>{v.ais_watched ? COPY.aisWatched : '—'}</td>
                  <td>{v.open_reviews || '—'}</td>
                  <td>{v.pinned.length ? v.pinned.map(label).join(', ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {next && state === 'ready' ? <button type="button" class="admin-button" onClick={() => void load(next)}>{ADMIN_COPY.more}</button> : null}
    </section>
  );
}

// ---- detail -----------------------------------------------------------------------
type Kind = 'text' | 'int' | 'real' | 'class' | 'status' | 'profile' | 'consent' | 'waters';
/** The columns an admin edits here, and how (server/fleet/admin/vessels.ts EDITABLE; name and name_norm stay with the resolver). */
const EDIT_KINDS: Record<string, Kind> = {
  operator_id: 'text', port_id: 'text', landing_id: 'text', vessel_class: 'class', waters_json: 'waters', uscg_doc: 'text', state_reg: 'text', hull_id: 'text',
  call_sign: 'text', mmsi: 'text', year_built: 'int', passengers_max: 'int', bunks: 'int', length_ft: 'real', beam_ft: 'real', cruise_kn: 'real',
  website: 'text', booking_url: 'text', booking_platform: 'text', phone_business: 'text', email_business: 'text',
  status: 'status', profile_status: 'profile', map_display_consent: 'consent',
};

/** A column's value as text: enum labels, lists joined. */
function shown(col: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (col === 'vessel_class') return COPY.classes[String(value)] ?? String(value);
  if (col === 'status') return COPY.vesselStatuses[String(value)] ?? String(value);
  if (col === 'profile_status') return COPY.profileStatuses[String(value)] ?? String(value);
  if (col === 'map_display_consent') return COPY.mapConsents[String(value)] ?? String(value);
  return valueText(value);
}

/** A fact's source: its https link, or "Admin edit" for admin:<id> (never a link, never the id). */
function Source({fact}: {fact: Pick<FleetFact, 'source_id' | 'source_url'>}) {
  if (fact.source_url.startsWith('admin:')) return <>{COPY.adminSource}</>;
  const link = httpsUrl(fact.source_url);
  return link ? <a href={link} target="_blank" rel="noopener noreferrer">{fact.source_id}</a> : <>{fact.source_id}</>;
}

/** The pinned marker: who pinned is an admin id, so only the time shows. */
function Pin({pin}: {pin: FleetPin}) {
  if (!pin) return <>—</>;
  return <><span class="admin-reason">{COPY.pinned}</span> <span class="admin-cell-note">{pin === true ? COPY.pinnedAll : COPY.pinnedAt(when(pin.at))}</span></>;
}

export function FleetVesselView({id}: {id: string}) {
  const [detail, setDetail] = useState<FleetVesselDetail | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed' | 'missing'>('loading');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let live = true;
    setState('loading'); setNotice('');
    getFleetVessel(id).then(d => { if (live) { setDetail(d); setState('ready'); } })
      .catch(e => { if (live) setState(e instanceof ApiError && e.status === 404 ? 'missing' : 'failed'); });
    return () => { live = false; };
  }, [id]);
  useEffect(() => { if (detail) document.title = `${detail.vessel.name} · ${ADMIN_COPY.pageTitle}`; }, [detail]);

  /** Post an edit; the answer is the vessel's new detail. Throws the error text. */
  async function edit(change: FleetVesselEdit, done: string): Promise<void> {
    try { setDetail(await editFleetVessel(id, change)); setNotice(done); }
    catch (e) { throw new Error(errorText(e)); }
  }

  return (
    <section class="admin-view" aria-labelledby="fleet-vessel-heading">
      <p><a href="#fleet-vessels">{COPY.backToVessels}</a></p>
      <h1 id="fleet-vessel-heading" tabIndex={-1}>{detail?.vessel.name ?? COPY.vesselsHeading}</h1>
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{ADMIN_COPY.loading}</p>
        : state === 'missing' ? <p class="admin-error" role="alert">{COPY.vesselMissing}</p>
        : state === 'failed' || !detail ? <p class="admin-error" role="alert">{ADMIN_COPY.loadFailed}</p>
        : <VesselDetail detail={detail} onEdit={edit} />}
    </section>
  );
}

type OnEdit = (change: FleetVesselEdit, done: string) => Promise<void>;

function VesselDetail({detail, onEdit}: {detail: FleetVesselDetail; onEdit: OnEdit}) {
  const v = detail.vessel;
  const [editing, setEditing] = useState<string | null>(null);
  const winners = new Set(Object.values(detail.fields).map(f => f.fact_id).filter(Boolean));
  const factById = new Map(detail.facts.map(f => [f.id, f]));

  return (
    <>
      <PublicState detail={detail} onEdit={onEdit} />
      <dl class="admin-fields">
        <Pair label={COPY.region}>{v.region} · {v.slug}</Pair>
        <Pair label={COPY.operator}>{detail.operator ? `${detail.operator.name} · ${detail.operator.consent_status} · ${detail.operator.outreach_status}` : '—'}</Pair>
        <Pair label={COPY.completenessLabel}>{percent(v.completeness)}</Pair>
        <Pair label={COPY.lastSeenSource}>{when(v.last_seen_at as string | null) || '—'}</Pair>
        <Pair label={COPY.updated}>{when(v.updated_at as string | null) || '—'}</Pair>
      </dl>

      <h2 id="fleet-fields-heading">{COPY.fieldsHeading}</h2>
      <p class="admin-hint">{COPY.fieldsHelp}</p>
      <div class="admin-scroll" role="region" aria-labelledby="fleet-fields-heading" tabIndex={0}>
        <table class="admin-counts">
          <caption class="admin-visually-hidden">{COPY.fieldsCaption}</caption>
          <thead><tr><th scope="col">{COPY.field}</th><th scope="col">{COPY.value}</th><th scope="col">{COPY.pin}</th><th scope="col">{COPY.winningFact}</th>
            <th scope="col">{ADMIN_COPY.actions}</th></tr></thead>
          <tbody>
            {Object.entries(detail.fields).map(([col, f]) => {
              const fact = f.fact_id ? factById.get(f.fact_id) : undefined;
              return editing === col ? (
                <tr key={col} id={`fleet-field-${col}`}>
                  <th scope="row">{label(col)}</th>
                  <td colSpan={4}><FieldEditor col={col} value={f.value} onCancel={() => setEditing(null)}
                    onSave={async value => { await onEdit({fields: {[col]: value}}, COPY.fieldSaved(label(col))); setEditing(null); }} /></td>
                </tr>
              ) : (
                <tr key={col} id={`fleet-field-${col}`}>
                  <th scope="row">{label(col)}</th>
                  <td>{shown(col, f.value)}</td>
                  <td><Pin pin={f.pinned} /></td>
                  <td>{fact ? <><Source fact={fact} /> <span class="admin-cell-note">{fact.method} · {fact.confidence.toFixed(2)}</span></> : <span class="admin-cell-note">{COPY.noFact}</span>}</td>
                  <td>
                    <div class="admin-actions is-tight">
                      {EDIT_KINDS[col] ? <button type="button" class="admin-button is-small" aria-label={COPY.editField(label(col))} onClick={() => setEditing(col)}>{COPY.edit}</button> : null}
                      {f.pinned && f.pinned !== true && EDIT_KINDS[col] ? <UnpinButton col={col} onEdit={onEdit} /> : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2 id="fleet-facts-heading">{COPY.factsHeading}</h2>
      {detail.facts.length === 0 ? <p class="admin-hint">{COPY.noneRecorded}</p> : (
        <div class="admin-scroll" role="region" aria-labelledby="fleet-facts-heading" tabIndex={0}>
          <table class="admin-counts">
            <caption class="admin-visually-hidden">{COPY.factsCaption}</caption>
            <thead><tr>{[COPY.field, COPY.value, COPY.source, COPY.method, COPY.confidence, COPY.rights, COPY.retrieved, COPY.state].map(c => <th key={c} scope="col">{c}</th>)}</tr></thead>
            <tbody>
              {detail.facts.map(f => (
                <tr key={f.id}>
                  <th scope="row">{f.field}</th>
                  <td>{valueText(f.value) || '—'}</td>
                  <td><Source fact={f} /></td>
                  <td>{f.method}</td>
                  <td>{f.confidence.toFixed(2)}</td>
                  <td>{f.rights}</td>
                  <td>{when(f.retrieved_at)}</td>
                  <td>{f.superseded_at ? COPY.superseded(when(f.superseded_at)) : winners.has(f.id) ? COPY.winning : COPY.current}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Table id="fleet-offerings" heading={COPY.offeringsHeading} columns={[ADMIN_COPY.name, COPY.tripType, COPY.price, COPY.departs, COPY.season, COPY.statusLabel]}
        rows={detail.offerings.map(o => [o.name, o.trip_type ?? '—', typeof o.price_cents === 'number' ? `$${(o.price_cents / 100).toFixed(2)}` : '—',
          o.departs_local ?? '—', o.season_from || o.season_to ? `${o.season_from ?? ''}–${o.season_to ?? ''}` : '—', o.status])} />
      <Table id="fleet-aliases" heading={COPY.aliasesHeading} columns={[COPY.alias, COPY.aliasKind, COPY.firstSeen, COPY.lastSeen]}
        rows={detail.aliases.map(a => [a.alias, a.kind, when(a.first_seen_at), when(a.last_seen_at)])} />
      <Table id="fleet-changes" heading={COPY.changesHeading} columns={[COPY.change, COPY.before, COPY.after, COPY.detected]}
        rows={detail.changes.map(c => [c.kind, <JsonValue value={c.before} />, <JsonValue value={c.after} />, when(c.detected_at)])} />
      <Table id="fleet-watch" heading={COPY.watchHeading} columns={[COPY.fieldLabels.mmsi!, COPY.matchMethod, COPY.statusLabel, COPY.lastSeen, COPY.positions30]}
        rows={detail.watch.map(w => [w.mmsi, w.match_method, w.status, when(w.last_seen_at) || '—', w.positions_30d ?? '—'])} />
      <Table id="fleet-trips" heading={COPY.tripsHeading} columns={[COPY.date, COPY.tripType, COPY.statusLabel, COPY.distance, COPY.fishingMin]}
        rows={detail.trips.map(t => [t.local_date, t.trip_type_inferred ?? '—', t.status, t.distance_nm ?? '—', t.fishing_min ?? '—'])} />
      <Table id="fleet-advisor" heading={COPY.advisorBoatsHeading} columns={[ADMIN_COPY.name, COPY.port, COPY.statusLabel]}
        rows={detail.advisor_boats.map(b => [<a href={`/boats/${encodeURIComponent(b.slug)}`} target="_blank" rel="noopener noreferrer">{b.name}</a>, b.port, b.status])} />
      <Table id="fleet-open-reviews" heading={COPY.openReviewsHeading} columns={[COPY.kindLabel, COPY.score, COPY.opened]}
        rows={detail.open_reviews.map(r => [<a href={fleetHref('fleet-review', v.region)}>{COPY.kinds[r.kind] ?? r.kind}</a>,
          typeof r.score === 'number' ? r.score.toFixed(2) : '—', when(r.opened_at)])} />
    </>
  );
}

/** Whether the vessel can appear on public pages; a removal request keeps it off even when listed (Q15). */
function PublicState({detail, onEdit}: {detail: FleetVesselDetail; onEdit: OnEdit}) {
  const v = detail.vessel;
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function record(): Promise<void> {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await onEdit({...(v.profile_status === 'hidden' ? {} : {fields: {profile_status: 'hidden'}}), removal_requested: true}, COPY.removalRecorded);
      setConfirming(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <section class="admin-card" aria-labelledby="fleet-public-heading">
      <h2 id="fleet-public-heading">{COPY.publicHeading}</h2>
      {v.removal_requested_at ? <p><span class="admin-reason is-due">{COPY.removalRequested(when(v.removal_requested_at))}</span></p>
        : vesselIsPublic(v) ? <p>{COPY.publicShown(v.slug)}</p> : <p>{COPY.publicHidden}</p>}
      <dl class="admin-fields">
        <Pair label={COPY.fieldLabels.status!}>{shown('status', v.status)}</Pair>
        <Pair label={COPY.fieldLabels.profile_status!}>{shown('profile_status', v.profile_status)}</Pair>
        <Pair label={COPY.fieldLabels.map_display_consent!}>{shown('map_display_consent', v.map_display_consent)}
          {' '}<span class="admin-cell-note">{COPY.mapConsentHelp}</span></Pair>
      </dl>
      {v.removal_requested_at ? null : confirming ? (
        <div class="admin-actions">
          <p class="admin-hint">{COPY.recordRemovalHelp}</p>
          <button type="button" class="admin-button is-danger" disabled={busy} onClick={() => void record()}>{COPY.recordRemoval}</button>
          <button type="button" class="admin-button" onClick={() => setConfirming(false)}>{COPY.cancel}</button>
        </div>
      ) : <div class="admin-actions"><button type="button" class="admin-button" onClick={() => setConfirming(true)}>{COPY.recordRemoval}</button></div>}
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </section>
  );
}

function UnpinButton({col, onEdit}: {col: string; onEdit: OnEdit}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <>
      <button type="button" class="admin-button is-small" aria-label={COPY.unpinField(label(col))} disabled={busy} onClick={() => {
        setBusy(true); setError('');
        onEdit({unpin: [col]}, COPY.fieldUnpinned(label(col))).catch(e => setError((e as Error).message)).finally(() => setBusy(false));
      }}>{COPY.unpin}</button>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </>
  );
}

/** One field's editor: the input its kind needs; empty clears a nullable column. */
function FieldEditor({col, value, onSave, onCancel}: {col: string; value: unknown; onSave: (value: FleetFieldValue) => Promise<void>; onCancel: () => void}) {
  const kind = EDIT_KINDS[col] ?? 'text';
  const [text, setText] = useState(value === null || value === undefined || Array.isArray(value) ? '' : String(value));
  const [waters, setWaters] = useState<string[]>(Array.isArray(value) ? value.map(String) : []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputId = `fleet-edit-${col}`;

  function parsed(): FleetFieldValue {
    if (kind === 'waters') return waters.length ? WATERS.filter(w => waters.includes(w)) : null;
    const t = text.trim();
    if (!t) return null;
    if (kind === 'int' || kind === 'real') { const n = Number(t); return Number.isFinite(n) ? n : t; }
    return t;
  }
  async function save(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try { await onSave(parsed()); } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  const options = (values: readonly string[], names: Record<string, string>, nullable: boolean) => (
    <select id={inputId} value={text} onChange={e => setText((e.currentTarget as HTMLSelectElement).value)}>
      {nullable ? <option value="">{COPY.notClassified}</option> : null}
      {values.map(o => <option key={o} value={o}>{names[o] ?? o}</option>)}
    </select>
  );

  return (
    <form class="admin-editor" onSubmit={e => void save(e)}>
      {kind === 'waters' ? (
        <fieldset class="admin-targets">
          <legend>{label(col)}</legend>
          {WATERS.map(w => (
            <label key={w} class="admin-check"><input type="checkbox" checked={waters.includes(w)}
              onChange={e => { const on = (e.currentTarget as HTMLInputElement).checked; setWaters(all => (on ? [...all, w] : all.filter(x => x !== w))); }} />{w}</label>
          ))}
        </fieldset>
      ) : (
        <label for={inputId}>{label(col)}{' '}
          {kind === 'class' ? options(VESSEL_CLASSES, COPY.classes, true)
            : kind === 'status' ? options(VESSEL_STATUSES, COPY.vesselStatuses, false)
            : kind === 'profile' ? options(PROFILE_STATUSES, COPY.profileStatuses, false)
            : kind === 'consent' ? options(MAP_CONSENTS, COPY.mapConsents, false)
            : <input id={inputId} type={kind === 'int' || kind === 'real' ? 'number' : 'text'} step={kind === 'real' ? 'any' : '1'} maxLength={254} value={text}
              aria-describedby={`${inputId}-help`} onInput={e => setText((e.currentTarget as HTMLInputElement).value)} />}
        </label>
      )}
      {kind === 'text' || kind === 'int' || kind === 'real' ? <p id={`${inputId}-help`} class="admin-hint">{COPY.clearValue}</p> : null}
      <div class="admin-actions is-tight">
        <button type="submit" class="admin-button is-primary is-small" disabled={busy}>{COPY.save}</button>
        <button type="button" class="admin-button is-small" onClick={onCancel}>{COPY.cancel}</button>
      </div>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </form>
  );
}

/** A small read-only table under its heading, or "None recorded." */
function Table({id, heading, columns, rows}: {id: string; heading: string; columns: string[]; rows: ComponentChildren[][]}) {
  return (
    <>
      <h2 id={`${id}-heading`}>{heading}</h2>
      {rows.length === 0 ? <p class="admin-hint">{COPY.noneRecorded}</p> : (
        <div class="admin-scroll" role="region" aria-labelledby={`${id}-heading`} tabIndex={0}>
          <table class="admin-counts">
            <thead><tr>{columns.map(c => <th key={c} scope="col">{c}</th>)}</tr></thead>
            <tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </>
  );
}
