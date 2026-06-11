# IVF-PQ + ADC Benchmark Result

- Created at: `2026-06-10T19:51:38`
- Source collection: `kb_legal_risk_database`
- Target collection: `kb_legal_risk_database_ivfpq_adc`
- Entities: `5937`
- Query count: `200`
- TopK: `10`
- Ground truth: `kb_legal_risk_database IVF_FLAT nprobe=128`

## Indexes

```json
{
  "source": [
    {
      "field_name": "vector",
      "params": {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {
          "nlist": 128
        }
      }
    }
  ],
  "target": [
    {
      "field_name": "vector",
      "params": {
        "index_type": "IVF_PQ",
        "metric_type": "COSINE",
        "params": {
          "nlist": 128,
          "m": 64,
          "nbits": 8
        }
      }
    }
  ]
}
```

## Build Cost

- Clone insert: `3.092s`
- IVF-PQ index build: `13.099s`

## Search Comparison

| nprobe | IVF_FLAT avg ms | IVF_FLAT p95 ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ p95 ms | IVF_PQ Recall@10 | speedup_vs_flat |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.713 | 1.892 | 0.7855 | 1.836 | 2.105 | 0.0015 | 0.933 |
| 2 | 1.768 | 1.980 | 0.8975 | 2.204 | 2.209 | 0.0015 | 0.802 |
| 5 | 1.726 | 1.940 | 0.9615 | 1.793 | 2.144 | 0.0015 | 0.963 |
| 10 | 1.814 | 2.082 | 0.9810 | 1.745 | 1.948 | 0.0015 | 1.040 |
| 20 | 1.959 | 2.484 | 0.9940 | 1.902 | 2.259 | 0.0015 | 1.030 |
| 32 | 1.895 | 2.074 | 0.9985 | 1.868 | 2.047 | 0.0015 | 1.015 |
| 64 | 2.145 | 2.791 | 1.0000 | 1.812 | 2.016 | 0.0015 | 1.184 |
| 128 | 2.738 | 3.100 | 1.0000 | 1.849 | 2.056 | 0.0015 | 1.481 |

## Notes

- `speedup_vs_flat = IVF_FLAT avg latency / IVF_PQ avg latency`.
- Values above `1.0` mean IVF-PQ was faster; below `1.0` mean IVF-PQ was slower.
- Recall is measured against the original IVF_FLAT collection with `nprobe=128`.
- At this dataset size, IVF-PQ may lose recall without improving latency because quantization overhead can dominate.
