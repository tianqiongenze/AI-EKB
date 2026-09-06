# Cache Key Design Specification

## 1. Scope

This document defines cache key naming, value shape, TTL policies, and invalidation strategy for Redis-backed hot-path caching in EKB.

## 2. Key Naming Convention

Pattern:

`yadea:{env}:{region}:{tenant}:{domain}:{entity}:{id}:{suffix}`

Examples:

- `yadea:prod:cn-north-1:tenant-a:authz:decision:user-123:v1`
- `yadea:prod:cn-east-1:tenant-a:route:dialogue:tenant-a:hint`
- `yadea:prod:eu-west-1:tenant-b:skill:allowlist:planner:1.2.0`
- `yadea:prod:cn-south-1:tenant-a:mcp:policy:invoke:tool-x`

## 3. Key Families

| Key Family | Purpose | Value JSON Shape | Recommended TTL |
|---|---|---|---|
| `authz:decision` | AuthZ decision cache | `{ "allowed": bool, "engine": str, "policy_version": str }` | 30-120s |
| `route:dialogue` | Gateway route hint cache | `{ "route": str, "mode": str, "updated_at": str }` | 60-300s |
| `skill:allowlist` | Skill tool/domain allowlist snapshot | `{ "tools": [str], "domains": [str], "version": str }` | 300-1800s |
| `mcp:policy` | MCP policy projection | `{ "tenant": str, "rules": object, "revision": str }` | 120-600s |
| `semantic:answer` | Optional semantic answer cache | `{ "answer": str, "evidence": [str], "confidence": number }` | 30-180s |

## 4. Batch Access Requirements

Implementation mapping:

- Read: `HighPerformanceRedisClient.mget_json(...)`
- Write: `HighPerformanceRedisClient.mset_json_with_ttl(...)`

Design principles:

1. Use `mget` for co-located keys per request path
2. Use pipelined `setex` for burst writes
3. Keep payloads compact JSON for low network overhead

## 5. Invalidation Rules

- Skill promotion invalidates `skill:allowlist:*`
- Policy changes invalidate `mcp:policy:*` and `authz:decision:*`
- Route strategy changes invalidate `route:dialogue:*`
- Emergency revocation can flush by prefix scan job per tenant/region

## 6. Safety and Isolation

- Always include tenant + region in key namespace
- Never cache raw secrets/credentials
- Avoid unbounded key cardinality; normalize IDs
- Keep TTL bounded to prevent stale governance decisions
