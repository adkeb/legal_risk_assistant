"""Retrieval quality metrics."""

from __future__ import annotations

from typing import Any, Dict, List

from ..utils import ratio


AUTHORITY_TYPES = {"law", "regulation", "judicial_interpretation", "court_decision", "regulator_guidance", "law/regulation"}
LOW_QUALITY_MARKERS = ("喜马拉雅", "华律", "律图", "原创力", "道客", "人人文库", "110网", "博客园")


class RetrievalMetricsTool:
    def compute(self, source_index: List[Dict[str, Any]], process_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
        process_result = process_result or {}
        source_types = [str(src.get("source_type", "unknown")).lower() for src in source_index]
        authority_count = sum(1 for src in source_index if self._is_authority(src))
        low_quality_count = sum(1 for src in source_index if self._is_low_quality(src))
        return {
            "source_type_coverage": len(set(source_types)),
            "official_source_ratio": ratio(authority_count, len(source_index), default=0.0),
            "authority_source_ratio": ratio(authority_count, len(source_index), default=0.0),
            "low_quality_source_ratio": ratio(low_quality_count, len(source_index), default=0.0),
            "unique_source_count": len(source_index),
            "legal_source_count": sum(1 for t in source_types if "law" in t or "regulation" in t),
            "case_source_count": sum(1 for t in source_types if "case" in t or "court" in t),
            "contract_source_count": sum(1 for t in source_types if "contract" in t or "clause" in t),
            "enforcement_source_count": sum(1 for t in source_types if "enforcement" in t or "penalty" in t),
            "num_search_calls": process_result.get("num_search_calls", 0),
            "unique_queries": process_result.get("unique_queries", 0),
        }

    def _is_authority(self, source: Dict[str, Any]) -> bool:
        stype = str(source.get("source_type", "")).lower()
        title = str(source.get("title", ""))
        url = str(source.get("url", "")).lower()
        return any(t in stype for t in AUTHORITY_TYPES) or ".gov" in url or "法院" in title or "监管" in title

    def _is_low_quality(self, source: Dict[str, Any]) -> bool:
        text = f"{source.get('title', '')} {source.get('url', '')} {source.get('source', '')}"
        return any(marker in text for marker in LOW_QUALITY_MARKERS)
