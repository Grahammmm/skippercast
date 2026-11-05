// The browser's localStorage, or null. A browser that refuses site data throws
// (SecurityError) from the localStorage getter itself, so the read is guarded
// and a throwing getter reads as no storage. Called lazily, never at load.
export function browserStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}
