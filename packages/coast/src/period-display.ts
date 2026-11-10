// Display-only wave period text: whole seconds, as the mark card already reads.
//
// The caller passes a period it has already admitted as finite and keeps its own
// null gate and " s" unit. Nothing reads this text back as a value: every rule,
// threshold and window compares the exact original period.
//
// Erasable syntax only: Node tests import this file by type stripping.

/** A period in whole seconds for copy: 14.285714 -> "14". */
export const periodSecondsText = (value: number): string => String(Math.round(value));
