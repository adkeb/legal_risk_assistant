"""Local document parsing, embedding, and Milvus ingestion."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from service.embedding_service import generate_embedding
from service.local_document_parser import parse_document
from service.milvus_service import get_milvus_service


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks, preferring sentence boundaries."""
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if end < len(text):
            for sep in ["。", "！", "？", ".", "!", "?", "\n"]:
                last_sep = chunk.rfind(sep)
                if last_sep > chunk_size // 2:
                    chunk = chunk[: last_sep + 1]
                    end = start + last_sep + 1
                    break

        if chunk.strip():
            chunks.append(chunk.strip())

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def process_document_with_local_parser(
    file_path: str,
    file_name: str,
    index_name: str,
    chunk_size: int = 500,
) -> Dict[str, Any]:
    """Parse a document locally, embed chunks, and store them in Milvus."""
    result: Dict[str, Any] = {
        "success": False,
        "message": "",
        "document_count": 0,
        "parse_method": "",
        "warnings": [],
    }

    try:
        print(f"Start local document processing: {file_name}")
        parsed = parse_document(file_path, file_name)
        text = parsed.text

        if not text or not text.strip():
            result["message"] = "Document content is empty"
            return result

        result["parse_method"] = parsed.method
        result["warnings"] = parsed.warnings
        print(
            f"Parsed text length: {len(text)}, method: {parsed.method}, "
            f"pages: {parsed.page_count}, ocr_pages: {parsed.ocr_pages}"
        )

        chunks = chunk_text(text, chunk_size=chunk_size)
        if not chunks:
            result["message"] = "Document chunking failed"
            return result

        print(f"Document chunking complete: {len(chunks)} chunks")
        embeddings = generate_embedding(chunks)

        if not embeddings:
            result["message"] = "Embedding generation failed: empty response"
            return result

        if len(embeddings) != len(chunks):
            result["message"] = (
                f"Embedding generation failed: count mismatch "
                f"({len(embeddings)} vs {len(chunks)})"
            )
            return result

        print(f"Embeddings generated, dimension: {len(embeddings[0])}")

        doc_id = hashlib.md5(file_name.encode()).hexdigest()
        documents = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = hashlib.md5(f"{file_name}_{i}_{chunk[:50]}".encode()).hexdigest()
            documents.append(
                {
                    "id": chunk_id,
                    "doc_id": doc_id,
                    "kb_id": index_name,
                    "filename": file_name,
                    "content": chunk,
                    "chunk_index": i,
                    "vector": embedding,
                }
            )

        print(f"Insert chunks into Milvus collection: {index_name}")
        milvus = get_milvus_service()
        milvus.insert_documents(index_name, documents)

        result["success"] = True
        result["message"] = (
            f"Successfully processed {len(documents)} chunks "
            f"using {parsed.method}"
        )
        result["document_count"] = len(documents)
        return result

    except Exception as exc:
        result["message"] = f"Processing failed: {exc}"
        print(f"Local document processing failed: {exc}")
        import traceback

        traceback.print_exc()
        return result
