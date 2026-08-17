"""Embedding providers used by the local Dense Retrieval channel."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Protocol, cast

import numpy as np


class EmbeddingProvider(Protocol):
    """Minimal batch embedding contract."""

    @property
    def model_name(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class OllamaEmbeddingProvider:
    """Use the local Ollama embedding endpoint with normalized vectors."""

    def __init__(
        self,
        *,
        model: str = "qwen3-embedding:0.6b",
        host: str = "http://127.0.0.1:11434",
    ) -> None:
        import ollama

        self._model = model
        self._client = ollama.Client(host=host)

    @property
    def model_name(self) -> str:
        return self._model

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a non-empty batch and L2-normalize it for cosine search."""
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        response = self._client.embed(model=self._model, input=list(texts))
        vectors = np.asarray(response["embeddings"], dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise RuntimeError("Ollama returned an invalid embedding matrix")
        return _normalize(vectors)


class HashingEmbeddingProvider:
    """Deterministic test provider; never used as a production fallback."""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 32:
            raise ValueError("test embedding dimensions must be at least 32")
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return f"test-hashing-{self._dimensions}"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _semantic_tokens(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                slot = int.from_bytes(digest[:4], "big") % self._dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vectors[row, slot] += sign
        return _normalize(vectors)


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return cast(np.ndarray, vectors / norms)


def _semantic_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
        tokens.extend(sequence[index : index + 3] for index in range(len(sequence) - 2))
    return tokens
