# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""知识库相关模型"""
import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from core.database import Base


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = "knowledge_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    document_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    """文档模型"""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50))
    file_size = Column(BigInteger)
    file_path = Column(String(500))
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    chunk_count = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    user = relationship("User", back_populates="documents")
    job = relationship("DocumentJob", back_populates="document", uselist=False, cascade="all, delete-orphan")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentJob(Base):
    """持久化文档入库任务"""
    __tablename__ = "document_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_hash = Column(String(64), nullable=False, index=True)
    source_path = Column(String(1000), nullable=False)
    status = Column(String(50), default="pending", index=True)
    current_stage = Column(String(50), default="stored")
    retry_count = Column(Integer, default=0)
    error_message = Column(Text)
    parser_version = Column(String(100), default="local_ingestion_v2")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("Document", back_populates="job")
    knowledge_base = relationship("KnowledgeBase")


class DocumentPage(Base):
    """文档页级解析与 OCR 证据链"""
    __tablename__ = "document_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_no = Column(Integer, nullable=False)
    status = Column(String(50), default="pending", index=True)
    text_layer_chars = Column(Integer, default=0)
    ocr_chars = Column(Integer, default=0)
    parser_method = Column(String(100))
    quality_score = Column(Float, default=0)
    image_path = Column(String(1000))
    ocr_json_path = Column(String(1000))
    ocr_text_path = Column(String(1000))
    spotting_json_path = Column(String(1000))
    box_image_path = Column(String(1000))
    quality_json_path = Column(String(1000))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("Document", back_populates="pages")


class DocumentChunk(Base):
    """可检索的结构化文本切片"""
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    page_no = Column(Integer)
    chunk_index = Column(Integer, nullable=False)
    section_title = Column(String(512))
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    parser_method = Column(String(100))
    quality_score = Column(Float, default=0)
    source_artifact_path = Column(String(1000))
    milvus_id = Column(String(64), index=True)
    sparse_index_id = Column(String(128), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")
    knowledge_base = relationship("KnowledgeBase")


Index("ix_document_pages_document_page", DocumentPage.document_id, DocumentPage.page_no)
Index("ix_document_chunks_document_index", DocumentChunk.document_id, DocumentChunk.chunk_index)
Index("ix_document_chunks_kb_hash", DocumentChunk.knowledge_base_id, DocumentChunk.content_hash)
