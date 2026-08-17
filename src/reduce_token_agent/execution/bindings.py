"""Restricted JSON-pointer bindings and small JSON-Schema shape checks."""

from __future__ import annotations

from typing import Any


class BindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def resolve_step_inputs(
    *,
    step: dict[str, Any],
    task_context: dict[str, Any],
    outputs: dict[str, dict[str, Any]],
    sample_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Resolve only compiler-approved pointers; otherwise use a local fixture."""
    bindings = step.get("input_bindings", {})
    if bindings:
        payload = dict(sample_payload)
        root = {"task": task_context, "context": task_context, "steps": {}}
        root["steps"] = {
            step_id: {"output": output}
            for step_id, output in outputs.items()
        }
        for field, pointer in bindings.items():
            payload[str(field)] = resolve_pointer(root, str(pointer))
        return payload, "BLUEPRINT_BINDINGS_WITH_SAMPLE_DEFAULTS"

    if step.get("step_type") == "VALIDATOR":
        dependencies = [str(item) for item in step.get("depends_on", [])]
        if not dependencies:
            raise BindingError(
                "VALIDATOR_INPUT_MISSING",
                "validator step requires a dependency output",
            )
        dependency = dependencies[-1]
        if dependency not in outputs:
            raise BindingError(
                "DEPENDENCY_OUTPUT_MISSING",
                f"no output for validator dependency {dependency}",
            )
        return {"payload": outputs[dependency]}, "DEPENDENCY_OUTPUT"

    payload = dict(sample_payload)
    entities = task_context.get("entities", {})
    if isinstance(entities, dict):
        for key in set(payload) & set(entities):
            payload[key] = entities[key]
    return payload, "ASSET_SAMPLE_WITH_TASK_ENTITY_OVERRIDES"


def resolve_pointer(root: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith(("/task/", "/context/", "/steps/")):
        raise BindingError("INPUT_BINDING_INVALID", f"pointer is not allowed: {pointer}")
    current: Any = root
    for raw_segment in pointer.removeprefix("/").split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index < len(current):
                current = current[index]
                continue
        raise BindingError(
            "INPUT_BINDING_UNRESOLVED",
            f"pointer segment is missing: {pointer}",
        )
    return current


def validate_schema_shape(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate the bounded subset used by local Registry contracts."""
    if schema.get("type") == "object" and not isinstance(payload, dict):
        raise BindingError("SCHEMA_TYPE_MISMATCH", "payload must be an object")
    missing = [
        str(field)
        for field in schema.get("required", [])
        if field not in payload
    ]
    if missing:
        raise BindingError(
            "SCHEMA_REQUIRED_FIELD_MISSING",
            ", ".join(missing),
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return
    for field, value in payload.items():
        rule = properties.get(field)
        if not isinstance(rule, dict) or "type" not in rule:
            continue
        expected = str(rule["type"])
        if not _matches_type(value, expected):
            raise BindingError(
                "SCHEMA_TYPE_MISMATCH",
                f"{field} must be {expected}",
            )


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True
