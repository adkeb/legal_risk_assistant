# IVF-PQ + ADC Benchmark Summary

测试时间：2026-06-10

测试目录独立于业务源码：

```text
/root/sakura/learn/deep/ivfpq_adc_benchmark
```

## 基准数据

- 源集合：`kb_legal_risk_database`
- 源索引：`IVF_FLAT + COSINE`
- 源索引参数：`nlist=128`
- 向量维度：`1024`
- 实体数：`5937`
- 查询样本：`200`
- TopK：`10`
- Ground truth：源集合 `IVF_FLAT` 使用 `nprobe=128`

## 测试变体

| 变体 | Target Collection | Metric | nlist | m | nbits | 说明 |
|---|---|---:|---:|---:|---:|---|
| PQ-64 | `kb_legal_risk_database_ivfpq_adc` | COSINE | 128 | 64 | 8 | 每条向量约 64 bytes PQ code，理论压缩约 64x |
| PQ-128 | `kb_legal_risk_database_ivfpq_adc_m128` | COSINE | 128 | 128 | 8 | 每条向量约 128 bytes PQ code，理论压缩约 32x |
| PQ-64-IPNorm | `kb_legal_risk_database_ivfpq_adc_ipnorm_m64` | IP | 128 | 64 | 8 | 归一化向量后用 IP 近似 COSINE |
| PQ-256 | `kb_legal_risk_database_ivfpq_adc_m256` | COSINE | 128 | 256 | 8 | 每条向量约 256 bytes PQ code，理论压缩约 16x |

## 建库与索引耗时

| 变体 | 复制向量耗时 | IVF-PQ 建索引耗时 |
|---|---:|---:|
| PQ-64 | 3.09s | 13.10s |
| PQ-128 | 3.52s | 12.10s |
| PQ-64-IPNorm | 3.92s | 13.41s |
| PQ-256 | 3.55s | 16.62s |

## nprobe=10 对比

项目当前默认检索参数是 `nprobe=10`，因此先看同口径结果。

| 方案 | IVF_FLAT avg ms | IVF_FLAT Recall@10 | IVF_PQ avg ms | IVF_PQ Recall@10 | speedup_vs_flat |
|---|---:|---:|---:|---:|---:|
| PQ-64 | 1.814 | 0.9810 | 1.745 | 0.0015 | 1.04x |
| PQ-128 | 1.690 | 0.9810 | 1.579 | 0.0015 | 1.07x |
| PQ-64-IPNorm | 1.722 | 0.9810 | 1.545 | 0.0015 | 1.11x |
| PQ-256 | 1.832 | 0.9810 | 1.980 | 0.0020 | 0.93x |

## 最佳召回观察

即使把 `nprobe` 提高到 `128`，IVF-PQ 的 Recall@10 仍然没有恢复：

| 方案 | IVF_PQ best Recall@10 | 对应现象 |
|---|---:|---|
| PQ-64 | 0.0015 | self-query 基本找不回原 chunk |
| PQ-128 | 0.0015 | 增大 m 后仍不可用 |
| PQ-64-IPNorm | 0.0015 | 归一化 IP 也不可用 |
| PQ-256 | 0.0020 | 召回略升但仍接近 0 |

## 结论

本数据集上，`IVF-PQ + ADC` 没有带来可用提升。

- 延迟方面：部分低压缩变体在 `nprobe=10` 上只比 `IVF_FLAT` 快约 4%-11%，`m=256` 反而更慢。
- 召回方面：`IVF_PQ` 的 Recall@10 从原 `IVF_FLAT` 的约 `0.9810` 掉到 `0.0015-0.0020`，属于不可接受。
- 法律风控场景不能使用当前这些 IVF-PQ 参数替代 IVF-FLAT，因为漏召回关键条文、案例或监管规则的风险极高。

当前推荐继续使用：

```text
IVF_FLAT + COSINE
nlist = 128
nprobe = 20
top_k = 10/20
```

前一轮测试中，`nprobe=20` 的 `IVF_FLAT` 平均检索耗时约 `1.8-2.0ms`，Recall@10 约 `0.994`，更适合当前 5937 chunk 的法律资料库。

## 后续建议

只有当数据扩大到几十万或百万级 chunk，并且内存压力明显高于延迟/召回要求时，才建议重新评估 PQ 类索引。届时优先测试：

- `HNSW`
- `IVF_SQ8`
- 更大训练集下的 `IVF_PQ`
- 两阶段召回：高召回向量召回 + reranker 精排

