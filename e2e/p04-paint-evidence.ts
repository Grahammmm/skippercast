// Small screenshot reader, not a new colour-domain proof. The existing contrast
// function is applied only to actual 8-bit screenshot backing pixels under the
// visible count's text rectangle. Analytical continuous-gradient proof stays separate.
import {inflateSync} from 'node:zlib';
import {contrast} from '../scripts/check_contrast.mjs';

export function pngPixels(png: Buffer) {
  if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw Error('Not PNG');
  let width = 0, height = 0, channels = 0;
  const chunks: Buffer[] = [];
  for (let at = 8; at < png.length;) {
    const length = png.readUInt32BE(at), kind = png.toString('ascii', at + 4, at + 8);
    const b = png.subarray(at + 8, at + 8 + length);
    if (kind === 'IHDR') {
      width = b.readUInt32BE(0); height = b.readUInt32BE(4);
      channels = b[9] === 6 ? 4 : b[9] === 2 ? 3 : 0;
      if (b[8] !== 8 || !channels || b[10] || b[11] || b[12]) throw Error('Unsupported PNG encoding');
    }
    if (kind === 'IDAT') chunks.push(b);
    at += length + 12;
    if (kind === 'IEND') break;
  }
  if (!width || !height || !channels) throw Error('Missing PNG header');
  const stride = width * channels, raw = inflateSync(Buffer.concat(chunks));
  if (raw.length !== height * (stride + 1)) throw Error('PNG scanline length');
  const out = Buffer.alloc(height * stride);
  const paeth = (a: number, b: number, c: number) => {
    const p = a + b - c, x = Math.abs(p - a), y = Math.abs(p - b), z = Math.abs(p - c);
    return x <= y && x <= z ? a : y <= z ? b : c;
  };
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)]!;
    if (filter > 4) throw Error('Unsupported PNG filter');
    for (let x = 0; x < stride; x++) {
      const left = x >= channels ? out[y * stride + x - channels]! : 0;
      const up = y ? out[(y - 1) * stride + x]! : 0;
      const upperLeft = y && x >= channels ? out[(y - 1) * stride + x - channels]! : 0;
      const add = [0, left, up, Math.floor((left + up) / 2), paeth(left, up, upperLeft)][filter]!;
      out[y * stride + x] = (raw[y * (stride + 1) + x + 1]! + add) & 255;
    }
  }
  return {width, height, pixel(x: number, y: number): number[] {
    if (x < 0 || y < 0 || x >= width || y >= height) throw Error('Pixel outside screenshot');
    const at = y * stride + x * channels;
    return [out[at]!, out[at + 1]!, out[at + 2]!, channels === 4 ? out[at + 3]! : 255];
  }};
}
const hex = (rgb: readonly number[]) => '#' + rgb.slice(0, 3).map(n => n.toString(16).padStart(2, '0')).join('');

export function backingContrast(png: Buffer, foreground: number[], rect: {x: number; y: number; width: number; height: number}) {
  if (foreground.length !== 4 || foreground[3] !== 255) throw Error('Count foreground must be opaque');
  const image = pngPixels(png), colours = new Map<string, number>();
  const left = Math.ceil(rect.x), top = Math.ceil(rect.y), right = Math.floor(rect.x + rect.width), bottom = Math.floor(rect.y + rect.height);
  if (right <= left || bottom <= top) throw Error('No whole pixels under count');
  let minimum = Infinity, samples = 0;
  for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
    const pixel = image.pixel(x, y);
    if (pixel[3] !== 255) throw Error('Screenshot backing is not opaque');
    const background = hex(pixel), ratio = contrast(hex(foreground), background);
    minimum = Math.min(minimum, ratio); samples++;
    colours.set(background, (colours.get(background) ?? 0) + 1);
  }
  return {minimum, samples, backgrounds: [...colours].map(([colour, pixels]) => ({colour, pixels})),
    scope: 'Actual screenshot backing at this count rectangle/viewport/theme only; no unsampled continuous-gradient or full-app cascade claim.'};
}
