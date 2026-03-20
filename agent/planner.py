import json
from typing import Any, Dict, List, Optional

from agent.llm import LLMRouter
from agent.models import Plan


PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
        },
        "target_urls": {
            "type": "array",
            "items": {"type": "string"},
        },
        "strategy": {"type": "string"},
        "notes": {"type": "string"},
        "max_pages": {"type": "integer"},
    },
    "required": ["search_queries", "target_urls", "strategy"],
    "additionalProperties": False,
}


class Planner:
    def __init__(self, llm: LLMRouter, model: str):
        self.llm = llm
        self.model = model

    def plan(
        self,
        prompt: str,
        urls: Optional[List[str]],
        schema: Optional[Dict[str, Any]],
        strict: bool,
    ) -> Plan:
        system_prompt = (
            "You are an agent planner. Produce a concise execution plan and search queries "
            "to satisfy the user prompt. Return JSON only."
        )
        user_payload = {
            "prompt": prompt,
            "provided_urls": urls or [],
            "strict_constrain_to_urls": strict,
            "schema": schema or {},
        }
        user_prompt = f"Plan the job.\n\nInput:\n{json.dumps(user_payload, indent=2)}"

        result = self.llm.generate_json(
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=PLAN_SCHEMA,
            temperature=0.2,
        )
        return Plan(**result.data)
