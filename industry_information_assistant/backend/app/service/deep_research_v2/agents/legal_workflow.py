"""Five named agents for the legal-risk artifact workflow."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from .base import BaseAgent
from ..artifact_schemas import make_envelope, validate_artifact
from ..state import (
    ResearchPhase,
    ResearchState,
    ensure_artifact_state_defaults,
    get_artifact_writes,
    put_artifact,
)
from ..prompts.legal_prompts import (
    ARTIFACT_ENVELOPE_RULE,
    LEGAL_WORKFLOW_GLOBAL_PROMPT,
    A1_SCOPE_SYSTEM_PROMPT,
    A1_SCOPE_USER_PROMPT,
    A2_SOURCE_SYSTEM_PROMPT,
    A2_SOURCE_USER_PROMPT,
    A3_EVIDENCE_SYSTEM_PROMPT,
    A3_EVIDENCE_USER_PROMPT,
    A4_ANALYSIS_SYSTEM_PROMPT,
    A4_ANALYSIS_USER_PROMPT,
    A5_QA_SYSTEM_PROMPT,
    A5_QA_USER_PROMPT,
    schema_hint,
)

try:
    from app.tools.tavily_tool import perform_internet_search
except ImportError:
    from tools.tavily_tool import perform_internet_search


def _json(data: Any, limit: int = 24000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) > limit:
        return text[:limit] + "\n...（内容过长已截断）"
    return text


def _artifact_id(session_id: str, artifact_key: str, iteration: int = 0) -> str:
    return f"{session_id or 'session'}:{artifact_key}:v{iteration + 1}"


def _material_manifest(state: Dict[str, Any]) -> List[Dict[str, str]]:
    query = state.get("query", "")
    return [{"material_id": "MATERIAL_USER_QUERY", "type": "user_query", "status": "read", "summary": query[:200]}]


def _material_text(state: Dict[str, Any]) -> str:
    return f"MATERIAL_USER_QUERY:\n{state.get('query', '')}"


def _contains_unread_placeholder(text: str) -> bool:
    return bool(re.search(r"\[(PDF|Word|图片|Image|Document|文件)[^\]]*:\s*[^\]]*\]", text or "", re.I))


CASE_SEARCH_TERMS = ["典型案例", "裁判规则", "法院 案例", "判决"]
FINAL_AI_NOTE = "AI生成，仅供参考"


INTERNAL_REPORT_TERMS = [
    "source_pack",
    "evidence_matrix",
    "scope_brief",
    "analysis_draft",
    "qa_verdict",
    "Source Pack",
    "Evidence Matrix",
    "Scope Brief",
    "Analysis Draft",
    "QA Verdict",
    "artifact",
    "Artifact",
    "工件",
    "pending_verification",
    "human_review_required",
    "material_unread",
    "A1-A3",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
]

OVER_DISCLAIMER_TERMS = [
    "免责声明",
    "不构成正式法律意见",
    "诉讼代理意见",
    "监管机关最终认定结论",
]

CORE_REPORT_TERMS = [
    "核心结论",
    "法律依据",
    "行动建议",
    FINAL_AI_NOTE,
]


ARTICLE_PATTERN = re.compile(r"(第?[一二三四五六七八九十百千万零〇\d]+条|第\s*\d+\s*条)")


def _source_tier(url: str, title: str = "", content: str = "") -> Tuple[str, str]:
    host = urlparse(url or "").netloc.lower()
    text = f"{host} {title} {content}"
    low_value = any(term in text for term in ["律师", "律所", "新闻", "博客", "问答", "广告"])
    commentary = any(term in text for term in ["解读", "亮点", "宣传", "一图读懂", "案例解析"])
    primary_domains = ["flk.npc.gov.cn", "npc.gov.cn", "www.gov.cn", "www.cac.gov.cn", "www.moj.gov.cn"]
    authority_domains = ["court.gov.cn", "spp.gov.cn", "samr.gov.cn", "cac.gov.cn"]
    if low_value:
        return "T5", "secondary_only"
    if any(domain in host for domain in primary_domains) and not commentary:
        return "T1", "verified_official"
    if any(domain in host for domain in authority_domains) and not commentary:
        return "T2", "verified_official"
    if any(term in text for term in ["案例", "判决", "处罚", "裁判文书"]):
        return "T3", "secondary_only"
    if host.endswith("gov.cn") and not commentary:
        return "T2", "verified_official"
    if host.endswith("gov.cn") and commentary:
        return "T4", "verified_official"
    return "T4", "fallback_mirror"


def _source_kind(title: str, content: str) -> str:
    text = f"{title} {content}"
    if any(term in text for term in ["案例", "判决", "裁判"]):
        return "case"
    if "处罚" in text:
        return "penalty"
    if any(term in text for term in ["个人信息保护法", "劳动合同法", "民法典", "刑法", "法律"]):
        return "law"
    if any(term in text for term in ["条例", "办法", "规定"]):
        return "regulation"
    if "司法解释" in text:
        return "judicial_interpretation"
    if any(term in text for term in ["指引", "指南", "通知", "FAQ"]):
        return "official_guidance"
    return "other"


def _first_sentence(text: str, fallback: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return fallback
    for mark in ["。", "；", "\n", "."]:
        if mark in text:
            return text.split(mark, 1)[0][:180]
    return text[:180]


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


def _is_article_locator(value: str) -> bool:
    text = _normalize_spaces(value)
    if not text or text in {"待定位", "未知", "unknown", "-", "N/A"}:
        return False
    return bool(ARTICLE_PATTERN.search(text) or any(mark in text for mark in ["章", "节", "款", "项"]))


def _looks_like_navigation(text: str) -> bool:
    compact = _normalize_spaces(text)
    if not compact:
        return True
    nav_hits = sum(1 for token in ["首页", "登录", "注册", "手机版", "加入收藏", "设为首页", "![]", "javascript:void"] if token in compact)
    return nav_hits >= 2


def _can_load_bearing_source(source: Dict[str, Any]) -> bool:
    tier = source.get("source_tier")
    return (
        tier in {"T1", "T2", "T3"}
        and bool(source.get("url"))
        and _is_article_locator(source.get("article_or_section", ""))
        and _is_article_locator(source.get("pinpoint", "") or source.get("article_or_section", ""))
        and len(_normalize_spaces(source.get("exact_quote", ""))) >= 18
        and not _looks_like_navigation(source.get("exact_quote", ""))
    )


def _can_support_preliminary_source(source: Dict[str, Any]) -> bool:
    """Allow exact rule excerpts from mirrors to support cautious user-facing analysis."""

    tier = source.get("source_tier")
    kind = source.get("source_kind")
    return (
        tier in {"T1", "T2", "T3", "T4"}
        and kind in {"law", "regulation", "judicial_interpretation", "official_guidance", "case", "penalty"}
        and _is_article_locator(source.get("article_or_section", ""))
        and len(_normalize_spaces(source.get("exact_quote", ""))) >= 28
        and not _looks_like_navigation(source.get("exact_quote", ""))
    )


def _source_quality(source: Dict[str, Any]) -> Tuple[int, int, int, int]:
    tier_rank = {"T1": 5, "T2": 4, "T3": 3, "T4": 2, "T5": 1}
    return (
        1 if source.get("use_for_load_bearing") else 0,
        1 if _is_article_locator(source.get("article_or_section", "")) else 0,
        tier_rank.get(source.get("source_tier"), 0),
        min(len(_normalize_spaces(source.get("exact_quote", ""))), 500),
    )


def _shorten_query_seed(text: str, max_terms: int = 6) -> str:
    text = re.sub(r"[《》（）()，。！？、；：:“”\"'`]", " ", text or "")
    words = [word for word in _normalize_spaces(text).split(" ") if word]
    stop = {"是否", "哪些", "可能", "如何", "什么", "需要", "用户", "客户", "问题", "风险", "规定", "相关", "其向", "行为"}
    picked = []
    for word in words:
        if any(token in word for token in stop) or len(word) > 18:
            continue
        if word not in picked:
            picked.append(word)
        if len(picked) >= max_terms:
            break
    return " ".join(picked)


def _dedupe_list(items: List[str], limit: int = 50) -> List[str]:
    seen = set()
    result = []
    for item in items:
        text = _normalize_spaces(str(item or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _missing_material_key(text: str) -> str:
    """Normalize material asks without topic-specific buckets."""
    return _normalize_spaces(text).lower()


def _dedupe_missing_materials(items: List[str], limit: int = 12) -> List[str]:
    seen = set()
    result = []
    for item in items:
        text = _normalize_spaces(str(item or ""))
        if not text:
            continue
        key = _missing_material_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _source_label(source: Dict[str, Any]) -> str:
    title = source.get("title") or "待核验法源"
    article = source.get("article_or_section") or "待定位"
    source_id = source.get("source_id") or ""
    return f"{title} {article}（{source_id}）"


def _contains_internal_report_terms(report: str) -> bool:
    return any(term in (report or "") for term in INTERNAL_REPORT_TERMS)


def _has_repeated_actions(actions: List[Dict[str, Any]]) -> bool:
    descriptions = [_normalize_spaces(action.get("description", "")) for action in actions]
    descriptions = [item for item in descriptions if item]
    return len(descriptions) != len(set(descriptions)) or len(descriptions) < 6


def _risk_title_is_question(title: str) -> bool:
    return bool(re.search(r"[？?]$", _normalize_spaces(title)))


def _report_has_final_ai_note(report: str) -> bool:
    lines = [line.strip() for line in (report or "").strip().splitlines() if line.strip()]
    return bool(lines) and lines[-1] == FINAL_AI_NOTE and (report or "").count(FINAL_AI_NOTE) == 1


def _has_over_disclaimer(report: str) -> bool:
    return any(term in (report or "") for term in OVER_DISCLAIMER_TERMS)


def _ensure_final_ai_note(report: str) -> str:
    text = report or ""
    text = re.sub(r"\n?#{1,6}\s*免责声明[\s\S]*?(?=\n#{1,6}\s|\Z)", "\n", text)
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped and (not cleaned_lines or not cleaned_lines[-1]):
            continue
        if FINAL_AI_NOTE in stripped:
            continue
        if any(term in stripped for term in OVER_DISCLAIMER_TERMS):
            continue
        cleaned_lines.append(line.rstrip())
    cleaned = "\n".join(cleaned_lines).strip()
    return f"{cleaned}\n\n{FINAL_AI_NOTE}\n" if cleaned else f"{FINAL_AI_NOTE}\n"


def _report_has_core_modules(report: str, scope: Dict[str, Any] | None = None, query: str = "") -> bool:
    text = report or ""
    return all(term in text for term in CORE_REPORT_TERMS)


def _has_case_reference(report: str, source_pack: Dict[str, Any]) -> bool:
    if any(term in (report or "") for term in ["类案", "案例", "判决", "裁判", "处罚"]):
        return True
    for source in source_pack.get("issue_sources") or []:
        if not isinstance(source, dict):
            continue
        text = f"{source.get('source_kind', '')} {source.get('title', '')} {source.get('exact_quote', '')}"
        if any(term in text for term in ["case", "penalty", "案例", "判决", "裁判", "处罚"]):
            return True
    return False


def _coerce_source_pack_shape(artifact: Dict[str, Any]) -> Dict[str, Any]:
    writes = artifact.setdefault("writes", {})
    allowed_source_keys = {
        "issue_id", "proposition", "source_id", "jurisdiction", "title", "issuing_body",
        "source_kind", "source_tier", "article_or_section", "effective_status", "exact_quote",
        "pinpoint", "language", "verification_status", "use_for_load_bearing",
        "not_load_bearing_reason", "url",
    }
    for source in writes.get("issue_sources") or []:
        if not isinstance(source, dict):
            continue
        source.setdefault("proposition", source.get("title") or source.get("issue_id") or "核心法律命题")
        for key in list(source.keys()):
            if key not in allowed_source_keys:
                source.pop(key, None)
        status = str(source.get("effective_status") or "unknown").lower()
        if status not in {"effective", "amended", "repealed", "unknown"}:
            text = str(source.get("effective_status") or "")
            if any(term in text for term in ["失效", "废止", "repeal"]):
                source["effective_status"] = "repealed"
            elif any(term in text for term in ["修订", "修改", "amend"]):
                source["effective_status"] = "amended"
            else:
                source["effective_status"] = "unknown"
        else:
            source["effective_status"] = status
        tier = str(source.get("source_tier") or "")
        if tier not in {"T1", "T2", "T3", "T4", "T5"}:
            source["source_tier"] = "T4"
        if not isinstance(source.get("use_for_load_bearing"), bool):
            source["use_for_load_bearing"] = str(source.get("use_for_load_bearing")).lower() in {"true", "yes", "1"}
    gaps = []
    for gap in writes.get("unresolved_source_gaps") or []:
        if isinstance(gap, str):
            gaps.append(gap)
        elif isinstance(gap, dict):
            message = gap.get("message") or gap.get("description") or gap.get("gap") or gap.get("reason")
            issue_id = gap.get("issue_id") or gap.get("id")
            gaps.append(_normalize_spaces(f"{issue_id or ''} {message or json.dumps(gap, ensure_ascii=False)}"))
        else:
            gaps.append(str(gap))
    writes["unresolved_source_gaps"] = _dedupe_list(gaps)
    return artifact


def _coerce_evidence_matrix_shape(artifact: Dict[str, Any]) -> Dict[str, Any]:
    writes = artifact.setdefault("writes", {})
    allowed_fact_keys = {"fact_id", "statement", "evidence_ids", "status"}
    allowed_evidence_keys = {"evidence_id", "source_type", "locator", "excerpt", "read_status"}
    allowed_issue_keys = {"issue_id", "supporting_evidence", "conflicting_evidence", "missing_evidence"}
    allowed_material_keys = {"material_id", "status", "reason"}

    def _gap_to_text(item: Any) -> str:
        if isinstance(item, str):
            return _normalize_spaces(item)
        if isinstance(item, dict):
            label = item.get("material_id") or item.get("evidence_id") or item.get("issue_id") or ""
            message = (
                item.get("reason")
                or item.get("description")
                or item.get("missing_evidence")
                or item.get("message")
                or item.get("gap")
                or json.dumps(item, ensure_ascii=False)
            )
            return _normalize_spaces(f"{label} {message}")
        return _normalize_spaces(str(item))

    for fact in writes.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        for key in list(fact.keys()):
            if key not in allowed_fact_keys:
                fact.pop(key, None)
        status = fact.get("status")
        if status not in {"verified", "partially_verified", "assumed"}:
            if status in {"pending_verification", "unverified_hearsay", "unverified", "low"}:
                fact["status"] = "partially_verified"
            else:
                fact["status"] = "assumed"
    for evidence in writes.get("evidence_items") or []:
        if not isinstance(evidence, dict):
            continue
        for key in list(evidence.keys()):
            if key not in allowed_evidence_keys:
                evidence.pop(key, None)
        if evidence.get("read_status") not in {"read", "unread", "partial"}:
            evidence["read_status"] = "partial"
    for issue in writes.get("issue_evidence_matrix") or []:
        if not isinstance(issue, dict):
            continue
        for key in list(issue.keys()):
            if key not in allowed_issue_keys:
                issue.pop(key, None)
        issue["supporting_evidence"] = [str(item) for item in (issue.get("supporting_evidence") or []) if item]
        issue["conflicting_evidence"] = [str(item) for item in (issue.get("conflicting_evidence") or []) if item]
        issue["missing_evidence"] = _dedupe_list([_gap_to_text(item) for item in (issue.get("missing_evidence") or [])])
    for material in writes.get("material_read_status") or []:
        if not isinstance(material, dict):
            continue
        for key in list(material.keys()):
            if key not in allowed_material_keys:
                material.pop(key, None)
        if material.get("status") not in {"read", "partial", "material_unread"}:
            material["status"] = "partial"
    writes["missing_materials"] = _dedupe_list([_gap_to_text(item) for item in (writes.get("missing_materials") or [])])
    return artifact


def _coerce_analysis_draft_shape(artifact: Dict[str, Any]) -> Dict[str, Any]:
    if "writes" not in artifact and any(
        key in artifact for key in ("issue_analysis", "risk_register", "action_plan", "report_markdown")
    ):
        artifact = {"writes": artifact}
    writes = artifact.setdefault("writes", {})
    nested = writes.get("writes")
    if isinstance(nested, dict) and not any(
        key in writes for key in ("issue_analysis", "risk_register", "action_plan", "report_markdown")
    ):
        artifact["writes"] = nested
        writes = artifact["writes"]
    writes.setdefault("human_review", {"required": False, "reasons": []})
    writes.setdefault("citation_index", [])
    allowed_issue_keys = {"issue_id", "conclusion", "reasoning", "source_ids", "evidence_ids", "certainty"}
    allowed_risk_keys = {"risk_id", "title", "level", "priority", "source_ids", "evidence_ids"}
    allowed_action_keys = {"action_id", "priority", "owner", "description", "depends_on"}
    allowed_citation_keys = {"citation_tag", "source_id"}
    for item in writes.get("issue_analysis") or []:
        if not isinstance(item, dict):
            continue
        for key in list(item.keys()):
            if key not in allowed_issue_keys:
                item.pop(key, None)
        if item.get("certainty") not in {"high", "medium", "low", "pending_verification"}:
            item["certainty"] = "pending_verification" if "pending" in str(item.get("certainty", "")).lower() else "medium"
        item.setdefault("source_ids", [])
        item.setdefault("evidence_ids", [])
    for item in writes.get("risk_register") or []:
        if not isinstance(item, dict):
            continue
        for key in list(item.keys()):
            if key not in allowed_risk_keys:
                item.pop(key, None)
        if item.get("level") not in {"critical", "high", "medium", "low", "note"}:
            item["level"] = "note"
        if item.get("priority") not in {"P0", "P1", "P2", "P3"}:
            item["priority"] = "P1"
        item.setdefault("source_ids", [])
        item.setdefault("evidence_ids", [])
    for index, item in enumerate(writes.get("action_plan") or [], start=1):
        if not isinstance(item, dict):
            continue
        for key in list(item.keys()):
            if key not in allowed_action_keys:
                item.pop(key, None)
        item.setdefault("action_id", f"ACT{index:02d}")
        item.setdefault("priority", "P1")
        item.setdefault("owner", "用户")
        item.setdefault("depends_on", [])
    for item in writes.get("citation_index") or []:
        if not isinstance(item, dict):
            continue
        for key in list(item.keys()):
            if key not in allowed_citation_keys:
                item.pop(key, None)
    review = writes.get("human_review")
    if not isinstance(review, dict):
        writes["human_review"] = {"required": False, "reasons": []}
    else:
        writes["human_review"] = {
            "required": bool(review.get("required")),
            "reasons": [str(reason) for reason in (review.get("reasons") or [])],
        }
    return artifact


def _coerce_qa_shape(artifact: Dict[str, Any]) -> Dict[str, Any]:
    meta = artifact.setdefault("meta", {})
    if meta.get("status") not in {"ok", "needs_more_facts", "needs_primary_recheck", "hard_fail"}:
        meta["status"] = "hard_fail" if artifact.get("writes", {}).get("hard_failures") else "ok"
    writes = artifact.setdefault("writes", {})
    route = writes.get("route")
    if isinstance(route, dict):
        if "instruction" not in route:
            route["instruction"] = route.get("reason") or route.get("message") or "按质量问题处理。"
        for key in list(route.keys()):
            if key not in {"next_agent", "instruction"}:
                route.pop(key, None)
    hard_failures = []
    for failure in writes.get("hard_failures") or []:
        if isinstance(failure, str):
            hard_failures.append(failure)
        elif isinstance(failure, dict):
            hard_failures.append(_normalize_spaces(failure.get("message") or failure.get("description") or json.dumps(failure, ensure_ascii=False)))
        else:
            hard_failures.append(str(failure))
    writes["hard_failures"] = _dedupe_list(hard_failures)

    issues = []
    for item in writes.get("issues") or []:
        if isinstance(item, str):
            issues.append({"severity": "major", "type": "quality_issue", "message": item, "route_to": "A4"})
            continue
        if not isinstance(item, dict):
            issues.append({"severity": "major", "type": "quality_issue", "message": str(item), "route_to": "A4"})
            continue
        severity = item.get("severity") or item.get("level") or "major"
        if severity not in {"critical", "major", "minor"}:
            severity = "major"
        route_to = item.get("route_to") or item.get("route") or item.get("next_agent") or item.get("target_agent") or "A4"
        if route_to not in {"A1", "A2", "A3", "A4"}:
            route_to = "A4"
        message = item.get("message") or item.get("description") or item.get("fix_instruction") or item.get("issue") or json.dumps(item, ensure_ascii=False)
        issues.append({
            "severity": severity,
            "type": item.get("type") or item.get("issue_type") or item.get("id") or "quality_issue",
            "message": _normalize_spaces(message),
            "route_to": route_to,
        })
    writes["issues"] = issues
    return artifact


def _pick_source_ids(sources: List[Dict[str, Any]], keywords: List[str], limit: int = 3, issue_id: str = "") -> List[str]:
    picked: List[str] = []
    scoped_sources = [source for source in sources if not issue_id or source.get("issue_id") == issue_id]
    search_sources = scoped_sources or sources
    for source in search_sources:
        text = f"{source.get('title', '')} {source.get('article_or_section', '')} {source.get('exact_quote', '')}"
        if any(keyword in text for keyword in keywords) and source.get("source_id"):
            picked.append(source["source_id"])
        if len(picked) >= limit:
            break
    if not picked:
        picked = [source.get("source_id") for source in scoped_sources if source.get("source_id") and source.get("use_for_load_bearing")][:limit]
    if not picked:
        picked = [source.get("source_id") for source in sources if source.get("source_id") and source.get("use_for_load_bearing")][:limit]
    return [source_id for source_id in picked if source_id]


def _format_source_list(sources: List[Dict[str, Any]]) -> str:
    rows = []
    for source in sources:
        if not source.get("source_id"):
            continue
        rows.append(f"- {_source_label(source)}")
    return "\n".join(rows) or "- 暂缺可承载结论的精确法源，需补充核验。"


def _source_supports_report(source: Dict[str, Any]) -> bool:
    return _can_load_bearing_source(source) or _can_support_preliminary_source(source)


def _blocking_source_gaps(source_pack: Dict[str, Any]) -> List[str]:
    sources = [source for source in source_pack.get("issue_sources", []) if isinstance(source, dict)]
    issue_has_source = {}
    for source in sources:
        issue_id = source.get("issue_id", "")
        if issue_id and source.get("use_for_load_bearing") and _source_supports_report(source):
            issue_has_source[issue_id] = True
    if not issue_has_source and source_pack.get("unresolved_source_gaps"):
        return list(source_pack.get("unresolved_source_gaps") or [])
    blocking = []
    nonblocking_terms = [
        "检索预算", "司法案例数据库", "待检索", "尚未完成", "需补充", "原文待检索", "待核验",
        "官方数据库获取", "公开案例", "裁判文书", "维权路径", "证据固定", "投诉举报",
        "当地统计局", "年度相关数据", "赔偿标准数据", "程序指引", "举证责任分配", "诉讼程序",
        "具体城市", "地方法规", "当地法规", "无法定位并检索", "证据保全", "操作指南",
        "电子证据", "公证", "报警", "诈骗", "敲诈勒索", "反电信网络诈骗", "应对策略", "N/A",
        "专门指南", "细化规则", "指导案例", "典型司法案例", "行政处罚案例", "实践中的定性", "量刑/处罚尺度",
        "具体裁判规则", "官方案例", "司法解释", "监管规定", "具体计算方式", "利息计算标准",
        "预收费资金监管", "专门规定", "地方性监管办法", "needs_case", "needs_regulation", "需要找到",
    ]
    for gap in source_pack.get("unresolved_source_gaps") or []:
        text = str(gap)
        issue_match = re.search(r"\b(I\d{2})\b", text)
        issue_id = issue_match.group(1) if issue_match else ""
        if any(term in text for term in ["司法案例", "案例数据库", "裁判文书数据库", "典型司法案例", "行政处罚案例", "指导案例"]):
            continue
        if any(term in text for term in ["具体城市", "地方法规", "当地法规", "无法定位并检索"]):
            continue
        if any(term in text for term in ["当地统计局", "年度相关数据", "赔偿标准数据", "程序指引", "举证责任分配", "诉讼程序", "证据保全", "操作指南", "电子证据", "公证", "报警", "诈骗", "敲诈勒索", "反电信网络诈骗", "应对策略", "N/A", "专门指南", "细化规则", "指导案例", "典型司法案例", "行政处罚案例", "实践中的定性", "量刑/处罚尺度", "具体裁判规则", "官方案例", "司法解释", "监管规定", "具体计算方式", "利息计算标准", "预收费资金监管", "专门规定", "地方性监管办法", "needs_case", "needs_regulation", "需要找到"]):
            continue
        if issue_id and issue_has_source.get(issue_id) and any(term in text for term in ["缺少", "未取得", "未包含", "未提供", "需从官方", "缺乏直接", "一级法源", "直接对应", "gap_description", "source_needed", "需要找到", "needs_case", "needs_regulation"]):
            continue
        if issue_id and issue_has_source.get(issue_id) and any(term in text for term in nonblocking_terms):
            continue
        if not issue_id and issue_has_source and any(term in text for term in nonblocking_terms):
            continue
        blocking.append(text)
    return _dedupe_list(blocking)


class ArtifactAgent(BaseAgent):
    artifact_key = ""
    agent_code = ""
    next_agent = ""
    system_prompt = ""
    user_prompt_template = ""

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
        artifact = validate_artifact(self.artifact_key, artifact)
        put_artifact(state, self.artifact_key, artifact)
        state["current_agent"] = self.agent_code
        self.add_message(
            state,
            "artifact_ready",
            {
                "artifact": self.artifact_key,
                "agent_code": self.agent_code,
                "status": artifact.get("meta", {}).get("status"),
                "summary": summary,
            },
        )
        return state

    async def process(self, state: ResearchState) -> ResearchState:
        raise NotImplementedError


class ScopeDefinitionAgent(ArtifactAgent):
    artifact_key = "scope_brief"
    agent_code = "A1"
    next_agent = "A2"
    system_prompt = A1_SCOPE_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("ScopeDefinitionAgent", "立项定界 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "A1 立项定界：生成 scope_brief")
        user_prompt = A1_SCOPE_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            user_query=state.get("query", ""),
            materials_manifest=_json(_material_manifest(state)),
            interactive_mode="batch",
            schema=schema_hint("scope_brief"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.2)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_scope_artifact(artifact, state)
        except Exception as exc:
            self.logger.warning("A1 fallback used: %s", exc)
            artifact = self._fallback(state)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "scope_definition", state.get("query", "")[:120], "scope_brief ready", duration)
        return self._finalize(state, artifact, "已完成法域、问题树、事实缺口和法源目标定界")

    def _normalize_scope_artifact(self, artifact: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        writes = artifact.setdefault("writes", {})
        targets = []
        for target in writes.get("source_targets") or []:
            short = _shorten_query_seed(str(target), max_terms=6)
            short = _normalize_spaces(ARTICLE_PATTERN.sub(" ", short))
            if short:
                targets.append(short)
        task_type = _normalize_spaces(str(writes.get("task_type") or "general_legal_research"))
        task_type = re.sub(r"[^0-9a-zA-Z_]+", "_", task_type.strip().lower()).strip("_") or "general_legal_research"
        writes["task_type"] = task_type[:64]
        if not targets:
            for issue in writes.get("issue_tree") or []:
                if isinstance(issue, dict):
                    seed = _shorten_query_seed(issue.get("question", ""), max_terms=6)
                    if seed:
                        targets.append(seed)
        writes["source_targets"] = _dedupe_list(targets, limit=10)
        return validate_artifact(self.artifact_key, artifact)

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = state.get("query", "")
        issues = [
            ("I01", "用户行为或业务安排是否存在主要法律风险", "P0", ["用户陈述的行为、材料处理记录、合同或授权记录"]),
            ("I02", "相对方可能主张哪些民事、行政或刑事责任边界", "P1", ["损害后果、传播范围、合同/平台/内部规则"]),
            ("I03", "应如何固定证据、止损、沟通和选择救济路径", "P1", ["原始材料、沟通记录、删除/投诉/和解记录"]),
        ]
        writes = {
            "task_type": "general_legal_research",
            "jurisdiction": {
                "primary": "中国大陆",
                "others": [],
                "status": "assumed",
                "jurisdiction_candidates": ["中国大陆"],
                "why_unknown": "",
            },
            "issue_tree": [
                {"issue_id": issue_id, "question": question, "priority": priority, "evidence_needed": evidence}
                for issue_id, question, priority, evidence in issues
            ],
            "facts_known": [query],
            "facts_assumed": ["若未特别说明，默认适用中国大陆法域。"],
            "facts_missing": ["核心事实原始证据", "相对方主体信息", "损害后果和传播范围", "用户已采取的止损措施"],
            "source_targets": ["民法典 人格权 侵权责任", "民事责任 赔偿 道歉 删除", "典型案例 裁判规则"],
            "clarification_questions": ["目前有哪些原始证据？", "相对方具体诉求是什么？", "是否已经删除、投诉或沟通过？"],
            "human_review": {"required": False, "reasons": []},
        }
        return make_envelope(
            agent="A1",
            artifact_id=_artifact_id(state.get("session_id", ""), "scope_brief", state.get("iteration", 0)),
            writes=writes,
            next_agent="A2",
            reason="完成最小可执行研究计划。",
            confidence=0.62,
        )

class SourceVerificationAgent(ArtifactAgent):
    artifact_key = "source_pack"
    agent_code = "A2"
    next_agent = "A3"
    system_prompt = A2_SOURCE_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, search_api_key: str = "", model: str = ""):
        super().__init__("SourceVerificationAgent", "法源检索与引注核验 Agent", llm_api_key, llm_base_url, model)
        self.search_api_key = search_api_key

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "A2 法源检索与引注核验：生成 source_pack")
        previous_source_pack = get_artifact_writes(state, "source_pack")
        search_results = await self._search_for_sources(state)
        scope = get_artifact_writes(state, "scope_brief")
        user_prompt = A2_SOURCE_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=_json(scope),
            search_budget=str(len(search_results) or 0),
            preferred_languages="zh-CN first; official EN allowed for EU",
            allowed_domains_policy="优先官方法律法规数据库、监管机关、法院、检察院、政府官网；低级来源仅作线索。",
            search_results_json=_json(search_results),
            schema=schema_hint("source_pack"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.1)
            artifact = _coerce_source_pack_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_source_pack(state, artifact)
        except Exception as exc:
            self.logger.warning("A2 fallback used: %s", exc)
            artifact = self._fallback(state, search_results)
        artifact = self._merge_with_previous_sources(state, artifact, previous_source_pack)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "source_verification", f"{len(search_results)} search results", "source_pack ready", duration)
        return self._finalize(state, artifact, "已完成法源候选检索、层级标记和引用核验状态标注")

    def _build_search_queries(self, state: Dict[str, Any]) -> List[str]:
        scope = get_artifact_writes(state, "scope_brief")
        queries: List[str] = []
        for target in scope.get("source_targets") or []:
            short = _shorten_query_seed(str(target), max_terms=6)
            if short:
                queries.append(f"{short} 官方")
        for issue in scope.get("issue_tree", []) or []:
            if not isinstance(issue, dict):
                continue
            question = issue.get("question", "")
            issue_queries: List[str] = []
            seed = _shorten_query_seed(question, max_terms=5)
            if seed:
                issue_queries.append(f"{seed} 法律依据")
                issue_queries.append(f"{seed} 典型案例 法院")
                issue_queries.append(f"{seed} 裁判规则")
            queries.extend(f"{query} 官方" if "官方" not in query and not any(term in query for term in CASE_SEARCH_TERMS) else query for query in issue_queries[:4])
            if seed:
                queries.append(f"{seed} 判决")
        if not queries:
            seed = _shorten_query_seed(state.get("query", ""), max_terms=6)
            queries = [f"{seed or '法律依据'} 官方", f"{seed or '法律纠纷'} 典型案例 法院"]
        return _dedupe_list(queries, limit=14)

    async def _search_for_sources(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not state.get("search_web", True):
            return []
        queries = self._build_search_queries(state)
        results: List[Dict[str, Any]] = []
        seen = set()
        for query in queries[:10]:
            try:
                data = await asyncio.to_thread(
                    perform_internet_search,
                    query=query,
                    topic="general",
                    max_results=5,
                    include_raw_content=True,
                )
                for item in data.get("results", []):
                    url = item.get("url")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    item = dict(item)
                    item["query"] = query
                    results.append(item)
            except Exception as exc:
                    results.append({"query": query, "error": str(exc)})
        return results[:20]

    def _common_sources_for_scope(self, scope: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _normalize_source_pack(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        issue_ids = [issue.get("issue_id") for issue in scope.get("issue_tree", []) if isinstance(issue, dict)]
        issue_priority = {
            issue.get("issue_id"): issue.get("priority", "P1")
            for issue in scope.get("issue_tree", [])
            if isinstance(issue, dict) and issue.get("issue_id")
        }
        issue_question = {
            issue.get("issue_id"): issue.get("question", "")
            for issue in scope.get("issue_tree", [])
            if isinstance(issue, dict) and issue.get("issue_id")
        }
        writes = artifact.setdefault("writes", {})
        normalized_sources: List[Dict[str, Any]] = []
        raw_sources = [source for source in writes.get("issue_sources") or [] if isinstance(source, dict)]
        for extra in self._common_sources_for_scope(scope):
            key = (extra.get("issue_id"), extra.get("title"), extra.get("article_or_section"), extra.get("pinpoint"))
            if not any((source.get("issue_id"), source.get("title"), source.get("article_or_section"), source.get("pinpoint")) == key for source in raw_sources):
                raw_sources.append(extra)
        for index, source in enumerate(raw_sources, start=1):
            if not isinstance(source, dict):
                continue
            item = dict(source)
            item.setdefault("source_id", f"S{index:02d}")
            item.setdefault("issue_id", issue_ids[min(index - 1, len(issue_ids) - 1)] if issue_ids else "I01")
            content = item.get("exact_quote", "")
            tier, verification = _source_tier(item.get("url", ""), item.get("title", ""), content)
            item["source_tier"] = tier
            item["verification_status"] = verification if item.get("verification_status") in {"verified_official", "verified_primary", "fallback_mirror", "secondary_only", "pending", "conflict"} else verification
            item["source_kind"] = item.get("source_kind") or _source_kind(item.get("title", ""), content)
            item["article_or_section"] = _normalize_spaces(item.get("article_or_section") or "待定位") or "待定位"
            item["pinpoint"] = _normalize_spaces(item.get("pinpoint") or item.get("article_or_section") or "待定位") or "待定位"
            if not _is_article_locator(item["pinpoint"]) and _is_article_locator(item["article_or_section"]):
                item["pinpoint"] = item["article_or_section"]
            if not _is_article_locator(item["article_or_section"]) and _is_article_locator(item["pinpoint"]):
                item["article_or_section"] = item["pinpoint"]
            item["exact_quote"] = _normalize_spaces(content)[:1200] or "该命题仍需官方原文核验。"
            item["effective_status"] = item.get("effective_status") if item.get("effective_status") in {"effective", "amended", "repealed", "unknown"} else "unknown"
            if _can_load_bearing_source(item) or _can_support_preliminary_source(item):
                item["use_for_load_bearing"] = True
                item["not_load_bearing_reason"] = ""
                if not _can_load_bearing_source(item) and item["verification_status"] in {"verified_official", "verified_primary"}:
                    item["verification_status"] = "fallback_mirror"
            else:
                item["use_for_load_bearing"] = False
                if item["verification_status"] in {"verified_official", "verified_primary"}:
                    item["verification_status"] = "pending" if item["article_or_section"] == "待定位" else "fallback_mirror"
                item["not_load_bearing_reason"] = item.get("not_load_bearing_reason") or "未取得可承载结论的精确条文定位和规则原文。"
            normalized_sources.append(item)

        existing_gaps = _dedupe_list(list(writes.get("unresolved_source_gaps") or []))
        issue_has_source = {
            issue_id: any(s.get("issue_id") == issue_id and s.get("use_for_load_bearing") for s in normalized_sources)
            for issue_id in issue_ids
        }
        gaps = []
        for gap in existing_gaps:
            issue_match = re.search(r"\b(I\d{2})\b", gap)
            issue_id = issue_match.group(1) if issue_match else ""
            if issue_id and issue_has_source.get(issue_id) and any(term in gap for term in ["检索预算", "官方数据库", "未包含", "未提供", "需从官方", "缺乏直接", "缺少", "原文", "待定位", "待核验", "一级法源", "直接对应", "gap_description", "source_needed", "需要找到", "needs_case", "needs_regulation"]):
                continue
            if any(term in gap for term in ["具体城市", "地方法规", "当地法规", "无法定位并检索"]):
                continue
            if issue_id and any(term in issue_question.get(issue_id, "") for term in ["证据", "保全", "收集", "固定"]) and any(term in gap for term in ["缺少可承载", "精确法源", "法源条文"]):
                continue
            if any(term in gap for term in ["当地统计局", "年度相关数据", "赔偿标准数据", "程序指引", "举证责任分配", "诉讼程序", "证据保全", "操作指南", "电子证据", "公证", "报警", "诈骗", "敲诈勒索", "反电信网络诈骗", "应对策略", "N/A", "专门指南", "细化规则", "指导案例", "典型司法案例", "行政处罚案例", "实践中的定性", "量刑/处罚尺度", "具体裁判规则", "官方案例", "司法解释", "监管规定", "具体计算方式", "利息计算标准", "预收费资金监管", "专门规定", "地方性监管办法", "needs_case", "needs_regulation", "需要找到"]):
                continue
            if issue_id and issue_priority.get(issue_id) not in {"P0"} and any(term in gap for term in ["公开", "案例", "裁判文书", "地方性法规", "维权", "投诉", "证据", "缺少可承载", "未检索到明确法源", "性质认定", "具体救济", "交叉适用"]):
                continue
            gaps.append(gap)
        for issue_id in issue_ids:
            if (
                issue_id
                and issue_priority.get(issue_id, "P1") == "P0"
                and not any(s.get("issue_id") == issue_id and s.get("use_for_load_bearing") for s in normalized_sources)
            ):
                gaps.append(f"{issue_id} 缺少可承载结论的精确法源条文。")
        writes["issue_sources"] = normalized_sources
        writes["unresolved_source_gaps"] = _dedupe_list(gaps)
        blocking_gaps = _blocking_source_gaps(writes)
        artifact["meta"]["status"] = "needs_primary_recheck" if blocking_gaps else "ok"
        artifact["meta"]["confidence"] = min(float(artifact["meta"].get("confidence", 0.7)), 0.72) if blocking_gaps else artifact["meta"].get("confidence", 0.8)
        return validate_artifact(self.artifact_key, artifact)

    def _merge_with_previous_sources(self, state: Dict[str, Any], artifact: Dict[str, Any], previous_source_pack: Dict[str, Any]) -> Dict[str, Any]:
        current = self._normalize_source_pack(state, artifact)
        previous_sources = previous_source_pack.get("issue_sources") or []
        if not previous_sources:
            return current
        previous_artifact = make_envelope(
            agent="A2",
            artifact_id=_artifact_id(state.get("session_id", ""), "source_pack", max(0, int(state.get("iteration", 0)) - 1)),
            writes={
                "issue_sources": previous_sources,
                "unresolved_source_gaps": previous_source_pack.get("unresolved_source_gaps") or [],
            },
            next_agent="A3",
            reason="normalize previous source_pack for merge",
        )
        previous = self._normalize_source_pack(state, previous_artifact)
        candidates = list(previous["writes"].get("issue_sources") or []) + list(current["writes"].get("issue_sources") or [])
        best_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for source in candidates:
            key = (
                source.get("issue_id", ""),
                source.get("article_or_section") if _is_article_locator(source.get("article_or_section", "")) else "",
                source.get("url") or source.get("title", ""),
            )
            old = best_by_key.get(key)
            if not old or _source_quality(source) > _source_quality(old):
                best_by_key[key] = dict(source)
        merged_sources = sorted(
            best_by_key.values(),
            key=lambda source: (source.get("issue_id", ""), tuple(-value for value in _source_quality(source))),
        )
        for index, source in enumerate(merged_sources, start=1):
            source["source_id"] = f"S{index:02d}"
        current["writes"]["issue_sources"] = merged_sources[:24]
        current = self._normalize_source_pack(state, current)
        return current

    def _fallback(self, state: Dict[str, Any], search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        issues = scope.get("issue_tree") or [{"issue_id": "I01", "question": state.get("query", "")}]
        usable_results = [item for item in search_results if item.get("url")]
        tier_rank = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
        usable_results.sort(
            key=lambda item: tier_rank.get(
                _source_tier(item.get("url", ""), item.get("title", ""), item.get("raw_content") or item.get("content") or "")[0],
                9,
            )
        )
        load_bearing_results = [
            item for item in usable_results
            if _source_tier(item.get("url", ""), item.get("title", ""), item.get("raw_content") or item.get("content") or "")[0] in {"T1", "T2", "T3"}
        ]
        preferred_results = load_bearing_results or usable_results
        sources: List[Dict[str, Any]] = []
        source_index = 1
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            item = preferred_results[(source_index - 1) % len(preferred_results)] if preferred_results else {}
            title = item.get("title") or "待核验官方法源"
            content = item.get("raw_content") or item.get("content") or ""
            tier, verification = _source_tier(item.get("url", ""), title, content)
            use_for_load = tier in {"T1", "T2", "T3"} and bool(item.get("url"))
            sources.append({
                "issue_id": issue.get("issue_id", f"I{source_index:02d}"),
                "proposition": issue.get("question", "核心法律命题"),
                "source_id": f"S{source_index:02d}",
                "jurisdiction": scope.get("jurisdiction", {}).get("primary") or "中国大陆",
                "title": title,
                "issuing_body": "待核验" if not use_for_load else "官方或权威来源",
                "source_kind": _source_kind(title, content),
                "source_tier": tier if item else "T5",
                "article_or_section": "待定位",
                "effective_status": "unknown",
                "exact_quote": _first_sentence(content, "该命题仍需官方原文核验。"),
                "pinpoint": "待定位",
                "language": "zh-CN",
                "verification_status": verification if item else "pending",
                "use_for_load_bearing": use_for_load,
                "not_load_bearing_reason": "" if use_for_load else "未取得可承载结论的官方或一级来源。",
                "url": item.get("url", ""),
            })
            source_index += 1
        gaps = []
        if not usable_results:
            gaps.append("未取得可核验的联网法源结果。")
        elif not any(source["use_for_load_bearing"] for source in sources):
            gaps.append("核心命题仍缺少 T1-T3 可承载法源。")
        return make_envelope(
            agent="A2",
            artifact_id=_artifact_id(state.get("session_id", ""), "source_pack", state.get("iteration", 0)),
            writes={"issue_sources": sources, "unresolved_source_gaps": gaps},
            next_agent="A3",
            reason="完成法源候选归集；未核验项已显式降级。",
            status="needs_primary_recheck" if gaps else "ok",
            confidence=0.55 if gaps else 0.72,
        )


class EvidenceCatalogAgent(ArtifactAgent):
    artifact_key = "evidence_matrix"
    agent_code = "A3"
    next_agent = "A4"
    system_prompt = A3_EVIDENCE_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("EvidenceCatalogAgent", "事实证据编目 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "A3 事实证据编目：生成 evidence_matrix")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        user_prompt = A3_EVIDENCE_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=_json(scope),
            source_pack_json=_json(source_pack),
            materials_text_or_extracts=_material_text(state),
            materials_manifest=_json(_material_manifest(state)),
            schema=schema_hint("evidence_matrix"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.15)
            artifact = _coerce_evidence_matrix_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_evidence_matrix(state, artifact)
        except Exception as exc:
            self.logger.warning("A3 fallback used: %s", exc)
            artifact = self._fallback(state)
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "evidence_catalog", "scope/source_pack/materials", "evidence_matrix ready", duration)
        return self._finalize(state, artifact, "已完成事实、证据、材料读取状态和 issue 证据矩阵")

    def _normalize_evidence_matrix(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        writes = artifact.setdefault("writes", {})
        evidence_items = writes.get("evidence_items") or []
        only_user_query = bool(evidence_items) and all(
            (item.get("source_type") == "user_material" and item.get("locator") in {"用户问题", "MATERIAL_USER_QUERY", "用户陈述"})
            for item in evidence_items if isinstance(item, dict)
        )
        for fact in writes.get("facts") or []:
            if isinstance(fact, dict) and only_user_query and fact.get("status") == "verified":
                fact["status"] = "partially_verified"
        missing = list(scope.get("facts_missing") or []) + list(writes.get("missing_materials") or [])
        evidence_ids = {
            item.get("evidence_id")
            for item in evidence_items
            if isinstance(item, dict) and item.get("evidence_id")
        }
        base_user_evidence = "E01" if "E01" in evidence_ids else next(iter(evidence_ids), "")
        for issue in writes.get("issue_evidence_matrix") or []:
            if isinstance(issue, dict):
                if base_user_evidence and not issue.get("supporting_evidence"):
                    issue["supporting_evidence"] = [base_user_evidence]
                missing.extend(issue.get("missing_evidence") or [])
        writes["missing_materials"] = _dedupe_list(missing)
        artifact["meta"]["status"] = "needs_more_facts" if writes["missing_materials"] else "ok"
        return validate_artifact(self.artifact_key, artifact)

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        query = state.get("query", "")
        unread = _contains_unread_placeholder(query)
        facts = []
        evidence_items = [{
            "evidence_id": "E01",
            "source_type": "user_material",
            "locator": "用户问题",
            "excerpt": query[:1000],
            "read_status": "partial" if unread else "read",
        }]
        for idx, fact in enumerate((scope.get("facts_known") or [query])[:8], start=1):
            facts.append({
                "fact_id": f"F{idx:02d}",
                "statement": fact,
                "evidence_ids": ["E01"],
                "status": "partially_verified",
            })
        issue_matrix = []
        for issue in scope.get("issue_tree", []) or [{"issue_id": "I01"}]:
            issue_matrix.append({
                "issue_id": issue.get("issue_id", "I01"),
                "supporting_evidence": ["E01"],
                "conflicting_evidence": [],
                "missing_evidence": list(issue.get("evidence_needed") or []) + list(scope.get("facts_missing") or []),
            })
        missing = list(scope.get("facts_missing") or [])
        for issue in issue_matrix:
            missing.extend(issue.get("missing_evidence") or [])
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
            "missing_materials": _dedupe_list(missing),
        }
        return make_envelope(
            agent="A3",
            artifact_id=_artifact_id(state.get("session_id", ""), "evidence_matrix", state.get("iteration", 0)),
            writes=writes,
            next_agent="A4",
            reason="完成事实证据矩阵；材料缺口已显式列出。",
            status="needs_more_facts" if missing else "ok",
            confidence=0.63,
        )


class LegalAnalysisDraftAgent(ArtifactAgent):
    artifact_key = "analysis_draft"
    agent_code = "A4"
    next_agent = "A5"
    system_prompt = A4_ANALYSIS_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("LegalAnalysisDraftAgent", "法律分析与报告起草 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "A4 法律分析与报告起草：生成 analysis_draft")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        user_prompt = A4_ANALYSIS_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=_json(scope),
            source_pack_json=_json(source_pack),
            evidence_matrix_json=_json(evidence_matrix),
            schema=schema_hint("analysis_draft"),
        )
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.25)
            artifact = _coerce_analysis_draft_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_analysis_artifact(state, artifact)
            report = artifact["writes"].get("report_markdown", "")
            if not _report_has_final_ai_note(report) or _has_over_disclaimer(report):
                raise ValueError("report_markdown final AI note invalid")
            if _contains_internal_report_terms(report):
                raise ValueError("report_markdown exposes internal workflow terms")
            if not _report_has_core_modules(report, scope, state.get("query", "")):
                raise ValueError("report_markdown missing required legal-risk modules")
            if _has_repeated_actions(artifact["writes"].get("action_plan") or []):
                raise ValueError("action_plan is repetitive or too thin")
        except Exception as exc:
            self.logger.warning("A4 fallback used: %s", exc)
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

    def _normalize_analysis_artifact(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        writes = artifact.setdefault("writes", {})
        report = writes.get("report_markdown", "")
        report = report.replace("Source Pack", "已核验法律依据")
        report = report.replace("Evidence Matrix", "已编目证据")
        report = report.replace("Scope Brief", "问题定界")
        task_sources = [source for source in (source_pack.get("issue_sources") or []) if isinstance(source, dict)]
        valid_source_ids = {
            source.get("source_id")
            for source in task_sources
            if source.get("source_id")
            and source.get("effective_status") != "repealed"
            and _source_supports_report(source)
        }
        sources_by_issue: Dict[str, List[str]] = {}
        for source in task_sources:
            source_id = source.get("source_id")
            issue_id = source.get("issue_id")
            if source_id in valid_source_ids and issue_id:
                sources_by_issue.setdefault(issue_id, []).append(source_id)
        fallback_source_ids = list(valid_source_ids)[:3]
        for item in writes.get("issue_analysis") or []:
            if isinstance(item, dict):
                item["source_ids"] = [sid for sid in (item.get("source_ids") or []) if sid in valid_source_ids]
                if not item["source_ids"]:
                    item["source_ids"] = sources_by_issue.get(item.get("issue_id"), [])[:2] or fallback_source_ids[:2]
        for risk in writes.get("risk_register") or []:
            if isinstance(risk, dict):
                risk["source_ids"] = [sid for sid in (risk.get("source_ids") or []) if sid in valid_source_ids]
                if not risk["source_ids"]:
                    risk["source_ids"] = sources_by_issue.get(risk.get("issue_id"), [])[:2] or fallback_source_ids[:2]
        base_evidence_ids = [
            item.get("evidence_id")
            for item in evidence_matrix.get("evidence_items", [])
            if isinstance(item, dict) and item.get("evidence_id")
        ]
        base_evidence_ids = [item for item in base_evidence_ids if item][:1]
        if base_evidence_ids:
            for item in writes.get("issue_analysis") or []:
                if isinstance(item, dict) and not item.get("evidence_ids"):
                    item["evidence_ids"] = base_evidence_ids
            for risk in writes.get("risk_register") or []:
                if isinstance(risk, dict) and not risk.get("evidence_ids"):
                    risk["evidence_ids"] = base_evidence_ids
        writes["report_markdown"] = _ensure_final_ai_note(report)
        return validate_artifact(self.artifact_key, artifact)

    def _fallback(self, state: Dict[str, Any]) -> Dict[str, Any]:
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        sources = [source for source in (source_pack.get("issue_sources") or []) if isinstance(source, dict)]
        load_sources = [source for source in sources if source.get("use_for_load_bearing")]
        evidence_items = evidence_matrix.get("evidence_items") or []
        evidence_ids = [item.get("evidence_id") for item in evidence_items if item.get("evidence_id")]
        base_evidence = evidence_ids[:1]
        source_gap = bool(_blocking_source_gaps(source_pack)) or not load_sources
        missing_materials = self._collect_missing_materials(scope, evidence_matrix, source_pack)
        human_review = {
            "required": bool(missing_materials or (scope.get("human_review") or {}).get("required")),
            "reasons": _dedupe_list(list((scope.get("human_review") or {}).get("reasons") or []) + missing_materials[:6]),
        }
        issues = [issue for issue in (scope.get("issue_tree") or []) if isinstance(issue, dict)]
        if not issues:
            issues = [{"issue_id": "I01", "question": state.get("query", "主要法律风险"), "priority": "P0"}]
        issue_analysis = []
        risk_register = []
        for index, issue in enumerate(issues[:8], start=1):
            issue_id = issue.get("issue_id") or f"I{index:02d}"
            question = _normalize_spaces(issue.get("question") or "主要法律风险")
            title = self._conclusion_title(question)
            keywords = [part for part in _shorten_query_seed(question, max_terms=5).split(" ") if part]
            sid = _pick_source_ids(load_sources, keywords, issue_id=issue_id)
            eids = base_evidence
            certainty = "pending_verification" if source_gap or not sid or not eids else "medium"
            issue_analysis.append({
                "issue_id": issue_id,
                "conclusion": title,
                "reasoning": self._generic_risk_reasoning(question),
                "source_ids": sid,
                "evidence_ids": eids,
                "certainty": certainty,
            })
            risk_register.append({
                "risk_id": f"R{index:02d}",
                "title": title,
                "level": "high" if sid and eids else "note",
                "priority": issue.get("priority") if issue.get("priority") in {"P0", "P1", "P2", "P3"} else ("P0" if index == 1 else "P1"),
                "source_ids": sid,
                "evidence_ids": eids,
            })
        action_plan = self._generic_action_plan(scope)
        report = self._build_report(
            scope,
            source_pack,
            evidence_matrix,
            issue_analysis,
            risk_register,
            action_plan,
            human_review,
            privacy_task=False,
        )
        writes = {
            "issue_analysis": issue_analysis,
            "risk_register": risk_register,
            "action_plan": action_plan,
            "report_markdown": report,
            "citation_index": [
                {"citation_tag": f"〔{source.get('source_id')},{source.get('article_or_section', '待定位')}〕", "source_id": source.get("source_id")}
                for source in sources if source.get("source_id")
            ],
            "human_review": human_review,
        }
        return make_envelope(
            agent="A4",
            artifact_id=_artifact_id(state.get("session_id", ""), "analysis_draft", state.get("iteration", 0)),
            writes=writes,
            next_agent="A5",
            reason="完成报告起草；待核验事项已显式写入。",
            confidence=0.66,
        )

    def _conclusion_title(self, question: str) -> str:
        text = re.sub(r"[？?。；;]+$", "", _normalize_spaces(question))
        text = re.sub(r"^(是否|能否|可否|如何判断|需要判断)", "", text).strip()
        if len(text) > 28:
            text = text[:28].rstrip()
        if not any(term in text for term in ["风险", "责任", "义务", "主张", "效力", "解除", "赔偿"]):
            text = f"{text}相关风险"
        return text or "核心法律风险"

    def _generic_risk_reasoning(self, question: str) -> str:
        return (
            f"围绕“{question}”，应先确认基础事实、合同或交易文件、付款/履行记录、沟通记录和损害结果，"
            "再把已核验法源与事实逐项对应。当前用户陈述可以作为分析起点，但不能替代合同原件、截图、票据、平台规则或主管机关/法院材料。"
        )

    def _generic_action_plan(self, scope: Dict[str, Any]) -> List[Dict[str, Any]]:
        task_type = scope.get("task_type") or "general_legal_research"
        issues = [issue for issue in (scope.get("issue_tree") or []) if isinstance(issue, dict)]
        actions: List[Tuple[str, str, str, str]] = [
            ("ACT01", "P0", "用户", "完整保存原始证据，包括合同或委托记录、付款凭证、聊天记录、照片视频、平台链接、转发记录、投诉回执和对方主张材料。"),
            ("ACT02", "P0", "用户", "按时间线整理事件经过，标明每个事实对应的原始证据、证据来源、取得时间和目前是否仍可访问。"),
            ("ACT03", "P0", "用户", "立即停止会扩大责任或损失的行为，并对已经扩散的内容、款项、材料或争议对象采取可证明的止损措施。"),
        ]
        for index, issue in enumerate(issues[:3], start=4):
            seed = _normalize_spaces(issue.get("question") or "核心争议")[:42]
            priority = issue.get("priority") if issue.get("priority") in {"P0", "P1", "P2", "P3"} else "P1"
            actions.append((f"ACT{index:02d}", priority, "用户", f"围绕“{seed}”补充关键材料，并把可确认事实、待核验事实和推测性说法分开整理。"))
        actions.extend([
            ("ACT07", "P1", "用户", "向相对方或平台发送书面沟通、删除、退款、赔偿、澄清或停止侵害请求，明确事实依据、法律依据、处理期限和保留追责权利。"),
            ("ACT08", "P1", "用户/律师", "根据证据强弱选择协商、投诉、调解、仲裁、诉讼、行政举报或报警路径，并先核验管辖、时效、主体和请求事项。"),
            ("ACT09", "P2", "用户", f"围绕 {task_type} 建立后续预防清单，把授权、验收、保密、付款节点、违约责任、平台处理和争议解决写成可留痕规则。"),
        ])
        deduped = []
        seen = set()
        for aid, priority, owner, desc in actions:
            if desc in seen:
                continue
            seen.add(desc)
            deduped.append({"action_id": aid, "priority": priority, "owner": owner, "description": desc, "depends_on": []})
        return deduped[:9]

    def _collect_missing_materials(self, scope: Dict[str, Any], evidence_matrix: Dict[str, Any], source_pack: Dict[str, Any]) -> List[str]:
        missing = list(scope.get("facts_missing") or []) + list(evidence_matrix.get("missing_materials") or []) + list(source_pack.get("unresolved_source_gaps") or [])
        for issue in evidence_matrix.get("issue_evidence_matrix") or []:
            if isinstance(issue, dict):
                missing.extend(issue.get("missing_evidence") or [])
        return _dedupe_list(missing)

    def _build_report(
        self,
        scope: Dict[str, Any],
        source_pack: Dict[str, Any],
        evidence_matrix: Dict[str, Any],
        issue_analysis: List[Dict[str, Any]],
        risk_register: List[Dict[str, Any]],
        action_plan: List[Dict[str, Any]],
        human_review: Dict[str, Any],
        privacy_task: bool = False,
    ) -> str:
        title = "法律风控深度研究报告"
        jurisdiction = (scope.get("jurisdiction") or {}).get("primary") or "中国大陆"
        sources = [source for source in (source_pack.get("issue_sources") or []) if isinstance(source, dict)]
        load_sources = [source for source in sources if source.get("use_for_load_bearing")]
        case_sources = [
            source for source in sources
            if str(source.get("source_kind", "")).lower() in {"case", "penalty"}
            or any(term in f"{source.get('title', '')} {source.get('exact_quote', '')}" for term in ["案例", "判决", "裁判", "处罚"])
        ]
        source_text = _format_source_list(load_sources)
        case_text = _format_source_list(case_sources) if case_sources else "- 本轮尚未取得可直接比附的官方案例或裁判文书；建议后续围绕争议类型、地域、案由和关键词继续补充案例检索。"
        facts = evidence_matrix.get("facts") or []
        fact_text = "\n".join(f"- {_normalize_spaces(fact.get('statement', ''))[:420]}" for fact in facts[:10]) or "- 用户陈述事实较少，以下分析以用户问题中已经提供的事实为基础。"
        source_by_id = {source.get("source_id"): source for source in sources if source.get("source_id")}

        issue_sections = []
        for item in issue_analysis:
            source_labels = [_source_label(source_by_id[source_id]) for source_id in item.get("source_ids", []) if source_id in source_by_id]
            source_label_text = "；".join(source_labels) if source_labels else "本项仍需补充精确法源或类案。"
            evidence_text = "、".join(item.get("evidence_ids") or []) or "待补充"
            certainty = item.get("certainty") or "pending_verification"
            certainty_text = "可以作初步判断" if certainty in {"high", "medium"} else "只能作待核验判断"
            issue_sections.append(
                f"### {item.get('conclusion') or '核心争点'}\n"
                f"**结论**：{item.get('conclusion') or '该争点需要重点处理'}，目前{certainty_text}。\n\n"
                f"**事实基础**：主要依据用户陈述及已编目证据（{evidence_text}）。\n\n"
                f"**适用依据**：{source_label_text}\n\n"
                f"**分析边界**：{item.get('reasoning') or '需结合完整材料、损害后果、相对方主张和可验证法源进一步判断。'}\n\n"
                f"**处理方向**：先固定原始证据和传播/履行/损害时间线，再围绕该争点选择沟通、投诉、调解、诉讼、行政举报或报警等路径。"
            )
        issue_text = "\n\n".join(issue_sections) or "### 核心问题\n当前事实不足以展开分项判断，应先补齐材料后再评估。"

        risk_rows = "\n".join(
            f"| {r.get('risk_id')} | {r.get('title')} | {r.get('level')} | {r.get('priority')} | {', '.join(r.get('source_ids', [])) or '待核验'} | {', '.join(r.get('evidence_ids', [])) or '待补'} |"
            for r in risk_register
        ) or "| R01 | 核心事实和法源仍待补强 | note | P1 | 待核验 | 待补 |"
        action_lines = "\n".join(f"- {a.get('priority')}：{a.get('description')}" for a in action_plan) or "- P0：先固定证据、停止扩大风险，并补充关键材料。"
        gaps = _dedupe_missing_materials((human_review.get("reasons") or []) + (evidence_matrix.get("missing_materials") or []) + (source_pack.get("unresolved_source_gaps") or []))
        gap_text = "\n".join(f"- {gap}" for gap in gaps[:10]) or "- 本轮未发现会立即改变初步判断的关键缺口；后续出现新证据时应更新结论。"

        report = f"""# {title}

## 核心结论
基于当前事实和已取得的法源，本案应放在{jurisdiction}法律框架下，围绕权利基础、责任主体、行为边界、损害后果、证据强弱和救济路径展开。现阶段可以给出初步法律判断，但凡涉及具体赔偿金额、行政或刑事边界、平台或第三方责任、是否已经造成实际损害的部分，仍需用原始证据继续补强。

这份报告不展示研究过程，而是直接面向用户说明：哪些主张最可能成立，哪些结论需要谨慎，哪些材料会影响最终判断，以及现在应该怎样止损、留痕、沟通和推进救济。

## 事实基础
{fact_text}

## 法律依据与类案参考
### 可承载结论的法律依据
{source_text}

### 类案与裁判参考
{case_text}

类案和裁判材料的作用，是帮助判断法院或监管机关通常如何看待类似事实，而不是机械套用结果。若本轮只取得规则原文而案例不足，后续应继续围绕本案关键词补充最高法典型案例、人民法院案例库、裁判文书、监管处罚或平台处理规则。

## 分项法律分析
{issue_text}

## 责任边界和证据强弱
1. **主观目的不是免责理由**：没有营利、没有恶意、只是开玩笑，通常可以影响过错程度、赔偿金额或和解空间，但不能当然排除侵权、违约或合规责任。
2. **传播范围会放大后果**：从小范围传播扩散到公司群、平台、客户或公共网络时，删除难度、损害范围、精神损害和公开澄清需求都会提高。
3. **证据决定结论强度**：聊天记录、原始文件、平台链接、播放量、评论、投诉回执、删除记录、对方损害证明等，会直接影响责任成立、赔偿金额和救济路径。
4. **第三方责任需单独判断**：平台、转发者、合作方或服务商是否担责，要看其是否知道侵权、是否收到通知、是否及时删除、是否继续传播或获利。

## 风险与主张清单
| Risk ID | 风险或主张 | 等级 | 优先级 | 法源 | 证据 |
|---|---|---|---|---|---|
{risk_rows}

## 行动建议
{action_lines}

## 待核验材料
{gap_text}
"""
        return _ensure_final_ai_note(report)


class QualityRoutingAgent(ArtifactAgent):
    artifact_key = "qa_verdict"
    agent_code = "A5"
    next_agent = "END"
    system_prompt = A5_QA_SYSTEM_PROMPT

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__("QualityRoutingAgent", "质量评估与路由 Agent", llm_api_key, llm_base_url, model)

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_artifact_state_defaults(state)
        start = time.time()
        self.add_message(state, "agent_start", "A5 质量评估与路由：生成 qa_verdict")
        scope = get_artifact_writes(state, "scope_brief")
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        analysis_draft = get_artifact_writes(state, "analysis_draft")
        user_prompt = A5_QA_USER_PROMPT.format(
            task_id=state.get("session_id", ""),
            scope_brief_json=_json(scope),
            source_pack_json=_json(source_pack),
            evidence_matrix_json=_json(evidence_matrix),
            analysis_draft_json=_json(analysis_draft),
            schema=schema_hint("qa_verdict"),
        )
        deterministic = self._deterministic_verdict(state)
        try:
            artifact = await self._call_json(self._system_prompt(), user_prompt, temperature=0.1)
            artifact = _coerce_qa_shape(artifact)
            artifact = validate_artifact(self.artifact_key, artifact)
            artifact = self._normalize_llm_verdict(state, artifact)
            artifact = self._merge_hard_gates(artifact, deterministic)
        except Exception as exc:
            self.logger.warning("A5 fallback used: %s", exc)
            artifact = deterministic
        duration = int((time.time() - start) * 1000)
        self.add_log(state, "quality_routing", "all artifacts", "qa_verdict ready", duration)
        route = artifact.get("writes", {}).get("route", {})
        state["route_instruction"] = route
        verdict = artifact.get("writes", {}).get("verdict")
        if route.get("next_agent") == "END" or verdict in {"approved", "approved_with_human_review"}:
            state["phase"] = ResearchPhase.COMPLETED.value
        return self._finalize(state, artifact, f"审查完成，verdict={verdict}，route={route.get('next_agent')}")

    def _normalize_llm_verdict(self, state: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
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
        next_agent = route.get("next_agent")
        if verdict in {"approved", "approved_with_human_review"}:
            next_agent = "END"
        elif next_agent not in {"A1", "A2", "A3", "A4"}:
            issue_routes = [issue.get("route_to") for issue in writes.get("issues") or [] if isinstance(issue, dict)]
            next_agent = next((item for item in issue_routes if item in {"A1", "A2", "A3", "A4"}), "A4")
        writes["route"] = {
            "next_agent": next_agent,
            "instruction": route.get("instruction") or ("通过。" if next_agent == "END" else "按质量评估意见返工。"),
        }
        artifact.setdefault("handoff", {})["next_agent"] = next_agent
        return validate_artifact(self.artifact_key, artifact)

    def _deterministic_verdict(self, state: Dict[str, Any]) -> Dict[str, Any]:
        source_pack = get_artifact_writes(state, "source_pack")
        evidence_matrix = get_artifact_writes(state, "evidence_matrix")
        analysis = get_artifact_writes(state, "analysis_draft")
        report = analysis.get("report_markdown", "")
        sources = [s for s in source_pack.get("issue_sources", []) if isinstance(s, dict)]
        source_ids = {s.get("source_id") for s in sources if s.get("source_id")}
        evidence_ids = {e.get("evidence_id") for e in evidence_matrix.get("evidence_items", []) if e.get("evidence_id")}
        hard_failures: List[str] = []
        issues: List[Dict[str, str]] = []

        def add_failure(kind: str, message: str, route_to: str = "A4") -> None:
            hard_failures.append(message)
            issues.append({"severity": "critical", "type": kind, "message": message, "route_to": route_to})

        if not _report_has_final_ai_note(report):
            add_failure("missing_final_ai_note", "报告缺少唯一固定结尾：AI生成，仅供参考。")
        if _has_over_disclaimer(report):
            add_failure("over_disclaimer", "报告存在过度免责声明。")
        if _contains_internal_report_terms(report):
            add_failure("internal_terms", "报告向用户暴露内部流程字段。")
        if not _report_has_core_modules(report):
            add_failure("missing_core_modules", "报告缺少核心结论、法律依据、行动建议或固定结尾。")
        if _has_repeated_actions(analysis.get("action_plan") or []):
            add_failure("thin_actions", "行动方案重复或少于 6 条具体动作。")
        if evidence_matrix.get("missing_materials") and "暂无额外待核验事项" in report:
            add_failure("missing_material_contradiction", "存在证据缺口但报告声称无待核验事项。")
        for source in sources:
            if source.get("use_for_load_bearing") and not _source_supports_report(source):
                add_failure("source_pinpoint", f"{source.get('source_id')} 被标记为承载结论来源，但缺少精确条文定位或规则原文。", "A2")
        used_source_ids = set()
        used_evidence_ids = set()
        for item in analysis.get("issue_analysis", []) or []:
            if isinstance(item, dict):
                used_source_ids.update(item.get("source_ids") or [])
                used_evidence_ids.update(item.get("evidence_ids") or [])
        for risk in analysis.get("risk_register", []) or []:
            if isinstance(risk, dict):
                used_source_ids.update(risk.get("source_ids") or [])
                used_evidence_ids.update(risk.get("evidence_ids") or [])
                if _risk_title_is_question(risk.get("title", "")):
                    add_failure("risk_title_question", f"{risk.get('risk_id')} 风险标题是问句。")
        outside_sources = [source_id for source_id in used_source_ids if source_id not in source_ids]
        outside_evidence = [evidence_id for evidence_id in used_evidence_ids if evidence_id not in evidence_ids]
        if outside_sources:
            add_failure("outside_source", f"报告使用 source_pack 外来源：{', '.join(outside_sources)}", "A2")
        if outside_evidence:
            add_failure("outside_evidence", f"报告使用 evidence_matrix 外证据：{', '.join(outside_evidence)}", "A3")

        next_agent = issues[0]["route_to"] if issues else "END"
        verdict = "needs_research" if next_agent == "A2" else "needs_evidence_rebuild" if next_agent == "A3" else "needs_revision" if issues else "approved"
        score = 0.0 if hard_failures else 100.0
        return make_envelope(
            agent="A5",
            artifact_id=_artifact_id(state.get("session_id", ""), "qa_verdict", state.get("iteration", 0)),
            writes={
                "score_total": score,
                "dimension_scores": {
                    "jurisdiction_scope": 15 if not hard_failures else 0,
                    "source_accuracy": 25 if not hard_failures else 0,
                    "evidence_closure": 15 if not hard_failures else 0,
                    "phase_discipline": 15 if not hard_failures else 0,
                    "reasoning_quality": 15 if not hard_failures else 0,
                    "readability": 15 if not hard_failures else 0,
                },
                "hard_failures": hard_failures,
                "issues": issues,
                "verdict": verdict,
                "route": {"next_agent": next_agent, "instruction": "通过。" if next_agent == "END" else "修复结构性硬失败。"},
            },
            next_agent=next_agent,
            reason="完成结构性护栏检查。",
            status="hard_fail" if hard_failures else "ok",
            confidence=0.9,
        )

    def _merge_hard_gates(self, llm_artifact: Dict[str, Any], deterministic: Dict[str, Any]) -> Dict[str, Any]:
        det_writes = deterministic.get("writes", {})
        if det_writes.get("hard_failures"):
            return deterministic
        return llm_artifact
