"""Scope-definition agent for the legal-risk workflow."""

from __future__ import annotations

import re
import time
from typing import Any, Dict

from .artifact_agent import ArtifactAgent
from .workflow_utils import (
    SCOPE_DEFINITION,
    SOURCE_VERIFICATION,
    artifact_id,
    clamp_priority,
    dedupe_strings,
    material_manifest,
    normalize_spaces,
    to_json,
)
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import ResearchState, ensure_artifact_state_defaults
from ..prompts.legal_prompts import (
    SCOPE_DEFINITION_SYSTEM_PROMPT,
    SCOPE_DEFINITION_USER_PROMPT,
    schema_hint,
)


class ScopeDefinitionAgent(ArtifactAgent):
    artifact_key = "scope_brief"
    agent_id = SCOPE_DEFINITION
    next_agent = SOURCE_VERIFICATION
    system_prompt = SCOPE_DEFINITION_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("ScopeDefinitionAgent", "立项定界 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "立项定界：生成 scope_brief")
        user_prompt = SCOPE_DEFINITION_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            user_query=state.get("query", ""),
            materials_manifest=to_json(material_manifest(state)),
            interactive_mode="batch",
            schema=schema_hint("scope_brief"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.2)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_scope_artifact(artifact)
        except Exception as exc:
            self.logger.warning("scope_definition fallback used: %s", exc)
            artifact = self._fallback(state)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "scope_definition", state.get("query", "")[:120], "scope_brief ready", duration)
        return self._finalize(state, artifact, "已完成法域、问题树、事实缺口和法源目标定界")

    def _normalize_scope_artifact(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        task_type = normalize_spaces(writes.get("task_type") or "general_legal_research")
        task_type = re.sub(r"[^0-9a-zA-Z_]+", "_", task_type.lower()).strip("_") or "general_legal_research"
        writes["task_type"] = task_type[:64]
        writes["source_targets"] = dedupe_strings(writes.get("source_targets") or [], limit=12)
        for issue in writes.get("issue_tree") or []:
            if not isinstance(issue, dict):
                continue
            issue["priority"] = clamp_priority(issue.get("priority"), default="P1")
            issue["evidence_needed"] = dedupe_strings(issue.get("evidence_needed") or [], limit=10)
        return validate_artifact(self.artifact_key, artifact)

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = normalize_spaces(state.get("query", ""))
        target = query[:48] or "法律风险"
        writes = {
            "task_type": "general_legal_research",
            "jurisdiction": {
                "primary": "中国大陆",
                "others": [],
                "status": "assumed",
                "jurisdiction_candidates": ["中国大陆"],
                "why_unknown": "",
            },
            "issue_tree": [{
                "issue_id": "I01",
                "question": target,
                "priority": "P0",
                "evidence_needed": ["用户陈述对应的原始材料", "相对方主张或沟通记录"],
            }],
            "facts_known": [query],
            "facts_assumed": ["若未特别说明，默认适用中国大陆法域。"],
            "facts_missing": ["完整原始材料", "关键时间线", "相对方主张", "损害或后果证明"],
            "source_targets": dedupe_strings([target, "法律责任", "证据规则"], limit=6),
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        }
        return make_envelope(
            agent=SCOPE_DEFINITION,
            artifact_id=artifact_id(state.get("session_id", ""), "scope_brief", state.get("iteration", 0)),
            writes=writes,
            next_agent=SOURCE_VERIFICATION,
            reason="完成最小可执行研究计划。",
            confidence=0.62,
        )
