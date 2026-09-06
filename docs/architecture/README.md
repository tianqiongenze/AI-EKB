# Architecture Knowledge Base Index

This directory consolidates architecture design thought process, implementation mappings, and foundational knowledge for engineering, operations, and onboarding.

## Documents

1. `technical-architecture.md`
   - Overall technical architecture and service boundaries
2. `data-architecture.md`
   - Data domain model, storage engines, data lifecycle, and governance
3. `deployment-architecture.md`
   - K8s/Helm/Kustomize and multi-region deployment patterns
4. `runtime-architecture.md`
   - Runtime behavior, resilience, observability, scaling, and degradation
5. `implementation-process.md`
   - End-to-end implementation flow from requirement to production rollout
6. `interaction-sequence-diagrams.md`
   - Core interaction sequence diagrams (Mermaid)
7. `foundations-and-skill-primer.md`
8. `a2a-architecture.md`
9. `industrial-scale-roadmap.md`
   - Foundational concepts and skill points for MCP/Skill/Harness and middleware
10. `../architecture-review-2026-09.md`
   - Expert architecture review: 10-dimension scoring with file:line evidence,
     industry best-practice benchmarking (hybrid RAG / MCP OAuth2.1 / Outbox-CDC),
     and the P0/P1/P2 refactoring roadmap

## Relationship with Existing Docs

- Existing docs under `docs/` remain source-of-truth for phase deliverables.
- This `docs/architecture/` bundle is a structured “design + knowledge” layer that cross-links those deliverables for external contributors and reviewers.
