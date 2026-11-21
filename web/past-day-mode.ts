import type {PastDayChoice} from './past-day.ts';

type PastDayMode =
  | {day: 'today'; hourPicker: true; chips: boolean}
  | {day: 'past'; date: string; hourPicker: false}
  | {day: 'none'; date: string; hourPicker: false; reason: 'no-history' | 'not-saved-offline' | 'not-observed'};

export function pastDayMode(choice: PastDayChoice, o: {online: boolean; hasHistory: boolean}): PastDayMode {
  switch (choice.kind) {
    case 'today':
      return {day: 'today', hourPicker: true, chips: o.hasHistory && o.online};
    case 'unshown':
      return {day: 'none', date: choice.day, hourPicker: false, reason: 'not-observed'};
    case 'past':
      if (!o.hasHistory) return {day: 'none', date: choice.day, hourPicker: false, reason: 'no-history'};
      if (!o.online) return {day: 'none', date: choice.day, hourPicker: false, reason: 'not-saved-offline'};
      return {day: 'past', date: choice.day, hourPicker: false};
  }
}
