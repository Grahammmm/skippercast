// Relative habitat fit within surveyed rocky candidates, not catch likelihood.
// Only use after the regional source and protected-area gates admit a target.
export function speciesFit(target, species) {
  if (!target?.metrics || !['lingcod', 'rockfish'].includes(species)) return null;
  const m = target.metrics;
  const relief = m.relief_210m_m;
  const rough = m.rugose_or_bedrock_fraction_210m;
  const area = m.rough_habitat_within_250m_ha;
  const complexity = m.plane_residual_rms_250m_m;
  if (![relief, rough, area, complexity].every(Number.isFinite) ||
      relief < 0 || rough < 0 || rough > 1 || area < 0 || complexity < 0) return null;
  // A structure-oriented lingcod screen and a broader rocky-habitat screen.
  // The thresholds classify map evidence; species presence is not measured.
  const score = species === 'lingcod'
    ? 0.4 * Math.min(relief / 10, 1) + 0.35 * rough + 0.15 * Math.min(complexity / 2, 1) + 0.1 * Math.min(area / 8, 1)
    : 0.15 * Math.min(relief / 10, 1) + 0.35 * rough + 0.15 * Math.min(complexity / 2, 1) + 0.35 * Math.min(area / 8, 1);
  // Fixed physical thresholds keep the grade comparable when a new region is
  // added. Rank 1 must have both strong combined terrain and substantial
  // mapped rough cover; it is deliberately a selective search priority.
  const rank = score >= 0.9 && rough >= 0.7 ? 1 : score >= 0.7 ? 2 : 3;
  const reason = species === 'lingcod'
    ? `${relief.toFixed(1)} m local relief; ${Math.round(rough * 100)}% mapped rough cover.`
    : `${area.toFixed(1)} ha nearby rough habitat; ${Math.round(rough * 100)}% mapped rough cover.`;
  return {rank, score:Math.round(score * 1000) / 1000, reason};
}
