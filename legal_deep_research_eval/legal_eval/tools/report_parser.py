"""Deterministic Markdown report parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List


DISCLAIMER_RE = re.compile(r"(不构成(正式)?法律意见|仅供.{0,12}参考|应咨询(执业)?律师|需由.{0,12}(律师|法务)复核)")
LAW_CIT_RE = re.compile(r"《[^》]{2,50}》第[一二三四五六七八九十百千万零〇0-9]+条")
CASE_NO_RE = re.compile(r"（\d{4}）[^\s，。；、]{1,40}号")
SOURCE_ID_RE = re.compile(r"\[(source_[A-Za-z0-9_-]+|law_[A-Za-z0-9_-]+|case_[A-Za-z0-9_-]+|E\d+|R\d+)\]")


class ReportParserTool:
    def parse(self, report_markdown: str) -> Dict[str, Any]:
        text = report_markdown or ""
        lines = text.splitlines()
        headings: List[Dict[str, Any]] = []
        for idx, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                headings.append({"level": len(match.group(1)), "heading": match.group(2).strip(), "line": idx})

        sections: List[Dict[str, Any]] = []
        for pos, heading in enumerate(headings):
            start = heading["line"] + 1
            end = headings[pos + 1]["line"] if pos + 1 < len(headings) else len(lines)
            sections.append({**heading, "content": "\n".join(lines[start:end]).strip()})

        title = ""
        if headings and headings[0]["level"] == 1:
            title = headings[0]["heading"]
        elif headings:
            title = headings[0]["heading"]

        paragraphs = [para.strip() for para in re.split(r"\n\s*\n", text) if para.strip()]
        table_blocks = self._extract_tables(lines)
        risk_mentions = [para for para in paragraphs if "风险" in para]
        action_items = [
            para
            for para in paragraphs
            if re.search(r"(建议|整改|修订|补充|完善|优先|期限|责任人|措施)", para)
        ]
        disclaimer_candidates = [para for para in paragraphs if DISCLAIMER_RE.search(para)]
        citation_markers = self._extract_citations(text)
        return {
            "title": title,
            "sections": sections,
            "tables": table_blocks,
            "risk_mentions": risk_mentions,
            "citation_markers": citation_markers,
            "disclaimer_candidates": disclaimer_candidates,
            "action_items": action_items,
            "paragraph_count": len(paragraphs),
            "char_count": len(text),
        }

    def _extract_tables(self, lines: List[str]) -> List[str]:
        tables: List[str] = []
        current: List[str] = []
        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                current.append(line)
            elif current:
                tables.append("\n".join(current))
                current = []
        if current:
            tables.append("\n".join(current))
        return tables

    def _extract_citations(self, text: str) -> List[Dict[str, str]]:
        citations: List[Dict[str, str]] = []
        for match in SOURCE_ID_RE.finditer(text):
            citations.append({"type": "source_id", "text": match.group(1)})
        for match in LAW_CIT_RE.finditer(text):
            citations.append({"type": "law", "text": match.group(0)})
        for match in CASE_NO_RE.finditer(text):
            citations.append({"type": "case_no", "text": match.group(0)})
        return citations
