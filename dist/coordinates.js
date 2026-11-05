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

// Reads a typed position: decimal degrees, degrees + decimal minutes or degrees + minutes + decimal seconds.
// Returns {value} (signed decimal degrees) or {error} (a plain-words reason).
export function parseCoordinate(text, axis) {
  const latitude = axis === 'latitude', limit = latitude ? 90 : 180;
  const fail = error => ({error});
  if (typeof text !== 'string' || !text.trim()) return fail('Enter a position; the text is empty.');
  let s = text.trim().replace(/[\u2033\u201d\u201c]|''|\u2032\u2032|"/g, '\u2033').replace(/[\u2032\u2019\u2018`']/g, '\u2032')
    .replace(/[\u00b0\u00ba]/g, '\u00b0').replace(/(\d)\s*d(?![a-z])/gi, '$1\u00b0');
  const letters = [];
  let m = s.match(/^([a-z])\s*/i);
  if (m) { letters.push(m[1].toUpperCase()); s = s.slice(m[0].length); }
  m = s.match(/\s*([a-z])$/i);
  if (m) { letters.push(m[1].toUpperCase()); s = s.slice(0, m.index); }
  if (letters.length > 1) return fail('Use only one hemisphere letter (N, S, E or W).');
  const letter = letters[0];
  if (letter && !'NSEW'.includes(letter)) return fail(`The letter ${letter} is not a hemisphere letter; use N, S, E or W.`);
  if (letter && 'NS'.includes(letter) !== latitude) {
    return fail(latitude ? `The letter ${letter} is for a longitude; a latitude uses N or S.` : `The letter ${letter} is for a latitude; a longitude uses E or W.`);
  }
  let negative = letter === 'S' || letter === 'W';
  s = s.trim();
  const sign = s.match(/^([+\-\u2212])\s*/);
  if (sign) {
    if (letter) return fail('Use either a minus sign or a hemisphere letter, not both.');
    negative = sign[1] !== '+';
    s = s.slice(sign[0].length);
  }
  if (!s) return fail('No number found in the position.');
  const body = s.replace(/\s+([\u00b0\u2032\u2033])/g, '$1').replace(/([\u00b0\u2032\u2033])/g, '$1 ').trim();
  const rawParts = body.split(/\s+/), marks = rawParts.map(p => /[\u00b0\u2032\u2033]$/.test(p) ? p.slice(-1) : '');
  const parts = rawParts.map((p, i) => marks[i] ? p.slice(0, -1) : p);
  if (parts.length > 3) return fail('Too many parts; use degrees, minutes and seconds at most.');
  if (marks.some((mark, i) => mark && mark !== ['\u00b0', '\u2032', '\u2033'][i])) {
    return fail('Degree, minute and second signs must come in that order: degrees (°) first, then minutes (′), then seconds (″).');
  }
  if (parts.some(p => /^[-\u2212]\d/.test(p))) return fail('Minutes and seconds cannot be negative.');
  if (parts.some(p => !/^(\d+\.?\d*|\.\d+)$/.test(p))) return fail('That is not a number; expected digits such as 35.3576, 35 21.456 or 35 21 27.36.');
  const nums = parts.map(Number);
  if (!nums.every(Number.isFinite)) return fail('The number is too large to read.');
  if (nums.length > 1 && !Number.isInteger(nums[0])) return fail('Degrees must be a whole number when minutes are given.');
  if (nums.length > 2 && !Number.isInteger(nums[1])) return fail('Minutes must be a whole number when seconds are given.');
  if (nums.length > 1 && nums[1] >= 60) return fail('Minutes must be less than 60.');
  if (nums.length > 2 && nums[2] >= 60) return fail('Seconds must be less than 60.');
  const magnitude = nums[0] + (nums[1] ?? 0) / 60 + (nums[2] ?? 0) / 3600;
  if (magnitude > limit) return fail(`A ${axis} must be between -${limit} and ${limit} degrees.`);
  return {value: negative ? -magnitude : magnitude};
}
