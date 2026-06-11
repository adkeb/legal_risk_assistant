# IVF-PQ + ADC Benchmark Result

- Created at: `2026-06-10T20:02:48`
- Source collection: `kb_legal_risk_database`
- Target collection: `kb_legal_risk_database_ivfpq_adc_ipnorm_m64`
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
        "metric_type": "IP",
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

- Clone insert: `3.922s`
- IVF-PQ index build: `13.408s`

## Search Comparison

| nprobe | IVF_FLAT avg ms | IVF_FLAT p95 ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ p95 ms | IVF_PQ Recall@10 | speedup_vs_flat |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.711 | 1.926 | 0.7855 | 1.595 | 1.753 | 0.0015 | 1.073 |
| 2 | 1.740 | 1.957 | 0.8975 | 1.522 | 1.674 | 0.0015 | 1.143 |
| 5 | 1.788 | 1.985 | 0.9615 | 1.554 | 1.738 | 0.0015 | 1.151 |
| 10 | 1.722 | 1.915 | 0.9810 | 1.545 | 1.706 | 0.0015 | 1.114 |
| 20 | 1.894 | 2.126 | 0.9940 | 1.606 | 1.793 | 0.0015 | 1.180 |
| 32 | 2.054 | 2.142 | 0.9985 | 1.793 | 2.117 | 0.0015 | 1.146 |
| 64 | 1.930 | 2.129 | 1.0000 | 1.944 | 2.630 | 0.0015 | 0.993 |
| 128 | 2.289 | 2.627 | 1.0000 | 1.842 | 2.088 | 0.0015 | 1.243 |

## Notes

- `speedup_vs_flat = IVF_FLAT avg latency / IVF_PQ avg latency`.
- Values above `1.0` mean IVF-PQ was faster; below `1.0` mean IVF-PQ was slower.
- Recall is measured against the original IVF_FLAT collection with `nprobe=128`.
- At this dataset size, IVF-PQ may lose recall without improving latency because quantization overhead can dominate.
