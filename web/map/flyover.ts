// The Chart flyover (#646, walkthrough slice 6; owner decision B): on the first
// Chart view of a visit, the camera tilts and turns slowly toward the region's
// harbor, then settles back north up and flat where it started, so the shared
// camera, `?view=` and every north-up overlay are as they were. It runs once
// per browser session, only over the region's home framing (never for a link
// that names a view, a spot or a habitat), and never when the browser asks for
// reduced motion or Save-Data, or the page is hidden. The first touch, click,
// wheel or key stops it and returns the Chart north up and flat at once
// (web/map/engine.ts `flyover`). The desktop 3D orbit is dot's renderer camera
// and is not here (interface note on #413).
//
// Erasable syntax only: tests/test_flyover.mjs imports it by type stripping.
import {saveData} from '../landing/save-data.ts';
import type {FlyLeg} from './engine.ts';

/** Session storage key: set when a flyover starts, so a reload in the same tab does not repeat it. */
export const FLYOVER_KEY = 'skippercast-flyover-v1';
/** The turn's limit either way, in degrees: past it the labels read sideways. */
export const MAX_TURN = 90;
/** The turn when no harbor is known, or the camera sits on it. */
export const DEFAULT_TURN = 30;
/** The steepest tilt, in degrees: steeper loads tiles out to the horizon. */
export const MAX_TILT = 50;

interface Point {readonly latitude: number; readonly longitude: number}

/** Initial great-circle bearing from `a` to `b`, degrees true in (-180, 180]. */
export function bearingTo(a: Point, b: Point): number {
  const rad = Math.PI / 180, p1 = a.latitude * rad, p2 = b.latitude * rad, dl = (b.longitude - a.longitude) * rad;
  const deg = Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)) / rad;
  return deg <= -180 ? deg + 360 : deg;
}

/** How far to turn, in degrees (positive turns the view clockwise): toward the harbor, at most MAX_TURN either way. */
export function flyoverTurn(center: Point, harbor: Point | null): number {
  const near = harbor && Math.abs(harbor.latitude - center.latitude) < 0.005 && Math.abs(harbor.longitude - center.longitude) < 0.005;
  if (!harbor || near) return DEFAULT_TURN;
  return Math.max(-MAX_TURN, Math.min(MAX_TURN, Math.round(bearingTo(center, harbor))));
}

/** The flight: tilt in while turning halfway, finish the turn, then settle north up and flat (about 19 seconds). */
export function flyoverLegs(center: Point, harbor: Point | null): FlyLeg[] {
  const turn = flyoverTurn(center, harbor);
  return [
    {pitch: MAX_TILT - 5, bearing: turn / 2, duration: 7000},
    {pitch: MAX_TILT, bearing: turn, duration: 7000},
    {pitch: 0, bearing: 0, duration: 5000},
  ];
}

export interface FlyoverGate {
  /** prefers-reduced-motion: reduce. */
  readonly reduced: boolean;
  /** The browser asked to save data. */
  readonly saveData: boolean;
  /** The page is hidden. */
  readonly hidden: boolean;
  /** The link names a view, a spot or a habitat: the visitor came for that place, not the tour. */
  readonly linked: boolean;
  /** A flyover already started in this browser session. */
  readonly seen: boolean;
}

/** Whether the first Chart view may fly: every gate open. */
export const mayFly = (g: FlyoverGate): boolean => !g.reduced && !g.saveData && !g.hidden && !g.linked && !g.seen;

/** Reads the session flag; storage that throws counts as unseen (the flight then happens once per page load). */
export function flyoverSeen(storage: () => Storage | null | undefined = () => sessionStorage): boolean {
  try { return storage()?.getItem(FLYOVER_KEY) === '1'; } catch { return false; }
}

/** Sets the session flag; storage that throws is ignored. */
export function markFlyoverSeen(storage: () => Storage | null | undefined = () => sessionStorage): void {
  try { storage()?.setItem(FLYOVER_KEY, '1'); } catch { /* storage denied */ }
}

/** The browser's gates, read now; `linked` is the caller's. Outside a browser nothing flies. */
export function browserGate(linked: boolean): FlyoverGate {
  if (typeof window === 'undefined' || typeof document === 'undefined') return {reduced: true, saveData: false, hidden: true, linked, seen: false};
  return {
    reduced: typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
    saveData: saveData(typeof navigator === 'undefined' ? null : navigator),
    hidden: document.hidden,
    linked,
    seen: flyoverSeen(),
  };
}
