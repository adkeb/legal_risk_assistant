"""Small shared helpers for legal workflow agents."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List


SCOPE_DEFINITION = "scope_definition"
SOURCE_VERIFICATION = "source_verification"
EVIDENCE_CATALOG = "evidence_catalog"
LEGAL_ANALYSIS_DRAFT = "legal_analysis_draft"
QUALITY_ROUTING = "quality_routing"
END = "END"

ROUTABLE_AGENT_IDS = {
    SCOPE_DEFINITION,
    SOURCE_VERIFICATION,
    EVIDENCE_CATALOG,
    LEGAL_ANALYSIS_DRAFT,
}

NEXT_AGENT_IDS = ROUTABLE_AGENT_IDS | {QUALITY_ROUTING, END}

FINAL_AI_NOTE = "AI生成，仅供参考"


def to_json(data: Any, limit: int = 24000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) > limit:
        return text[:limit] + "\n...（内容过长已截断）"
    return text


def artifact_id(session_id: str, artifact_key: str, iteration: int = 0) -> str:
    return f"{session_id or 'session'}:{artifact_key}:v{iteration + 1}"


def material_manifest(state: Dict[str, Any]) -> List[Dict[str, str]]:
    query = state.get("query", "")
    return [{"material_id": "MATERIAL_USER_QUERY", "type": "user_query", "status": "read", "summary": query[:200]}]


def material_text(state: Dict[str, Any]) -> str:
    return f"MATERIAL_USER_QUERY:\n{state.get('query', '')}"


def contains_unread_placeholder(text: str) -> bool:
    return bool(re.search(r"\[(PDF|Word|图片|Image|Document|文件)[^\]]*:\s*[^\]]*\]", text or "", re.I))


def normalize_spaces(text: Any) -> str:
    return " ".join(str(text or "").split())


def dedupe_strings(items: Iterable[Any], limit: int = 50) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items or []:
        text = normalize_spaces(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def ensure_final_ai_note(report: str) -> str:
    cleaned_lines = []
    for line in (report or "").splitlines():
        stripped = line.strip()
        if FINAL_AI_NOTE in stripped:
            continue
        if not stripped and (not cleaned_lines or not cleaned_lines[-1]):
            continue
        cleaned_lines.append(line.rstrip())
    cleaned = "\n".join(cleaned_lines).strip()
    return f"{cleaned}\n\n{FINAL_AI_NOTE}\n" if cleaned else f"{FINAL_AI_NOTE}\n"


def has_final_ai_note(report: str) -> bool:
    lines = [line.strip() for line in (report or "").strip().splitlines() if line.strip()]
    return bool(lines) and lines[-1] == FINAL_AI_NOTE and (report or "").count(FINAL_AI_NOTE) == 1


def is_load_bearing_source(source: Dict[str, Any]) -> bool:
    if not isinstance(source, dict) or not as_bool(source.get("use_for_load_bearing")):
        return False
    if source.get("source_tier") not in {"T1", "T2", "T3"}:
        return False
    if not normalize_spaces(source.get("url")):
        return False
    if normalize_spaces(source.get("article_or_section")) in {"", "待定位", "unknown"}:
        return False
    quote = normalize_spaces(source.get("exact_quote"))
    if not quote or "待核验" in quote or "仍需" in quote:
        return False
    return True


def source_pack_has_load_bearing(source_pack: Dict[str, Any]) -> bool:
    return any(is_load_bearing_source(source) for source in (source_pack.get("issue_sources") or []))


def strip_internal_report_markers(report: str) -> str:
    """Remove machine-only workflow markers from user-visible Markdown."""

    text = str(report or "")
    replacements = {
        "source_pack": "法源检索结果",
        "Source Pack": "法源检索结果",
        "evidence_matrix": "证据材料",
        "Evidence Matrix": "证据材料",
        "scope_brief": "问题定界结果",
        "analysis_draft": "分析草稿",
        "qa_verdict": "质量审查结果",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\b(?:GAP|ACT|I|F|E|M)\d{2,}\b", "", text)
    text = re.sub(r"（\s*(?:对应)?\s*(?:[,，、\s]*)\s*）", "", text)
    text = re.sub(r"\(\s*(?:对应)?\s*(?:[,，、\s]*)\s*\)", "", text)
    text = re.sub(r"[ \t]+([，。；：、）\)])", r"\1", text)
    text = re.sub(r"([（\(])[ \t]+", r"\1", text)
    return text


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def coerce_string_list(value: Any, limit: int = 50) -> List[str]:
    if isinstance(value, list):
        return dedupe_strings(value, limit=limit)
    if value in (None, ""):
        return []
    return dedupe_strings([value], limit=limit)


def clamp_priority(value: Any, default: str = "P1") -> str:
    text = normalize_spaces(value)
    return text if text in {"P0", "P1", "P2", "P3"} else default


def default_scores(score: float) -> Dict[str, float]:
    return {
        "jurisdiction_scope": min(15.0, score * 0.15),
        "source_accuracy": min(25.0, score * 0.25),
        "evidence_closure": min(15.0, score * 0.15),
        "phase_discipline": min(15.0, score * 0.15),
        "reasoning_quality": min(15.0, score * 0.15),
        "readability": min(15.0, score * 0.15),
    }
