"""Hybrid dense/sparse retrieval with RRF fusion and optional rerank."""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, literal, or_
from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.knowledge import Document, DocumentChunk, KnowledgeBase
from service.embedding_service import generate_embedding
from service.milvus_service import get_milvus_service


DEFAULT_DENSE_TOP_K = 30
DEFAULT_SPARSE_TOP_K = 30
DEFAULT_RRF_K = 60
DEFAULT_RERANK_TOP_N = 10


def hybrid_retrieve_content(
    index_name: str,
    question: str,
    top_k: int = 10,
    kb_id: Optional[str] = None,
    dense_top_k: int = DEFAULT_DENSE_TOP_K,
    sparse_top_k: int = DEFAULT_SPARSE_TOP_K,
    rrf_k: int = DEFAULT_RRF_K,
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
) -> List[Dict[str, Any]]:
    dense_results = _dense_search(index_name, question, dense_top_k, kb_id)
    db = SessionLocal()
    try:
        sparse_results = _sparse_search(db, index_name, question, sparse_top_k, kb_id)
    finally:
        db.close()

    fused = _rrf_fuse(dense_results, sparse_results, rrf_k=rrf_k)
    if not fused:
        return []

    rerank_pool = fused[: max(top_k, rerank_top_n, 10)]
    reranked = _rerank(question, rerank_pool, top_n=min(rerank_top_n, len(rerank_pool)))
    return [_to_retrieval_message(item, index + 1) for index, item in enumerate(reranked[:top_k])]


def _dense_search(index_name: str, question: str, top_k: int, kb_id: Optional[str]) -> List[Dict[str, Any]]:
    try:
        query_vectors = generate_embedding([question])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]
        if not query_vector:
            return []
        results = get_milvus_service().search(index_name, query_vector, top_k=top_k, kb_id=kb_id)
        dense = []
        for rank, result in enumerate(results, start=1):
            dense.append(
                {
                    "rank": rank,
                    "retrieval_source": "dense",
                    "id": result.get("id"),
                    "document_id": result.get("document_id") or result.get("doc_id"),
                    "knowledge_base_id": result.get("knowledge_base_id") or result.get("kb_id"),
                    "document_name": result.get("filename", "N/A"),
                    "content": result.get("content", ""),
                    "chunk_index": result.get("chunk_index"),
                    "page_no": result.get("page_no"),
                    "section_title": result.get("section_title"),
                    "content_hash": result.get("content_hash"),
                    "parser_method": result.get("parser_method"),
                    "quality_score": result.get("quality_score"),
                    "dense_score": float(result.get("score") or 0),
                }
            )
        return dense
    except Exception as exc:
        print(f"[hybrid_retrieval] dense search failed: {exc}")
        return []


def _sparse_search(
    db: Session,
    index_name: str,
    question: str,
    top_k: int,
    kb_id: Optional[str],
) -> List[Dict[str, Any]]:
    if not question.strip():
        return []
    try:
        tsquery = func.plainto_tsquery("simple", question)
        vector = func.to_tsvector("simple", DocumentChunk.content)
        rank_expr = func.ts_rank_cd(vector, tsquery)
        query = (
            db.query(DocumentChunk, Document, rank_expr.label("rank"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == DocumentChunk.knowledge_base_id)
        )
        query = _apply_kb_filter(query, index_name, kb_id)
        phrase = f"%{question[:80]}%"
        query = query.filter(or_(vector.op("@@")(tsquery), DocumentChunk.content.ilike(phrase)))
        rows = query.order_by(rank_expr.desc(), DocumentChunk.created_at.desc()).limit(top_k).all()

        if not rows:
            rows = _sparse_ilike_fallback(db, index_name, question, top_k, kb_id)

        results = []
        for rank, (chunk, doc, sparse_rank) in enumerate(rows, start=1):
            results.append(
                {
                    "rank": rank,
                    "retrieval_source": "sparse",
                    "id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "knowledge_base_id": str(chunk.knowledge_base_id),
                    "document_name": doc.filename,
                    "content": chunk.content,
                    "chunk_index": chunk.chunk_index,
                    "page_no": chunk.page_no,
                    "section_title": chunk.section_title,
                    "content_hash": chunk.content_hash,
                    "parser_method": chunk.parser_method,
                    "quality_score": chunk.quality_score,
                    "source_artifact_path": chunk.source_artifact_path,
                    "sparse_score": float(sparse_rank or 0),
                }
            )
        return results
    except Exception as exc:
        print(f"[hybrid_retrieval] sparse search failed: {exc}")
        return []


def _apply_kb_filter(query: Any, index_name: str, kb_id: Optional[str]) -> Any:
    if kb_id:
        try:
            return query.filter(DocumentChunk.knowledge_base_id == uuid.UUID(str(kb_id)))
        except ValueError:
            return query.filter(DocumentChunk.knowledge_base_id == kb_id)
    if index_name.startswith("kb_"):
        normalized_name = index_name[3:].lower()
        return query.filter(func.replace(func.lower(KnowledgeBase.name), " ", "_") == normalized_name)
    return query


def _sparse_ilike_fallback(
    db: Session,
    index_name: str,
    question: str,
    top_k: int,
    kb_id: Optional[str],
) -> list:
    terms = _extract_terms(question)
    if not terms:
        return []
    query = (
        db.query(DocumentChunk, Document, literal(1.0).label("rank"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == DocumentChunk.knowledge_base_id)
    )
    query = _apply_kb_filter(query, index_name, kb_id)
    query = query.filter(or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in terms[:8]]))
    return query.order_by(DocumentChunk.created_at.desc()).limit(top_k).all()


def _extract_terms(question: str) -> List[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_.-]{2,}", question or "")
    seen = set()
    output = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            output.append(term)
    return output


def _rrf_fuse(dense_results: List[Dict[str, Any]], sparse_results: List[Dict[str, Any]], rrf_k: int) -> List[Dict[str, Any]]:
    fused: Dict[str, Dict[str, Any]] = {}
    for source_results in (dense_results, sparse_results):
        for rank, item in enumerate(source_results, start=1):
            key = _result_key(item)
            if key not in fused:
                fused[key] = dict(item)
                fused[key]["rrf_score"] = 0.0
                fused[key]["retrieval_sources"] = set()
            fused[key]["rrf_score"] += 1.0 / (rrf_k + rank)
            fused[key]["retrieval_sources"].add(item.get("retrieval_source", "unknown"))
            for field in ("source_artifact_path", "page_no", "section_title", "parser_method", "quality_score"):
                if not fused[key].get(field) and item.get(field):
                    fused[key][field] = item.get(field)

    values = list(fused.values())
    for item in values:
        item["retrieval_sources"] = sorted(item["retrieval_sources"])
    values.sort(key=lambda row: row.get("rrf_score", 0), reverse=True)
    return values


def _result_key(item: Dict[str, Any]) -> str:
    if item.get("content_hash"):
        return f"hash:{item['content_hash']}"
    return f"doc:{item.get('document_id')}:{item.get('chunk_index')}:{hash(item.get('content', ''))}"


def _rerank(query: str, docs: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    api_key = _env_first("RERANK_API_KEY", "LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY")
    if not api_key or not docs:
        return docs
    try:
        from dashscope import TextReRank

        response = TextReRank.call(
            model=_env_first("RERANK_MODEL", default="gte-rerank"),
            query=query,
            documents=[item.get("content", "") for item in docs],
            top_n=top_n,
            api_key=api_key,
            return_documents=False,
        )
        output = getattr(response, "output", None) or (response.get("output") if isinstance(response, dict) else None)
        results = output.get("results", []) if isinstance(output, dict) else []
        reranked = []
        used = set()
        for result in results:
            index = result.get("index")
            if isinstance(index, int) and 0 <= index < len(docs):
                item = dict(docs[index])
                item["rerank_score"] = float(result.get("relevance_score") or result.get("score") or 0)
                reranked.append(item)
                used.add(index)
        for index, item in enumerate(docs):
            if index not in used:
                reranked.append(item)
        return reranked
    except Exception as exc:
        print(f"[hybrid_retrieval] rerank failed: {exc}")
        return docs


def _to_retrieval_message(item: Dict[str, Any], ordinal: int) -> Dict[str, Any]:
    content = item.get("content", "")
    return {
        "id": ordinal,
        "document_id": item.get("document_id", "N/A"),
        "document_name": item.get("document_name", "N/A"),
        "content_with_weight": content,
        "content": content,
        "score": item.get("rerank_score", item.get("rrf_score", item.get("dense_score", item.get("sparse_score", 0)))),
        "retrieval_sources": item.get("retrieval_sources", [item.get("retrieval_source", "unknown")]),
        "page_no": item.get("page_no"),
        "section_title": item.get("section_title"),
        "source_artifact_path": item.get("source_artifact_path"),
        "parser_method": item.get("parser_method"),
        "quality_score": item.get("quality_score"),
    }


def _env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default
