# EKB 管理台（M1）

React 18 + Vite + TypeScript，设计令牌（`tokens/tokens.json`，W3C DTCG 格式）经 `src/tokens.css` 生成注入——多端品牌一致性的单一视觉源。

## 四页（对应 M1 验收）

1. 运行健康：readyz + Outbox 状态 + `/metrics` 原文
2. 容量估算：默认基线一键估算
3. Skill 治理：一键注册 + 三级晋级（review→staging→production）
4. 审计查询：tenant 维度最近审计

## 运行

```bash
npm install
VITE_API_BASE=http://127.0.0.1:8080 npm run dev   # 开发（或 vite.config.ts 代理 /api）
npm run build                                      # 产物 dist/
```

环境变量：`VITE_API_BASE`（默认 /api）、`VITE_EKB_AUTH_TOKEN`（可选 Bearer）。
