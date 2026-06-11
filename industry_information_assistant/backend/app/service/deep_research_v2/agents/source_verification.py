"""Source-verification agent for the legal-risk workflow."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from .artifact_agent import ArtifactAgent
from .workflow_utils import (
    EVIDENCE_CATALOG,
    SOURCE_VERIFICATION,
    artifact_id,
    as_bool,
    dedupe_strings,
    normalize_spaces,
    to_json,
)
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import ResearchState, ensure_artifact_state_defaults, get_artifact_writes
from ..prompts.legal_prompts import (
    SOURCE_VERIFICATION_SYSTEM_PROMPT,
    SOURCE_VERIFICATION_USER_PROMPT,
    schema_hint,
)

try:
    from app.tools.legal_search_tool import perform_legal_search
except ImportError:
    from tools.legal_search_tool import perform_legal_search


class SourceVerificationAgent(ArtifactAgent):
    artifact_key = "source_pack"
    agent_id = SOURCE_VERIFICATION
    next_agent = EVIDENCE_CATALOG
    system_prompt = SOURCE_VERIFICATION_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, search_api_key: str = "", model: str = ""):
        super().__init__("SourceVerificationAgent", "法源检索与引注核验 Agent", llm_api_key, llm_base_url, model)
        self.search_api_key = search_api_key

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "法源检索与引注核验：生成 source_pack")
        search_results = await self._search_for_sources(state)
        search_summary = state.get("_source_search_summary") or {}
        scope = get_artifact_writes(state, "scope_brief")
        user_prompt = SOURCE_VERIFICATION_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=to_json(scope),
            search_budget=str(len(search_results) or 0),
            preferred_languages="zh-CN first; official EN allowed for EU",
            allowed_domains_policy="优先官方法律法规数据库、监管机关、法院、检察院、政府官网；低级来源仅作线索。",
            search_results_json=to_json(search_results),
            schema=schema_hint("source_pack"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.1)
            artifact = self._coerce_source_pack_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._apply_source_health(artifact, search_summary)
        except Exception as exc:
            self.logger.warning("source_verification fallback used: %s", exc)
            artifact = self._fallback(state, search_results)
        duration = int((time.time() - start) * 1000)
        summary = artifact.get("writes", {}).get("search_summary") or search_summary
        input_summary = (
            f"search_attempts={summary.get('search_attempts', 0)}, "
            f"valid_results={summary.get('valid_results', 0)}, "
            f"tool_errors={summary.get('tool_errors', 0)}, "
            f"providers_used={','.join(summary.get('providers_used', []) or [])}"
        )
        self.add_log(state, "source_verification", input_summary, "source_pack ready", duration)
        return self._finalize(state, artifact, "已完成法源候选检索、层级标记和引用核验状态标注")

    def _build_search_queries(self, state: Dict[str, Any]) -> List[str]:
        scope = get_artifact_writes(state, "scope_brief")
        queries: List[str] = []
        queries.extend(scope.get("source_targets") or [])
        for issue in scope.get("issue_tree") or []:
            if isinstance(issue, dict) and issue.get("question"):
                queries.append(str(issue["question"])[:60])
        if not queries:
            queries.append(str(state.get("query", ""))[:60] or "法律依据")
        return dedupe_strings(queries, limit=12)

    async def _search_for_sources(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not state.get("search_web", True):
            state["_source_search_summary"] = {
                "search_attempts": 0,
                "valid_results": 0,
                "tool_errors": 0,
                "providers_used": [],
                "disabled": True,
            }
            return []
        results: List[Dict[str, Any]] = []
        seen = set()
        queries = self._build_search_queries(state)[:10]
        providers_used: List[str] = []
        tool_errors = 0
        query_summaries: List[Dict[str, Any]] = []
        for query in queries:
            data = await asyncio.to_thread(
                perform_legal_search,
                query=query,
                max_results=5,
                include_raw_content=True,
                bocha_api_key=self.search_api_key,
            )
            providers_used.extend(data.get("providers_used") or [])
            tool_errors += int(data.get("tool_errors") or 0)
            query_results = data.get("results") or []
            query_summaries.append({
                "query": query,
                "providers_used": data.get("providers_used") or [],
                "result_count": len(query_results),
                "attempts": data.get("attempts") or [],
            })
            if not query_results:
                errors = [
                    attempt.get("error")
                    for attempt in data.get("attempts", [])
                    if attempt.get("error")
                ]
                results.append({
                    "provider": "+".join(data.get("providers_used") or ["unknown"]),
                    "query": query,
                    "error": "; ".join(errors) or "搜索未返回有效结果",
                })
                continue
            for item in query_results:
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(dict(item))
        state["_source_search_summary"] = {
            "search_attempts": len(queries),
            "valid_results": len([item for item in results if item.get("url")]),
            "tool_errors": tool_errors,
            "providers_used": dedupe_strings(providers_used, limit=4),
            "queries": query_summaries,
        }
        return results[:20]

    def _coerce_source_pack_shape(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        sources = []
        allowed_keys = {
            "issue_id",
            "proposition",
            "source_id",
            "jurisdiction",
            "title",
            "issuing_body",
            "source_kind",
            "source_tier",
            "article_or_section",
            "effective_status",
            "exact_quote",
            "pinpoint",
            "language",
            "verification_status",
            "use_for_load_bearing",
            "not_load_bearing_reason",
            "url",
        }
        for index, source in enumerate(writes.get("issue_sources") or [], start=1):
            if not isinstance(source, dict):
                continue
            item = {key: value for key, value in source.items() if key in allowed_keys}
            item.setdefault("issue_id", "I01")
            item.setdefault("proposition", item.get("title") or item.get("issue_id") or "核心法律命题")
            item.setdefault("source_id", f"S{index:02d}")
            item.setdefault("jurisdiction", "中国大陆")
            item.setdefault("title", item.get("proposition") or "待核验法源")
            item.setdefault("issuing_body", "")
            item.setdefault("source_kind", "other")
            if item.get("source_tier") not in {"T1", "T2", "T3", "T4", "T5"}:
                item["source_tier"] = "T5"
            item.setdefault("article_or_section", "待定位")
            if item.get("effective_status") not in {"effective", "amended", "repealed", "unknown"}:
                item["effective_status"] = "unknown"
            item.setdefault("exact_quote", "该来源仍需进一步核验原文。")
            item.setdefault("pinpoint", item.get("article_or_section") or "待定位")
            item.setdefault("language", "zh-CN")
            item.setdefault("verification_status", "pending")
            item["use_for_load_bearing"] = as_bool(item.get("use_for_load_bearing"))
            item.setdefault("not_load_bearing_reason", "")
            item.setdefault("url", "")
            sources.append(item)
        writes["issue_sources"] = sources
        writes["unresolved_source_gaps"] = dedupe_strings(writes.get("unresolved_source_gaps") or [], limit=20)
        writes["search_summary"] = writes.get("search_summary") if isinstance(writes.get("search_summary"), dict) else {}
        writes["source_health"] = writes.get("source_health") or "unknown"
        return artifact

    def _is_load_bearing_source(self, source: Dict[str, Any]) -> bool:
        if not as_bool(source.get("use_for_load_bearing")):
            return False
        if source.get("source_tier") not in {"T1", "T2", "T3"}:
            return False
        if not source.get("url"):
            return False
        if normalize_spaces(source.get("article_or_section")) in {"", "待定位", "unknown"}:
            return False
        quote = normalize_spaces(source.get("exact_quote"))
        if not quote or "仍需" in quote or "待核验" in quote:
            return False
        return True

    def _apply_source_health(self, artifact: Dict[str, Any], search_summary: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        load_bearing_count = 0
        for source in writes.get("issue_sources") or []:
            if not isinstance(source, dict):
                continue
            if self._is_load_bearing_source(source):
                load_bearing_count += 1
                continue
            source["use_for_load_bearing"] = False
            source["not_load_bearing_reason"] = source.get("not_load_bearing_reason") or "该来源缺少可承载核心结论所需的层级、URL、定位或可核验原文。"
        writes["search_summary"] = dict(search_summary or writes.get("search_summary") or {})
        writes["search_summary"]["load_bearing_sources"] = load_bearing_count
        if load_bearing_count:
            writes["source_health"] = "load_bearing"
            if artifact.get("meta", {}).get("status") == "hard_fail":
                artifact["meta"]["status"] = "needs_primary_recheck"
        else:
            writes["source_health"] = "source_unavailable"
            if not writes.get("unresolved_source_gaps"):
                writes["unresolved_source_gaps"] = ["source_unavailable：未取得可承载核心法律结论的法源。"]
            artifact.setdefault("meta", {})["status"] = "hard_fail"
            artifact.setdefault("meta", {})["confidence"] = min(float(artifact.get("meta", {}).get("confidence") or 0.3), 0.3)
            artifact.setdefault("handoff", {})["reason"] = "未取得可承载核心法律结论的法源，下游只能生成待法源核验的临时草稿。"
        return validate_artifact(self.artifact_key, artifact)

    def _fallback(self, state: Dict[str, Any], search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        issues = scope.get("issue_tree") or [{"issue_id": "I01", "question": state.get("query", "")}]
        usable_results = [item for item in search_results if item.get("url")]
        sources: List[Dict[str, Any]] = []
        for index, issue in enumerate(issues[:8], start=1):
            item = usable_results[index - 1] if index - 1 < len(usable_results) else {}
            content = normalize_spaces(item.get("raw_content") or item.get("content") or "")
            sources.append({
                "issue_id": issue.get("issue_id", f"I{index:02d}") if isinstance(issue, dict) else f"I{index:02d}",
                "proposition": issue.get("question", "核心法律命题") if isinstance(issue, dict) else "核心法律命题",
                "source_id": f"S{index:02d}",
                "jurisdiction": (scope.get("jurisdiction") or {}).get("primary") or "中国大陆",
                "title": item.get("title") or "待核验法源",
                "issuing_body": "",
                "source_kind": "other",
                "source_tier": "T5",
                "article_or_section": "待定位",
                "effective_status": "unknown",
                "exact_quote": content[:500] or "本项仍需补充可核验法源原文。",
                "pinpoint": "待定位",
                "language": "zh-CN",
                "verification_status": "pending",
                "use_for_load_bearing": False,
                "not_load_bearing_reason": "fallback 只归集检索线索，是否可承载结论需由法源核验阶段继续确认。",
                "url": item.get("url", ""),
            })
        search_summary = state.get("_source_search_summary") or {}
        if usable_results:
            source_health = "source_candidates_only"
            gaps = ["source_unavailable：仅取得检索线索，尚未核验到可承载核心法律结论的法源。"]
            status = "needs_primary_recheck"
            confidence = 0.45
        else:
            source_health = "source_unavailable"
            gaps = ["source_unavailable：Tavily 与博查均未取得有效联网法源结果。"]
            status = "hard_fail"
            confidence = 0.0
        search_summary = dict(search_summary)
        search_summary["load_bearing_sources"] = 0
        return make_envelope(
            agent=SOURCE_VERIFICATION,
            artifact_id=artifact_id(state.get("session_id", ""), "source_pack", state.get("iteration", 0)),
            writes={
                "issue_sources": sources if usable_results else [],
                "unresolved_source_gaps": gaps,
                "search_summary": search_summary,
                "source_health": source_health,
            },
            next_agent=EVIDENCE_CATALOG,
            reason="完成法源候选归集；未核验项已显式降级。",
            status=status,
            confidence=confidence,
        )
