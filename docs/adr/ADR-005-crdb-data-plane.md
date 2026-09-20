# ADR-005: 控制面数据面引入 CockroachDB（对齐 ESP ADR-24 模式）

- 状态：accepted（2026-09-20）
- 背景：参考项目 ESP 经 ADR-24 将主数据面从 TiDB 切至 CRDB（PG wire + follower-read 读写分离）；本集群（175/176）已有 infra ns 三节点 CRDB v24.3.11 可复用。
- 决策：`EKB_DB_DRIVER=crdb`（SQLite/TiDB/CRDB 三驱动并存）；读路径 follower-read（`SET TRANSACTION AS OF SYSTEM TIME follower_read_timestamp(), READ ONLY`——真机验证的唯一可行形态）；写路径 PG 方言（IDENTITY/JSONB/ON CONFLICT 幂等）。
- 关键工程事实（真机实证）：①psycopg2 SELECT 隐式开事务，读不 commit 即泄漏，CCL 无 license 版并发事务上限极低（~7 即全集群拒新事务）——读路径必须 `_read_commit()`；②语句级 AS OF 与事务复用冲突，须用 SET TRANSACTION 首语句形态；③v24.3 bounded staleness 不支持多 range。
- 后果：单机房 follower/strong 差异 ~0.3ms（多区域才显著）；license 是上量前置；Pulsar 后端接入为下一步。
- 证据：`docs/deploy-report-crdb-lan-2026-09-20.md`（T1-T12 全过，1275rps/p99 85ms，事务泄漏归零）。
