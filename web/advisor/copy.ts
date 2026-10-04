// User-facing strings of the Text Advisor's pages (docs/plans/text-advisor/01-architecture.md
// § touch points: every advisor page string lives here so scripts/check_copy.mjs
// lints it). TA-C4 adds the upload page; TA-W1 adds the site pages' copy.

/** The upload link page, dist/upload.html + dist/advisor/upload.js (03 § Uploads for compressed channels). */
export const UPLOAD_COPY = {
  heading: 'Send a photo or video',
  intro: 'Pick one file from your phone. It goes straight to SkipperCast, and you get a text back once it is in.',
  choose: 'Choose a file',
  send: 'Send it',
  sending: 'Sending…',
  progress: (percent: number): string => `Sent ${percent}%`,
  done: 'Got it. Watch your texts for the reply.',
  another: 'Send another',
  tooLarge: 'That file is over 300 MB. Send a shorter clip.',
  unsupported: 'That file type cannot be used. Send a JPEG, PNG, HEIC photo or an MP4 or MOV video.',
  expired: 'This link has expired. Text SkipperCast for a new one.',
  failed: 'The upload did not finish. Check your signal and try again.',
  noFile: 'Choose a file first.',
} as const;

/** Largest file the upload page accepts, in bytes (the server checks it again). */
export const UPLOAD_MAX_BYTES = 300 * 1024 * 1024;
