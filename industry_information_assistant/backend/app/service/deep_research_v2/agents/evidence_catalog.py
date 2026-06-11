"""Evidence-catalog agent for the legal-risk workflow."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .artifact_agent import ArtifactAgent
from .workflow_utils import (
    EVIDENCE_CATALOG,
    LEGAL_ANALYSIS_DRAFT,
    artifact_id,
    contains_unread_placeholder,
    dedupe_strings,
    material_manifest,
    material_text,
    normalize_spaces,
    to_json,
)
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import ResearchState, ensure_artifact_state_defaults, get_artifact_writes
from ..prompts.legal_prompts import (
    EVIDENCE_CATALOG_SYSTEM_PROMPT,
    EVIDENCE_CATALOG_USER_PROMPT,
    schema_hint,
)


class EvidenceCatalogAgent(ArtifactAgent):
    artifact_key = "evidence_matrix"
    agent_id = EVIDENCE_CATALOG
    next_agent = LEGAL_ANALYSIS_DRAFT
    system_prompt = EVIDENCE_CATALOG_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("EvidenceCatalogAgent", "事实证据编目 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "事实证据编目：生成 evidence_matrix")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        user_prompt = EVIDENCE_CATALOG_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=to_json(scope),
            source_pack_json=to_json(source_pack),
            materials_text_or_extracts=material_text(state),
            materials_manifest=to_json(material_manifest(state)),
            schema=schema_hint("evidence_matrix"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.15)
            artifact = self._coerce_evidence_matrix_shape(state, artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
        except Exception as exc:
            self.logger.warning("evidence_catalog fallback used: %s", exc)
            artifact = self._fallback(state)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "evidence_catalog", "scope/source_pack/materials", "evidence_matrix ready", duration)
        return self._finalize(state, artifact, "已完成事实、证据、材料读取状态和 issue 证据矩阵")

    def _coerce_evidence_matrix_shape(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        writes = artifact.setdefault("writes", {})
        for index, evidence in enumerate(writes.get("evidence_items") or [], start=1):
            if not isinstance(evidence, dict):
                continue
            evidence.setdefault("evidence_id", f"E{index:02d}")
            evidence.setdefault("source_type", "other")
            evidence.setdefault("locator", "")
            evidence.setdefault("excerpt", "")
            if evidence.get("read_status") not in {"read", "unread", "partial"}:
                evidence["read_status"] = "partial"
        known_evidence_ids = {
            item.get("evidence_id")
            for item in writes.get("evidence_items") or []
            if isinstance(item, dict) and item.get("evidence_id")
        }
        fallback_evidence = next(iter(known_evidence_ids), "")
        for index, fact in enumerate(writes.get("facts") or [], start=1):
            if not isinstance(fact, dict):
                continue
            fact.setdefault("fact_id", f"F{index:02d}")
            fact.setdefault("statement", "")
            fact["evidence_ids"] = [
                evidence_id for evidence_id in (fact.get("evidence_ids") or []) if evidence_id in known_evidence_ids
            ] or ([fallback_evidence] if fallback_evidence else [])
            if fact.get("status") not in {"verified", "partially_verified", "assumed"}:
                fact["status"] = "partially_verified"
        for issue in writes.get("issue_evidence_matrix") or []:
            if not isinstance(issue, dict):
                continue
            issue.setdefault("issue_id", "I01")
            issue["supporting_evidence"] = [
                evidence_id for evidence_id in (issue.get("supporting_evidence") or []) if evidence_id in known_evidence_ids
            ]
            issue["conflicting_evidence"] = [
                evidence_id for evidence_id in (issue.get("conflicting_evidence") or []) if evidence_id in known_evidence_ids
            ]
            issue["missing_evidence"] = dedupe_strings(issue.get("missing_evidence") or [], limit=20)
        for material in writes.get("material_read_status") or []:
            if not isinstance(material, dict):
                continue
            material.setdefault("material_id", "MATERIAL_USER_QUERY")
            if material.get("status") not in {"read", "partial", "material_unread"}:
                material["status"] = "partial"
            material.setdefault("reason", "")
        writes["missing_materials"] = self._merge_missing_materials(scope, writes)
        return artifact

    def _gap_with_impact(self, gap: Any) -> str:
        text = normalize_spaces(gap)
        if not text:
            return ""
        if "影响" in text and ("结论" in text or "责任" in text or "风险" in text):
            return text
        return f"{text}：影响相关结论的确定性、责任范围、风险等级或可执行处理路径。"

    def _merge_missing_materials(self, scope: Dict[str, Any], writes: Dict[str, Any]) -> List[str]:
        gaps: List[str] = []
        gaps.extend(writes.get("missing_materials") or [])
        gaps.extend(scope.get("facts_missing") or [])
        for issue in writes.get("issue_evidence_matrix") or []:
            if isinstance(issue, dict):
                gaps.extend(issue.get("missing_evidence") or [])
        return dedupe_strings([self._gap_with_impact(item) for item in gaps], limit=30)

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        query = state.get("query", "")
        unread = contains_unread_placeholder(query)
        evidence_items = [{
            "evidence_id": "E01",
            "source_type": "user_material",
            "locator": "用户问题",
            "excerpt": query[:1000],
            "read_status": "partial" if unread else "read",
        }]
        facts = []
        for index, fact in enumerate((scope.get("facts_known") or [query])[:8], start=1):
            facts.append({
                "fact_id": f"F{index:02d}",
                "statement": str(fact),
                "evidence_ids": ["E01"],
                "status": "partially_verified",
            })
        issue_matrix = []
        missing: List[str] = list(scope.get("facts_missing") or [])
        for issue in scope.get("issue_tree", []) or [{"issue_id": "I01", "evidence_needed": []}]:
            needed = list(issue.get("evidence_needed") or []) if isinstance(issue, dict) else []
            missing.extend(needed)
            issue_matrix.append({
                "issue_id": issue.get("issue_id", "I01") if isinstance(issue, dict) else "I01",
                "supporting_evidence": ["E01"],
                "conflicting_evidence": [],
                "missing_evidence": needed,
            })
        if unread:
            missing.append("存在附件占位文本，正文未解析。")
        writes = {
            "facts": facts,
            "evidence_items": evidence_items,
            "issue_evidence_matrix": issue_matrix,
            "material_read_status": [{
                "material_id": "MATERIAL_USER_QUERY",
                "status": "material_unread" if unread else "read",
                "reason": "检测到附件占位文本，不能视为已读取正文。" if unread else "",
            }],
            "missing_materials": dedupe_strings([self._gap_with_impact(item) for item in missing], limit=30),
        }
        return make_envelope(
            agent=EVIDENCE_CATALOG,
            artifact_id=artifact_id(state.get("session_id", ""), "evidence_matrix", state.get("iteration", 0)),
            writes=writes,
            next_agent=LEGAL_ANALYSIS_DRAFT,
            reason="完成事实证据矩阵；材料缺口已显式列出。",
            status="needs_more_facts" if writes["missing_materials"] else "ok",
            confidence=0.63,
        )
