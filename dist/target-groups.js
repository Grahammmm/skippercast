// UI groups share habitat and report filters, never combined legal limits.
export const targetSpecies = (target) => target === "reef" ? ["lingcod", "rockfish"] : [target];
export const matchesTargetSpecies = (species, target) => targetSpecies(target).includes(species);
