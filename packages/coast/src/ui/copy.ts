// Optional presentation copy for the shared renderers (historyView, chart). A host that wants another
// language passes a CoastCopy; with none, every renderer keeps its original English text and formatters.
// The packages never import the app's catalogue: the host supplies text/time/number/age. Type-only plus the key list.
const METRICS = ['waterTempF', 'waveFt', 'windKnots', 'airTempF', 'gustKnots', 'periodS'] as const;
export const COAST_COPY_KEYS = [
  'history.eyebrow', 'history.ready.heading', 'history.ready.subtitle', 'history.indexed', 'history.unavail.heading', 'history.unavail.body',
  'history.station', 'history.measurement', 'history.metricUnavailable', 'history.range.aria', 'history.days', 'history.missingMetric',
  'history.latest', 'history.hourStart', 'history.stale', 'history.noMeasurement', 'history.average', 'history.bins', 'history.median',
  'history.year.one', 'history.year.other', 'history.hour.one', 'history.hour.other', 'history.coverageSuffix', 'history.versus', 'history.comparison',
  'history.noComparison', 'history.notForecast', 'history.chartTitle', 'history.chartAria', 'history.hint.recent', 'history.legend.hourly', 'history.legend.gaps',
  'history.season.eyebrow', 'history.season.title', 'history.noAnnualRef', 'history.season.aria', 'history.hint.season', 'history.legend.median', 'history.legend.utc',
  'history.season.caveat', 'history.ref.summary', 'history.ref.detail', 'history.ref.none', 'history.ref.years', 'history.none', 'history.unknown', 'history.loaded',
  'history.provCoverage', 'history.sourceReport', 'history.noaaRecord', 'history.recentAria', 'history.noRecent', 'history.seasonAria', 'history.noAnnual',
  'history.month.1', 'history.month.2', 'history.month.3', 'history.month.4', 'history.month.5', 'history.month.6',
  'history.month.7', 'history.month.8', 'history.month.9', 'history.month.10', 'history.month.11', 'history.month.12',
  'history.caveat.position', 'history.caveat.gust', 'history.caveat.period', 'history.caveat.common',
  'chart.noSamples', 'chart.series', 'chart.aria',
  ...METRICS.map(m => `history.metric.${m}` as const), ...METRICS.map(m => `history.metricLower.${m}` as const),
] as const;
export type CoastCopyKey = typeof COAST_COPY_KEYS[number];

export interface CoastCopy {
  /** The text of `key` with `{name}` variables filled; variables are raw, the renderer escapes the result once. */
  text(key: CoastCopyKey, vars?: Readonly<Record<string, string | number>>): string;
  /** A time in the host language and zone; the renderer passes the same instant, options and zone it would format itself. */
  time(at: string, tz: string, options: Intl.DateTimeFormatOptions): string;
  /** A number with exactly `digits` decimals (grouped when `group`). Display only: never used for coordinates or arithmetic. */
  number(value: number, digits: number, group?: boolean): string;
  /** How long ago `at` was, from the same thresholds as ageLabel. */
  age(at: string, now: Date): string;
}
