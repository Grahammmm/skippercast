// One source for the web's unit factors (RF0708-2): exact definitions, not rounded spellings.
// Erasable syntax only: Node tests import this file by type stripping.
export const M_PER_FT = 0.3048;
export const FT_PER_M = 1 / M_PER_FT;
export const M_PER_NMI = 1852;
export const KT_PER_MS = 3600 / M_PER_NMI;
export const KMH_PER_KT = M_PER_NMI / 1000;
export const MPH_PER_KT = M_PER_NMI / 1609.344;
export const WIND_SPEED = {kt: {factor: 1, label: 'kt'}, mph: {factor: MPH_PER_KT, label: 'mph'}, kmh: {factor: KMH_PER_KT, label: 'km/h'}} as const;
export const fToC = (f: number): number => (f - 32) * 5 / 9;
