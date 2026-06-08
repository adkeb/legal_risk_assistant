"""Shared helpers for JSON, text normalization, paths, and source extraction."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(read_text(Path(path)))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    path = Path(path)
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {"_parse_error": True, "raw": line}
        if isinstance(item, dict):
            items.append(item)
    return items


def write_json(path: Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ratio(numerator: int | float, denominator: int | float, default: float = 1.0) -> float:
    if not denominator:
        return default
    return max(0.0, min(1.0, float(numerator) / float(denominator)))


def clamp(value: float, low: float = 0.0, high: float = 5.0) -> float:
    return max(low, min(high, value))


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", "", str(text)).lower()


def normalize_jurisdiction(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return "unknown"
    cn_markers = ("中国大陆", "大陆", "内地", "cn-mainland", "mainlandchina", "prc", "china")
    hk_markers = ("香港", "hongkong", "hk")
    eu_markers = ("欧盟", "eu", "gdpr", "europeanunion")
    us_markers = ("美国", "usa", "us", "ofac")
    if any(marker in text for marker in cn_markers):
        return "CN-mainland"
    if any(marker in text for marker in hk_markers):
        return "HK"
    if any(marker in text for marker in eu_markers):
        return "EU"
    if any(marker in text for marker in us_markers):
        return "US"
    return str(value)


def task_allows_cross_border(task_meta: Dict[str, Any]) -> bool:
    jurisdiction = task_meta.get("jurisdiction") or task_meta.get("primary_jurisdiction") or ""
    if isinstance(jurisdiction, dict):
        if jurisdiction.get("cross_border"):
            return True
        jurisdiction = " ".join(
            [str(jurisdiction.get("primary", ""))]
            + [str(item) for item in jurisdiction.get("secondary", [])]
        )
    text = str(jurisdiction)
    return any(mark in text for mark in ("/", "、", ",", "香港", "EU", "欧盟", "美国", "跨境", "多法域"))


def get_task_jurisdictions(task_meta: Dict[str, Any]) -> List[str]:
    jurisdiction = task_meta.get("jurisdiction") or task_meta.get("primary_jurisdiction") or "中国大陆"
    values: List[Any] = []
    if isinstance(jurisdiction, dict):
        values.append(jurisdiction.get("primary"))
        values.extend(jurisdiction.get("secondary") or [])
    elif isinstance(jurisdiction, list):
        values.extend(jurisdiction)
    else:
        values.extend(re.split(r"[/,，、;；]+", str(jurisdiction)))
    normalized = [normalize_jurisdiction(item) for item in values if str(item).strip()]
    return list(dict.fromkeys(normalized)) or ["CN-mainland"]


def source_identity(source: Dict[str, Any], fallback: str) -> str:
    for key in ("source_id", "id", "law_id", "case_id", "evidence_id", "risk_id"):
        value = source.get(key)
        if value:
            return str(value)
    return fallback


def normalize_source(source: Dict[str, Any], fallback_index: int) -> Dict[str, Any]:
    sid = source_identity(source, f"source_{fallback_index:03d}")
    title = source.get("title") or source.get("name") or source.get("law_name") or source.get("document_title") or ""
    source_type = source.get("source_type") or source.get("type") or source.get("category") or "unknown"
    article_no = source.get("article_no") or source.get("article") or source.get("clause_no") or source.get("span") or ""
    case_no = source.get("case_no") or source.get("case_number") or ""
    jurisdiction = source.get("jurisdiction") or source.get("legal_jurisdiction") or source.get("region") or "unknown"
    return {
        **source,
        "source_id": sid,
        "title": str(title),
        "source_type": str(source_type),
        "article_no": str(article_no),
        "case_no": str(case_no),
        "jurisdiction": normalize_jurisdiction(jurisdiction),
        "effective_from": source.get("effective_from") or source.get("valid_from"),
        "effective_to": source.get("effective_to") or source.get("valid_to"),
        "validity_status": source.get("validity_status") or source.get("status") or "",
        "url": source.get("url") or source.get("link") or "",
        "span": source.get("span") or article_no,
        "content": source.get("content") or source.get("snippet") or source.get("quote") or "",
    }


def normalize_source_index(raw_sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for idx, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            continue
        item = normalize_source(raw, idx)
        key = (item.get("source_id"), item.get("title"), item.get("article_no"), item.get("case_no"))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def extract_sources_from_state(state_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []
    for key in (
        "legal_sources",
        "applicable_laws",
        "case_sources",
        "enforcement_sources",
        "contract_clauses",
        "references",
        "raw_sources",
    ):
        values = state_json.get(key) or []
        if isinstance(values, dict):
            values = list(values.values())
        if isinstance(values, list):
            raw.extend([item for item in values if isinstance(item, dict)])
    return normalize_source_index(raw)


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def json_safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "")
    return safe.strip("._") or "eval_result"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path, excluded_parts: Iterable[str]) -> Iterator[Path]:
    excluded = set(excluded_parts)
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & excluded:
            continue
        yield path
