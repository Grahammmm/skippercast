// Strings for the fleet Coverage and AIS health views (CF-35; docs/plans/charter-fleet/design.md § 13).
// Kept apart from CF-31's fleet-copy.ts so no two tasks share a copy file. AIS presence is
// "seen" or "not seen" and nothing stronger: many small boats carry no transponder.

/** A duration in seconds as "45 s", "12 min", "3 h 5 min" or "2 d 4 h". */
export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  return h % 24 ? `${Math.floor(h / 24)} d ${h % 24} h` : `${Math.floor(h / 24)} d`;
}
/** A percentage, or a dash when there was nothing to count. */
export const percent = (p: number | null | undefined): string => p === null || p === undefined ? '—' : `${p}%`;

export const FLEET_COVERAGE_COPY = {
  views: {'fleet-coverage': 'Coverage', 'fleet-ais': 'AIS health'},

  // Coverage (#fleet-coverage)
  coverageHeading: 'Fleet coverage',
  region: 'Region',
  allRegions: 'All regions',
  coverageNote: 'Active boats only. “Seen” means a watched AIS transponder was heard in the last 30 days; “not seen” only means we have no AIS for the boat in that time, and many small boats carry no transponder at all.',
  totalsHeading: 'All ports',
  byPortHeading: 'By port and class',
  port: 'Port',
  vesselClass: 'Class',
  noPort: 'No port',
  unclassified: 'Unclassified',
  portTotal: 'All classes',
  boats: 'Boats',
  mmsi: 'With MMSI',
  seen: 'Seen in AIS (30 d)',
  notSeen: 'Not seen',
  singleSource: 'Single source',
  completeness: 'Completeness',
  groupsHeading: 'Completeness by field group',
  groups: {identity: 'Identity (class, waters, port, landing)', registry: 'Registry ids (USCG, state, hull, call sign, MMSI)',
    specs: 'Specs (year, passengers, bunks, length, beam, speed)', contact: 'Contact (website, booking, phone, email)'} as Record<string, string>,
  groupShort: {identity: 'Identity', registry: 'Registry ids', specs: 'Specs', contact: 'Contact'} as Record<string, string>,
  sourcesHeading: 'Sources per boat',
  sourcesNote: 'Distinct sources behind each boat’s current facts; admin edits and AIS records are left out.',
  sourcesCount: (k: string): string => k === '1' ? '1 source' : `${k} sources`,
  singleHeading: 'Single-source boats',
  singleEmpty: 'Every boat has two or more sources.',
  name: 'Boat',
  source: 'Source',
  ais: 'AIS (30 d)',
  aisSeen: 'Seen',
  aisNotSeen: 'Not seen',
  runsHeading: 'Recent runs',
  runsEmpty: 'No pipeline runs yet.',
  step: 'Step',
  status: 'Status',
  started: 'Started',
  finished: 'Finished',
  counts: 'Counts',
  error: 'Error',
  truncated: 'Only the first 5,000 boats are counted here.',
  noBoats: 'No active boats in the registry yet.',
  countOf: (n: number, pct: number | null): string => `${n} (${percent(pct)})`,

  // AIS health (#fleet-ais)
  aisHeading: 'AIS health',
  aisNote: 'From the listener’s heartbeat and hourly counters, as the processor pushes them. An hour with no messages counts as down.',
  noRegions: 'No AIS state yet: the processor has pushed no heartbeat or counters.',
  receiving: 'Receiving',
  stale: 'Stale: no message for over 3 hours',
  lastMessage: 'Last message',
  lastMessageAge: 'Last message age',
  never: 'Never',
  heartbeat: 'Heartbeat written',
  heartbeatUnreadable: 'The stored heartbeat could not be read.',
  connected: 'Connected',
  yes: 'Yes',
  no: 'No',
  messagesPerMin: 'Messages per minute',
  watchedPerMin: 'Watched messages per minute',
  last24Heading: 'Last 24 hours',
  messages24: 'Messages',
  reconnects24: 'Reconnects',
  dropped24: 'Dropped',
  hoursReported: 'Hours reported',
  messagesTrend: 'Messages per hour, last 24 hours',
  uptimeHeading: 'Uptime',
  uptime7: '7 days',
  uptime30: '30 days',
  uptimeLine: (pct: number | null, up: number, hours: number): string => `${percent(pct)} (${up} of ${hours} h)`,
  gapsHeading: 'Gaps over 10 minutes (7 days)',
  gapsEmpty: 'No gap over 10 minutes.',
  hour: 'Hour (UTC)',
  maxGap: 'Longest silence',
  outagesHeading: 'Hours without messages (7 days)',
  outagesEmpty: 'Every hour had messages.',
  from: 'From (UTC)',
  to: 'To (UTC)',
  hours: 'Hours',
  processorHeading: 'Processor',
  processorLast: 'Last run',
  processorAge: 'Age',
  watchHeading: 'Watch list',
  watched: 'Watched MMSIs',
  candidates: 'Candidates',
  listenerWatch: 'Held by the listener',
  ago: (s: number | null): string => s === null ? '—' : `${duration(s)} ago`,
} as const;
