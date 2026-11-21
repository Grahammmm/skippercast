type Choice = 'auto' | 'off';
type CalibrationChoice = {choice: Choice; boat: string | null};
type Validation =
  | ({ok: true} & CalibrationChoice)
  | {ok: false; field: 'body' | 'choice' | 'boat'; error: 'not-object' | 'unexpected-key' | 'bad-choice' | 'bad-boat'};

function isChoice(value: unknown): value is Choice {
  return value === 'auto' || value === 'off';
}

// Undefined signals a rejected value; null is the canonical absence of a boat.
function normalizeBoat(value: unknown): string | null | undefined {
  if (value === null) return null;
  if (typeof value !== 'string') return undefined;
  const boat = value.trim();
  return boat.length > 80 ? undefined : boat || null;
}

export function validateCalibrationChoice(body: unknown): Validation {
  try {
    if (body !== null && typeof body === 'object' && !Array.isArray(body)) {
      const proto = Object.getPrototypeOf(body);
      if (proto === Object.prototype || proto === null) {
        const keys = Reflect.ownKeys(body);
        if (keys.some(key => key !== 'choice' && key !== 'boat')) {
          return {ok: false, field: 'body', error: 'unexpected-key'};
        }
        const record = body as Record<string, unknown>;
        const choice = keys.includes('choice') ? record.choice : undefined;
        const boat = keys.includes('boat') ? normalizeBoat(record.boat) : null;
        if (!isChoice(choice)) return {ok: false, field: 'choice', error: 'bad-choice'};
        if (boat === undefined) return {ok: false, field: 'boat', error: 'bad-boat'};
        return {ok: true, choice, boat};
      }
    }
  } catch {
    // Inspection may invoke a throwing accessor or proxy trap.
  }
  return {ok: false, field: 'body', error: 'not-object'};
}

export function readCalibrationChoice(stored: unknown): CalibrationChoice {
  try {
    const value: unknown = typeof stored === 'string' ? JSON.parse(stored) : stored;
    if (value !== null && typeof value === 'object' && !Array.isArray(value) && Object.hasOwn(value, 'choice')) {
      const record = value as Record<string, unknown>;
      const choice = record.choice;
      if (isChoice(choice)) {
        try {
          const boat = Object.hasOwn(record, 'boat') ? normalizeBoat(record.boat) : null;
          return {choice, boat: boat ?? null};
        } catch {
          // An unreadable boat must not reset a valid choice, especially 'off'.
          return {choice, boat: null};
        }
      }
    }
  } catch {
    // Missing or unreadable stored choices use the account default.
  }
  return {choice: 'auto', boat: null};
}

/** Serialize the normalized value returned by validation or reading. */
export function storedCalibrationChoice({choice, boat}: CalibrationChoice): string {
  return JSON.stringify({choice, boat});
}
