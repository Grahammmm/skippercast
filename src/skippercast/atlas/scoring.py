"""The atlas's fixed terrain heuristic, not a catch-probability model."""

import math


def habitat_score(metrics: dict) -> int:
    """Combine relief, rough cover, detrended complexity, and usable area."""
    keys = ("relief_210m_m", "rugose_or_bedrock_fraction_210m",
            "plane_residual_rms_250m_m", "rough_habitat_within_250m_ha")
    values = [metrics[k] for k in keys]
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("Habitat metrics must be finite, nonnegative numbers")
    relief, rough_fraction, complexity, area = values
    if rough_fraction > 1:
        raise ValueError("Rough habitat coverage must be a fraction from 0 to 1")
    return round(35 * min(relief / 15, 1)
                 + 30 * rough_fraction
                 + 20 * min(complexity / 3, 1)
                 + 15 * min(area / 10, 1))


def habitat_grade(score: int) -> str:
    return "A" if score >= 75 else "B" if score >= 55 else "C"
