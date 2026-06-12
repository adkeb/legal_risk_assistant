"""MinerU hybrid document parsing helpers."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TEST_MINERU_BIN = (
    PROJECT_ROOT
    / "ocr_chunk_comparison"
    / "20260612_ocr_vs_text_pdf_chunks"
    / ".mineru_venv"
    / "bin"
    / "mineru"
)


@dataclass
class MinerUPage:
    page_no: int
    markdown: str
    text: str
    blocks: List[Dict[str, Any]]
    box_count: int


@dataclass
class MinerUResult:
    pages: List[MinerUPage]
    output_dir: Path
    work_dir: Path
    markdown_path: Optional[Path]
    content_list_path: Optional[Path]
    content_list_v2_path: Optional[Path]
    middle_json_path: Optional[Path]
    model_json_path: Optional[Path]
    layout_pdf_path: Optional[Path]
    method: str


class MinerUParseError(RuntimeError):
    """Raised when MinerU cannot produce usable parsed output."""


def parse_with_mineru_hybrid(source_path: Path, *, output_dir: Optional[Path] = None) -> MinerUResult:
    """Run MinerU hybrid medium and return page-level Markdown/text."""
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="mineru_hybrid_"))
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        _mineru_bin(),
        "-p",
        str(source_path),
        "-o",
        str(output_dir),
        "-b",
        "hybrid-engine",
        "--effort",
        os.getenv("MINERU_HYBRID_EFFORT", "medium"),
        "-m",
        os.getenv("MINERU_PARSE_METHOD", "auto"),
        "-l",
        os.getenv("MINERU_LANG", "ch"),
    ]
    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", os.getenv("MINERU_MODEL_SOURCE", "modelscope"))
    timeout = _env_int("MINERU_TIMEOUT", 1800)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    if completed.returncode != 0:
        message = "\n".join(
            part.strip()
            for part in [completed.stdout[-2000:], completed.stderr[-2000:]]
            if part and part.strip()
        )
        raise MinerUParseError(f"MinerU hybrid failed for {source_path.name}: {message[:3000]}")

    result = load_mineru_result(output_dir)
    if not result.pages:
        raise MinerUParseError(f"MinerU hybrid produced no page text for {source_path.name}.")
    return result


def load_mineru_result(output_dir: Path) -> MinerUResult:
    """Load MinerU output files produced by the CLI."""
    md_path = _first_file(output_dir, "**/*.md")
    v2_path = _first_file(output_dir, "**/*_content_list_v2.json")
    content_path = _first_file(output_dir, "**/*_content_list.json")
    middle_path = _first_file(output_dir, "**/*_middle.json")
    model_path = _first_file(output_dir, "**/*_model.json")
    layout_path = _first_file(output_dir, "**/*_layout.pdf")
    work_dir = (md_path or v2_path or content_path or output_dir).parent

    pages = _pages_from_content_v2(v2_path) if v2_path else []
    if not pages and content_path:
        pages = _pages_from_content_list(content_path)
    if not pages and md_path:
        markdown = md_path.read_text(encoding="utf-8")
        pages = [MinerUPage(page_no=1, markdown=markdown, text=_markdown_to_plain_text(markdown), blocks=[], box_count=0)]

    return MinerUResult(
        pages=pages,
        output_dir=output_dir,
        work_dir=work_dir,
        markdown_path=md_path,
        content_list_path=content_path,
        content_list_v2_path=v2_path,
        middle_json_path=middle_path,
        model_json_path=model_path,
        layout_pdf_path=layout_path,
        method=f"mineru:hybrid:{os.getenv('MINERU_HYBRID_EFFORT', 'medium')}:{os.getenv('MINERU_PARSE_METHOD', 'auto')}",
    )


def render_pdf_pages(pdf_path: Path, output_dir: Path, *, prefix_name: str = "page", dpi: Optional[int] = None) -> List[Path]:
    if not shutil.which("pdftoppm"):
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob(f"{prefix_name}_*.png"):
        old.unlink()
    prefix = output_dir / prefix_name
    command = ["pdftoppm", "-png", "-r", str(dpi or _env_int("LOCAL_OCR_DPI", 200)), str(pdf_path), str(prefix)]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return []
    rendered = []
    for index, path in enumerate(sorted(output_dir.glob(f"{prefix_name}-*.png")), start=1):
        target = output_dir / f"{prefix_name}_{index}.png"
        path.rename(target)
        rendered.append(target)
    return rendered


def page_markdown_from_blocks(blocks: List[Dict[str, Any]]) -> str:
    parts = []
    for block in blocks:
        text = _block_to_markdown(block)
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _mineru_bin() -> str:
    configured = os.getenv("MINERU_BIN", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.exists() else configured
    found = shutil.which("mineru")
    if found:
        return found
    if DEFAULT_TEST_MINERU_BIN.exists():
        return str(DEFAULT_TEST_MINERU_BIN)
    raise MinerUParseError("MinerU executable not found. Install mineru==3.3.1 or set MINERU_BIN.")


def _pages_from_content_v2(path: Path) -> List[MinerUPage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages: List[MinerUPage] = []
    if isinstance(data, list) and all(isinstance(item, list) for item in data):
        for index, blocks in enumerate(data, start=1):
            normalized_blocks = [block for block in blocks if isinstance(block, dict)]
            markdown = page_markdown_from_blocks(normalized_blocks)
            pages.append(
                MinerUPage(
                    page_no=index,
                    markdown=markdown,
                    text=_markdown_to_plain_text(markdown),
                    blocks=normalized_blocks,
                    box_count=sum(1 for block in normalized_blocks if block.get("bbox")),
                )
            )
    return pages


def _pages_from_content_list(path: Path) -> List[MinerUPage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_page: Dict[int, List[Dict[str, Any]]] = {}
    if isinstance(data, list):
        for block in data:
            if not isinstance(block, dict):
                continue
            page_no = int(block.get("page_idx") or 0) + 1
            by_page.setdefault(page_no, []).append(block)
    pages: List[MinerUPage] = []
    for page_no, blocks in sorted(by_page.items()):
        markdown = page_markdown_from_blocks(blocks)
        pages.append(
            MinerUPage(
                page_no=page_no,
                markdown=markdown,
                text=_markdown_to_plain_text(markdown),
                blocks=blocks,
                box_count=sum(1 for block in blocks if block.get("bbox")),
            )
        )
    return pages


def _block_to_markdown(block: Dict[str, Any]) -> str:
    block_type = str(block.get("type") or "").lower()
    content = block.get("content")
    if "text" in block and isinstance(block["text"], str):
        text = block["text"].strip()
        level = block.get("text_level")
        if isinstance(level, int) and level > 0:
            return f"{'#' * min(max(level, 1), 6)} {text}"
        return text

    if block_type == "title" and isinstance(content, dict):
        level = int(content.get("level") or 2)
        title = _extract_content_text(content.get("title_content"))
        return f"{'#' * min(max(level, 1), 6)} {title}".strip()
    if block_type == "paragraph" and isinstance(content, dict):
        return _extract_content_text(content.get("paragraph_content"))
    if block_type == "table":
        for key in ("table_body", "html", "content"):
            text = _extract_content_text(content.get(key) if isinstance(content, dict) else block.get(key))
            if text.strip():
                return text
    if block_type in {"image", "figure"}:
        caption = _extract_content_text(content.get("image_caption") if isinstance(content, dict) else block.get("caption"))
        image_path = block.get("img_path") or block.get("image_path")
        if image_path:
            return f"![{caption}]({image_path})"
        return caption
    return _extract_content_text(content if content is not None else block)


def _extract_content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_extract_content_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("content", "text", "html", "table_body", "title_content", "paragraph_content"):
            if key in value:
                text = _extract_content_text(value[key])
                if text.strip():
                    return text
        return "\n".join(filter(None, (_extract_content_text(item) for item in value.values())))
    return str(value).strip()


def _markdown_to_plain_text(markdown: str) -> str:
    text = markdown or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda match: match.group(0).split("](", 1)[0].lstrip("["), text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", text, flags=re.I)
    text = re.sub(r"</tr>\s*<tr[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _first_file(root: Path, pattern: str) -> Optional[Path]:
    matches = sorted(root.glob(pattern))
    return matches[0] if matches else None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
