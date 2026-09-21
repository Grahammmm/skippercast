"""Pure alert lifecycle decisions for externally reviewed assessments.

These functions send nothing and persist nothing. ``previous`` must represent
successfully delivered alerts, not attempted sends or merely saved assessments.
The caller supplies aware times in its planning timezone.
"""

from datetime import date, datetime, timedelta
import hashlib
import json
import math


MATERIAL_FIELDS = (
    "comfort_score", "fishing_conditions_score", "confidence", "area",
    "departure", "fishing_start", "fishing_end", "return", "hazards",
    "critical_gaps", "verification_complete", "meets_numeric_targets",
)


def _qualifying_score(value):
    return (type(value) in (int, float) and math.isfinite(value)
            and 9 <= value <= 10)


def qualifies(assessment):
    """Apply an alert gate; this does not calculate or verify the assessment.

Absent/null hazard or gap lists are unknown, not empty. Scores and explicit
verification flags must have been supplied by a reviewer of the whole trip.
"""
    return (
        isinstance(assessment, dict)
        and assessment.get("verification_complete") is True
        and assessment.get("meets_numeric_targets") is True
        and assessment.get("hazards") == []
        and assessment.get("critical_gaps") == []
        and assessment.get("confidence") in ("Moderate", "High")
        and _qualifying_score(assessment.get("comfort_score"))
        and _qualifying_score(assessment.get("fishing_conditions_score"))
    )


def fingerprint(assessment):
    """Hash material fields, excluding retrieval times and editorial wording."""
    values = {key: assessment.get(key) for key in MATERIAL_FIELDS}
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def action_for(trip_date, assessment, previous, now):
    """Return an alert type or ``None``; never mark an alert delivered.

    The previous evening's final assessment remains due after a retraction.
    A missed final is reported once instead of being silently backdated.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware in the planning timezone")
    if not isinstance(assessment, dict):
        raise ValueError("assessment must be a dictionary")
    if previous is not None and not isinstance(previous, dict):
        raise ValueError("previous must be a dictionary or None")
    previous = previous or {}
    day = date.fromisoformat(trip_date)
    if previous.get("final_assessment_delivered") is True:
        return None
    if day <= now.date():
        if previous.get("ever_alerted") is True and previous.get("missed_final_reported") is not True:
            return "Missed final assessment"
        return None
    final_due = now.date() == day - timedelta(days=1) and now.hour >= 18
    ever_alerted = previous.get("ever_alerted") is True
    if final_due and ever_alerted:
        return "Day-before assessment"
    current = qualifies(assessment)
    if current and not ever_alerted:
        return "Day-before assessment" if final_due else "Early opportunity"
    if not ever_alerted:
        return None
    if previous.get("qualified_at_last_alert") is True and not current:
        return "No longer qualifies"
    if fingerprint(assessment) != previous.get("material_fingerprint"):
        return "Update"
    return None
