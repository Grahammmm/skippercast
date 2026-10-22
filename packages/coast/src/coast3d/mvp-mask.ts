/** Mask-aware terrain-RGB handling for the local C3 viewer.
 *  The C2 producer writes unsupported cells as alpha=0 with RGB=0. MapLibre decodes RGB only,
 *  so RGB=0 reads as -10000 m and draws a false cliff at every support edge. Unsupported
 *  cells must therefore never reach the decoder as elevation. */
export const MASK_PROTOCOL = 'mvpmask';

/** Mapbox terrain-RGB decode, as MapLibre does it (RGB only, alpha ignored). */
export function decodeMapboxElevation(r: number, g: number, b: number): number {
  return -10000 + (r * 65536 + g * 256 + b) * 0.1;
}
function encodeMapboxElevation(m: number): [number, number, number] {
  const code = Math.max(0, Math.round((m + 10000) * 10));
  return [(code >> 16) & 255, (code >> 8) & 255, code & 255];
}

/** Replace every unsupported cell (alpha < 255) with the nearest supported elevation,
 *  so no fabricated depth is introduced and no cell falls below the real minimum.
 *  Result is fully opaque. Returns null when no cell is supported (tile must be treated as missing). */
export function maskTerrainRgba(rgba: Uint8ClampedArray, width: number, height: number): {data: Uint8ClampedArray<ArrayBuffer>; unsupported: number} | null {
  const n = width * height;
  if (rgba.length !== n * 4) throw Error('Terrain tile size mismatch');
  const out = new Uint8ClampedArray(rgba);
  const queue = new Int32Array(n);
  const done = new Uint8Array(n);
  let head = 0, tail = 0;
  for (let i = 0; i < n; i++) if (rgba[i * 4 + 3] === 255) { done[i] = 1; queue[tail++] = i; }
  const unsupported = n - tail;
  if (!tail) return null;
  while (head < tail) {
    const i = queue[head++]!, x = i % width, y = (i - x) / width;
    for (const j of [x > 0 ? i - 1 : -1, x < width - 1 ? i + 1 : -1, y > 0 ? i - width : -1, y < height - 1 ? i + width : -1]) {
      if (j < 0 || done[j]) continue;
      done[j] = 1; out[j * 4] = out[i * 4]!; out[j * 4 + 1] = out[i * 4 + 1]!; out[j * 4 + 2] = out[i * 4 + 2]!;
      queue.set([j], tail++);
    }
  }
  for (let i = 0; i < n; i++) out[i * 4 + 3] = 255;
  return {data: out, unsupported};
}
export {encodeMapboxElevation};

/** Register the same-origin masking protocol (browser only). Tiles with no supported cell are rejected. */
export async function registerMaskProtocol(addProtocol: (name: string, load: (p: {url: string}, c: AbortController) => Promise<{data: ArrayBuffer}>) => void, origin: string): Promise<void> {
  addProtocol(MASK_PROTOCOL, async (params, abort) => {
    const url = new URL(params.url.slice(MASK_PROTOCOL.length + 3));
    if (url.origin !== origin) throw Error('Terrain must be local');
    const res = await fetch(url, {redirect: 'error', signal: abort.signal});
    if (!res.ok) throw Error('Terrain tile unavailable');
    const bitmap = await createImageBitmap(await res.blob(), {premultiplyAlpha: 'none', colorSpaceConversion: 'none'});
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const ctx = canvas.getContext('2d', {willReadFrequently: true})!;
    ctx.drawImage(bitmap, 0, 0);
    const img = ctx.getImageData(0, 0, bitmap.width, bitmap.height);
    const masked = maskTerrainRgba(img.data, img.width, img.height);
    if (!masked) throw Error('Terrain tile has no supported cells');
    ctx.putImageData(new ImageData(masked.data, img.width, img.height), 0, 0);
    return {data: await (await canvas.convertToBlob({type: 'image/png'})).arrayBuffer()};
  });
}
