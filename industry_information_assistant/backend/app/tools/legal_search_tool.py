"""Legal-source search adapter with Tavily primary and Bocha fallback."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

try:
    from app.tools.tavily_tool import perform_internet_search
except ImportError:
    from tools.tavily_tool import perform_internet_search


BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_result(provider: str, query: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = item.get("url") or item.get("link")
    if not url:
        return None
    content = (
        item.get("content")
        or item.get("summary")
        or item.get("snippet")
        or item.get("description")
        or ""
    )
    raw_content = item.get("raw_content") or item.get("rawContent") or content
    return {
        "provider": provider,
        "query": query,
        "title": item.get("title") or item.get("name") or "",
        "url": url,
        "content": content,
        "raw_content": raw_content,
        "published_date": item.get("published_date") or item.get("publishedDate") or item.get("datePublished") or "",
        "error": "",
    }


def _search_tavily(query: str, max_results: int, include_raw_content: bool) -> List[Dict[str, Any]]:
    data = perform_internet_search(
        query=query,
        topic="general",
        max_results=max_results,
        include_raw_content=include_raw_content,
    )
    results = []
    for item in data.get("results", []) or []:
        normalized = _normalize_result("tavily", query, item)
        if normalized:
            results.append(normalized)
    return results


def _search_bocha(query: str, max_results: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    bocha_api_key = api_key or os.getenv("BOCHA_API_KEY", "")
    if not bocha_api_key:
        raise RuntimeError("BOCHA_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {bocha_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "summary": True,
        "count": max(1, min(int(max_results or 5), 20)),
        "page": 1,
    }
    response = requests.post(BOCHA_SEARCH_URL, headers=headers, json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Bocha API error: HTTP {response.status_code}")
    data = response.json()
    value_list = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
    if not isinstance(value_list, list):
        value_list = []
    results = []
    for item in value_list:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_result("bocha", query, item)
        if normalized:
            results.append(normalized)
    return results


def perform_legal_search(
    query: str,
    max_results: int = 5,
    include_raw_content: bool = True,
    bocha_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Search legal/public sources with Tavily first, Bocha as fallback."""

    normalized_query = _clean_text(query)
    if not normalized_query:
        return {
            "query": "",
            "results": [],
            "attempts": [],
            "providers_used": [],
            "tool_errors": 0,
        }

    attempts: List[Dict[str, Any]] = []
    providers_used: List[str] = []

    for provider, search in (
        ("tavily", lambda: _search_tavily(normalized_query, max_results, include_raw_content)),
        ("bocha", lambda: _search_bocha(normalized_query, max_results, bocha_api_key)),
    ):
        providers_used.append(provider)
        try:
            results = search()
            attempts.append({
                "provider": provider,
                "query": normalized_query,
                "status": "ok" if results else "empty",
                "result_count": len(results),
                "error": "",
            })
            if results:
                return {
                    "query": normalized_query,
                    "results": results,
                    "attempts": attempts,
                    "providers_used": providers_used,
                    "tool_errors": sum(1 for item in attempts if item.get("error")),
                }
        except Exception as exc:
            attempts.append({
                "provider": provider,
                "query": normalized_query,
                "status": "error",
                "result_count": 0,
                "error": str(exc),
            })

    return {
        "query": normalized_query,
        "results": [],
        "attempts": attempts,
        "providers_used": providers_used,
        "tool_errors": sum(1 for item in attempts if item.get("error")),
    }
