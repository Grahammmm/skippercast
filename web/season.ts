// A calendar of the registry's reviewed dates, not a current-source verification.
import {CDFW_OCEAN, officialURL, ruleProfile, speciesPage, validRegulations, type RulesRegion} from './regs.ts';
export type MonthState = 'open' | 'limits' | 'closed' | 'scheduled' | 'not-reviewed' | 'part' | 'area';
const LABEL: Record<MonthState, string> = {open: 'Open', limits: 'Open · limits', closed: 'Closed', scheduled: 'Opener unconfirmed', 'not-reviewed': 'Not reviewed', part: 'Mixed', area: 'Choose fishing location'};
// Geography is unknown until a location is chosen, so it outranks a closed reef member.
const ORDER: MonthState[] = ['not-reviewed', 'area', 'closed', 'scheduled', 'limits', 'open'];
export function seasonYear(data: any, species: string, region: RulesRegion, year: number): {
  months: {month: number; state: MonthState; label: string}[]; revision: string; link: {href: string; label: string};
} | null {
  if (!Number.isInteger(year) || year < 1000 || year > 9999 || !validRegulations(data, region)) return null;
  const ids = species === 'reef' ? ['lingcod', 'rockfish'] : [species];
  const profiles = ids.map(id => ruleProfile(data, id, region));
  if (profiles.some(p => !p)) return null;
  const stateOn = (day: string): MonthState => {
    if (data.rules_review_status !== 'reviewed' || day < data.valid_from || day > data.valid_through) return 'not-reviewed';
    const states = profiles.map((p): MonthState => {
      const w = p.windows.find((w: any) => day >= w.start && day <= w.end);
      if (!w) return 'closed';
      if (w.requires_opening_review) return 'scheduled';
      if (w.geography) return 'area';
      return w.restriction || (w.start_at && day === w.start) ? 'limits' : 'open';
    });
    return ORDER.find(s => states.includes(s))!;
  };
  const months = Array.from({length: 12}, (_, m) => {
    // These are civil date keys, not UTC instants. DST cannot shift a day into another month.
    const days = Array.from({length: new Date(Date.UTC(year, m + 1, 0)).getUTCDate()}, (_, d) =>
      stateOn(`${year}-${String(m + 1).padStart(2, '0')}-${String(d + 1).padStart(2, '0')}`));
    const unique = new Set(days);
    const state: MonthState = unique.size === 1 ? days[0]! : unique.has('not-reviewed') && unique.size === 2 ? 'not-reviewed' : 'part';
    let label = LABEL[state];
    if (state === 'part') {
      const open = (s: MonthState) => s === 'open' || s === 'limits';
      const first = days.findIndex(open);
      if (first >= 0) {
        const after = days.findIndex((s, i) => i > first && !open(s));
        label = `Part open: ${first + 1}–${after < 0 ? days.length : after}`;
      }
    }
    return {month: m + 1, state, label};
  });
  const primary = profiles[0].primary_source_id || profiles[0].source_ids[0];
  const link = speciesPage(data, species, region) ?? {href: officialURL(data.sources[primary]?.url ?? CDFW_OCEAN, region), label: 'Official rules'};
  return {months, revision: data.reviewed_at, link};
}
