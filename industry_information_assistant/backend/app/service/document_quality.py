"""Quality gates for parsed pages and OCR output."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


GENERATED_PHRASES = (
    "解决步骤",
    "总结如下",
    "以下是",
    "建议您",
    "我无法",
    "作为一个",
    "请注意",
    "综上所述",
)


def normalize_visible_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def evaluate_page_quality(
    *,
    text_layer_text: str = "",
    ocr_text: str = "",
    spotting_box_count: int = 0,
    parser_method: str = "",
    used_ocr: bool = False,
) -> Dict[str, Any]:
    """Return a deterministic quality report for one page."""
    text_layer_chars = len(normalize_visible_text(text_layer_text))
    ocr_chars = len(normalize_visible_text(ocr_text))
    final_chars = ocr_chars if used_ocr else text_layer_chars
    flags = [phrase for phrase in GENERATED_PHRASES if phrase in (ocr_text or "")]

    score = 100.0
    decision = "accept"
    reasons: List[str] = []

    if final_chars == 0:
        score = 0.0
        decision = "reject"
        reasons.append("empty_text")

    if used_ocr:
        if ocr_chars < 20:
            score -= 35
            decision = "review_required"
            reasons.append("ocr_text_too_short")
        if spotting_box_count == 0 and ocr_chars >= 80:
            score -= 45
            decision = "review_required"
            reasons.append("ocr_text_without_spotting_boxes")
        if text_layer_chars > 0:
            ratio = ocr_chars / max(text_layer_chars, 1)
            if ratio > 8 or ratio < 0.1:
                score -= 25
                decision = "review_required"
                reasons.append("ocr_to_text_ratio_abnormal")
        else:
            ratio = None
    else:
        ratio = None

    if flags:
        score -= 50
        decision = "review_required"
        reasons.append("generated_phrase_flags")

    score = max(0.0, min(100.0, score))
    if decision == "accept" and score < 60:
        decision = "review_required"

    return {
        "text_layer_chars": text_layer_chars,
        "ocr_chars": ocr_chars,
        "ocr_to_text_ratio": ratio,
        "spotting_box_count": spotting_box_count,
        "generated_phrase_flags": flags,
        "quality_score": score,
        "decision": decision,
        "reasons": reasons,
        "parser_method": parser_method,
    }


def write_quality_report(path: Path, report: Dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
