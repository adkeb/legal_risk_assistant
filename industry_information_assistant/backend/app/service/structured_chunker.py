"""Structure-aware chunking for legal RAG ingestion."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


LEGAL_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百千万零〇\d]+[章节条款项]|[一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）|\(\d+\))"
)
CASE_HEADING_RE = re.compile(r"^(裁判要旨|基本案情|裁判理由|裁判结果|争议焦点|法院认为|本院认为)[:：]?$")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")


@dataclass
class StructuredChunk:
    content: str
    content_hash: str
    chunk_index: int
    page_no: Optional[int]
    section_title: str
    parser_method: str
    quality_score: float
    source_artifact_path: Optional[str]


def make_content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def chunk_parsed_text(
    text: str,
    *,
    parser_method: str,
    page_no: Optional[int] = None,
    quality_score: float = 100.0,
    source_artifact_path: Optional[str] = None,
    start_index: int = 0,
    target_min_chars: int = 300,
    target_max_chars: int = 800,
    overlap_chars: int = 80,
) -> List[StructuredChunk]:
    """Chunk text while preserving legal article/case section boundaries when possible."""
    blocks = list(_iter_blocks(text))
    chunks: List[StructuredChunk] = []
    current: List[str] = []
    current_title = ""

    def flush(force_title: Optional[str] = None) -> None:
        nonlocal current, current_title
        content = "\n\n".join(part.strip() for part in current if part.strip()).strip()
        current = []
        if not content:
            return
        title = force_title or current_title
        if len(content) <= target_max_chars:
            chunks.append(_new_chunk(content, start_index + len(chunks), page_no, title, parser_method, quality_score, source_artifact_path))
            return
        for piece in _split_long_text(content, target_max_chars, overlap_chars):
            chunks.append(_new_chunk(piece, start_index + len(chunks), page_no, title, parser_method, quality_score, source_artifact_path))

    for block in blocks:
        heading = _heading_text(block)
        is_boundary = bool(heading)
        if is_boundary:
            if current and _char_len("\n\n".join(current)) >= target_min_chars:
                flush()
            current_title = heading

        block_len = _char_len(block)
        current_len = _char_len("\n\n".join(current))
        if current and current_len + block_len > target_max_chars and current_len >= target_min_chars:
            flush()
        current.append(block)

    flush()
    if not chunks and text.strip():
        chunks.append(_new_chunk(text.strip()[:target_max_chars], start_index, page_no, "", parser_method, quality_score, source_artifact_path))
    return chunks


def _new_chunk(
    content: str,
    chunk_index: int,
    page_no: Optional[int],
    section_title: str,
    parser_method: str,
    quality_score: float,
    source_artifact_path: Optional[str],
) -> StructuredChunk:
    return StructuredChunk(
        content=content,
        content_hash=make_content_hash(content),
        chunk_index=chunk_index,
        page_no=page_no,
        section_title=section_title[:512] if section_title else "",
        parser_method=parser_method,
        quality_score=quality_score,
        source_artifact_path=source_artifact_path,
    )


def _iter_blocks(text: str) -> Iterable[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = _inject_boundaries(normalized)
    for block in re.split(r"\n\s*\n+", normalized):
        block = block.strip()
        if block:
            yield block


def _inject_boundaries(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and (LEGAL_HEADING_RE.match(stripped) or CASE_HEADING_RE.match(stripped)):
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(stripped)
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def _heading_text(block: str) -> str:
    first = block.splitlines()[0].strip()
    md = MARKDOWN_HEADING_RE.match(first)
    if md:
        return md.group(1).strip()
    if CASE_HEADING_RE.match(first):
        return first.rstrip("：:")
    if LEGAL_HEADING_RE.match(first):
        return first[:80]
    return ""


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> Iterable[str]:
    text = text.strip()
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            punctuation = max(text.rfind("。", start, end), text.rfind("\n", start, end), text.rfind("；", start, end))
            if punctuation > start + max_chars // 2:
                end = punctuation + 1
        piece = text[start:end].strip()
        if piece:
            yield piece
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)


def _char_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))
