import {useEffect, useState} from 'preact/hooks';
import type {ConditionsForecast} from '../conditions.ts';
import {readingSource} from '../brief/mark-forecast.ts';
import {language, num, t, type Language} from '../i18n.ts';
import {createEntry, readEntries, saveEntry, type MapLogEntry} from '../private-map-log.ts';
import {Button} from '../ui/Button.tsx';

/** A status is an id, not captured text, so a language switch re-renders it with no storage read or write. */
export type LogNotice = 'saved' | 'full' | 'unavailable' | 'readFailed';
const NOTICE = {saved: 'privateMapLog.saved', full: 'privateMapLog.full', unavailable: 'privateMapLog.unavailable', readFailed: 'privateMapLog.readFailed'} as const;
export const noticeText = (notice: LogNotice | null, lang: Language): string => notice ? t(NOTICE[notice], lang) : '';
/** The summary line: a count (0 included) or, for an unreadable log, unavailable; never zero for unreadable. */
export const countText = (entries: readonly MapLogEntry[] | null, lang: Language): string =>
  entries ? t('privateMapLog.count', lang, {n: num(entries.length, lang, 0)}) : t('privateMapLog.countUnavailable', lang);

/**
 * One stored entry. App labels follow the reader's language; the stored snapshot (positionBasis and each reading line, written
 * in English by web/private-map-log.ts) is shown exactly as stored inside lang="en", never re-translated or re-derived.
 */
export function LogEntry({entry, tz, lang}: {entry: MapLogEntry; tz: string; lang: Language}) {
  const c = entry.conditions;
  return <li data-private-entry>
    <p>{t(entry.kind === 'catch' ? 'privateMapLog.kind.catch' : 'privateMapLog.kind.blank', lang)} · {entry.name} · {entry.region} · <time dateTime={entry.recordedAt}>{entry.recordedAt}</time></p>
    <p class="ui-mono">{entry.position.latitude.toFixed(5)}, {entry.position.longitude.toFixed(5)} · <span lang="en">{entry.positionBasis}</span></p>
    {!c ? <p>{t('privateMapLog.noConditions', lang)}</p> : <>
      <p>{c.retrievedAt === null ? t('privateMapLog.retrievedNone', lang) : t('privateMapLog.retrieved', lang, {time: new Date(c.retrievedAt).toISOString()})}</p>
      <ul>{[...c.forecast.families.flatMap(f => f.rows), c.forecast.current].map((r, j) => <li key={j} lang="en">
        {r.label}: {r.value ?? t('privateMapLog.snapshot.gap', 'en', {gap: r.gap})} · {readingSource(r, c.at, tz, 'en')}
        {r.validAt !== null ? ` · ${t('privateMapLog.snapshot.valid', 'en', {time: new Date(r.validAt).toISOString()})}` : ''}
        {r.issuedAt !== null ? ` · ${t('privateMapLog.snapshot.run', 'en', {time: new Date(r.issuedAt).toISOString()})}` : ''}
      </li>)}</ul>
    </>}
  </li>;
}

/** Independent of account log, trip/share state and the map's forecast-hour selector. New entries keep the v1 English snapshot (see docs/web-app.md). */
export function PrivateMapLog({mark, region, forecast, tz}: {
  mark: {name: string; position?: {latitude: number; longitude: number}; withheld?: boolean};
  region: string; forecast: ConditionsForecast | null; tz: string;
}) {
  const lang = language.value;
  const [entries, setEntries] = useState<readonly MapLogEntry[] | null>(null), [notice, setNotice] = useState<LogNotice | null>(null);
  const reload = () => { try { setEntries(readEntries()); } catch { setNotice('readFailed'); } };
  useEffect(() => { reload(); }, []);

  if (!createEntry(mark, 'catch', region, null, Date.now(), tz)) return null;
  const save = (kind: 'catch' | 'blank') => {
    const result = saveEntry(createEntry(mark, kind, region, forecast, Date.now(), tz));
    setNotice(result);
    if (result === 'saved') reload();
  };
  const status = noticeText(notice, lang);
  return <section class="app-mark-forecast" aria-label={t('privateMapLog.title', lang)}>
    <p class="ui-eyebrow">{t('privateMapLog.title', lang)}</p>
    <p>{t('privateMapLog.explain', lang)}</p>
    <div class="app-mark-actions">
      <Button size="sm" onClick={() => save('catch')}>{t('privateMapLog.logCatch', lang)}</Button>
      <Button size="sm" onClick={() => save('blank')}>{t('privateMapLog.logBlank', lang)}</Button>
    </div>
    <p role={status ? 'status' : undefined}>{status}</p>
    <p>{t('privateMapLog.privacy', lang)}</p>
    <details><summary>{countText(entries, lang)}</summary>
      <p>{t('privateMapLog.evidence', lang)} <a href="/sources">{t('privateMapLog.sources', lang)}</a></p>
      <p>{t('privateMapLog.snapshotEnglish', lang)}</p>
      <ul>{[...(entries ?? [])].reverse().map((entry, i) => <LogEntry key={i} entry={entry} tz={tz} lang={lang} />)}</ul>
    </details>
  </section>;
}
