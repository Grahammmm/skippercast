"""Encode and validate offline WCOFS eddy tile documents."""

from collections.abc import Iterable
from datetime import datetime, timezone
import math

from skippercast.pipeline.eddies import EddyFeature

_FEATURE_KEYS = {"outline", "sense", "diameter_km", "ow_min"}
_TILE_KEYS = {"frame_time", "features"}
# The Chart's parser (web/map/eddies-feed.ts MAX_EDDIES, MAX_OUTLINE_POINTS) refuses anything larger.
_MAX_EDDIES = 200
_MAX_OUTLINE_POINTS = 2000


class EddyTileError(ValueError):
    """The eddy tile or a feature does not conform to the tile format."""


def _finite_number(value: object) -> bool:
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _valid_outline(outline: object) -> bool:
    if not isinstance(outline, (list, tuple)) or len(outline) < 5:
        return False
    for point in outline:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return False
        lon, lat = point
        if not (_finite_number(lon) and _finite_number(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            return False
    return outline[0] == outline[-1]


def _validate_feature(feature: object, index: int) -> None:
    label = f"features[{index}]"
    if not isinstance(feature, dict) or feature.keys() != _FEATURE_KEYS:
        raise EddyTileError(f"{label} must contain exactly outline, sense, diameter_km and ow_min")
    if feature["sense"] not in ("cw", "ccw"):
        raise EddyTileError(f"{label}.sense must be 'cw' or 'ccw'")
    outline = feature["outline"]
    if isinstance(outline, (list, tuple)) and len(outline) > _MAX_OUTLINE_POINTS:
        raise EddyTileError(f"{label}.outline must have at most {_MAX_OUTLINE_POINTS} points")
    if not _valid_outline(outline):
        raise EddyTileError(f"{label}.outline must be a closed ring of at least 5 valid [lon, lat] points")
    diameter = feature["diameter_km"]
    if not _finite_number(diameter) or diameter <= 0:
        raise EddyTileError(f"{label}.diameter_km must be finite and positive")
    ow = feature["ow_min"]
    if not _finite_number(ow) or ow >= 0:
        raise EddyTileError(f"{label}.ow_min must be finite and negative")


def eddies_tile(frame_time: datetime, features: Iterable[EddyFeature]) -> dict:
    """Build a fresh tile, rejecting features that become invalid after rounding."""
    if frame_time.utcoffset() is None:
        raise EddyTileError("frame_time must be timezone-aware")
    stamp = frame_time.astimezone(timezone.utc).isoformat(timespec="seconds").removesuffix("+00:00") + "Z"
    encoded: list[EddyFeature] = []
    for index, feature in enumerate(features):
        if index >= _MAX_EDDIES:
            raise EddyTileError(f"features must contain at most {_MAX_EDDIES} eddies")
        _validate_feature(feature, index)
        diameter = round(feature["diameter_km"], 2)
        ow = float(f"{feature['ow_min']:.4g}")
        if diameter <= 0:
            raise EddyTileError(f"features[{index}].diameter_km must be finite and positive after rounding")
        if not math.isfinite(ow) or ow >= 0:
            raise EddyTileError(f"features[{index}].ow_min must be finite and negative after rounding")
        encoded.append({
            "outline": [[round(lon, 5), round(lat, 5)] for lon, lat in feature["outline"]],
            "sense": feature["sense"],
            "diameter_km": diameter,
            "ow_min": ow,
        })
    encoded.sort(key=lambda item: (-item["diameter_km"], item["outline"]))
    return {"frame_time": stamp, "features": encoded}


def read_eddies_tile(doc: object) -> dict:
    """Validate an already decoded tile without changing its fields or order."""
    if not isinstance(doc, dict) or doc.keys() != _TILE_KEYS:
        raise EddyTileError("tile must contain exactly frame_time and features")
    stamp = doc["frame_time"]
    message = "frame_time must be an ISO datetime with a Z or +00:00 zone"
    if not isinstance(stamp, str) or not stamp.endswith(("Z", "+00:00")) or ("T" not in stamp and " " not in stamp):
        raise EddyTileError(message)
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise EddyTileError(message) from exc

    features = doc["features"]
    if not isinstance(features, list):
        raise EddyTileError("features must be a list")
    if len(features) > _MAX_EDDIES:
        raise EddyTileError(f"features must contain at most {_MAX_EDDIES} eddies")
    for index, feature in enumerate(features):
        _validate_feature(feature, index)
    return doc
