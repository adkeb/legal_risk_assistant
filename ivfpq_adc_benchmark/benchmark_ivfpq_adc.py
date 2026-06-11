#!/usr/bin/env python3
"""Benchmark Milvus IVF_PQ + ADC against the existing IVF_FLAT collection.

This script does not modify application source code. It creates or reuses a
benchmark-only Milvus collection containing the same vectors and metadata as
the source collection, then builds an IVF_PQ index on that clone.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)


DEFAULT_ENV = "/root/sakura/learn/deep/industry_information_assistant/backend/.env"
DEFAULT_SOURCE = "kb_legal_risk_database"
DEFAULT_TARGET = "kb_legal_risk_database_ivfpq_adc"
VECTOR_FIELD = "vector"
OUTPUT_FIELDS = ["id", "doc_id", "kb_id", "filename", "content", "chunk_index", VECTOR_FIELD]


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * pct) - 1))
    return ordered[index]


def summarize_times(times: List[float]) -> Dict[str, float]:
    return {
        "avg_ms": sum(times) / len(times) if times else 0.0,
        "p50_ms": statistics.median(times) if times else 0.0,
        "p95_ms": percentile(times, 0.95),
        "p99_ms": percentile(times, 0.99),
    }


def normalize_vector(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def connect(env_file: str) -> None:
    load_dotenv(env_file)
    host = os.getenv("MILVUS_HOST", "localhost")
    port = os.getenv("MILVUS_PORT", "19530")
    connections.connect(alias="default", host=host, port=port)
    print(f"connected={host}:{port}")


def ensure_source_collection(name: str) -> Collection:
    if not utility.has_collection(name):
        raise RuntimeError(f"source collection does not exist: {name}")
    collection = Collection(name)
    collection.load()
    return collection


def create_target_collection(name: str, dim: int, description: str) -> Collection:
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="filename", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
        FieldSchema(name=VECTOR_FIELD, dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields=fields, description=description)
    return Collection(name=name, schema=schema)


def vector_dim(collection: Collection) -> int:
    for field in collection.schema.fields:
        if field.name == VECTOR_FIELD:
            return int(field.params["dim"])
    raise RuntimeError(f"vector field not found: {VECTOR_FIELD}")


def get_index_params(collection: Collection) -> List[Dict[str, Any]]:
    return [{"field_name": idx.field_name, "params": idx.params} for idx in collection.indexes]


def fetch_rows(collection: Collection, limit: int) -> List[Dict[str, Any]]:
    # The current legal benchmark collection has 5937 entities, so one query is
    # enough and avoids introducing primary-key pagination assumptions.
    rows = collection.query(expr="chunk_index >= 0", output_fields=OUTPUT_FIELDS, limit=limit)
    rows.sort(key=lambda row: (str(row.get("filename", "")), int(row.get("chunk_index", 0)), str(row.get("id", ""))))
    return rows


def insert_rows(
    collection: Collection,
    rows: List[Dict[str, Any]],
    batch_size: int,
    normalize_vectors: bool,
) -> float:
    started = time.perf_counter()
    inserted = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset: offset + batch_size]
        data = [
            [row["id"] for row in batch],
            [row["doc_id"] for row in batch],
            [row["kb_id"] for row in batch],
            [row["filename"][:512] for row in batch],
            [row["content"][:65535] for row in batch],
            [int(row["chunk_index"]) for row in batch],
            [
                normalize_vector(row[VECTOR_FIELD]) if normalize_vectors else row[VECTOR_FIELD]
                for row in batch
            ],
        ]
        collection.insert(data)
        inserted += len(batch)
        print(f"clone_inserted={inserted}/{len(rows)}")
    collection.flush()
    return time.perf_counter() - started


def build_ivfpq_index(
    collection: Collection,
    metric_type: str,
    nlist: int,
    m: int,
    nbits: int,
) -> float:
    started = time.perf_counter()
    index_params = {
        "index_type": "IVF_PQ",
        "metric_type": metric_type,
        "params": {"nlist": nlist, "m": m, "nbits": nbits},
    }
    collection.create_index(field_name=VECTOR_FIELD, index_params=index_params)
    collection.load()
    return time.perf_counter() - started


def ensure_target(
    args: argparse.Namespace,
    source: Collection,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    dim = vector_dim(source)
    if dim % args.m != 0:
        raise RuntimeError(f"IVF_PQ m must divide vector dimension: dim={dim}, m={args.m}")

    if utility.has_collection(args.target_collection):
        if args.rebuild:
            print(f"drop_existing_target={args.target_collection}")
            utility.drop_collection(args.target_collection)
        else:
            target = Collection(args.target_collection)
            target.load()
            return {
                "collection": target,
                "created": False,
                "clone_insert_sec": 0.0,
                "index_build_sec": 0.0,
            }

    target = create_target_collection(
        args.target_collection,
        dim,
        "Benchmark-only IVF_PQ + ADC clone for legal RAG vectors",
    )
    clone_insert_sec = insert_rows(target, rows, args.insert_batch_size, args.normalize_target_vectors)
    index_build_sec = build_ivfpq_index(
        target,
        metric_type=args.target_metric_type,
        nlist=args.nlist,
        m=args.m,
        nbits=args.nbits,
    )
    target.load()
    return {
        "collection": target,
        "created": True,
        "clone_insert_sec": clone_insert_sec,
        "index_build_sec": index_build_sec,
    }


def search_ids(
    collection: Collection,
    vector: List[float],
    metric_type: str,
    nprobe: int,
    top_k: int,
) -> List[str]:
    result = collection.search(
        data=[vector],
        anns_field=VECTOR_FIELD,
        param={"metric_type": metric_type, "params": {"nprobe": nprobe}},
        limit=top_k,
        output_fields=["id"],
    )
    return [hit.entity.get("id") for hit in result[0]]


def benchmark_collection(
    collection: Collection,
    query_vectors: Iterable[List[float]],
    ground_truth: List[List[str]],
    metric_type: str,
    nprobe_values: List[int],
    top_k: int,
) -> Dict[int, Dict[str, float]]:
    results: Dict[int, Dict[str, float]] = {}
    vectors = list(query_vectors)
    for nprobe in nprobe_values:
        times: List[float] = []
        recalls: List[float] = []
        for index, vector in enumerate(vectors):
            started = time.perf_counter()
            ids = search_ids(collection, vector, metric_type, nprobe, top_k)
            times.append((time.perf_counter() - started) * 1000)
            expected = set(ground_truth[index])
            recalls.append(len(expected.intersection(ids)) / top_k)
        summary = summarize_times(times)
        summary["recall_at_10"] = sum(recalls) / len(recalls) if recalls else 0.0
        results[nprobe] = summary
        print(
            f"{collection.name} nprobe={nprobe} "
            f"avg={summary['avg_ms']:.3f}ms p95={summary['p95_ms']:.3f}ms "
            f"recall={summary['recall_at_10']:.4f}"
        )
    return results


def make_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# IVF-PQ + ADC Benchmark Result",
        "",
        f"- Created at: `{report['created_at']}`",
        f"- Source collection: `{report['source_collection']}`",
        f"- Target collection: `{report['target_collection']}`",
        f"- Entities: `{report['entities']}`",
        f"- Query count: `{report['query_count']}`",
        f"- TopK: `{report['top_k']}`",
        f"- Ground truth: `{report['ground_truth']}`",
        "",
        "## Indexes",
        "",
        "```json",
        json.dumps(report["indexes"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Build Cost",
        "",
        f"- Clone insert: `{report['target_build']['clone_insert_sec']:.3f}s`",
        f"- IVF-PQ index build: `{report['target_build']['index_build_sec']:.3f}s`",
        "",
        "## Search Comparison",
        "",
        "| nprobe | IVF_FLAT avg ms | IVF_FLAT p95 ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ p95 ms | IVF_PQ Recall@10 | speedup_vs_flat |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["comparison"]:
        lines.append(
            "| {nprobe} | {flat_avg:.3f} | {flat_p95:.3f} | {flat_recall:.4f} | "
            "{pq_avg:.3f} | {pq_p95:.3f} | {pq_recall:.4f} | {speedup:.3f} |".format(**row)
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- `speedup_vs_flat = IVF_FLAT avg latency / IVF_PQ avg latency`.",
        "- Values above `1.0` mean IVF-PQ was faster; below `1.0` mean IVF-PQ was slower.",
        "- Recall is measured against the original IVF_FLAT collection with `nprobe=128`.",
        "- At this dataset size, IVF-PQ may lose recall without improving latency because quantization overhead can dominate.",
        "",
    ])
    return "\n".join(lines)


def parse_nprobes(value: str) -> List[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=DEFAULT_ENV)
    parser.add_argument("--source-collection", default=DEFAULT_SOURCE)
    parser.add_argument("--target-collection", default=DEFAULT_TARGET)
    parser.add_argument("--rebuild", action="store_true", help="Drop and rebuild the benchmark target collection.")
    parser.add_argument("--metric-type", default="COSINE", help="Metric for the original IVF_FLAT source collection.")
    parser.add_argument("--target-metric-type", default=None, help="Metric for the IVF_PQ target collection. Defaults to --metric-type.")
    parser.add_argument(
        "--normalize-target-vectors",
        action="store_true",
        help="Normalize cloned vectors and target query vectors. Use with --target-metric-type IP to approximate COSINE.",
    )
    parser.add_argument("--nlist", type=int, default=128)
    parser.add_argument("--m", type=int, default=64)
    parser.add_argument("--nbits", type=int, default=8)
    parser.add_argument("--nprobes", default="1,2,5,10,20,32,64,128")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--query-count", type=int, default=200)
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--insert-batch-size", type=int, default=500)
    parser.add_argument("--results-dir", default="/root/sakura/learn/deep/ivfpq_adc_benchmark/results")
    args = parser.parse_args()
    if args.target_metric_type is None:
        args.target_metric_type = args.metric_type

    warnings.filterwarnings("ignore")
    connect(args.env_file)
    source = ensure_source_collection(args.source_collection)
    rows = fetch_rows(source, args.max_rows)
    if not rows:
        raise RuntimeError("source collection returned no rows")
    print(f"source_entities={source.num_entities} fetched_rows={len(rows)}")

    target_info = ensure_target(args, source, rows)
    target: Collection = target_info["collection"]
    print(f"target_entities={target.num_entities}")

    query_rows = rows[: min(args.query_count, len(rows))]
    query_vectors = [row[VECTOR_FIELD] for row in query_rows]
    target_query_vectors = [
        normalize_vector(vector) if args.normalize_target_vectors else vector
        for vector in query_vectors
    ]
    nprobe_values = parse_nprobes(args.nprobes)

    print("building_ground_truth=source_ivf_flat_nprobe_128")
    ground_truth = [
        search_ids(source, vector, args.metric_type, args.nlist, args.top_k)
        for vector in query_vectors
    ]

    # Warm up both collections to reduce first-query load jitter.
    for _ in range(5):
        search_ids(source, query_vectors[0], args.metric_type, min(10, args.nlist), args.top_k)
        search_ids(target, target_query_vectors[0], args.target_metric_type, min(10, args.nlist), args.top_k)

    print("benchmark=ivf_flat")
    flat_results = benchmark_collection(
        source,
        query_vectors,
        ground_truth,
        args.metric_type,
        nprobe_values,
        args.top_k,
    )
    print("benchmark=ivf_pq_adc")
    pq_results = benchmark_collection(
        target,
        target_query_vectors,
        ground_truth,
        args.target_metric_type,
        nprobe_values,
        args.top_k,
    )

    comparison = []
    for nprobe in nprobe_values:
        flat = flat_results[nprobe]
        pq = pq_results[nprobe]
        speedup = flat["avg_ms"] / pq["avg_ms"] if pq["avg_ms"] else 0.0
        comparison.append({
            "nprobe": nprobe,
            "flat_avg": flat["avg_ms"],
            "flat_p95": flat["p95_ms"],
            "flat_recall": flat["recall_at_10"],
            "pq_avg": pq["avg_ms"],
            "pq_p95": pq["p95_ms"],
            "pq_recall": pq["recall_at_10"],
            "speedup": speedup,
        })

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_collection": args.source_collection,
        "target_collection": args.target_collection,
        "entities": target.num_entities,
        "query_count": len(query_vectors),
        "top_k": args.top_k,
        "ground_truth": f"{args.source_collection} IVF_FLAT nprobe={args.nlist}",
        "ivfpq_params": {
            "index_type": "IVF_PQ",
            "metric_type": args.target_metric_type,
            "nlist": args.nlist,
            "m": args.m,
            "nbits": args.nbits,
            "normalize_target_vectors": args.normalize_target_vectors,
        },
        "target_build": {
            "created": target_info["created"],
            "clone_insert_sec": target_info["clone_insert_sec"],
            "index_build_sec": target_info["index_build_sec"],
        },
        "indexes": {
            "source": get_index_params(source),
            "target": get_index_params(target),
        },
        "flat_results": flat_results,
        "pq_results": pq_results,
        "comparison": comparison,
    }

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"ivfpq_adc_benchmark_{stamp}.json"
    md_path = results_dir / f"ivfpq_adc_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(make_markdown(report), encoding="utf-8")
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")


if __name__ == "__main__":
    main()
