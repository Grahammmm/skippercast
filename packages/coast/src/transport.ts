/** Public read-only paths through SkipperCast's reviewed coastal bridge. */
export function coastPath(path: string): string {
  if (!path.startsWith('/') || /[%\\]|\/\/|(?:^|\/)\.{1,2}(?:\/|$)/.test(path)) throw Error('Invalid coastal path');
  const input = new URL(path, 'https://coast.invalid');
  if (/^\/api\/(?:report|history|ocean|habitat\/(?:release|tiles))$/.test(input.pathname)) return '/api/coast' + path.slice(4);
  if (input.pathname.startsWith('/data/')) return '/coast-data' + path;
  throw Error('Unsupported coastal path');
}
export const coastFetch: typeof fetch = (input, init) => {
  if (typeof input !== 'string') throw Error('Coastal requests require a public relative path');
  const method = init?.method?.toUpperCase();
  if (method && !['GET','HEAD'].includes(method)) throw Error('Coastal data is read only');
  return fetch(coastPath(input), {...init, ...(method && {method}), credentials: 'omit', redirect: 'error'});
};
