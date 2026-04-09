import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI
from anthropic import Anthropic


@dataclass
class LLMResult:
    data: Dict[str, Any]
    used_fallback: bool
    provider: str


class LLMProvider:
    def generate_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def extract_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIProvider")
        self.client = OpenAI(api_key=api_key)

    @staticmethod
    def _response_format(schema: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_output",
                "strict": True,
                "schema": schema,
            },
        }

    def generate_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=self._response_format(schema),
            temperature=temperature,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned empty content")
        return json.loads(content)

    def extract_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        return self.generate_json(model, system_prompt, user_prompt, schema, temperature=temperature)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for ClaudeProvider")
        self.client = Anthropic(api_key=api_key)

    def _tool_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": "extract",
            "description": "Return structured JSON that matches the provided schema.",
            "input_schema": schema,
        }

    def _parse_tool_output(self, response) -> Dict[str, Any]:
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        raise ValueError("Claude did not return tool output")

    def generate_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        response = self.client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[self._tool_schema(schema)],
            tool_choice={"type": "tool", "name": "extract"},
        )
        return self._parse_tool_output(response)

    def extract_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        return self.generate_json(model, system_prompt, user_prompt, schema, temperature=temperature)


class LLMRouter:
    def __init__(
        self,
        primary: LLMProvider,
        fallback: Optional[LLMProvider],
        fallback_model: Optional[str] = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.fallback_model = fallback_model

    def generate_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.2,
    ) -> LLMResult:
        try:
            data = self.primary.generate_json(model, system_prompt, user_prompt, schema, temperature=temperature)
            return LLMResult(data=data, used_fallback=False, provider="primary")
        except Exception:
            if not self.fallback:
                raise
            fallback_model = self.fallback_model or model
            data = self.fallback.generate_json(
                fallback_model, system_prompt, user_prompt, schema, temperature=temperature
            )
            return LLMResult(data=data, used_fallback=True, provider="fallback")

    def extract_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        temperature: float = 0.0,
    ) -> LLMResult:
        try:
            data = self.primary.extract_json(model, system_prompt, user_prompt, schema, temperature=temperature)
            return LLMResult(data=data, used_fallback=False, provider="primary")
        except Exception:
            if not self.fallback:
                raise
            fallback_model = self.fallback_model or model
            data = self.fallback.extract_json(
                fallback_model, system_prompt, user_prompt, schema, temperature=temperature
            )
            return LLMResult(data=data, used_fallback=True, provider="fallback")
