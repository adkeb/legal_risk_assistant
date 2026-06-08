"""Tavily internet search adapter.

The business entry point is ``perform_internet_search`` which returns Tavily's
structured dictionary response. ``internet_search.invoke`` is a lightweight
tool-style wrapper for agent code that expects a string result.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Optional

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass


TavilyTopic = Literal["general", "news", "finance"]
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
VALID_TOPICS = {"general", "news", "finance"}


class TavilySearchError(RuntimeError):
    """Raised when Tavily returns an unusable response."""


def _normalize_topic(topic: str | None) -> TavilyTopic:
    if topic in VALID_TOPICS:
        return topic  # type: ignore[return-value]
    return "general"


def _normalize_max_results(max_results: int | str | None) -> int:
    try:
        value = int(max_results or 5)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 20))


def _clean_result(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "content": item.get("content") or "",
        "score": item.get("score"),
        "published_date": item.get("published_date") or item.get("publishedDate") or "",
        "raw_content": item.get("raw_content") or item.get("rawContent") or "",
    }


def perform_internet_search(
    query: str,
    topic: TavilyTopic = "general",
    max_results: int = 5,
    include_raw_content: bool = False,
    timeout: int = 30,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Search the internet with Tavily and return a structured dictionary."""
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return {"query": "", "results": []}

    tavily_api_key = api_key or os.getenv("TAVILY_API_KEY", "")
    if not tavily_api_key:
        raise TavilySearchError("TAVILY_API_KEY is not configured")

    payload = {
        "api_key": tavily_api_key,
        "query": normalized_query,
        "topic": _normalize_topic(topic),
        "max_results": _normalize_max_results(max_results),
        "include_raw_content": bool(include_raw_content),
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {tavily_api_key}",
    }

    response = requests.post(
        TAVILY_SEARCH_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise TavilySearchError(f"Tavily API error: HTTP {response.status_code}")

    data = response.json()
    results = data.get("results", [])
    if not isinstance(results, list):
        results = []

    return {
        "query": data.get("query") or normalized_query,
        "results": [
            _clean_result(item)
            for item in results
            if isinstance(item, dict) and item.get("url")
        ],
    }


def _format_results_for_agent(result: Dict[str, Any]) -> str:
    items: Iterable[Dict[str, Any]] = result.get("results") or []
    lines = [f"query: {result.get('query', '')}"]
    for index, item in enumerate(items, start=1):
        lines.append(
            "\n".join(
                [
                    f"[{index}] {item.get('title', '')}",
                    f"url: {item.get('url', '')}",
                    f"published_date: {item.get('published_date', '')}",
                    f"content: {item.get('content', '')}",
                    f"raw_content: {item.get('raw_content', '')}" if item.get("raw_content") else "",
                ]
            ).strip()
        )
    return "\n\n".join(line for line in lines if line)


class _InternetSearchTool:
    """Small ``.invoke`` wrapper compatible with simple agent tool calls."""

    name = "internet_search"
    description = "Use Tavily to search public internet sources and return concise text."

    def invoke(self, params: Dict[str, Any] | str) -> str:
        if isinstance(params, str):
            params = {"query": params}
        try:
            result = perform_internet_search(
                query=str(params.get("query") or ""),
                topic=_normalize_topic(params.get("topic")),
                max_results=_normalize_max_results(params.get("max_results")),
                include_raw_content=bool(params.get("include_raw_content", False)),
            )
        except Exception as exc:
            return json.dumps({"error": str(exc), "results": []}, ensure_ascii=False)
        return _format_results_for_agent(result)


internet_search = _InternetSearchTool()

