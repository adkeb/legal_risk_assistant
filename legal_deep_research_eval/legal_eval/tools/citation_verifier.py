"""Citation and source-index alignment checks."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..utils import normalize_text, ratio
from .report_parser import CASE_NO_RE, LAW_CIT_RE, SOURCE_ID_RE


class CitationVerifierTool:
    def verify(
        self,
        report_markdown: str,
        source_index: List[Dict[str, Any]],
        claims: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        text = report_markdown or ""
        claims = claims or []
        citations = self.extract_citations(text)
        matched = []
        unmatched = []
        for citation in citations:
            match = self._match_citation(citation, source_index)
            if match:
                matched.append({**citation, "matched_source_id": match.get("source_id")})
            else:
                unmatched.append(citation)
        source_id_citations = [c for c in citations if c["type"] == "source_id"]
        pinpoint = [c for c in citations if c["type"] in {"law", "case_no", "source_id"}]
        critical_claims = [claim for claim in claims if claim.get("importance") in {"high", "medium"}]
        cited_claims = [claim for claim in critical_claims if claim.get("linked_citations")]
        return {
            "citation_validity": bool(citations) and bool(source_index) and not unmatched,
            "num_citations_found": len(citations),
            "num_citations_matched": len(matched),
            "citation_match_rate": ratio(len(matched), len(citations), default=1.0 if not citations else 0.0),
            "pinpoint_citation_rate": ratio(len(pinpoint), len(citations), default=1.0),
            "critical_claim_citation_coverage": ratio(len(cited_claims), len(critical_claims), default=1.0),
            "unmatched_citations": unmatched,
            "matched_citations": matched,
            "source_id_citation_count": len(source_id_citations),
            "warnings": [] if source_index else [{"code": "SOURCE_INDEX_MISSING", "message": "source_index is empty"}],
        }

    def extract_citations(self, text: str) -> List[Dict[str, str]]:
        citations: List[Dict[str, str]] = []
        for match in SOURCE_ID_RE.finditer(text or ""):
            citations.append({"type": "source_id", "text": match.group(1)})
        for match in LAW_CIT_RE.finditer(text or ""):
            raw = match.group(0)
            title_match = re.match(r"《([^》]+)》第(.+条)", raw)
            citations.append(
                {
                    "type": "law",
                    "text": raw,
                    "title": title_match.group(1) if title_match else raw,
                    "article_no": title_match.group(2) if title_match else "",
                }
            )
        for match in CASE_NO_RE.finditer(text or ""):
            citations.append({"type": "case_no", "text": match.group(0), "case_no": match.group(0)})
        return citations

    def _match_citation(self, citation: Dict[str, str], source_index: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not source_index:
            return None
        ctype = citation.get("type")
        ctext = normalize_text(citation.get("text"))
        if ctype == "source_id":
            for source in source_index:
                if normalize_text(source.get("source_id")) == ctext:
                    return source
        if ctype == "law":
            title = normalize_text(citation.get("title"))
            article = normalize_text(citation.get("article_no"))
            for source in source_index:
                source_title = normalize_text(source.get("title"))
                source_article = normalize_text(source.get("article_no") or source.get("span"))
                if title and title in source_title or source_title and source_title in title:
                    if not article or not source_article or article in source_article or source_article in article:
                        return source
        if ctype == "case_no":
            case_no = normalize_text(citation.get("case_no"))
            for source in source_index:
                if case_no and case_no == normalize_text(source.get("case_no")):
                    return source
        return None
