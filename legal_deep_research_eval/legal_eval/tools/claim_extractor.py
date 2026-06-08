"""Rule-based critical claim extraction."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .report_parser import LAW_CIT_RE, SOURCE_ID_RE


CLAIM_PATTERNS = (
    r"(构成|不构成|适用|不适用)",
    r"(高风险|重大风险|中风险|低风险)",
    r"(应当|建议|需要|必须)",
    r"(可能导致|可能承担|面临)",
)


class ClaimExtractorTool:
    def extract_by_rules(self, report_markdown: str) -> List[Dict[str, Any]]:
        text = report_markdown or ""
        sentences = self._split_sentences(text)
        claims: List[Dict[str, Any]] = []
        for sentence, start, end in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            if not self._is_claim(stripped):
                continue
            claim_id = f"C{len(claims) + 1:03d}"
            claims.append(
                {
                    "claim_id": claim_id,
                    "text": stripped,
                    "claim_type": self._claim_type(stripped),
                    "importance": self._importance(stripped),
                    "section": "",
                    "linked_citations": SOURCE_ID_RE.findall(stripped) + LAW_CIT_RE.findall(stripped),
                    "source_span": {"start": start, "end": end},
                }
            )
        return claims

    def extract(self, report_markdown: str) -> List[Dict[str, Any]]:
        return self.extract_by_rules(report_markdown)

    def _split_sentences(self, text: str) -> List[tuple[str, int, int]]:
        parts: List[tuple[str, int, int]] = []
        start = 0
        for match in re.finditer(r"[。！？!?]\s*|\n+", text):
            end = match.end()
            part = text[start:end].strip()
            if part:
                parts.append((part, start, end))
            start = end
        if start < len(text):
            part = text[start:].strip()
            if part:
                parts.append((part, start, len(text)))
        return parts

    def _is_claim(self, sentence: str) -> bool:
        return bool(
            any(re.search(pattern, sentence) for pattern in CLAIM_PATTERNS)
            or LAW_CIT_RE.search(sentence)
        )

    def _claim_type(self, sentence: str) -> str:
        if re.search(r"(高风险|重大风险|中风险|低风险|风险)", sentence):
            return "risk_conclusion"
        if LAW_CIT_RE.search(sentence) or re.search(r"(适用|不适用|构成|不构成)", sentence):
            return "legal_conclusion"
        if re.search(r"(建议|整改|修订|补充)", sentence):
            return "recommendation"
        return "factual_or_process_claim"

    def _importance(self, sentence: str) -> str:
        if re.search(r"(高风险|重大风险|必须|一定|必然|严重)", sentence):
            return "high"
        if re.search(r"(中风险|建议|需要|可能)", sentence):
            return "medium"
        return "low"
