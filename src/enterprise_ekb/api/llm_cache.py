"""P1-7 routes: LLM semantic cache observability + admin clear.

The module-level ``_SEMANTIC_CACHE`` singleton is the shared instance for this
process; the main wiring thread may re-bind it onto the control-plane context
(``ctx``) later — handlers always read through the module attribute so the swap
is transparent to in-flight routes.

Per LCO ironrule, responses carry ``cache_hit`` / ``cache_layer`` metadata so
cache-effectiveness is observable at the API boundary; the Prometheus counters
(``llm_cache_hits_total{layer}``) are wired by the observability layer.
"""

from __future__ import annotations

from typing import Any

from litestar import Request, get, post

from enterprise_ekb.semantic_cache import SemanticCache

_SEMANTIC_CACHE = SemanticCache()


def routes(ctx: Any) -> list:
    @get("/llm-cache/stats", sync_to_thread=True)
    def llm_cache_stats(request: Request) -> dict:
        ctx._require_auth(request)
        payload = _SEMANTIC_CACHE.stats()
        payload.setdefault("cache_hit", False)
        payload.setdefault("cache_layer", "none")
        return payload

    @post("/llm-cache/clear", status_code=200, sync_to_thread=True)
    def llm_cache_clear(request: Request) -> dict:
        ctx._require_admin_auth(request)
        removed = _SEMANTIC_CACHE.clear()
        return {
            "cleared": removed,
            "cache_hit": False,
            "cache_layer": "none",
        }

    return [llm_cache_stats, llm_cache_clear]
