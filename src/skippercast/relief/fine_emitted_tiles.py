"""Offline QA for caller-supplied emitted fine-zoom XYZ tiles."""
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral
from os import PathLike

from skippercast.relief import fine_proof
from skippercast.relief.pmtiles_v3 import Tile


@dataclass(frozen=True)
class FineTileAudit:
    """Disjoint groups of unique fine tile IDs, sorted as (z, x, y)."""

    certified: tuple[Tile, ...]
    missing_proof: tuple[Tile, ...]  # No raster supplied at this zoom.
    uncertified: tuple[Tile, ...]  # Matching raster exists, but tile did not pass.

    @property
    def passed(self) -> bool:
        return not (self.missing_proof or self.uncertified)


def audit_emitted_tiles(
    emitted: Sequence[Sequence[int]], proof_paths: Sequence[str | PathLike[str]],
) -> FineTileAudit:
    """Check only emitted (z, x, y) IDs against one or two local proof rasters.

    Validate all IDs, then ignore z0–15. Match proof by its decoded zoom, never
    by path order or by reusing another zoom. A tile outside a matching raster's
    rectangle is uncertified. Invalid or unreadable supplied proof raises
    ``fine_proof.FineProofError`` rather than being reported as absent.
    """
    fine_tiles: set[Tile] = set()
    for index, tile in enumerate(emitted):
        if (not isinstance(tile, Sequence) or len(tile) != 3
                or not all(isinstance(n, Integral) and not isinstance(n, bool) for n in tile)):
            raise ValueError(f'emitted tile at index {index} must be an integer (z, x, y) triple')
        z, x, y = map(int, tile)
        if not 0 <= z <= 17 or not (0 <= x < (1 << z) and 0 <= y < (1 << z)):
            raise ValueError(f'emitted tile at index {index} is outside the supported XYZ grid: {(z, x, y)}')
        if z >= 16:
            fine_tiles.add((z, x, y))

    if not 1 <= len(proof_paths) <= 2:
        raise ValueError('supply one or two fine-proof raster paths')
    proofs: dict[int, fine_proof.FineProof] = {}
    for path in proof_paths:
        proof = fine_proof.read(path)
        if proof.zoom in proofs:
            raise ValueError(f'multiple fine-proof rasters for z{proof.zoom}')
        proofs[proof.zoom] = proof

    certified, missing, uncertified = [], [], []
    for tile in sorted(fine_tiles):
        proof = proofs.get(tile[0])
        if proof is None:
            missing.append(tile)
        elif proof.certified(*tile):
            certified.append(tile)
        else:
            uncertified.append(tile)
    return FineTileAudit(tuple(certified), tuple(missing), tuple(uncertified))
