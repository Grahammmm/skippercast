// Pure sampling of one frame's verified habitat tile rows. No fetching, units conversion or gap filling.

export class HabitatGridError extends Error {
  override name = 'HabitatGridError';
}

type Cell = {readonly lat: number; readonly lon: number};
type Reading = {readonly value: number | null; readonly cell: Cell};
export type HabitatSample = Reading | {readonly value: null; readonly reason: 'gap' | 'outside'};

interface Axis {
  readonly center: number;
  readonly step: number;
  readonly edge: (i: number) => number;
}

export interface HabitatCellIndex {
  readonly axes: readonly [Axis, Axis] | null;
  readonly north: number;
  readonly east: number;
  readonly cells: ReadonlyMap<string, Reading>;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const key = (y: number, x: number): string => `${y},${x}`;

// Convert the wire numbers' decimal spellings to a common integer scale. Forming an edge
// as center + (i - 0.5) * step in binary can move it by an ulp, even if the edge is itself
// an exactly representable decimal input. Round only the final edge to a JS number.
function decimal(value: number): [bigint, number] {
  const [whole, fraction = '', exponent = '0'] = /^(-?\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/.exec(String(value))!.slice(1);
  return [BigInt(whole + fraction), Number(exponent) - fraction.length];
}

function axis(center: number, step: number): Axis {
  const [c, ce] = decimal(center), [s, se] = decimal(step);
  const e = Math.min(ce, se) - 1;
  const origin = c * 10n ** BigInt(ce - e), halfStep = 5n * s * 10n ** BigInt(se - e - 1);
  return {center, step, edge: i => Number(`${origin + (2n * BigInt(i) - 1n) * halfStep}e${e}`)};
}

function rowAddress(coord: number, a: Axis): number {
  const offset = coord - a.center, i = Math.round(offset / a.step);
  // Two independent five-decimal roundings can differ by a whole last-place unit.
  // Allow that on ingest only, never on lookup; cap it well below half a cell.
  const tolerance = Math.min(a.step / 10, 0.00001 + 360 * Number.EPSILON);
  if (!Number.isSafeInteger(i) || i >= 2 ** 49 || Math.abs(offset - i * a.step) > tolerance) {
    throw new HabitatGridError(`Coordinate ${coord} is off the habitat grid lattice`);
  }
  return i;
}

/**
 * Index one frame in O(rows) time/space with O(1) point lookup. Rows use the tile's field
 * order and [lat, lon] resolution. The first data field is sampled unless valueField is
 * named explicitly (e.g. temperature gradient). Values are returned in wire units.
 *
 * Tile coordinates are pixel centres. Per axis, the smallest supplied centre fixes the
 * native phase and the origin is half a step below it. Keys are floor((point - origin) /
 * step) on each axis, not floored against geographic zero (which would move shifted grids).
 * Bounds are the rectangle of indexed native cells, including rows with a null reading.
 */
export function cellIndex(rows: readonly (readonly unknown[])[], resolution: readonly [number, number],
  fields: readonly string[], valueField = fields[2]): HabitatCellIndex {
  const [dy, dx] = resolution;
  const column = valueField === undefined ? -1 : fields.indexOf(valueField);
  if (fields[0] !== 'latitude' || fields[1] !== 'longitude' || column < 2) throw new HabitatGridError('Invalid habitat sample fields');
  if (!finite(dy) || !finite(dx) || dy <= 0 || dx <= 0) throw new HabitatGridError('Invalid habitat grid resolution');

  const cells = new Map<string, Reading>();
  if (!rows.length) return {axes: null, north: 0, east: 0, cells};
  let south = Infinity, west = Infinity;
  for (const row of rows) {
    const [lat, lon] = row;
    if (row.length !== fields.length || !finite(lat) || Math.abs(lat) > 90 || !finite(lon) || Math.abs(lon) > 180) {
      throw new HabitatGridError('Invalid habitat cell coordinates or width');
    }
    south = Math.min(south, lat);
    west = Math.min(west, lon);
  }

  const y = axis(south, dy), x = axis(west, dx);
  let top = 0, right = 0;
  for (const row of rows) {
    const lat = row[0] as number, lon = row[1] as number, value = row[column];
    const i = rowAddress(lat, y), j = rowAddress(lon, x), id = key(i, j);
    if (cells.has(id)) throw new HabitatGridError(`Duplicate habitat cell at ${lat}, ${lon}`);
    if (value !== null && !finite(value)) throw new HabitatGridError(`Invalid habitat value for ${valueField}`);
    cells.set(id, {value, cell: {lat, lon}});
    top = Math.max(top, i);
    right = Math.max(right, j);
  }
  return {axes: [y, x], north: y.edge(top + 1), east: x.edge(right + 1), cells};
}

function pointAddress(coord: number, a: Axis): number {
  // Division estimates the nearest boundary, not which side the point is on. The strict
  // comparison decides that, including when division rounds a point onto the boundary.
  const i = Math.round((coord - a.center) / a.step + 0.5);
  return coord < a.edge(i) ? i - 1 : i;
}

/** Half-open [south, north) × [west, east): an exact edge belongs north/east. */
export function sampleAt(index: HabitatCellIndex, lat: number, lon: number): HabitatSample {
  if (!index.axes || !finite(lat) || !finite(lon)) return {value: null, reason: 'outside'};
  const [y, x] = index.axes;
  if (lat < y.edge(0) || lon < x.edge(0) || lat >= index.north || lon >= index.east) return {value: null, reason: 'outside'};
  return index.cells.get(key(pointAddress(lat, y), pointAddress(lon, x))) ?? {value: null, reason: 'gap'};
}
