// Vision error classes and the image-kind list (docs/plans/text-advisor/07-vision.md).
// Their own module so vision/index.ts and vision/claude.ts both import them
// without a circular import; index.ts re-exports everything here.
import type {ImageKind} from './index.ts';

export const IMAGE_KINDS: readonly ImageKind[] = ['count_board', 'fish', 'action', 'scenery', 'video', 'document', 'unknown'];

/** The original is over THRESHOLDS.maxImageBytes (or a provider's own limit): classify the derived public.jpg instead (TA-M1). */
export class MediaTooLarge extends Error {
  bytes: number;
  constructor(bytes: number, detail = '') { super(`image too large for vision (${bytes} bytes)${detail ? ': ' + detail : ''}`); this.name = 'MediaTooLarge'; this.bytes = bytes; }
}
/** A format the provider cannot read (HEIC before conversion, video, audio). */
export class UnsupportedImage extends Error {
  mime: string;
  constructor(mime: string) { super(`unsupported image type ${mime}`); this.name = 'UnsupportedImage'; this.mime = mime; }
}
/** The provider is not set up in this deploy (no URL or key): skipped without marking it down. */
export class ProviderNotConfigured extends Error {
  constructor(provider: string, detail = 'not-configured') { super(`${provider}: ${detail}`); this.name = 'ProviderNotConfigured'; }
}
/** ADVISOR_GLOBAL_DAILY_VISION reached (Claude provider only). */
export class VisionCapReached extends Error {
  constructor(limit: number) { super(`global daily vision cap reached (${limit})`); this.name = 'VisionCapReached'; }
}
/** Every provider in the chain failed or was skipped. */
export class VisionUnavailable extends Error {
  constructor(detail: string) { super(`no vision provider answered: ${detail}`); this.name = 'VisionUnavailable'; }
}
