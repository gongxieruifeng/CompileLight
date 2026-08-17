"""Local model adapters."""

from reduce_token_agent.llm.base import StructuredModel, StructuredResult
from reduce_token_agent.llm.embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from reduce_token_agent.llm.ollama_client import OllamaStructuredModel

__all__ = [
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OllamaStructuredModel",
    "StructuredModel",
    "StructuredResult",
]
