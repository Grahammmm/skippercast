import type {regionList} from './catch-region.ts';

type Region = ReturnType<typeof regionList>['regions'][number];

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function watchCoverage(
  {lat, lon}: {lat: unknown; lon: unknown},
  regionId: string,
  regions: readonly Region[],
): 'inside' | 'outside-region' | 'unknown-region' | 'bad-position' {
  if (!finite(lat) || !finite(lon) || Math.abs(lat) >= 90 || Math.abs(lon) >= 180) {
    return 'bad-position';
  }
  const region = regions.find(({id}) => id === regionId);
  if (!region) return 'unknown-region';

  const [west, south, east, north] = region.bounds;
  if (lon < west || east < lon || lat < south || north < lat) return 'outside-region';
  return 'inside';
}
