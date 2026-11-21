// Keep in sync with OWNER_PAGE in server/trip-queue.ts:25.
export const MAX_OWNER_PAGE = 500;

function checkLimit(limit: number): void {
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_OWNER_PAGE) {
    throw new RangeError('Invalid owner page limit');
  }
}

export function mergeOwnerPages(
  trips: readonly string[], watches: readonly string[], limit: number,
): {owners: string[]; next: string | null} {
  checkLimit(limit);
  let bound: string | null = null;
  for (const page of [trips, watches]) {
    if (page.length > limit) throw new RangeError('Owner page exceeds limit');
    let last: string | undefined;
    for (const owner of page) {
      if (last !== undefined && !(last < owner)) {
        throw new RangeError('Owner page is not strictly ascending');
      }
      last = owner;
    }
    // A full page may have unseen owners beyond its tail. A short one cannot
    // constrain the cursor; its entries past the bound will be read again.
    if (page.length === limit && last !== undefined && (bound === null || last < bound)) {
      bound = last;
    }
  }
  const owners = [...new Set([...trips, ...watches])]
    .filter(owner => bound === null || owner <= bound)
    .sort();
  return {owners, next: bound};
}

/** Walk both sources; each read returns the first `limit` owners strictly after `after`. */
export async function allCheckOwners(
  read: (source: 'trips' | 'watches', after: string, limit: number) => Promise<string[]>,
  limit: number, maxRounds = 10_000,
): Promise<string[]> {
  checkLimit(limit);
  const all: string[] = [];
  let after = '';
  for (let round = 1; round <= maxRounds; round++) {
    const [trips, watches] = await Promise.all([
      read('trips', after, limit), read('watches', after, limit),
    ]);
    const {owners, next} = mergeOwnerPages(trips, watches, limit);
    all.push(...owners);
    if (next === null) return all;
    if (next <= after) throw new RangeError('Owner cursor did not advance');
    after = next;
  }
  throw new RangeError('Owner walk exceeded its round limit');
}
