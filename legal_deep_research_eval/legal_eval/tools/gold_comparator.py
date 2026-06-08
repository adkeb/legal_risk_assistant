"""Gold key-point coverage checks."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..utils import normalize_text, ratio


class GoldComparatorTool:
    def compare(self, report_markdown: str, gold_reference: Dict[str, Any] | None) -> Dict[str, Any]:
        if not gold_reference:
            return {
                "required_points_recall": 1.0,
                "critical_omission_count": 0,
                "covered_points": [],
                "missing_points": [],
                "warnings": [{"code": "GOLD_REFERENCE_MISSING", "message": "gold_reference is not provided"}],
            }
        points = gold_reference.get("must_cover_points") or gold_reference.get("expected_answer_points") or []
        covered: List[str] = []
        missing: List[str] = []
        for point in points:
            if self._point_covered(str(point), report_markdown):
                covered.append(str(point))
            else:
                missing.append(str(point))
        return {
            "required_points_recall": ratio(len(covered), len(points), default=1.0),
            "critical_omission_count": len(missing),
            "covered_points": covered,
            "missing_points": missing,
            "warnings": [],
        }

    def _point_covered(self, point: str, report: str) -> bool:
        report_norm = normalize_text(report)
        point_norm = normalize_text(point)
        if point_norm and point_norm in report_norm:
            return True
        terms = [
            term
            for term in re.split(r"[，。；、：:（）() /\-]+", point)
            if len(term.strip()) >= 2 and term.strip() not in {"应识别", "应检查", "应指出", "应提示", "不能直接"}
        ]
        if not terms:
            return False
        hits = sum(1 for term in terms if normalize_text(term) in report_norm)
        return hits >= max(1, min(3, len(terms) // 2))
