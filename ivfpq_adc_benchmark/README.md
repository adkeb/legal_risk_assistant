# IVF-PQ + ADC Benchmark

This folder is intentionally separate from the application source code. It benchmarks a Milvus `IVF_PQ` index, whose search path uses ADC-style asymmetric distance computation, against the existing `IVF_FLAT` legal RAG collection.

## Goal

Compare the current baseline collection:

- Source collection: `kb_legal_risk_database`
- Baseline index: `IVF_FLAT`
- Metric: `COSINE`
- Vector field: `vector`
- Dimension: `1024`

with a benchmark-only clone:

- Target collection: `kb_legal_risk_database_ivfpq_adc`
- Test index: `IVF_PQ`
- Metric: `COSINE`
- Parameters: `nlist=128`, `m=64`, `nbits=8`

## Why IVF-PQ + ADC

`IVF_PQ` combines two ideas:

- IVF: partition vectors into inverted lists, controlled by `nlist` at index build time and `nprobe` at query time.
- PQ: compress each vector into product quantization codes.

During search, the query vector stays full precision while database vectors are represented by PQ codes. Milvus computes approximate query-to-code distances through lookup tables. This is the ADC, or asymmetric distance computation, path.

Compared with `IVF_FLAT`, expected tradeoffs are:

- lower vector storage and memory pressure;
- possible speedup at large scale;
- lower recall because database vectors are quantized;
- possible slowdown at small scale because PQ decode/lookup overhead can dominate.

For the current 5k-6k chunk dataset, `IVF_PQ` may not be faster. The point of this benchmark is to measure that instead of assuming it.

## Run

From the repository root:

```bash
cd /root/sakura/learn/deep
PYTHONPATH=industry_information_assistant/backend/app \
industry_information_assistant/backend/.venv/bin/python \
ivfpq_adc_benchmark/benchmark_ivfpq_adc.py --rebuild
```

The script writes JSON and Markdown reports into:

```text
ivfpq_adc_benchmark/results/
```

If direct `IVF_PQ + COSINE` gives poor recall, test the normalized inner-product variant:

```bash
cd /root/sakura/learn/deep
PYTHONPATH=industry_information_assistant/backend/app \
industry_information_assistant/backend/.venv/bin/python \
ivfpq_adc_benchmark/benchmark_ivfpq_adc.py \
  --rebuild \
  --target-collection kb_legal_risk_database_ivfpq_adc_ipnorm \
  --target-metric-type IP \
  --normalize-target-vectors
```

This stores normalized vectors in the IVF-PQ collection and normalizes query
vectors before target search. It approximates the original COSINE behavior
because cosine similarity equals inner product after L2 normalization.

## Output Metrics

- `avg_ms`: average Milvus search latency, excluding query embedding.
- `p50_ms`, `p95_ms`, `p99_ms`: latency percentiles.
- `recall_at_10`: overlap with a high-recall baseline from the original `IVF_FLAT` collection using `nprobe=128`.
- `speedup_vs_flat`: `IVF_FLAT latency / IVF_PQ latency`. Values above `1.0` mean IVF-PQ is faster.
