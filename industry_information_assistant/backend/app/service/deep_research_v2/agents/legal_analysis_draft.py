"""Legal-analysis and report-drafting agent."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .artifact_agent import ArtifactAgent
from .workflow_utils import (
    LEGAL_ANALYSIS_DRAFT,
    QUALITY_ROUTING,
    artifact_id,
    clamp_priority,
    dedupe_strings,
    ensure_final_ai_note,
    normalize_spaces,
    source_pack_has_load_bearing,
    strip_internal_report_markers,
    to_json,
)
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import ResearchState, ensure_artifact_state_defaults, get_artifact_writes
from ..prompts.legal_prompts import (
    LEGAL_ANALYSIS_DRAFT_SYSTEM_PROMPT,
    LEGAL_ANALYSIS_DRAFT_USER_PROMPT,
    schema_hint,
)


class LegalAnalysisDraftAgent(ArtifactAgent):
    artifact_key = "analysis_draft"
    agent_id = LEGAL_ANALYSIS_DRAFT
    next_agent = QUALITY_ROUTING
    system_prompt = LEGAL_ANALYSIS_DRAFT_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("LegalAnalysisDraftAgent", "法律分析与报告起草 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "法律分析与报告起草：生成 analysis_draft")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        user_prompt = LEGAL_ANALYSIS_DRAFT_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=to_json(scope),
            source_pack_json=to_json(source_pack),
            evidence_matrix_json=to_json(evidence_matrix),
            schema=schema_hint("analysis_draft"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.25)
            artifact = self._coerce_analysis_draft_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_analysis_artifact(state, artifact)
            artifact = self._apply_source_availability_mode(state, artifact)
        except Exception as exc:
            self.logger.warning("legal_analysis_draft fallback used: %s", exc)
            artifact = self._fallback(state)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "legal_analysis_draft", "scope/source/evidence", "analysis_draft ready", duration)
        state = self._finalize(state, artifact, "已完成逐项分析、风险登记、行动方案和 Markdown 报告")
        self.add_message(
            state,
            "report_draft",
            {
                "content": artifact["writes"].get("report_markdown", ""),
                "word_count": len(artifact["writes"].get("report_markdown", "")),
            },
        )
        return state

    def _coerce_analysis_draft_shape(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        if "writes" not in artifact and any(
            key in artifact for key in {"issue_analysis", "risk_register", "action_plan", "report_markdown"}
        ):
            artifact = {"writes": artifact}
        writes = artifact.setdefault("writes", {})
        writes.setdefault("issue_analysis", [])
        writes.setdefault("risk_register", [])
        writes.setdefault("action_plan", [])
        writes.setdefault("report_markdown", "")
        writes.setdefault("citation_index", [])
        writes.setdefault("human_review", {"required": False, "reasons": []})
        for index, item in enumerate(writes.get("issue_analysis") or [], start=1):
            if not isinstance(item, dict):
                continue
            item.setdefault("issue_id", f"I{index:02d}")
            item.setdefault("conclusion", "待形成结论")
            item.setdefault("reasoning", "")
            item.setdefault("source_ids", [])
            item.setdefault("evidence_ids", [])
            if item.get("certainty") not in {"high", "medium", "low", "pending_verification"}:
                item["certainty"] = "medium"
        for index, item in enumerate(writes.get("risk_register") or [], start=1):
            if not isinstance(item, dict):
                continue
            item.setdefault("risk_id", f"R{index:02d}")
            item.setdefault("title", item.get("conclusion") or "法律风险")
            if item.get("level") not in {"critical", "high", "medium", "low", "note"}:
                item["level"] = "note"
            item["priority"] = clamp_priority(item.get("priority"), default="P1")
            item.setdefault("source_ids", [])
            item.setdefault("evidence_ids", [])
        for index, item in enumerate(writes.get("action_plan") or [], start=1):
            if not isinstance(item, dict):
                continue
            item.setdefault("action_id", f"ACT{index:02d}")
            item["priority"] = clamp_priority(item.get("priority"), default="P1")
            item.setdefault("owner", "用户")
            item.setdefault("description", "")
            item.setdefault("depends_on", [])
        review = writes.get("human_review")
        if not isinstance(review, dict):
            writes["human_review"] = {"required": False, "reasons": []}
        else:
            writes["human_review"] = {
                "required": bool(review.get("required")),
                "reasons": dedupe_strings(review.get("reasons") or [], limit=20),
            }
        return artifact

    def _normalize_analysis_artifact(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        writes = artifact.setdefault("writes", {})
        valid_evidence_ids = {
            item.get("evidence_id")
            for item in evidence_matrix.get("evidence_items", [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        fact_id_to_evidence_ids: Dict[str, List[str]] = {}
        for fact in evidence_matrix.get("facts", []) or []:
            if not isinstance(fact, dict) or not fact.get("fact_id"):
                continue
            mapped = [evidence_id for evidence_id in (fact.get("evidence_ids") or []) if evidence_id in valid_evidence_ids]
            if mapped:
                fact_id_to_evidence_ids[fact["fact_id"]] = mapped
        fallback_evidence_ids = list(valid_evidence_ids)[:1]

        def clean_evidence_ids(raw_ids: List[str]) -> List[str]:
            cleaned: List[str] = []
            for raw_id in raw_ids or []:
                candidates = [raw_id] if raw_id in valid_evidence_ids else fact_id_to_evidence_ids.get(str(raw_id), [])
                for evidence_id in candidates:
                    if evidence_id in valid_evidence_ids and evidence_id not in cleaned:
                        cleaned.append(evidence_id)
            return cleaned or list(fallback_evidence_ids)

        for item in writes.get("issue_analysis") or []:
            if isinstance(item, dict):
                item["evidence_ids"] = clean_evidence_ids(item.get("evidence_ids") or [])
        for item in writes.get("risk_register") or []:
            if isinstance(item, dict):
                item["evidence_ids"] = clean_evidence_ids(item.get("evidence_ids") or [])
        writes["report_markdown"] = ensure_final_ai_note(strip_internal_report_markers(writes.get("report_markdown", "")))
        return validate_artifact(self.artifact_key, artifact)

    def _apply_source_availability_mode(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        source_pack = get_artifact_writes(state, "source_pack")
        if source_pack_has_load_bearing(source_pack):
            return validate_artifact(self.artifact_key, artifact)

        writes = artifact.setdefault("writes", {})
        for item in writes.get("issue_analysis") or []:
            if isinstance(item, dict):
                item["source_ids"] = []
                item["certainty"] = "pending_verification"
                item["conclusion"] = self._prefix_pending(item.get("conclusion"))
        for item in writes.get("risk_register") or []:
            if isinstance(item, dict):
                item["source_ids"] = []
                item["level"] = "note"
                item["title"] = self._prefix_pending(item.get("title"))
        review = writes.get("human_review") if isinstance(writes.get("human_review"), dict) else {"required": True, "reasons": []}
        reasons = list(review.get("reasons") or [])
        reasons.extend(source_pack.get("unresolved_source_gaps") or [])
        writes["human_review"] = {
            "required": True,
            "reasons": dedupe_strings(reasons or ["未取得可承载核心法律结论的法源。"], limit=20),
        }
        writes["report_markdown"] = self._build_source_unavailable_report(state, writes)
        artifact.setdefault("meta", {})["status"] = "needs_primary_recheck"
        artifact.setdefault("meta", {})["confidence"] = min(float(artifact.get("meta", {}).get("confidence") or 0.35), 0.35)
        artifact.setdefault("handoff", {})["reason"] = "未取得可承载法源，只能生成待法源核验的临时风险梳理草稿。"
        return validate_artifact(self.artifact_key, artifact)

    def _prefix_pending(self, text: Any) -> str:
        cleaned = normalize_spaces(text)
        if not cleaned:
            return "待法源核验"
        if "待法源核验" in cleaned:
            return cleaned
        return f"待法源核验：{cleaned}"

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        issues = [issue for issue in scope.get("issue_tree", []) if isinstance(issue, dict)] or [{
            "issue_id": "I01",
            "question": normalize_spaces(state.get("query", ""))[:80] or "核心法律问题",
            "priority": "P0",
        }]
        evidence_ids = [
            item.get("evidence_id")
            for item in evidence_matrix.get("evidence_items", [])
            if isinstance(item, dict) and item.get("evidence_id")
        ]
        base_evidence = evidence_ids[:1]
        sources = [source for source in source_pack.get("issue_sources", []) if isinstance(source, dict)]
        source_ids = [source.get("source_id") for source in sources if source.get("source_id")]
        issue_analysis = []
        risk_register = []
        for index, issue in enumerate(issues[:6], start=1):
            issue_id = issue.get("issue_id") or f"I{index:02d}"
            title = normalize_spaces(issue.get("question") or "核心法律问题")[:42] or "核心法律问题"
            sid = source_ids[:2]
            issue_analysis.append({
                "issue_id": issue_id,
                "conclusion": f"{title}需要结合事实和法源作审慎判断",
                "reasoning": "当前报告由兜底模板生成，需优先以模型起草稿或人工复核补强具体法律推理。",
                "source_ids": sid,
                "evidence_ids": base_evidence,
                "certainty": "pending_verification" if not sid or not base_evidence else "medium",
            })
            risk_register.append({
                "risk_id": f"R{index:02d}",
                "title": title,
                "level": "medium" if sid and base_evidence else "note",
                "priority": clamp_priority(issue.get("priority"), "P1"),
                "source_ids": sid,
                "evidence_ids": base_evidence,
            })
        actions = [
            "固定并备份全部原始材料、沟通记录、交易记录、截图、合同文本和对方主张。",
            "按时间顺序整理事实经过，标注每个事实对应的证据编号和目前缺失材料。",
            "核对主体身份、合同或授权基础、行为发生时间、结果范围和是否已经采取补救措施。",
            "围绕报告列出的核心争点补充法源原文、监管或司法参考来源。",
            "先用书面方式与相对方沟通事实和处理方案，避免口头承诺扩大责任。",
            "根据证据强弱选择协商、投诉、调解、仲裁、诉讼或行政程序，并在采取行动前复核时效和管辖。",
        ]
        action_plan = [
            {"action_id": f"ACT{index:02d}", "priority": "P0" if index <= 3 else "P1", "owner": "用户", "description": desc, "depends_on": []}
            for index, desc in enumerate(actions, start=1)
        ]
        report = self._build_fallback_report(scope, source_pack, evidence_matrix, issue_analysis, risk_register, action_plan)
        writes = {
            "issue_analysis": issue_analysis,
            "risk_register": risk_register,
            "action_plan": action_plan,
            "report_markdown": report,
            "citation_index": [
                {"citation_tag": f"〔{source.get('source_id')},{source.get('article_or_section', '待定位')}〕", "source_id": source.get("source_id")}
                for source in sources if source.get("source_id")
            ],
            "human_review": {
                "required": True,
                "reasons": dedupe_strings((scope.get("facts_missing") or []) + (evidence_matrix.get("missing_materials") or []), limit=12),
            },
        }
        if not source_pack_has_load_bearing(source_pack):
            for item in writes["issue_analysis"]:
                item["source_ids"] = []
                item["certainty"] = "pending_verification"
                item["conclusion"] = self._prefix_pending(item.get("conclusion"))
            for item in writes["risk_register"]:
                item["source_ids"] = []
                item["level"] = "note"
                item["title"] = self._prefix_pending(item.get("title"))
            writes["report_markdown"] = self._build_source_unavailable_report(state, writes)
            writes["human_review"] = {
                "required": True,
                "reasons": dedupe_strings((source_pack.get("unresolved_source_gaps") or []) + (scope.get("facts_missing") or []), limit=20),
            }
        return make_envelope(
            agent=LEGAL_ANALYSIS_DRAFT,
            artifact_id=artifact_id(state.get("session_id", ""), "analysis_draft", state.get("iteration", 0)),
            writes=writes,
            next_agent=QUALITY_ROUTING,
            reason="完成兜底报告起草；建议优先使用模型生成稿或人工复核。",
            status="needs_primary_recheck" if not source_pack_has_load_bearing(source_pack) else "ok",
            confidence=0.35 if not source_pack_has_load_bearing(source_pack) else 0.55,
        )

    def _build_source_unavailable_report(self, state: Dict[str, Any], writes: Dict[str, Any]) -> str:
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        jurisdiction = (scope.get("jurisdiction") or {}).get("primary") or "中国大陆"
        facts = [
            normalize_spaces(fact.get("statement"))
            for fact in evidence_matrix.get("facts", [])
            if isinstance(fact, dict) and normalize_spaces(fact.get("statement"))
        ]
        if not facts:
            facts = [normalize_spaces(state.get("query")) or "用户已提出法律风险咨询，但原始材料尚需补充。"]
        fact_text = "\n".join(f"- {item}" for item in facts[:10])

        issue_items = []
        for item in writes.get("issue_analysis") or []:
            if not isinstance(item, dict):
                continue
            conclusion = normalize_spaces(item.get("conclusion"))
            reasoning = normalize_spaces(item.get("reasoning"))
            if conclusion or reasoning:
                issue_items.append(f"- {conclusion or '相关法律风险待核验'}：{reasoning or '需要补充可承载法源后再确定。'}")
        if not issue_items:
            for issue in scope.get("issue_tree") or []:
                if isinstance(issue, dict) and issue.get("question"):
                    issue_items.append(f"- {normalize_spaces(issue.get('question'))}：待补充可承载法源后再判断。")
        issue_text = "\n".join(issue_items[:8]) or "- 当前无法形成经法源支撑的分项法律分析。"

        action_items = [
            normalize_spaces(item.get("description"))
            for item in writes.get("action_plan") or []
            if isinstance(item, dict) and normalize_spaces(item.get("description"))
        ]
        action_text = "\n".join(f"{index}. {item}" for index, item in enumerate(action_items[:8], start=1)) or (
            "1. 先固定原始材料和沟通记录。\n"
            "2. 补充关键事实和损失证明。\n"
            "3. 等法源核验完成后再作最终处理决定。"
        )

        missing = dedupe_strings(
            (source_pack.get("unresolved_source_gaps") or [])
            + (evidence_matrix.get("missing_materials") or [])
            + (scope.get("facts_missing") or []),
            limit=12,
        )
        missing_text = "\n".join(
            f"- {normalize_spaces(item)}"
            for item in missing
        ) or "- 未取得可承载法律依据；需重新检索官方法源或补充材料。"

        report = f"""# 临时风险梳理草稿（待法源核验）

## 核心结论
本轮未取得可承载核心法律结论的法源，因此不能形成正式法律风险报告。以下内容仅能作为{jurisdiction}框架下的临时风险梳理，所有责任成立、风险等级、赔偿范围、行政或刑事边界，都需要在法源检索恢复并补充材料后重新核验。

## 已知事实
{fact_text}

## 法源状态
Tavily 与备用搜索未能提供足以承载核心结论的可核验法源。系统没有使用常识反推法条，也没有伪造引用。当前结论状态为待法源核验。

## 临时风险判断
{issue_text}

## 先行处置建议
{action_text}

## 待核验材料与影响
{missing_text}
"""
        return ensure_final_ai_note(strip_internal_report_markers(report))

    def _build_fallback_report(
        self,
        scope: Dict[str, Any],
        source_pack: Dict[str, Any],
        evidence_matrix: Dict[str, Any],
        issue_analysis: List[Dict[str, Any]],
        risk_register: List[Dict[str, Any]],
        action_plan: List[Dict[str, Any]],
    ) -> str:
        jurisdiction = (scope.get("jurisdiction") or {}).get("primary") or "中国大陆"
        facts = "\n".join(
            f"- {normalize_spaces(fact.get('statement'))[:360]}"
            for fact in evidence_matrix.get("facts", [])
            if isinstance(fact, dict)
        ) or "- 当前主要依据用户问题中的陈述事实，仍需补充原始材料。"
        sources = "\n".join(
            f"- {source.get('title', '待核验法源')} {source.get('article_or_section', '待定位')}（{source.get('source_id', '')}）：{normalize_spaces(source.get('exact_quote'))[:220]}"
            for source in source_pack.get("issue_sources", [])
            if isinstance(source, dict)
        ) or "- 本轮暂缺可直接承载结论的精确法源，需继续补充检索。"
        issue_text = "\n\n".join(
            f"### {item.get('issue_id')} {item.get('conclusion')}\n"
            f"**结论**：{item.get('conclusion')}。\n\n"
            f"**事实基础**：主要绑定证据 {', '.join(item.get('evidence_ids') or []) or '待补'}。\n\n"
            f"**适用依据**：主要参考 {', '.join(item.get('source_ids') or []) or '待补充来源'}。\n\n"
            f"**分析边界**：{item.get('reasoning')}"
            for item in issue_analysis
        )
        risk_rows = "\n".join(
            f"| {risk.get('risk_id')} | {risk.get('title')} | {risk.get('level')} | {risk.get('priority')} | {', '.join(risk.get('source_ids') or []) or '待补'} | {', '.join(risk.get('evidence_ids') or []) or '待补'} |"
            for risk in risk_register
        )
        action_lines = "\n".join(
            f"{index}. {action.get('description')}"
            for index, action in enumerate(action_plan, start=1)
        )
        missing = dedupe_strings((scope.get("facts_missing") or []) + (evidence_matrix.get("missing_materials") or []) + (source_pack.get("unresolved_source_gaps") or []), limit=12)
        missing_text = "\n".join(
            f"- {item}：会影响结论强弱、责任范围、赔偿或救济路径，需要补强后再确定最终处理策略。"
            for item in missing
        ) or "- 暂未列出额外材料缺口；后续如出现新材料，应重新评估结论。"
        report = f"""# 法律风控深度研究报告

## 核心结论
本案暂按{jurisdiction}法律框架处理。当前材料可以支持一份初步法律风险分析，但具体责任成立、责任范围、赔偿金额、行政或刑事边界以及最终救济路径，仍取决于原始材料、完整时间线、相对方主张、损害后果和可核验法源。

这份报告直接给出面向用户的初步结论：先控制风险、固定证据、补齐材料，再根据法源和证据强弱选择协商、投诉、调解、仲裁、诉讼或行政处理路径。

## 事实基础
{facts}

## 法律依据与类案参考
{sources}

## 分项法律分析
{issue_text}

## 风险与主张清单
| Risk ID | 风险或主张 | 等级 | 优先级 | 法源 | 证据 |
|---|---|---|---|---|---|
{risk_rows}

## 行动建议
{action_lines}

## 待核验材料
{missing_text}
"""
        return ensure_final_ai_note(strip_internal_report_markers(report))
