// Queue keyboard shortcuts and the decisions each kind offers (08 § Admin:
// "Keyboard: a/r/e"; TA-W2). Plain TypeScript so the Node tests load it.
import type {Decision, ReviewKind} from './api.ts';

const KEYS: Readonly<Record<string, Decision>> = {a: 'approve', r: 'reject', e: 'edit'};

export interface KeyLike {key: string; altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; isComposing?: boolean; target?: unknown}

/** True when the key press belongs to a text field (typing there never triggers a shortcut). */
export function typingIn(target: unknown): boolean {
  const el = target as {tagName?: string; isContentEditable?: boolean} | null;
  const tag = String(el?.tagName ?? '').toUpperCase();
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable === true;
}

/** The decision a key press asks for on a focused item, or null (modifiers, text fields, other keys). */
export function shortcutFor(event: KeyLike): Decision | null {
  if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing || typingIn(event.target)) return null;
  return KEYS[event.key.length === 1 ? event.key.toLowerCase() : ''] ?? null;
}

/** The decisions a review item offers (server/advisor/admin/decisions.ts): edit only where there is something to edit. */
export function decisionsFor(kind: ReviewKind, reason: string): Decision[] {
  switch (kind) {
    case 'media': return ['approve', 'edit', 'reject'];
    case 'report': return ['approve', 'edit', 'reject'];
    case 'skipper': return reason === 'new_skipper' ? ['approve', 'reject'] : ['approve'];
    case 'conversation': return ['approve', 'edit', 'reject'];   // edit opens the reply box
    case 'rule': return ['approve', 'reject'];
    case 'post': return ['approve', 'edit', 'reject'];   // TA-S1: edit opens the post editor, whose save also approves
    default: return [];
  }
}
