# IVF-PQ + ADC Benchmark Result

- Created at: `2026-06-10T20:05:50`
- Source collection: `kb_legal_risk_database`
- Target collection: `kb_legal_risk_database_ivfpq_adc_m256`
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
          "m": 256,
          "nbits": 8
        }
      }
    }
  ]
}
```

## Build Cost

- Clone insert: `3.545s`
- IVF-PQ index build: `16.617s`

## Search Comparison

| nprobe | IVF_FLAT avg ms | IVF_FLAT p95 ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ p95 ms | IVF_PQ Recall@10 | speedup_vs_flat |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.702 | 1.932 | 0.7855 | 2.144 | 2.219 | 0.0015 | 0.794 |
| 2 | 1.876 | 2.099 | 0.8975 | 1.769 | 1.984 | 0.0015 | 1.061 |
| 5 | 1.818 | 2.024 | 0.9615 | 1.847 | 2.124 | 0.0020 | 0.984 |
| 10 | 1.832 | 2.070 | 0.9810 | 1.980 | 2.179 | 0.0020 | 0.925 |
| 20 | 1.866 | 2.113 | 0.9940 | 1.885 | 2.194 | 0.0020 | 0.989 |
| 32 | 1.875 | 2.139 | 0.9985 | 2.036 | 2.466 | 0.0020 | 0.921 |
| 64 | 2.211 | 2.478 | 1.0000 | 2.197 | 2.440 | 0.0020 | 1.006 |
| 128 | 2.576 | 2.891 | 1.0000 | 2.317 | 2.601 | 0.0020 | 1.112 |

## Notes

- `speedup_vs_flat = IVF_FLAT avg latency / IVF_PQ avg latency`.
- Values above `1.0` mean IVF-PQ was faster; below `1.0` mean IVF-PQ was slower.
- Recall is measured against the original IVF_FLAT collection with `nprobe=128`.
- At this dataset size, IVF-PQ may lose recall without improving latency because quantization overhead can dominate.
