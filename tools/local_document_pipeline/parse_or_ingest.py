#!/usr/bin/env python3
"""Parse local documents, optionally embedding and inserting them into Milvus."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "industry_information_assistant" / "backend"
APP_ROOT = BACKEND_ROOT / "app"

sys.path.insert(0, str(APP_ROOT))

from dotenv import load_dotenv  # noqa: E402
from service.local_document_ingestion import process_document_with_local_parser  # noqa: E402
from service.local_document_parser import SUPPORTED_EXTENSIONS, parse_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run local document parsing or local parsing plus Milvus ingestion."
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to process.")
    parser.add_argument(
        "--index",
        default="kb_legal_risk_database",
        help="Milvus collection/index name used when ingesting.",
    )
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Only extract text and report parser metadata; do not embed or insert.",
    )
    parser.add_argument(
        "--no-direct-network-env",
        action="store_true",
        help="Do not clear proxy variables for this process.",
    )
    args = parser.parse_args()

    if not args.no_direct_network_env:
        apply_direct_network_env()

    load_dotenv(BACKEND_ROOT / ".env")

    files = list(iter_input_files([Path(item) for item in args.paths]))
    if not files:
        print("No supported files found.", file=sys.stderr)
        return 2

    failures = 0
    for file_path in files:
        if args.parse_only:
            ok = parse_only(file_path)
        else:
            ok = ingest(file_path, args.index, args.chunk_size)
        failures += 0 if ok else 1

    return 1 if failures else 0


def apply_direct_network_env() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def iter_input_files(paths: List[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path
        elif path.is_dir():
            for candidate in sorted(path.rglob("*")):
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                    yield candidate


def parse_only(path: Path) -> bool:
    try:
        result = parse_document(str(path), path.name)
        payload = {
            "file": str(path),
            "success": True,
            "method": result.method,
            "length": len(result.text),
            "page_count": result.page_count,
            "ocr_pages": result.ocr_pages,
            "warnings": result.warnings,
            "sample": result.text[:300],
        }
        print(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception as exc:
        print(
            json.dumps(
                {"file": str(path), "success": False, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return False


def ingest(path: Path, index_name: str, chunk_size: int) -> bool:
    result = process_document_with_local_parser(
        file_path=str(path),
        file_name=path.name,
        index_name=index_name,
        chunk_size=chunk_size,
    )
    payload = {
        "file": str(path),
        "success": result.get("success"),
        "message": result.get("message"),
        "document_count": result.get("document_count", 0),
        "parse_method": result.get("parse_method"),
        "warnings": result.get("warnings", []),
    }
    stream = sys.stdout if result.get("success") else sys.stderr
    print(json.dumps(payload, ensure_ascii=False), file=stream)
    return bool(result.get("success"))


if __name__ == "__main__":
    raise SystemExit(main())
