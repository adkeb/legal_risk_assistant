"""Persistent, stage-aware document ingestion pipeline."""
from __future__ import annotations

import traceback
import uuid
from datetime import datetime
from typing import Iterable, List

from sqlalchemy.orm import Session

from models.knowledge import Document, DocumentChunk, DocumentJob, DocumentPage
from service.embedding_service import generate_embedding
from service.milvus_service import get_milvus_service
from service.parser_router import ParsedDocument, ParserRouter
from service.structured_chunker import chunk_parsed_text


PARSER_VERSION = "local_ingestion_v2"
VECTOR_DIM = 1024


class IngestionPipelineError(RuntimeError):
    """Raised when an ingestion stage cannot complete."""


def run_ingestion_pipeline(db: Session, *, document_id: str, job_id: str) -> dict:
    """Run the full ingestion pipeline for one persisted document job."""
    doc_uuid = uuid.UUID(str(document_id))
    job_uuid = uuid.UUID(str(job_id))
    doc = db.query(Document).filter(Document.id == doc_uuid).first()
    job = db.query(DocumentJob).filter(DocumentJob.id == job_uuid).first()
    if not doc or not job:
        raise IngestionPipelineError("Document or document job not found.")

    try:
        _mark_running(db, doc, job, "stored")
        if _complete_duplicate_if_present(db, doc, job):
            return {"success": True, "status": "completed", "duplicate": True}

        parsed = parse_document_stage(db, doc, job)
        if _has_review_required_page(parsed):
            _mark_review_required(db, doc, job, "Quality gate requires manual review.")
            return {"success": False, "status": "review_required"}

        chunks = chunk_document_stage(db, doc, job, parsed)
        embed_and_index_stage(db, doc, job, chunks)

        doc.status = "completed"
        doc.error_message = None
        doc.chunk_count = len(chunks)
        job.status = "completed"
        job.current_stage = "indexed"
        job.error_message = None
        db.commit()
        return {"success": True, "status": "completed", "chunks": len(chunks)}
    except Exception as exc:
        _mark_failed(db, doc, job, exc)
        raise


def parse_document_stage(db: Session, doc: Document, job: DocumentJob) -> ParsedDocument:
    job.current_stage = "parsed"
    job.updated_at = datetime.utcnow()
    db.commit()

    db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).delete(synchronize_session=False)
    db.commit()

    parser = ParserRouter()
    parsed = parser.parse(file_path=job.source_path, file_name=doc.filename, document_id=str(doc.id))
    if not parsed.pages:
        raise IngestionPipelineError("Parser produced no pages.")

    for page in parsed.pages:
        report = page.quality_report or {}
        db.add(
            DocumentPage(
                document_id=doc.id,
                page_no=page.page_no,
                status=report.get("decision", "accept"),
                text_layer_chars=report.get("text_layer_chars", 0),
                ocr_chars=report.get("ocr_chars", 0),
                parser_method=page.parser_method,
                quality_score=report.get("quality_score", 0),
                image_path=page.image_path,
                ocr_json_path=page.ocr_json_path,
                ocr_text_path=page.ocr_text_path,
                spotting_json_path=page.spotting_json_path,
                box_image_path=page.box_image_path,
                quality_json_path=page.quality_json_path,
            )
        )
    db.commit()
    return parsed


def chunk_document_stage(
    db: Session,
    doc: Document,
    job: DocumentJob,
    parsed: ParsedDocument,
) -> List[DocumentChunk]:
    job.current_stage = "chunked"
    job.updated_at = datetime.utcnow()
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(synchronize_session=False)
    db.commit()

    chunks_to_add: List[DocumentChunk] = []
    chunk_index = 0
    for page in parsed.pages:
        report = page.quality_report or {}
        page_chunks = chunk_parsed_text(
            page.text,
            parser_method=page.parser_method,
            page_no=page.page_no,
            quality_score=float(report.get("quality_score") or 0),
            source_artifact_path=page.source_artifact_path,
            start_index=chunk_index,
        )
        chunk_index += len(page_chunks)
        for chunk in page_chunks:
            chunks_to_add.append(
                DocumentChunk(
                    document_id=doc.id,
                    knowledge_base_id=doc.knowledge_base_id,
                    page_no=chunk.page_no,
                    chunk_index=chunk.chunk_index,
                    section_title=chunk.section_title,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    parser_method=chunk.parser_method,
                    quality_score=chunk.quality_score,
                    source_artifact_path=chunk.source_artifact_path,
                )
            )

    if not chunks_to_add:
        raise IngestionPipelineError("Chunker produced no chunks.")

    db.add_all(chunks_to_add)
    doc.chunk_count = len(chunks_to_add)
    db.commit()
    for chunk in chunks_to_add:
        db.refresh(chunk)
    return chunks_to_add


def embed_and_index_stage(
    db: Session,
    doc: Document,
    job: DocumentJob,
    chunks: Iterable[DocumentChunk],
) -> int:
    chunks = list(chunks)
    job.current_stage = "embedded"
    job.updated_at = datetime.utcnow()
    db.commit()

    texts = [chunk.content for chunk in chunks]
    embeddings = generate_embedding(texts, dimensions=VECTOR_DIM)
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise IngestionPipelineError("Embedding returned an invalid batch result.")

    for index, vector in enumerate(embeddings):
        if not vector or len(vector) != VECTOR_DIM:
            raise IngestionPipelineError(f"Embedding vector at index {index} is empty or not {VECTOR_DIM} dimensions.")

    job.current_stage = "indexed"
    job.updated_at = datetime.utcnow()
    db.commit()

    collection_name = f"kb_{doc.knowledge_base.name}".lower().replace(" ", "_")
    milvus = get_milvus_service()
    milvus.delete_by_doc_id(collection_name, str(doc.id))

    now = datetime.utcnow().isoformat()
    milvus_docs = []
    for chunk, vector in zip(chunks, embeddings):
        milvus_id = str(uuid.uuid4())
        chunk.milvus_id = milvus_id
        chunk.sparse_index_id = str(chunk.id)
        milvus_docs.append(
            {
                "id": milvus_id,
                "doc_id": str(doc.id),
                "document_id": str(doc.id),
                "kb_id": str(doc.knowledge_base_id),
                "knowledge_base_id": str(doc.knowledge_base_id),
                "filename": doc.filename,
                "page_no": chunk.page_no or 0,
                "section_title": chunk.section_title or "",
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "parser_method": chunk.parser_method or "",
                "quality_score": float(chunk.quality_score or 0),
                "created_at": now,
                "vector": vector,
            }
        )

    inserted = milvus.insert_documents(collection_name, milvus_docs)
    db.commit()
    return inserted


def _mark_running(db: Session, doc: Document, job: DocumentJob, stage: str) -> None:
    doc.status = "processing"
    doc.error_message = None
    job.status = "running"
    job.current_stage = stage
    job.error_message = None
    job.parser_version = PARSER_VERSION
    job.updated_at = datetime.utcnow()
    db.commit()


def _mark_review_required(db: Session, doc: Document, job: DocumentJob, message: str) -> None:
    doc.status = "review_required"
    doc.error_message = message
    job.status = "review_required"
    job.error_message = message
    job.updated_at = datetime.utcnow()
    db.commit()


def _mark_failed(db: Session, doc: Document, job: DocumentJob, exc: Exception) -> None:
    message = f"{exc}\n{traceback.format_exc(limit=8)}"
    doc.status = "failed"
    doc.error_message = str(exc)
    job.status = "failed"
    job.error_message = message[:8000]
    job.retry_count = (job.retry_count or 0) + 1
    job.updated_at = datetime.utcnow()
    db.commit()


def _has_review_required_page(parsed: ParsedDocument) -> bool:
    for page in parsed.pages:
        decision = (page.quality_report or {}).get("decision")
        if decision in {"review_required", "reject"}:
            return True
    return False


def _complete_duplicate_if_present(db: Session, doc: Document, job: DocumentJob) -> bool:
    existing = (
        db.query(DocumentJob)
        .filter(
            DocumentJob.knowledge_base_id == job.knowledge_base_id,
            DocumentJob.file_hash == job.file_hash,
            DocumentJob.status == "completed",
            DocumentJob.document_id != doc.id,
        )
        .order_by(DocumentJob.updated_at.desc())
        .first()
    )
    if not existing:
        return False

    existing_doc = db.query(Document).filter(Document.id == existing.document_id).first()
    doc.status = "completed"
    doc.error_message = f"Duplicate file hash; reused completed ingestion from document {existing.document_id}."
    doc.chunk_count = existing_doc.chunk_count if existing_doc else 0
    job.status = "completed"
    job.current_stage = "indexed"
    job.error_message = doc.error_message
    job.updated_at = datetime.utcnow()
    db.commit()
    return True
