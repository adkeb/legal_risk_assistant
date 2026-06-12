# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Milvus 向量存储服务"""
import os
from typing import List, Dict, Any, Optional
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)


class MilvusService:
    """Milvus 向量存储服务"""

    def __init__(self):
        self.host = os.getenv("MILVUS_HOST", "localhost")
        self.port = int(os.getenv("MILVUS_PORT", "19530"))
        self.vector_dim = 1024  # text-embedding-v4 维度
        self._connect()

    def _connect(self):
        """连接到 Milvus"""
        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port,
            )
            print(f"已连接到 Milvus: {self.host}:{self.port}")
        except Exception as e:
            print(f"连接 Milvus 失败: {e}")
            raise

    def create_collection(self, collection_name: str) -> Collection:
        """
        创建集合（如果不存在）

        Args:
            collection_name: 集合名称

        Returns:
            Collection 对象
        """
        # 检查集合是否存在
        if utility.has_collection(collection_name):
            print(f"集合 {collection_name} 已存在")
            collection = Collection(collection_name)
            collection.load()
            return collection

        # 定义字段。保留 doc_id/kb_id 兼容旧代码，同时新增更完整的 RAG 元数据。
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="knowledge_base_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="filename", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="page_no", dtype=DataType.INT64),
            FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="content_hash", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="parser_method", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="quality_score", dtype=DataType.FLOAT),
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.vector_dim),
        ]

        schema = CollectionSchema(fields=fields, description=f"Knowledge base: {collection_name}")
        collection = Collection(name=collection_name, schema=schema)

        # 创建索引
        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        collection.create_index(field_name="vector", index_params=index_params)

        # 加载集合到内存
        collection.load()

        print(f"集合 {collection_name} 创建成功")
        return collection

    def insert_documents(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
    ) -> int:
        """
        插入文档

        Args:
            collection_name: 集合名称
            documents: 文档列表，每个文档包含:
                - id: 文档ID
                - doc_id: 原始文档ID
                - kb_id: 知识库ID
                - filename: 文件名
                - content: 文本内容
                - chunk_index: 切片索引
                - vector: 向量

        Returns:
            插入的文档数量
        """
        collection = self.create_collection(collection_name)

        field_names = [field.name for field in collection.schema.fields if not getattr(field, "auto_id", False)]
        data = [
            [self._field_value(doc, field_name) for doc in documents]
            for field_name in field_names
        ]
        collection.insert(data)
        collection.flush()

        print(f"成功插入 {len(documents)} 条文档到 {collection_name}")
        return len(documents)

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 5,
        kb_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        向量搜索

        Args:
            collection_name: 集合名称
            query_vector: 查询向量
            top_k: 返回结果数量
            kb_id: 知识库ID（可选，用于过滤）

        Returns:
            搜索结果列表
        """
        if not utility.has_collection(collection_name):
            print(f"集合 {collection_name} 不存在")
            return []

        collection = Collection(collection_name)
        collection.load()

        field_names = self._collection_field_names(collection)
        expr = self._kb_expr(kb_id, field_names)

        # 搜索参数
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10},
        }

        results = collection.search(
            data=[query_vector],
            anns_field="vector",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=[name for name in field_names if name != "vector"],
        )

        # 格式化结果
        formatted_results = []
        for hits in results:
            for hit in hits:
                formatted_results.append({
                    "id": hit.entity.get("id"),
                    "doc_id": hit.entity.get("doc_id") or hit.entity.get("document_id"),
                    "document_id": hit.entity.get("document_id") or hit.entity.get("doc_id"),
                    "kb_id": hit.entity.get("kb_id") or hit.entity.get("knowledge_base_id"),
                    "knowledge_base_id": hit.entity.get("knowledge_base_id") or hit.entity.get("kb_id"),
                    "filename": hit.entity.get("filename"),
                    "page_no": hit.entity.get("page_no"),
                    "section_title": hit.entity.get("section_title"),
                    "content": hit.entity.get("content"),
                    "chunk_index": hit.entity.get("chunk_index"),
                    "content_hash": hit.entity.get("content_hash"),
                    "parser_method": hit.entity.get("parser_method"),
                    "quality_score": hit.entity.get("quality_score"),
                    "created_at": hit.entity.get("created_at"),
                    "score": hit.score,
                })

        return formatted_results

    def delete_by_doc_id(self, collection_name: str, doc_id: str) -> bool:
        """
        根据文档ID删除所有相关切片

        Args:
            collection_name: 集合名称
            doc_id: 文档ID

        Returns:
            是否成功
        """
        if not utility.has_collection(collection_name):
            return True

        try:
            collection = Collection(collection_name)
            field_names = self._collection_field_names(collection)
            if "doc_id" in field_names and "document_id" in field_names:
                expr = f'doc_id == "{doc_id}" or document_id == "{doc_id}"'
            elif "document_id" in field_names:
                expr = f'document_id == "{doc_id}"'
            else:
                expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            print(f"已删除文档 {doc_id} 的所有切片")
            return True
        except Exception as e:
            print(f"删除文档失败: {e}")
            return False

    def delete_collection(self, collection_name: str) -> bool:
        """
        删除集合

        Args:
            collection_name: 集合名称

        Returns:
            是否成功
        """
        try:
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                print(f"集合 {collection_name} 已删除")
            return True
        except Exception as e:
            print(f"删除集合失败: {e}")
            return False

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """
        获取集合统计信息

        Args:
            collection_name: 集合名称

        Returns:
            统计信息
        """
        if not utility.has_collection(collection_name):
            return {"exists": False}

        collection = Collection(collection_name)
        return {
            "exists": True,
            "name": collection_name,
            "num_entities": collection.num_entities,
        }

    def get_chunks_by_filename(
        self,
        collection_name: str,
        filename: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        根据文件名获取所有切片

        Args:
            collection_name: 集合名称
            filename: 文件名
            limit: 最大返回数量

        Returns:
            切片列表
        """
        if not utility.has_collection(collection_name):
            print(f"集合 {collection_name} 不存在")
            return []

        try:
            collection = Collection(collection_name)
            collection.load()
            field_names = self._collection_field_names(collection)

            # 查询表达式
            expr = f'filename == "{filename}"'

            results = collection.query(
                expr=expr,
                output_fields=[name for name in field_names if name != "vector"],
                limit=limit,
            )

            # 按 chunk_index 排序
            results.sort(key=lambda x: x.get("chunk_index", 0))

            return results
        except Exception as e:
            print(f"查询切片失败: {e}")
            return []

    def _collection_field_names(self, collection: Collection) -> List[str]:
        return [field.name for field in collection.schema.fields]

    def _kb_expr(self, kb_id: Optional[str], field_names: List[str]) -> Optional[str]:
        if not kb_id:
            return None
        if "knowledge_base_id" in field_names and "kb_id" in field_names:
            return f'knowledge_base_id == "{kb_id}" or kb_id == "{kb_id}"'
        if "knowledge_base_id" in field_names:
            return f'knowledge_base_id == "{kb_id}"'
        if "kb_id" in field_names:
            return f'kb_id == "{kb_id}"'
        return None

    def _field_value(self, doc: Dict[str, Any], field_name: str) -> Any:
        if field_name == "id":
            return str(doc.get("id", ""))
        if field_name == "doc_id":
            return str(doc.get("doc_id") or doc.get("document_id") or "")
        if field_name == "document_id":
            return str(doc.get("document_id") or doc.get("doc_id") or "")
        if field_name == "kb_id":
            return str(doc.get("kb_id") or doc.get("knowledge_base_id") or "")
        if field_name == "knowledge_base_id":
            return str(doc.get("knowledge_base_id") or doc.get("kb_id") or "")
        if field_name == "filename":
            return str(doc.get("filename", ""))[:512]
        if field_name == "page_no":
            return int(doc.get("page_no") or 0)
        if field_name == "section_title":
            return str(doc.get("section_title", ""))[:512]
        if field_name == "content":
            return str(doc.get("content", ""))[:65535]
        if field_name == "chunk_index":
            return int(doc.get("chunk_index") or 0)
        if field_name == "content_hash":
            return str(doc.get("content_hash", ""))[:64]
        if field_name == "parser_method":
            return str(doc.get("parser_method", ""))[:100]
        if field_name == "quality_score":
            return float(doc.get("quality_score") or 0)
        if field_name == "created_at":
            return str(doc.get("created_at", ""))[:64]
        if field_name == "vector":
            return doc["vector"]
        return doc.get(field_name)


# 单例实例
_milvus_service: Optional[MilvusService] = None


def get_milvus_service() -> MilvusService:
    """获取 Milvus 服务单例"""
    global _milvus_service
    if _milvus_service is None:
        _milvus_service = MilvusService()
    return _milvus_service
