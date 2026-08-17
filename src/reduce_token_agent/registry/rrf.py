"""Reciprocal-rank fusion for independent sparse and dense channels."""

from __future__ import annotations

from collections.abc import Mapping


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    rank_constant: int = 60,
) -> dict[str, float]:
    """Fuse ranked reference lists without comparing channel score scales."""
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, asset_ref in enumerate(ranking, start=1):
            fused[asset_ref] = fused.get(asset_ref, 0.0) + 1.0 / (
                rank_constant + rank
            )
    return fused


def ranks_by_ref(ranking: list[str]) -> Mapping[str, int]:
    """Return stable one-based ranks for provenance."""
    return {asset_ref: rank for rank, asset_ref in enumerate(ranking, start=1)}
