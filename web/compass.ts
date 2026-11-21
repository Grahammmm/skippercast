const POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
/** 16-point compass name for degrees true. */
export const compass = (deg: number): string => POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]!;
