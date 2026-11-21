export const WATCHES_PER_SPOT = 5;
export const WATCHES_PER_OWNER = 50;

/** Check room for one more watch in the supplied owner's rows. */
export function watchRoom(
  existing: readonly {spot_id: unknown}[], spotId: string,
): {ok: true; spotLeft: number; ownerLeft: number} | {ok: false; limit: 'owner' | 'spot' | 'bad-spot'} {
  if (typeof spotId !== 'string' || spotId.length === 0 || spotId.length > 64) {
    return {ok: false, limit: 'bad-spot'};
  }
  const ownerCount = existing.length;
  if (ownerCount >= WATCHES_PER_OWNER) return {ok: false, limit: 'owner'};

  let spotCount = 0;
  for (let i = 0; i < ownerCount; i++) {
    try {
      // Strict equality with the validated string excludes non-string IDs.
      if (existing[i]?.spot_id === spotId) spotCount++;
    } catch {
      // An unreadable row still occupies an owner slot, but matches no spot.
    }
  }
  if (spotCount >= WATCHES_PER_SPOT) return {ok: false, limit: 'spot'};
  return {
    ok: true,
    spotLeft: WATCHES_PER_SPOT - spotCount - 1,
    ownerLeft: WATCHES_PER_OWNER - ownerCount - 1,
  };
}
