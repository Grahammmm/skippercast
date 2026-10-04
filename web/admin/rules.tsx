// The admin Rules view (08 § Admin, Rules; OP-6; TA-A4): the advisor_rules table
// as an editor. Filter by jurisdiction and status (#rules?jurisdiction=<id> from
// a rule-change card); rows due for review (in review, or past review_due) are
// marked and listed with their source link. Saving a row, even unchanged,
// records the review (active, reviewed today, due again in 90 days or at the
// season's end); retiring keeps the row but it is never quoted again.
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {ApiError, createRule, editRule, getRules, retireRule, when} from './api.ts';
import type {NewRule, Rule, RuleFields, RulesList} from './api.ts';
import {rulesHref} from './route.ts';

const STATUSES = ['', 'due', 'active', 'review', 'retired'] as const;
const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : COPY.decisionFailed);
const inches = (n: number | null): string => (n === null ? '' : `${n}`);
const season = (r: Rule): string => (r.season_open && r.season_close ? `${r.season_open} – ${r.season_close}` : r.bag_limit === 0 ? '—' : COPY.yearRound);

export function RulesView({jurisdiction: initial}: {jurisdiction: string}) {
  const [jurisdiction, setJurisdiction] = useState(initial);
  const [status, setStatus] = useState<typeof STATUSES[number]>('');
  const [data, setData] = useState<RulesList | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState<string | null>(null);

  useEffect(() => { setJurisdiction(initial); }, [initial]);
  async function load(): Promise<void> {
    setState('loading');
    try { setData(await getRules(jurisdiction, status)); setState('ready'); } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, [jurisdiction, status]);
  function changeJurisdiction(value: string): void {
    setJurisdiction(value);
    history.replaceState(null, '', rulesHref(value));   // keeps the filter in the address without a hashchange
  }
  const replace = (rule: Rule, text: string): void => {
    setData(d => (d ? {...d, rules: d.rules.map(r => (r.id === rule.id ? rule : r))} : d));
    setEditing(null); setNotice(text);
  };

  return (
    <section class="admin-view" aria-labelledby="rules-heading">
      <h1 id="rules-heading" tabIndex={-1}>{COPY.rulesHeading}</h1>
      <p class="admin-hint">{COPY.rulesHelp}</p>
      <div class="admin-filters">
        <label>
          <span>{COPY.jurisdiction}</span>
          <select value={jurisdiction} onChange={e => changeJurisdiction((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">{COPY.allJurisdictions}</option>
            {(data?.jurisdictions ?? (jurisdiction ? [jurisdiction] : [])).map(j => <option key={j} value={j}>{j}</option>)}
          </select>
        </label>
        <label>
          <span>{COPY.ruleStatusLabel}</span>
          <select value={status} onChange={e => setStatus((e.currentTarget as HTMLSelectElement).value as typeof STATUSES[number])}>
            {STATUSES.map(s => <option key={s} value={s}>{COPY.ruleStatuses[s]}</option>)}
          </select>
        </label>
      </div>
      <p class="admin-notice" role="status">{notice}</p>
      {data ? <NewRuleForm list={data} jurisdiction={jurisdiction} onCreated={rule => { setData(d => (d ? {...d, rules: [...d.rules, rule]} : d)); setNotice(COPY.ruleCreated); }} /> : null}
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'failed' || !data ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : data.rules.length === 0 ? <p>{COPY.rulesNone}</p> : (
        <div class="admin-scroll" role="region" aria-label={COPY.rulesCaption} tabIndex={0}>
          <table class="admin-counts admin-rules">
            <caption class="admin-visually-hidden">{COPY.rulesCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{COPY.species}</th><th scope="col">{COPY.jurisdiction}</th><th scope="col">{COPY.size}</th><th scope="col">{COPY.bag}</th>
                <th scope="col">{COPY.season}</th><th scope="col">{COPY.ruleStatusLabel}</th><th scope="col">{COPY.reviewed}</th><th scope="col">{COPY.due}</th>
                <th scope="col">{COPY.source}</th><th scope="col">{COPY.actions}</th>
              </tr>
            </thead>
            <tbody>
              {data.rules.map(rule => editing === rule.id
                ? <tr key={rule.id}><td colSpan={10}><RuleEditor rule={rule} onSaved={r => replace(r, COPY.ruleSaved)} onCancel={() => setEditing(null)} /></td></tr>
                : <RuleRow key={rule.id} rule={rule} onEdit={() => setEditing(rule.id)} onChanged={replace} />)}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RuleRow({rule, onEdit, onChanged}: {rule: Rule; onEdit: () => void; onChanged: (rule: Rule, text: string) => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(fn: () => Promise<{rule: Rule}>, text: string): Promise<void> {
    if (busy) return;
    setBusy(true); setError('');
    try { onChanged((await fn()).rule, text); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const label = `${rule.species_label}${rule.region !== '*' ? ` (${rule.region})` : ''}`;
  return (
    <tr class={rule.due ? 'is-due' : rule.status === 'retired' ? 'is-retired' : undefined}>
      <th scope="row">{label}{rule.due ? <> <span class="admin-reason is-due">{COPY.dueBadge}</span></> : null}</th>
      <td>{rule.jurisdiction}</td>
      <td>{inches(rule.size_min_in)}{rule.size_max_in !== null ? `–${rule.size_max_in}` : ''}</td>
      <td>{rule.bag_limit ?? ''}{rule.bag_notes ? <span class="admin-muted admin-cell-note">{rule.bag_notes}</span> : null}</td>
      <td>{season(rule)}</td>
      <td>{COPY.ruleStatus[rule.status]}</td>
      <td>{when(rule.reviewed_at)}</td>
      <td>{rule.review_due}</td>
      <td><a href={rule.source_url} target="_blank" rel="noopener noreferrer">{rule.source_name}</a></td>
      <td>
        <div class="admin-actions is-tight">
          {rule.status !== 'retired' && rule.due ? <button type="button" class="admin-button is-primary is-small" disabled={busy} onClick={() => void run(() => editRule(rule.id, {}), COPY.ruleSaved)}>{COPY.confirmRule}</button> : null}
          <button type="button" class="admin-button is-small" disabled={busy} onClick={onEdit} aria-label={`${COPY.editRule}: ${label}`}>{COPY.editRule}</button>
          {rule.status !== 'retired' ? <button type="button" class="admin-button is-danger is-small" disabled={busy} aria-label={`${COPY.retireRule}: ${label}`}
            onClick={() => void run(() => retireRule(rule.id), COPY.ruleRetired)}>{COPY.retireRule}</button> : null}
        </div>
        {error ? <p class="admin-error" role="alert">{error}</p> : null}
      </td>
    </tr>
  );
}

type Draft = Record<'species_label' | 'size_min_in' | 'size_max_in' | 'bag_limit' | 'bag_notes' | 'season_open' | 'season_close' | 'depth_limit_ft' | 'area_notes' | 'gear_notes' | 'source_name' | 'source_url', string>;
const draftOf = (r: Partial<Rule>): Draft => ({
  species_label: r.species_label ?? '', size_min_in: r.size_min_in == null ? '' : String(r.size_min_in), size_max_in: r.size_max_in == null ? '' : String(r.size_max_in),
  bag_limit: r.bag_limit == null ? '' : String(r.bag_limit), bag_notes: r.bag_notes ?? '', season_open: r.season_open ?? '', season_close: r.season_close ?? '',
  depth_limit_ft: r.depth_limit_ft == null ? '' : String(r.depth_limit_ft), area_notes: r.area_notes ?? '', gear_notes: r.gear_notes ?? '', source_name: r.source_name ?? '', source_url: r.source_url ?? '',
});
/** The fields that differ from `base` (all of them for a new rule); empty text clears a field. */
function changes(draft: Draft, base: Draft | null): RuleFields {
  const out: RuleFields = {};
  for (const key of Object.keys(draft) as (keyof Draft)[]) if (!base || draft[key].trim() !== base[key]) out[key] = draft[key].trim() === '' ? null : draft[key].trim();
  return out;
}

function Fields({id, draft, set}: {id: string; draft: Draft; set: (key: keyof Draft, value: string) => void}) {
  const field = (key: keyof Draft, label: string, type = 'text', extra: Record<string, unknown> = {}) => (
    <label for={`${id}-${key}`}>{label}<input id={`${id}-${key}`} type={type} value={draft[key]} onInput={e => set(key, (e.currentTarget as HTMLInputElement).value)} {...extra} /></label>
  );
  return (
    <>
      <div class="admin-editor-row">
        {field('species_label', COPY.speciesLabel, 'text', {required: true, maxLength: 80})}
        {field('size_min_in', COPY.sizeMin, 'number', {min: 0, max: 120, step: 0.5})}
        {field('size_max_in', COPY.sizeMax, 'number', {min: 0, max: 120, step: 0.5})}
        {field('bag_limit', COPY.bag, 'number', {min: 0, max: 100, step: 1})}
        {field('depth_limit_ft', COPY.depth, 'number', {min: 0, max: 2000, step: 1})}
      </div>
      <div class="admin-editor-row">
        {field('season_open', COPY.seasonOpen, 'text', {placeholder: 'MM-DD', maxLength: 10, 'aria-describedby': `${id}-season-hint`})}
        {field('season_close', COPY.seasonClose, 'text', {placeholder: 'MM-DD', maxLength: 10, 'aria-describedby': `${id}-season-hint`})}
      </div>
      <p id={`${id}-season-hint`} class="admin-muted">{COPY.seasonHint}</p>
      {field('bag_notes', COPY.bagNotes, 'text', {maxLength: 500})}
      {field('area_notes', COPY.areaNotes, 'text', {maxLength: 500})}
      {field('gear_notes', COPY.gearNotes, 'text', {maxLength: 500})}
      <div class="admin-editor-row">
        {field('source_name', COPY.sourceName, 'text', {required: true, maxLength: 120})}
        {field('source_url', COPY.sourceUrl, 'url', {required: true, maxLength: 300})}
      </div>
    </>
  );
}

function RuleEditor({rule, onSaved, onCancel}: {rule: Rule; onSaved: (rule: Rule) => void; onCancel: () => void}) {
  const base = draftOf(rule);
  const [draft, setDraft] = useState<Draft>(base);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try { onSaved((await editRule(rule.id, changes(draft, base))).rule); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return (
    <form class="admin-editor" onSubmit={save} aria-label={`${COPY.editRule}: ${rule.species_label}`}>
      <Fields id={`rule-${rule.id}`} draft={draft} set={(k, v) => setDraft(d => ({...d, [k]: v}))} />
      <div class="admin-actions">
        <button type="submit" class="admin-button is-primary" disabled={busy}>{COPY.saveRule}</button>
        <button type="button" class="admin-button" onClick={onCancel}>{COPY.cancel}</button>
      </div>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </form>
  );
}

function NewRuleForm({list, jurisdiction, onCreated}: {list: RulesList; jurisdiction: string; onCreated: (rule: Rule) => void}) {
  const [target, setTarget] = useState({jurisdiction: jurisdiction || list.jurisdictions[0] || '', region: '*', species_key: list.species[0]?.key ?? ''});
  const [draft, setDraft] = useState<Draft>(draftOf({}));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (jurisdiction) setTarget(t => ({...t, jurisdiction, region: '*'})); }, [jurisdiction]);
  async function create(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const rule: NewRule = {...target, ...changes(draft, null)};
      onCreated((await createRule(rule)).rule);
      setDraft(draftOf({}));
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return (
    <details class="admin-card admin-new-rule">
      <summary>{COPY.addRule}</summary>
      <form class="admin-editor" onSubmit={create}>
        <div class="admin-editor-row">
          <label for="new-rule-jurisdiction">{COPY.jurisdiction}
            <select id="new-rule-jurisdiction" value={target.jurisdiction} onChange={e => setTarget(t => ({...t, jurisdiction: (e.currentTarget as HTMLSelectElement).value, region: '*'}))}>
              {list.jurisdictions.map(j => <option key={j} value={j}>{j}</option>)}
            </select>
          </label>
          <label for="new-rule-region">{COPY.region}
            <select id="new-rule-region" value={target.region} onChange={e => setTarget(t => ({...t, region: (e.currentTarget as HTMLSelectElement).value}))}>
              <option value="*">{COPY.allRegions}</option>
              {list.regions.filter(r => r.jurisdiction === target.jurisdiction).map(r => <option key={r.id} value={r.id}>{r.id}</option>)}
            </select>
          </label>
          <label for="new-rule-species">{COPY.speciesKey}
            <select id="new-rule-species" value={target.species_key} onChange={e => setTarget(t => ({...t, species_key: (e.currentTarget as HTMLSelectElement).value}))}>
              {list.species.map(s => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
          </label>
        </div>
        <Fields id="new-rule" draft={draft} set={(k, v) => setDraft(d => ({...d, [k]: v}))} />
        <div class="admin-actions"><button type="submit" class="admin-button is-primary" disabled={busy}>{COPY.createRule}</button></div>
        {error ? <p class="admin-error" role="alert">{error}</p> : null}
      </form>
    </details>
  );
}
