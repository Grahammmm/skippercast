// Display only: GPX serialization always uses the original decimal degrees.
export const COORDINATE_FORMATS = ['dd', 'ddm', 'dms'];
export const coordinateFormat = value => COORDINATE_FORMATS.includes(value) ? value : 'dd';

export function formatCoordinate(value, axis, format = 'dd') {
  const limit = axis === 'latitude' ? 90 : 180;
  if (!Number.isFinite(value) || Math.abs(value) > limit) return '—';
  const negative = value < 0 || Object.is(value, -0);
  const hemisphere = axis === 'latitude' ? (negative ? 'S' : 'N') : (negative ? 'W' : 'E');
  const mode = coordinateFormat(format), magnitude = Math.abs(value);
  if (mode === 'dd') return `${magnitude.toFixed(5)}° ${hemisphere}`;
  // Round total units first so seconds/minutes carry into the next degree.
  const scale = mode === 'ddm' ? 60000 : 360000;
  const total = Math.round(magnitude * scale), degrees = Math.floor(total / scale), rest = total % scale;
  if (mode === 'ddm') return `${degrees}° ${(rest / 1000).toFixed(3).padStart(6, '0')}′ ${hemisphere}`;
  const minutes = Math.floor(rest / 6000), seconds = (rest % 6000) / 100;
  return `${degrees}° ${String(minutes).padStart(2, '0')}′ ${seconds.toFixed(2).padStart(5, '0')}″ ${hemisphere}`;
}

export const formatCoordinates = (latitude, longitude, format = 'dd') =>
  `${formatCoordinate(latitude, 'latitude', format)}, ${formatCoordinate(longitude, 'longitude', format)}`;
