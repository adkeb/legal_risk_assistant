"""Jurisdiction and law-version checks."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from ..utils import get_task_jurisdictions, normalize_jurisdiction, parse_date, ratio, task_allows_cross_border


BOUNDARY_TERMS = ("比较法", "参考法域", "不直接适用", "仅供参考", "并行影响法域", "辅助分析")


class JurisdictionVersionCheckerTool:
    def verify(
        self,
        task_meta: Dict[str, Any],
        source_index: List[Dict[str, Any]],
        report_markdown: str,
        run_date: date | None = None,
    ) -> Dict[str, Any]:
        run_date = run_date or date.today()
        task_jurisdictions = set(get_task_jurisdictions(task_meta))
        cross_border = task_allows_cross_border(task_meta)
        has_boundary = any(term in (report_markdown or "") for term in BOUNDARY_TERMS)

        jurisdiction_sources = [
            src for src in source_index if normalize_jurisdiction(src.get("jurisdiction")) != "unknown"
        ]
        wrong_sources: List[Dict[str, Any]] = []
        matched = 0
        for source in jurisdiction_sources:
            jur = normalize_jurisdiction(source.get("jurisdiction"))
            if jur in task_jurisdictions or cross_border:
                matched += 1
            else:
                wrong_sources.append(
                    {
                        "source_id": source.get("source_id"),
                        "jurisdiction": jur,
                        "title": source.get("title", ""),
                    }
                )

        expired: List[Dict[str, Any]] = []
        valid_count = 0
        version_checked = 0
        for source in source_index:
            effective_to = parse_date(source.get("effective_to"))
            validity_status = str(source.get("validity_status") or "").lower()
            if effective_to or validity_status:
                version_checked += 1
            if effective_to and effective_to < run_date or validity_status in {"expired", "invalid", "失效", "废止"}:
                title = str(source.get("title", ""))
                historical = any(term in report_markdown for term in ("历史版本", "修订前", "旧案", "历史对比", title + "（历史"))
                if not historical:
                    expired.append({"source_id": source.get("source_id"), "title": title})
            else:
                if effective_to or validity_status:
                    valid_count += 1

        jurisdiction_match_rate = ratio(matched, len(jurisdiction_sources), default=1.0)
        version_match_rate = ratio(valid_count, version_checked, default=1.0)
        boundary_problem = cross_border and not has_boundary and len(task_jurisdictions) > 1
        return {
            "jurisdiction_match": not wrong_sources and not boundary_problem,
            "law_version_match": not expired,
            "jurisdiction_match_rate": jurisdiction_match_rate,
            "effective_version_match_rate": version_match_rate,
            "wrong_jurisdiction_sources": wrong_sources,
            "expired_sources_used_as_current": expired,
            "cross_border": cross_border,
            "has_boundary_statement": has_boundary,
            "boundary_warning": boundary_problem,
        }
