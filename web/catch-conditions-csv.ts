import { parseConditionsV1 } from '../server/conditions-v1.ts';

export const CONDITIONS_CSV_COLUMNS = Object.freeze([
  'water_temp_f', 'contrast_f_per_nm', 'front_nm', 'chlorophyll_mg_m3',
  'current_kn', 'current_toward_deg', 'swell_ft', 'swell_period_s', 'swell_from_deg',
  'wind_kn', 'wind_from_deg', 'tide_stage', 'tide_height_ft', 'conditions_note',
] as const);

// Match the account CSV formula guard; the caller handles quoting.
const guardText = (text: string): string => /^[ \n]*[=+\-@\t\r]/.test(text) ? "'" + text : text;

function fixed(value: number, decimals: number): string {
  // toFixed switches to exponential notation here; these values are already integers.
  if (Math.abs(value) >= 1e21) {
    return BigInt(value).toString() + (decimals === 0 ? '' : '.' + '0'.repeat(decimals));
  }
  return value.toFixed(decimals);
}

/** Project a validated snapshot into unquoted CSV cells, with no I/O. */
export function conditionsCsvCells(raw: unknown): string[] {
  const cells = Array<string>(CONDITIONS_CSV_COLUMNS.length).fill('');
  if (raw == null) return cells;

  const parsed = parseConditionsV1(raw);
  const noteIndex = cells.length - 1;
  if (!parsed.ok) cells[noteIndex] = 'invalid';
  else if ('pending' in parsed.value) cells[noteIndex] = 'pending';
  else if ('missing' in parsed.value) cells[noteIndex] = guardText(parsed.value.missing);
  else {
    const { layers } = parsed.value;
    const notes: string[] = [];
    function writeLayer<T extends object>(
      name: keyof typeof layers, start: number, layer: T | { missing: string } | undefined,
      format: (value: T) => string[],
    ): void {
      if (layer === undefined) return;
      if ('missing' in layer) notes.push(`${name}: ${layer.missing}`);
      else format(layer).forEach((cell, offset) => { cells[start + offset] = cell; });
    }

    writeLayer('water_temp', 0, layers.water_temp, v => [fixed(v.value, 1)]);
    writeLayer('contrast', 1, layers.contrast, v => [fixed(v.value, 2)]);
    writeLayer('front_nm', 2, layers.front_nm, v => [fixed(v.value, 1)]);
    writeLayer('chlorophyll', 3, layers.chlorophyll, v => [fixed(v.value, 2)]);
    writeLayer('current', 4, layers.current, v => [fixed(v.kn, 1), fixed(v.toward_deg, 0)]);
    writeLayer('swell', 6, layers.swell, v => [fixed(v.ft, 1), fixed(v.period_s, 0), fixed(v.from_deg, 0)]);
    writeLayer('wind', 9, layers.wind, v => [fixed(v.kn, 1), fixed(v.from_deg, 0)]);
    writeLayer('tide', 11, layers.tide, v => [guardText(v.stage), fixed(v.height_ft, 1)]);
    cells[noteIndex] = guardText(notes.join('; '));
  }
  return cells;
}
