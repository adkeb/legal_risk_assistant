# IVF-PQ + ADC Benchmark Result

- Created at: `2026-06-10T19:56:13`
- Source collection: `kb_legal_risk_database`
- Target collection: `kb_legal_risk_database_ivfpq_adc_m128`
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
          "m": 128,
          "nbits": 8
        }
      }
    }
  ]
}
```

## Build Cost

- Clone insert: `3.524s`
- IVF-PQ index build: `12.100s`

## Search Comparison

| nprobe | IVF_FLAT avg ms | IVF_FLAT p95 ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ p95 ms | IVF_PQ Recall@10 | speedup_vs_flat |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.744 | 2.117 | 0.7855 | 1.583 | 1.804 | 0.0015 | 1.102 |
| 2 | 1.755 | 2.248 | 0.8975 | 1.821 | 1.757 | 0.0015 | 0.964 |
| 5 | 1.726 | 1.903 | 0.9615 | 1.641 | 1.988 | 0.0015 | 1.052 |
| 10 | 1.690 | 1.899 | 0.9810 | 1.579 | 1.743 | 0.0015 | 1.071 |
| 20 | 1.687 | 1.917 | 0.9940 | 1.670 | 1.889 | 0.0015 | 1.010 |
| 32 | 1.723 | 1.906 | 0.9985 | 1.766 | 2.016 | 0.0015 | 0.976 |
| 64 | 1.886 | 2.086 | 1.0000 | 1.739 | 1.991 | 0.0015 | 1.085 |
| 128 | 2.278 | 2.582 | 1.0000 | 1.816 | 2.077 | 0.0015 | 1.255 |

## Notes

- `speedup_vs_flat = IVF_FLAT avg latency / IVF_PQ avg latency`.
- Values above `1.0` mean IVF-PQ was faster; below `1.0` mean IVF-PQ was slower.
- Recall is measured against the original IVF_FLAT collection with `nprobe=128`.
- At this dataset size, IVF-PQ may lose recall without improving latency because quantization overhead can dominate.
