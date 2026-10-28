// Terrain grade filter (walkthrough slice 3, #620): the rail's "All grades / A and B /
// A only" choice, written as `?grade=` so a shared link keeps it. A terrain grade ranks
// physical search priority from surveys (the atlas's `habitat_grade`, the seafloor
// publication's `terrain_grade`); it is never a catch rating. A filter narrows what
// draws; it never adds anything the target, profile depth or protected-area screen left out.
//
// Erasable syntax only: Node tests import this file by type stripping.

export const GRADE_FILTERS = ['all', 'ab', 'a'] as const;
export type GradeFilter = typeof GRADE_FILTERS[number];

/** The rail's labels, strongest-only last. */
export const GRADE_LABELS: Readonly<Record<GradeFilter, string>> = {all: 'All', ab: 'A and B', a: 'A only'};

/** The legend's one sentence on what a grade means. */
export const GRADE_MEANING = 'Terrain grade ranks search priority from surveys, not catch.';

/** `?grade=` as the filter: `a` or `ab`; anything else, an absent key included, is all grades. */
export function parseGrade(value: string | null | undefined): GradeFilter {
  const v = (value ?? '').toLowerCase();
  return v === 'a' || v === 'ab' ? v : 'all';
}

/** The `?grade=` value for `filter`: null (no key) for all grades. */
export const gradeParam = (filter: GradeFilter): string | null => filter === 'all' ? null : filter;

/**
 * Whether a feature graded `grade` ("A", "B", "C") passes `filter`. With every grade allowed an ungraded
 * feature stays; with a filter on, only a stated grade inside it passes, so an unranked area never reads as A.
 */
export function gradeAllows(filter: GradeFilter, grade: unknown): boolean {
  if (filter === 'all') return true;
  const g = typeof grade === 'string' ? grade.trim().toUpperCase() : '';
  return filter === 'a' ? g === 'A' : g === 'A' || g === 'B';
}
