// User-facing strings of the Text Advisor's pages (docs/plans/text-advisor/01-architecture.md
// § touch points: every advisor page string lives here so scripts/check_copy.mjs
// lints it). TA-C4 adds the upload page, TA-C3 the web chat; TA-W1 adds the site pages' copy.

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

/** The web chat island, web/advisor/chat.tsx on dist/chat.html (08 § Web chat; TA-C3). */
export const CHAT_COPY = {
  pageTitle: 'Text SkipperCast',
  pageIntro: 'Ask about the bite, the weather window or what you can keep. Or text the same questions from your phone.',
  open: 'Text SkipperCast',
  close: 'Close chat',
  panelLabel: 'Chat with SkipperCast',
  logLabel: 'Messages',
  heading: 'SkipperCast',
  greeting: 'Hi. Ask me where to fish, what the ocean is doing or what you can keep.',
  inputLabel: 'Message',
  placeholder: 'Type a message',
  send: 'Send',
  attach: 'Add a photo',
  attached: (name: string): string => `Photo ready: ${name}`,
  removePhoto: 'Remove photo',
  uploading: 'Adding the photo…',
  thinking: 'Thinking…',
  stillThinking: 'Still thinking. This one takes a moment.',
  pending: 'That is taking longer than usual. Ask again in a minute.',
  failed: 'The message did not go through. Check your connection and try again.',
  limited: 'Too many messages at once. Wait a minute, then try again.',
  photoTooLarge: 'That photo is over 8 MB. Pick a smaller one.',
  photoType: 'Send a photo: JPEG, PNG, HEIC, GIF or WebP.',
  photoFailed: 'The photo did not upload. Try again.',
  you: 'You',
  skippercast: 'SkipperCast',
  continueHeading: 'Continue by text',
  saveContact: 'Save the number',
  textUs: 'Text us',
} as const;

/** Largest photo the chat accepts, in bytes (the server checks it again). */
export const CHAT_MAX_PHOTO_BYTES = 8 * 1024 * 1024;
/** When the chat says "still thinking", and when it stops waiting (08: 40 s on the server). */
export const CHAT_STILL_THINKING_MS = 8000;
export const CHAT_TIMEOUT_MS = 45000;
