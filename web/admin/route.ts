// The admin app's hash routes (08 § Admin; TA-W2, TA-W3). Plain TypeScript so the
// Node tests load it. Views are #queue, #skippers, #rules, #posts, #funnel and
// #health; #contact/<id> opens one contact (by id only: there is no search by
// number). Anything else is the queue.
import type {AdminView} from '../advisor/copy.ts';

export const VIEWS: readonly AdminView[] = ['queue', 'skippers', 'rules', 'posts', 'funnel', 'health'];
export interface Route {view: AdminView | 'contact'; arg: string}
/** The view a hash names: one of VIEWS, or contact/<id>; anything else is the queue. */
export function routeOf(hash: string): Route {
  const [head = '', ...rest] = hash.replace(/^#/, '').split('/');
  let id = '';
  try { id = rest.length === 1 ? decodeURIComponent(rest[0]!) : ''; } catch { /* a malformed escape is no id */ }
  if (head === 'contact' && /^[\w-]{1,64}$/.test(id)) return {view: 'contact', arg: id};
  return {view: (VIEWS as readonly string[]).includes(head) ? head as AdminView : 'queue', arg: ''};
}
