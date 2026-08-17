"""Small-scale NumPy cosine ranking over stored normalized vectors."""

from __future__ import annotations

import numpy as np


def encode_vector(vector: np.ndarray) -> bytes:
    """Serialize one float32 vector for SQLite."""
    return np.asarray(vector, dtype=np.float32).tobytes(order="C")


def decode_vector(blob: bytes, dimensions: int) -> np.ndarray:
    """Decode and validate one stored vector."""
    vector = np.frombuffer(blob, dtype=np.float32)
    if vector.shape != (dimensions,):
        raise ValueError("stored embedding dimension mismatch")
    return vector


def cosine_ranking(
    query_vector: np.ndarray,
    vectors: list[tuple[str, np.ndarray]],
) -> list[tuple[str, float]]:
    """Rank normalized document vectors by cosine similarity."""
    if not vectors:
        return []
    query = np.asarray(query_vector, dtype=np.float32)
    norm = float(np.linalg.norm(query))
    if norm == 0:
        return []
    query = query / norm
    scored = [
        (asset_ref, float(np.dot(query, vector)))
        for asset_ref, vector in vectors
    ]
    return sorted(scored, key=lambda item: (-item[1], item[0]))
