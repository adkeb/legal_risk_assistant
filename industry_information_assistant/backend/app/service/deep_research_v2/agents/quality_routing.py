"""Quality-routing agent for the legal-risk workflow."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .artifact_agent import ArtifactAgent
from .workflow_utils import (
    END,
    EVIDENCE_CATALOG,
    LEGAL_ANALYSIS_DRAFT,
    QUALITY_ROUTING,
    ROUTABLE_AGENT_IDS,
    SOURCE_VERIFICATION,
    artifact_id,
    default_scores,
    has_final_ai_note,
    normalize_spaces,
    source_pack_has_load_bearing,
    to_json,
)
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import ResearchPhase, ResearchState, ensure_artifact_state_defaults, get_artifact_writes
from ..prompts.legal_prompts import (
    QUALITY_ROUTING_SYSTEM_PROMPT,
    QUALITY_ROUTING_USER_PROMPT,
    schema_hint,
)


class QualityRoutingAgent(ArtifactAgent):
    artifact_key = "qa_verdict"
    agent_id = QUALITY_ROUTING
    next_agent = END
    system_prompt = QUALITY_ROUTING_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("QualityRoutingAgent", "质量评估与路由 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "质量评估与路由：生成 qa_verdict")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        analysis_draft = get_artifact_writes(state, "analysis_draft")
        user_prompt = QUALITY_ROUTING_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=to_json(scope),
            source_pack_json=to_json(source_pack),
            evidence_matrix_json=to_json(evidence_matrix),
            analysis_draft_json=to_json(analysis_draft),
            schema=schema_hint("qa_verdict"),
        )
        deterministic = self._deterministic_verdict(state)
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.1)
            artifact = self._coerce_qa_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_llm_verdict(artifact)
            artifact = self._merge_hard_gates(artifact, deterministic)
        except Exception as exc:
            self.logger.warning("quality_routing fallback used: %s", exc)
            artifact = deterministic
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "quality_routing", "all artifacts", "qa_verdict ready", duration)
        route = artifact.get("writes", {}).get("route", {})
        state["route_instruction"] = route
        verdict = artifact.get("writes", {}).get("verdict")
        if route.get("next_agent") == END or verdict in {"approved", "approved_with_human_review"}:
            state["phase"] = ResearchPhase.COMPLETED.value
        return self._finalize(state, artifact, f"审查完成，verdict={verdict}，route={route.get('next_agent')}")

    def _coerce_qa_shape(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        writes.setdefault("score_total", 0)
        writes.setdefault("dimension_scores", default_scores(float(writes.get("score_total") or 0)))
        writes["hard_failures"] = [
            normalize_spaces(item.get("message") if isinstance(item, dict) else item)
            for item in (writes.get("hard_failures") or [])
            if normalize_spaces(item.get("message") if isinstance(item, dict) else item)
        ]
        issues = []
        for item in writes.get("issues") or []:
            if isinstance(item, str):
                issues.append({"severity": "major", "type": "quality_issue", "message": item, "route_to": LEGAL_ANALYSIS_DRAFT})
                continue
            if not isinstance(item, dict):
                continue
            severity = item.get("severity") if item.get("severity") in {"critical", "major", "minor"} else "major"
            route_to = item.get("route_to") if item.get("route_to") in ROUTABLE_AGENT_IDS else LEGAL_ANALYSIS_DRAFT
            message = item.get("message") or item.get("description") or item.get("issue") or "质量问题"
            issues.append({
                "severity": severity,
                "type": item.get("type") or item.get("issue_type") or "quality_issue",
                "message": normalize_spaces(message),
                "route_to": route_to,
            })
        writes["issues"] = issues
        route = writes.get("route") if isinstance(writes.get("route"), dict) else {}
        if route.get("next_agent") not in ROUTABLE_AGENT_IDS | {END}:
            route["next_agent"] = issues[0]["route_to"] if issues else END
        route.setdefault("instruction", "通过。" if route.get("next_agent") == END else "按质量问题返工。")
        writes["route"] = route
        writes.setdefault("verdict", "approved" if route["next_agent"] == END else "needs_revision")
        return artifact

    def _normalize_llm_verdict(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        verdict = writes.get("verdict")
        if verdict not in {"approved", "approved_with_human_review", "needs_research", "needs_evidence_rebuild", "needs_revision", "rejected"}:
            try:
                score = float(writes.get("score_total") or 0)
            except (TypeError, ValueError):
                score = 0.0
            verdict = "approved" if score >= 85 else "approved_with_human_review" if score >= 75 else "needs_revision"
            writes["verdict"] = verdict
        route = writes.get("route") if isinstance(writes.get("route"), dict) else {}
        if verdict in {"approved", "approved_with_human_review"}:
            route["next_agent"] = END
        elif route.get("next_agent") not in ROUTABLE_AGENT_IDS:
            issue_routes = [issue.get("route_to") for issue in writes.get("issues") or [] if isinstance(issue, dict)]
            route["next_agent"] = next((item for item in issue_routes if item in ROUTABLE_AGENT_IDS), LEGAL_ANALYSIS_DRAFT)
        route.setdefault("instruction", "通过。" if route.get("next_agent") == END else "按质量评估意见返工。")
        writes["route"] = route
        artifact.setdefault("handoff", {})["next_agent"] = route["next_agent"]
        return validate_artifact(self.artifact_key, artifact)

    def _deterministic_verdict(self, state: Dict[str, Any]) -> Dict[str, Any]:
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        analysis = get_artifact_writes(state, "analysis_draft")
        report = analysis.get("report_markdown", "")
        source_ids = {
            source.get("source_id")
            for source in source_pack.get("issue_sources", [])
            if isinstance(source, dict) and source.get("source_id")
        }
        evidence_ids = {
            item.get("evidence_id")
            for item in evidence_matrix.get("evidence_items", [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        failures: List[str] = []
        issues: List[Dict[str, str]] = []

        def add_failure(kind: str, message: str, route_to: str) -> None:
            failures.append(message)
            issues.append({"severity": "critical", "type": kind, "message": message, "route_to": route_to})

        if not has_final_ai_note(report):
            add_failure("missing_final_ai_note", "报告缺少唯一固定结尾：AI生成，仅供参考。", LEGAL_ANALYSIS_DRAFT)

        if not source_pack_has_load_bearing(source_pack):
            add_failure(
                "source_unavailable",
                "source_pack 未包含可承载核心法律结论的法源；报告只能作为待法源核验的临时草稿，不能批准。",
                SOURCE_VERIFICATION,
            )

        used_source_ids = set()
        used_evidence_ids = set()
        for item in analysis.get("issue_analysis", []) or []:
            if isinstance(item, dict):
                used_source_ids.update(item.get("source_ids") or [])
                used_evidence_ids.update(item.get("evidence_ids") or [])
        for item in analysis.get("risk_register", []) or []:
            if isinstance(item, dict):
                used_source_ids.update(item.get("source_ids") or [])
                used_evidence_ids.update(item.get("evidence_ids") or [])

        outside_sources = [source_id for source_id in used_source_ids if source_id not in source_ids]
        outside_evidence = [evidence_id for evidence_id in used_evidence_ids if evidence_id not in evidence_ids]
        if outside_sources:
            add_failure("outside_source", f"报告使用 source_pack 外来源：{', '.join(outside_sources)}", SOURCE_VERIFICATION)
        if outside_evidence:
            add_failure("outside_evidence", f"报告使用 evidence_matrix 外证据：{', '.join(outside_evidence)}", EVIDENCE_CATALOG)

        next_agent = issues[0]["route_to"] if issues else END
        if next_agent == SOURCE_VERIFICATION:
            verdict = "needs_research"
        elif next_agent == EVIDENCE_CATALOG:
            verdict = "needs_evidence_rebuild"
        elif next_agent == LEGAL_ANALYSIS_DRAFT:
            verdict = "needs_revision"
        else:
            verdict = "approved"
        score = 0.0 if failures else 100.0
        return make_envelope(
            agent=QUALITY_ROUTING,
            artifact_id=artifact_id(state.get("session_id", ""), "qa_verdict", state.get("iteration", 0)),
            writes={
                "score_total": score,
                "dimension_scores": default_scores(score),
                "hard_failures": failures,
                "issues": issues,
                "verdict": verdict,
                "route": {"next_agent": next_agent, "instruction": "通过。" if next_agent == END else "修复结构性硬失败。"},
            },
            next_agent=next_agent,
            reason="完成最小结构护栏检查。",
            status="hard_fail" if failures else "ok",
            confidence=0.9,
        )

    def _merge_hard_gates(self, llm_artifact: Dict[str, Any], deterministic: Dict[str, Any]) -> Dict[str, Any]:
        if deterministic.get("writes", {}).get("hard_failures"):
            return deterministic
        return llm_artifact
