"""Base class for legal artifact agents."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseAgent
from .workflow_utils import END
from ..artifact_schemas import validate_artifact
from ..state import ResearchState, put_artifact
from ..prompts.legal_prompts import ARTIFACT_ENVELOPE_RULE, LEGAL_WORKFLOW_GLOBAL_PROMPT


class ArtifactAgent(BaseAgent):
    artifact_key = ""
    agent_id = ""
    next_agent = END
    system_prompt = ""

    def _system_prompt(self) -> str:
        return "\n\n".join([LEGAL_WORKFLOW_GLOBAL_PROMPT, ARTIFACT_ENVELOPE_RULE, self.system_prompt])

    async def _call_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
        try:
            response = await self.call_llm(system_prompt, user_prompt, json_mode=True, temperature=temperature)
        except Exception as first_error:
            self.logger.warning("JSON-mode LLM call failed, retrying without response_format: %s", first_error)
            try:
                response = await self.call_llm(system_prompt, user_prompt, json_mode=False, temperature=temperature)
            except Exception:
                raise first_error
        return self.parse_json_response(response)

    def _finalize(self, state: ResearchState, artifact: Dict[str, Any], summary: str) -> ResearchState:
        artifact.setdefault("meta", {})["agent"] = self.agent_id
        handoff = artifact.setdefault("handoff", {})
        if not handoff.get("next_agent"):
            handoff["next_agent"] = self.next_agent
        handoff.setdefault("reason", summary)
        artifact = validate_artifact(self.artifact_key, artifact)
        put_artifact(state, self.artifact_key, artifact)
        state["current_agent"] = self.agent_id
        self.add_message(
            state,
            "artifact_ready",
            {
                "artifact": self.artifact_key,
                "agent_id": self.agent_id,
                "status": artifact.get("meta", {}).get("status"),
                "summary": summary,
            },
        )
        return state
