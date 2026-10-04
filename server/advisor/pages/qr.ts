// A small QR code encoder for the Text Advisor's printed and on-screen QR
// (GET /qr/text.svg, docs/plans/text-advisor/03-channels.md § contact card and
// deep links; TA-C6). Byte mode, error correction level M, versions 1 to 10
// (up to 213 bytes), all eight masks scored with the standard penalty rules
// (ISO/IEC 18004 § 7.8.3). No dependency: the structure follows the public
// specification and Project Nayuki's reference description of it.
//
// encodeQr(text) -> the module matrix (true = dark); qrSvg(text) -> an SVG
// with a four-module quiet zone. Pure: same text, same matrix, same SVG.

export const MIN_VERSION = 1;
export const MAX_VERSION = 10;

// Level M, versions 1..10 (index 0 = version 1): error-correction codewords per block, and blocks.
const ECC_PER_BLOCK = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
const BLOCKS = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
const FORMAT_M = 0;   // the two error-correction bits for level M in the format information

export interface QrCode {version: number; size: number; mask: number; modules: boolean[][]}

/** Raw data modules of a version: every module that is not part of a function pattern. */
export function rawDataModules(version: number): number {
  let result = (16 * version + 128) * version + 64;
  if (version >= 2) {
    const align = Math.floor(version / 7) + 2;
    result -= (25 * align - 10) * align - 55;
    if (version >= 7) result -= 36;
  }
  return result;
}

/** Data codewords (bytes) a version holds at level M. */
export function dataCodewords(version: number): number {
  return Math.floor(rawDataModules(version) / 8) - ECC_PER_BLOCK[version - 1]! * BLOCKS[version - 1]!;
}

/** Bytes of text a version holds in byte mode at level M (4-bit mode, 8- or 16-bit count). */
export function byteCapacity(version: number): number {
  return Math.floor((dataCodewords(version) * 8 - 4 - (version <= 9 ? 8 : 16)) / 8);
}

/** Centres of the alignment patterns along one axis. */
export function alignmentPositions(version: number): number[] {
  if (version === 1) return [];
  const count = Math.floor(version / 7) + 2, size = version * 4 + 17;
  const step = Math.floor((version * 8 + count * 3 + 5) / (count * 4 - 4)) * 2;
  const out: number[] = [];
  for (let pos = size - 7; out.length < count - 1; pos -= step) out.unshift(pos);
  out.unshift(6);
  return out;
}

// ---- Reed-Solomon over GF(256), polynomial 0x11D ---------------------------------

function gfMultiply(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

/** The generator polynomial of a degree, highest term omitted, coefficients highest first. */
export function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < result.length; j++) {
      result[j] = gfMultiply(result[j]!, root);
      if (j + 1 < result.length) result[j]! ^= result[j + 1]!;
    }
    root = gfMultiply(root, 0x02);
  }
  return result;
}

/** The error-correction codewords of `data` for a divisor. */
export function rsRemainder(data: readonly number[], divisor: readonly number[]): number[] {
  const result = new Array<number>(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift()!;
    result.push(0);
    divisor.forEach((coef, i) => { result[i]! ^= gfMultiply(coef, factor); });
  }
  return result;
}

// ---- data codewords ---------------------------------------------------------------

/** The smallest version (1..10) whose level-M byte capacity holds `length` bytes, or null. */
export function versionFor(length: number): number | null {
  for (let v = MIN_VERSION; v <= MAX_VERSION; v++) if (length <= byteCapacity(v)) return v;
  return null;
}

/** Mode, count, data, terminator, padding: the data codewords before error correction. */
function dataBytes(bytes: Uint8Array, version: number): number[] {
  const bits: number[] = [];
  const put = (value: number, length: number) => { for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(0b0100, 4);
  put(bytes.length, version <= 9 ? 8 : 16);
  for (const b of bytes) put(b, 8);
  const capacity = dataCodewords(version) * 8;
  put(0, Math.min(4, capacity - bits.length));
  put(0, (8 - bits.length % 8) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) put(pad, 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  return out;
}

/** Split into blocks, add each block's error correction, interleave (ISO 18004 § 7.6). */
export function addEccAndInterleave(data: readonly number[], version: number): number[] {
  const blocks = BLOCKS[version - 1]!, eccLen = ECC_PER_BLOCK[version - 1]!;
  const raw = Math.floor(rawDataModules(version) / 8);
  const shortBlocks = blocks - raw % blocks, shortLen = Math.floor(raw / blocks);
  const divisor = rsDivisor(eccLen);
  const all: number[][] = [];
  for (let i = 0, k = 0; i < blocks; i++) {
    const dat = data.slice(k, k + shortLen - eccLen + (i < shortBlocks ? 0 : 1));
    k += dat.length;
    const ecc = rsRemainder(dat, divisor);
    // Short blocks get a placeholder so every block has the same length; it is skipped below.
    all.push([...dat, ...(i < shortBlocks ? [-1] : []), ...ecc]);
  }
  const out: number[] = [];
  for (let i = 0; i < all[0]!.length; i++) {
    all.forEach((block, j) => { if (i !== shortLen - eccLen || j >= shortBlocks) out.push(block[i]!); });
  }
  return out;
}

// ---- the matrix ---------------------------------------------------------------------

/** The format information bits (15) for level M and a mask. */
export function formatBits(mask: number): number {
  const data = (FORMAT_M << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

/** The version information bits (18) for versions 7 and up. */
export function versionBits(version: number): number {
  let rem = version;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  return (version << 12) | rem;
}

const MASKS: ((x: number, y: number) => boolean)[] = [
  (x, y) => (x + y) % 2 === 0,
  (_x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => (x * y) % 2 + (x * y) % 3 === 0,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0,
  (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0,
];
export const maskAt = (mask: number, x: number, y: number): boolean => MASKS[mask]!(x, y);

class Matrix {
  readonly size: number;
  readonly modules: boolean[][];
  readonly fixed: boolean[][];
  readonly version: number;
  constructor(version: number) {
    this.version = version;
    this.size = version * 4 + 17;
    this.modules = Array.from({length: this.size}, () => new Array<boolean>(this.size).fill(false));
    this.fixed = Array.from({length: this.size}, () => new Array<boolean>(this.size).fill(false));
  }
  set(x: number, y: number, dark: boolean): void { this.modules[y]![x] = dark; this.fixed[y]![x] = true; }

  functionPatterns(): void {
    const {size} = this;
    for (let i = 0; i < size; i++) { this.set(6, i, i % 2 === 0); this.set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]] as const) {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy, dist = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) this.set(x, y, dist !== 2 && dist !== 4);
      }
    }
    const align = alignmentPositions(this.version), last = align.length - 1;
    align.forEach((cx, i) => align.forEach((cy, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) this.set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }));
    this.format(0);   // reserves the format areas; redrawn with the chosen mask
    if (this.version >= 7) {
      const bits = versionBits(this.version);
      for (let i = 0; i < 18; i++) {
        const dark = ((bits >>> i) & 1) === 1, a = size - 11 + i % 3, b = Math.floor(i / 3);
        this.set(a, b, dark); this.set(b, a, dark);
      }
    }
  }

  format(mask: number): void {
    const bits = formatBits(mask), bit = (i: number) => ((bits >>> i) & 1) === 1, {size} = this;
    for (let i = 0; i <= 5; i++) this.set(8, i, bit(i));
    this.set(8, 7, bit(6)); this.set(8, 8, bit(7)); this.set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) this.set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) this.set(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) this.set(8, size - 15 + i, bit(i));
    this.set(8, size - 8, true);   // the dark module
  }

  codewords(data: readonly number[]): void {
    const {size} = this;
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) {
        const x = right - j, upward = ((right + 1) & 2) === 0, y = upward ? size - 1 - vert : vert;
        if (!this.fixed[y]![x] && i < data.length * 8) { this.modules[y]![x] = ((data[i >>> 3]! >>> (7 - (i & 7))) & 1) === 1; i++; }
      }
    }
  }

  applyMask(mask: number): void {
    for (let y = 0; y < this.size; y++) for (let x = 0; x < this.size; x++) if (!this.fixed[y]![x] && maskAt(mask, x, y)) this.modules[y]![x] = !this.modules[y]![x];
  }
}

/**
 * The standard penalty score of a finished matrix (lower is better): runs of
 * five or more, 2x2 blocks, 1:1:3:1:1 finder-like runs with four light modules
 * on one side (counted on run lengths, the border as light, as the reference
 * implementations do) and the dark/light balance.
 */
export function penalty(modules: boolean[][]): number {
  const size = modules.length;
  let score = 0;
  const addHistory = (run: number, history: number[]): void => {
    if (history[0] === 0) run += size;   // the light border before the first run
    history.pop(); history.unshift(run);
  };
  const countPatterns = (h: number[]): number => {
    const n = h[1]!, core = n > 0 && h[2] === n && h[3] === n * 3 && h[4] === n && h[5] === n;
    return (core && h[0]! >= n * 4 && h[6]! >= n ? 1 : 0) + (core && h[6]! >= n * 4 && h[0]! >= n ? 1 : 0);
  };
  const scan = (at: (i: number, j: number) => boolean): void => {
    for (let i = 0; i < size; i++) {
      let color = false, run = 0;
      const history = [0, 0, 0, 0, 0, 0, 0];
      for (let j = 0; j < size; j++) {
        if (at(i, j) === color) { run++; if (run === 5) score += 3; else if (run > 5) score++; continue; }
        addHistory(run, history);
        if (!color) score += countPatterns(history) * 40;
        color = at(i, j); run = 1;
      }
      if (color) { addHistory(run, history); run = 0; }
      addHistory(run + size, history);
      score += countPatterns(history) * 40;
    }
  };
  scan((y, x) => modules[y]![x]!);
  scan((x, y) => modules[y]![x]!);
  for (let y = 0; y + 1 < size; y++) for (let x = 0; x + 1 < size; x++) {
    const c = modules[y]![x];
    if (c === modules[y]![x + 1] && c === modules[y + 1]![x] && c === modules[y + 1]![x + 1]) score += 3;
  }
  let dark = 0;
  for (const row of modules) for (const m of row) if (m) dark++;
  const total = size * size;
  score += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
  return score;
}

/** The QR code of `text` (UTF-8, byte mode, level M), with the lowest-penalty mask (or `forceMask`, for tests). Throws when it does not fit version 10. */
export function encodeQr(text: string, forceMask?: number): QrCode {
  const bytes = new TextEncoder().encode(text);
  const version = versionFor(bytes.length);
  if (version == null) throw Error(`QR payload too long (${bytes.length} bytes; at most ${byteCapacity(MAX_VERSION)})`);
  const codewords = addEccAndInterleave(dataBytes(bytes, version), version);
  let best: QrCode | null = null, bestScore = Infinity;
  for (let mask = 0; mask < 8; mask++) {
    if (forceMask != null && mask !== forceMask) continue;
    const m = new Matrix(version);
    m.functionPatterns();
    m.codewords(codewords);
    m.applyMask(mask);
    m.format(mask);
    const score = penalty(m.modules);
    if (score < bestScore) { bestScore = score; best = {version, size: m.size, mask, modules: m.modules}; }
  }
  return best!;
}

export const QUIET_ZONE = 4;

/** An SVG of the code: one path of dark runs on a white square, `QUIET_ZONE` modules of margin, `scale` px per module. */
export function qrSvg(text: string, scale = 8): string {
  const code = encodeQr(text), side = code.size + QUIET_ZONE * 2;
  let d = '';
  code.modules.forEach((row, y) => {
    for (let x = 0; x < code.size;) {
      if (!row[x]) { x++; continue; }
      let end = x;
      while (end < code.size && row[end]) end++;
      d += `M${x + QUIET_ZONE} ${y + QUIET_ZONE}h${end - x}v1h-${end - x}z`;
      x = end;
    }
  });
  const px = side * scale;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${side} ${side}" width="${px}" height="${px}" shape-rendering="crispEdges" role="img" aria-label="QR code: text SkipperCast">`
    + `<rect width="${side}" height="${side}" fill="#fff"/><path fill="#000" d="${d}"/></svg>\n`;
}
