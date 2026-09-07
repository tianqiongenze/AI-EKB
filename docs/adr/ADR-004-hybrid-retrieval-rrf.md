# ADR-004: 混合检索采用 RRF 融合（加权可配 + 重排钩子）

- 状态：accepted（2026-09）
- 背景：向量/图/全文三索引并存但无融合层；行业实证 hybrid NDCG +26-31%，RRF 为生产默认融合方法。
- 决策：`retrieval.py` RRF（k=60，纯函数）+ 三腿（lexical=域能力目录 / vector=Milvus / graph=可插拔钩子）；支持加权（弱势源降权）与 reranker 钩子（cross-encoder 预留）；不可用腿降级不失败（degraded + 分腿计数）。
- 后果：POST /retrieval/hybrid 契约化；graph 腿待 Neo4j 读接口补充；未来按标注数据可升级 learned fusion。
