# Documentation Style Guide

This guide defines the canonical documentation taxonomy, file naming conventions, and placement rules for the Yadea EKB repository. It is authoritative for all new docs and reorganizations.

## 1. Canonical Taxonomy

Top-level documentation lives under `docs/` and must be grouped by intent:

- `docs/architecture/` — system architecture, designs, decision logic
- `docs/storage/` — data storage schema, cache keys, contract mappings
- `docs/api/` — developer API manuals and references
- `docs/product/` — product feature guides and user-facing docs
- `docs/` root — program-level and release/operations docs
- `docs/sources/` — **source inputs** and original research/requirements artifacts

## 2. Naming Conventions

**Default naming:**

- Use **lowercase** ASCII with hyphens: `lower-kebab-case.md`
- Prefix with a short domain token when scope is ambiguous:
  - `architecture-...`
  - `deployment-...`
  - `runtime-...`

**Locale suffix:**

- English default: `document-name.md`
- Chinese: `document-name.zh-CN.md`

**Source inputs:**

- Must live under `docs/sources/`
- Use **ASCII, semantic names**: `subject-area-brief.zh-CN.md` or `subject-area-report.zh-CN.pdf`

## 3. Placement Rules

1. Root directory **must not** contain design drafts or external research.
2. All non-code inputs are archived in `docs/sources/`.
3. Generated artifacts and local caches are **never** committed.
4. Versioned or release documents remain under `docs/` root.

## 4. Examples

- `docs/architecture/runtime-architecture.md`
- `docs/storage/cache-keys.md`
- `docs/api/developer-api-manual.zh-CN.md`
- `docs/product/platform-product-guide.en.md`
- `docs/sources/yadea-ai-kb-requirements-research-report.zh-CN.pdf`

## 5. Enforcement

- CI rejects accidental commits of generated artifacts (see `release-gate` in `.github/workflows/ci-multilang.yml`).
- Pre-commit hooks are recommended to block violations locally.
