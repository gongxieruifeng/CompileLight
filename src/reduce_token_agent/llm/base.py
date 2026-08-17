"""One structured model interface shared by all control-plane LLM stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredUsage:
    stage: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_duration_ns: int | None
    estimated: bool
    attempts: int


@dataclass(frozen=True, slots=True)
class StructuredResult[OutputT]:
    value: OutputT
    usage: StructuredUsage


class StructuredModel(Protocol):
    """LLM may propose typed data but never approve or execute it."""

    def generate_structured(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[OutputT],
    ) -> StructuredResult[OutputT]: ...
