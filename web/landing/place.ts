// Lightweight place metadata, shared with the deferred readings loader.
import {t} from './i18n.ts';
export const DEFAULT_REGION = 'morro-bay';
/** The default region's name (its region.json `name`, equal by test), shown until that loads: the readout names the place it reads (#422). */
export const DEFAULT_PLACE = t('landing.place.default', 'en');
/** "Morro Bay & Avila area"; a name that already ends in "area" is kept as it is. */
export const placeLabel = (name: string): string => /\barea$/i.test(name.trim()) ? name.trim() : `${name.trim()} area`;
