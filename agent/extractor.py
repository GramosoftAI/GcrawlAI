import json
from typing import Any, Dict, Tuple

import jsonschema

from agent.llm import LLMResult, LLMRouter


class ExtractionError(Exception):
    pass


def ensure_strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    if schema.get("type") == "object":
        schema.setdefault("additionalProperties", False)
        properties = schema.get("properties", {})
        if properties and "required" not in schema:
            schema["required"] = list(properties.keys())
        for key, value in properties.items():
            properties[key] = ensure_strict_schema(value) if isinstance(value, dict) else value
        schema["properties"] = properties
    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            schema["items"] = ensure_strict_schema(items)
    return schema


def validate_schema(schema: Dict[str, Any]) -> None:
    jsonschema.Draft7Validator.check_schema(schema)


def validate_payload(schema: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        jsonschema.validate(instance=payload, schema=schema)
        return True, ""
    except jsonschema.ValidationError as exc:
        return False, str(exc)


class Extractor:
    def __init__(self, llm: LLMRouter, model: str, max_retries: int = 2):
        self.llm = llm
        self.model = model
        self.max_retries = max_retries

    def extract(
        self,
        schema: Dict[str, Any],
        content: str,
        context: Dict[str, Any],
    ) -> LLMResult:
        strict_schema = ensure_strict_schema(schema)
        validate_schema(strict_schema)

        system_prompt = (
            "You are a precise data extraction engine. Return JSON that strictly "
            "matches the provided schema. Do not add extra keys."
        )
        base_prompt = {
            "context": context,
            "content": content,
        }

        last_error = None
        for attempt in range(1, self.max_retries + 2):
            user_prompt = (
                f"Extract the required fields from the content below. "
                f"Attempt {attempt}.\n\n"
                f"{json.dumps(base_prompt, ensure_ascii=False)[:8000]}"
            )
            result = self.llm.extract_json(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=strict_schema,
                temperature=0.0,
            )
            is_valid, error = validate_payload(strict_schema, result.data)
            if is_valid:
                return result
            last_error = error
            base_prompt["validation_error"] = error

        raise ExtractionError(f"Schema validation failed: {last_error}")
