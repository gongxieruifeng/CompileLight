"""Ollama structured-output adapter for qwen3.5:9b control proposals."""

from __future__ import annotations

import json
from typing import Any

import ollama
from pydantic import ValidationError

from reduce_token_agent.llm.base import (
    OutputT,
    StructuredModel,
    StructuredResult,
    StructuredUsage,
)


class StructuredModelError(RuntimeError):
    """Typed boundary error; callers route it without parsing model prose."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class OllamaStructuredModel(StructuredModel):
    """Generate Pydantic-validated JSON with at most one format repair."""

    def __init__(
        self,
        *,
        model: str = "qwen3.5:9b",
        host: str = "http://127.0.0.1:11434",
        max_format_repairs: int = 1,
    ) -> None:
        self.model = model
        self.client = ollama.Client(host=host)
        self.max_format_repairs = max_format_repairs

    def generate_structured(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[OutputT],
    ) -> StructuredResult[OutputT]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        last_error = ""
        for attempt in range(1, self.max_format_repairs + 2):
            response = self.client.chat(
                model=self.model,
                messages=messages,
                format=output_model.model_json_schema(),
                options={"temperature": 0},
                think=False,
            )
            if not isinstance(response, ollama.ChatResponse):
                raise StructuredModelError(
                    "MODEL_OUTPUT_INVALID",
                    "streaming response is not supported by the control plane",
                )
            content = response.message.content or ""
            try:
                value = output_model.model_validate_json(content)
                return StructuredResult(
                    value=value,
                    usage=StructuredUsage(
                        stage=stage,
                        model=self.model,
                        input_tokens=response.prompt_eval_count,
                        output_tokens=response.eval_count,
                        total_duration_ns=response.total_duration,
                        estimated=False,
                        attempts=attempt,
                    ),
                )
            except ValidationError as exc:
                last_error = str(exc)
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "只修复 JSON 结构，不改变业务目标。校验错误："
                                + last_error[:1200]
                            ),
                        },
                    ]
                )
        raise StructuredModelError(
            "MODEL_OUTPUT_INVALID",
            last_error or "model did not return valid structured output",
        )
