"""Document parser router with text-layer-first OCR artifacts."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.document_quality import evaluate_page_quality, write_quality_report
from service.ingestion_paths import document_artifact_dir, page_artifact_dir
from service.local_document_parser import (
    IMAGE_EXTENSIONS,
    LocalDocumentParseError,
    _env_int,
    _has_meaningful_text,
    _normalize_text,
    parse_document,
)
from service.mineru_document_parser import MinerUPage, parse_with_mineru_hybrid, render_pdf_pages


@dataclass
class ParsedPage:
    page_no: int
    text: str
    parser_method: str
    quality_report: Dict[str, Any]
    image_path: Optional[str] = None
    ocr_json_path: Optional[str] = None
    ocr_text_path: Optional[str] = None
    spotting_json_path: Optional[str] = None
    box_image_path: Optional[str] = None
    quality_json_path: Optional[str] = None
    source_artifact_path: Optional[str] = None


@dataclass
class ParsedDocument:
    pages: List[ParsedPage]
    method: str
    warnings: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())


class LayoutParser:
    """Reserved extension point for DeepDOC or Paddle layout parsing."""

    def parse(self, file_path: str, document_id: str) -> ParsedDocument:
        raise NotImplementedError


class ParserRouter:
    """Route files to direct parsers, page OCR, or future layout parsers."""

    def __init__(self, layout_parser: Optional[LayoutParser] = None):
        self.layout_parser = layout_parser

    def parse(self, *, file_path: str, file_name: str, document_id: str) -> ParsedDocument:
        path = Path(file_path)
        ext = Path(file_name or path.name).suffix.lower() or path.suffix.lower()
        if ext == ".pdf":
            return self._parse_pdf(path, document_id)
        if ext in IMAGE_EXTENSIONS:
            return self._parse_image(path, document_id)
        return self._parse_direct_file(path, file_name)

    def _parse_pdf(self, path: Path, document_id: str) -> ParsedDocument:
        warnings: List[str] = []
        text_pages, method = _extract_pdf_text_layer_pages(path, warnings)
        joined = "\n\n".join(text_pages)
        if _has_meaningful_text(joined):
            pages = []
            for index, text in enumerate(text_pages or [joined], start=1):
                normalized = _normalize_text(text)
                if not normalized:
                    continue
                report = evaluate_page_quality(
                    text_layer_text=normalized,
                    parser_method=method,
                    used_ocr=False,
                )
                pages.append(
                    ParsedPage(
                        page_no=index,
                        text=normalized,
                        parser_method=method,
                        quality_report=report,
                    )
                )
            return ParsedDocument(pages=pages, method=method, warnings=warnings)

        return self._ocr_pdf(path, document_id, warnings)

    def _parse_image(self, path: Path, document_id: str) -> ParsedDocument:
        page_dir = page_artifact_dir(document_id, 1)
        output_dir = page_dir / "mineru_hybrid"
        result = parse_with_mineru_hybrid(path, output_dir=output_dir)
        source_page = result.pages[0]
        page = _mineru_page_to_parsed_page(
            source_page,
            document_id=document_id,
            text_layer_text="",
            page_image_source=path,
            layout_image_source=None,
            mineru_result=result,
        )
        return ParsedDocument(pages=[page], method=page.parser_method)

    def _parse_direct_file(self, path: Path, file_name: str) -> ParsedDocument:
        result = parse_document(str(path), file_name=file_name)
        report = evaluate_page_quality(
            text_layer_text=result.text,
            parser_method=result.method,
            used_ocr=False,
        )
        page = ParsedPage(
            page_no=1,
            text=result.text,
            parser_method=result.method,
            quality_report=report,
        )
        return ParsedDocument(pages=[page], method=result.method, warnings=result.warnings)

    def _ocr_pdf(self, path: Path, document_id: str, warnings: List[str]) -> ParsedDocument:
        max_pages = _env_int("LOCAL_OCR_MAX_PAGES", 0)
        mineru_source = path
        limited_tmp_dir: Optional[Path] = None
        if max_pages > 0:
            limited_tmp_dir = document_artifact_dir(document_id) / "mineru_limited_source"
            if limited_tmp_dir.exists():
                shutil.rmtree(limited_tmp_dir)
            limited_tmp_dir.mkdir(parents=True, exist_ok=True)
            limited_pdf = limited_tmp_dir / "limited.pdf"
            if shutil.which("pdfseparate") and shutil.which("pdfunite"):
                page_files = []
                for page_no in range(1, max_pages + 1):
                    page_file = limited_tmp_dir / f"page_{page_no}.pdf"
                    completed = subprocess.run(
                        ["pdfseparate", "-f", str(page_no), "-l", str(page_no), str(path), str(page_file)],
                        check=False,
                        capture_output=True,
                    )
                    if completed.returncode == 0 and page_file.exists():
                        page_files.append(page_file)
                if page_files:
                    completed = subprocess.run(
                        ["pdfunite", *[str(item) for item in page_files], str(limited_pdf)],
                        check=False,
                        capture_output=True,
                    )
                    if completed.returncode == 0 and limited_pdf.exists():
                        mineru_source = limited_pdf
                        warnings.append(f"OCR limited to first {max_pages} PDF pages.")

        output_dir = document_artifact_dir(document_id) / "mineru_hybrid"
        result = parse_with_mineru_hybrid(mineru_source, output_dir=output_dir)

        render_dir = document_artifact_dir(document_id) / "rendered_pages"
        if render_dir.exists():
            shutil.rmtree(render_dir)
        image_paths = render_pdf_pages(mineru_source, render_dir, prefix_name="page")

        layout_paths: List[Path] = []
        if result.layout_pdf_path and result.layout_pdf_path.exists():
            layout_render_dir = document_artifact_dir(document_id) / "mineru_layout_pages"
            if layout_render_dir.exists():
                shutil.rmtree(layout_render_dir)
            layout_paths = render_pdf_pages(result.layout_pdf_path, layout_render_dir, prefix_name="layout")

        pages = []
        for index, mineru_page in enumerate(result.pages, start=1):
            page = _mineru_page_to_parsed_page(
                mineru_page,
                document_id=document_id,
                text_layer_text="",
                page_image_source=image_paths[index - 1] if index - 1 < len(image_paths) else None,
                layout_image_source=layout_paths[index - 1] if index - 1 < len(layout_paths) else None,
                mineru_result=result,
            )
            pages.append(page)
        return ParsedDocument(pages=pages, method=result.method, warnings=warnings)


def _extract_pdf_text_layer_pages(path: Path, warnings: List[str]) -> tuple[List[str], str]:
    if shutil.which("pdftotext"):
        try:
            completed = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                check=False,
                capture_output=True,
                timeout=_env_int("PDFTOTEXT_TIMEOUT", 120),
            )
            if completed.returncode == 0:
                text = completed.stdout.decode("utf-8", errors="ignore")
                pages = [page.strip() for page in text.split("\f")]
                if _has_meaningful_text("\n".join(pages)):
                    return pages, "pdf:pdftotext"
            else:
                error = completed.stderr.decode("utf-8", errors="ignore").strip()
                warnings.append(f"pdftotext returned {completed.returncode}: {error[:200]}")
        except Exception as exc:
            warnings.append(f"pdftotext failed: {exc}")
    else:
        warnings.append("pdftotext is not installed; skipped direct PDF extraction.")

    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages = [(page.extract_text() or "").strip() for page in pdf.pages]
        if _has_meaningful_text("\n".join(pages)):
            return pages, "pdf:pdfplumber"
    except Exception as exc:
        warnings.append(f"pdfplumber failed: {exc}")
    return [], "pdf:text-layer-empty"


def _mineru_page_to_parsed_page(
    page: MinerUPage,
    *,
    document_id: str,
    text_layer_text: str,
    page_image_source: Optional[Path],
    layout_image_source: Optional[Path],
    mineru_result: Any,
) -> ParsedPage:
    page_dir = page_artifact_dir(document_id, page.page_no)
    page_image = page_dir / f"page_{page.page_no}.png"
    if page_image_source:
        _copy_image_as_png(page_image_source, page_image)

    ocr_json_path = page_dir / "ocr_raw.json"
    ocr_md_path = page_dir / "ocr.md"
    ocr_text_path = page_dir / "ocr.txt"
    spotting_json_path = page_dir / "spotting_raw.json"
    box_image_path = page_dir / "spotting_boxes.png"
    quality_path = page_dir / "quality.json"

    parser_method = mineru_result.method
    markdown = page.markdown.strip() or page.text.strip()
    ocr_text = page.text.strip() or _plain_text_from_markdown(markdown)
    ocr_data = {
        "engine": "mineru",
        "backend": "hybrid-engine",
        "method": parser_method,
        "page_no": page.page_no,
        "markdown": markdown,
        "text": ocr_text,
        "blocks": page.blocks,
        "mineru_output_dir": str(mineru_result.output_dir),
        "mineru_work_dir": str(mineru_result.work_dir),
        "mineru_markdown_path": str(mineru_result.markdown_path) if mineru_result.markdown_path else None,
        "mineru_content_list_path": str(mineru_result.content_list_path) if mineru_result.content_list_path else None,
        "mineru_content_list_v2_path": str(mineru_result.content_list_v2_path) if mineru_result.content_list_v2_path else None,
        "mineru_middle_json_path": str(mineru_result.middle_json_path) if mineru_result.middle_json_path else None,
        "mineru_model_json_path": str(mineru_result.model_json_path) if mineru_result.model_json_path else None,
        "mineru_layout_pdf_path": str(mineru_result.layout_pdf_path) if mineru_result.layout_pdf_path else None,
    }
    spotting_data = {
        "engine": "mineru",
        "source": "content_list_v2_blocks",
        "page_no": page.page_no,
        "box_count": page.box_count,
        "blocks": page.blocks,
    }
    _write_json(ocr_json_path, ocr_data)
    ocr_md_path.write_text(markdown, encoding="utf-8")
    ocr_text_path.write_text(ocr_text, encoding="utf-8")
    _write_json(spotting_json_path, spotting_data)
    if layout_image_source:
        _copy_image_as_png(layout_image_source, box_image_path)
    elif page_image.exists():
        _draw_mineru_boxes(page_image, page.blocks, box_image_path)

    report = evaluate_page_quality(
        text_layer_text=text_layer_text,
        ocr_text=ocr_text,
        spotting_box_count=page.box_count,
        parser_method=parser_method,
        used_ocr=True,
    )
    write_quality_report(quality_path, report)

    return ParsedPage(
        page_no=page.page_no,
        text=_normalize_text(markdown),
        parser_method=parser_method,
        quality_report=report,
        image_path=str(page_image) if page_image.exists() else None,
        ocr_json_path=str(ocr_json_path),
        ocr_text_path=str(ocr_text_path),
        spotting_json_path=str(spotting_json_path),
        box_image_path=str(box_image_path) if box_image_path.exists() else None,
        quality_json_path=str(quality_path),
        source_artifact_path=str(page_dir),
    )


def _draw_mineru_boxes(image_path: Path, blocks: List[Dict[str, Any]], output_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw

        image = Image.open(image_path).convert("RGB")
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        colors = [
            (220, 30, 30, 255),
            (20, 110, 220, 255),
            (20, 150, 70, 255),
            (190, 110, 0, 255),
            (140, 60, 180, 255),
        ]
        bboxes = [block.get("bbox") for block in blocks if isinstance(block.get("bbox"), list)]
        max_x = max([float(box[2]) for box in bboxes if len(box) >= 4] or [image.width])
        max_y = max([float(box[3]) for box in bboxes if len(box) >= 4] or [image.height])
        scale_x = image.width / max(max_x, 1)
        scale_y = image.height / max(max_y, 1)
        for idx, bbox in enumerate(bboxes):
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            points = [
                (int(x1 * scale_x), int(y1 * scale_y)),
                (int(x2 * scale_x), int(y1 * scale_y)),
                (int(x2 * scale_x), int(y2 * scale_y)),
                (int(x1 * scale_x), int(y2 * scale_y)),
            ]
            color = colors[idx % len(colors)]
            draw.polygon(points, fill=color[:3] + (22,))
            draw.line(points + [points[0]], fill=color, width=3)
            x = min(point[0] for point in points)
            y = min(point[1] for point in points)
            _draw_label(draw, int(x) + 2, int(y) + 2, str(idx), color)
        Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(output_path)
    except Exception:
        shutil.copyfile(image_path, output_path)


def _normalize_poly(value: Any) -> List[tuple[int, int]]:
    points: List[tuple[int, int]] = []
    if not isinstance(value, list):
        return points
    for point in value:
        if (
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((int(round(point[0])), int(round(point[1]))))
    return points


def _draw_label(draw: Any, x: int, y: int, text: str, color: tuple[int, int, int, int]) -> None:
    pad = 3
    bbox = draw.textbbox((x, y), text)
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=(255, 255, 255, 230),
        outline=color,
    )
    draw.text((x, y), text, fill=(0, 0, 0, 255))


def _copy_image_as_png(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".png":
        shutil.copyfile(source, target)
        return
    try:
        from PIL import Image

        Image.open(source).convert("RGB").save(target)
    except Exception:
        shutil.copyfile(source, target)


def _plain_text_from_markdown(markdown: str) -> str:
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)
