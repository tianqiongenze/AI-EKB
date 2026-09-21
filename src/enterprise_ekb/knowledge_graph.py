"""P1-6 auto-built knowledge graph over knowledge-base chunks (LCO L3 layer).

Deterministic entity/relation extraction with no external LLM call (MPB: no
mock backends in production paths — this is the real, rule-based extractor).

Storage is in-process:
  * nodes: ``dict[entity, {"type", "mentions"}]``
  * edges: ``dict[frozenset[a, b], {"relation", "weight", "sources", "pair"}]``

DEFERRED: Neo4j persistence + multi-replica shared graph. The single-replica
LAN deployment can deterministically rebuild the graph from document chunks
via :meth:`KnowledgeGraphService.build_from_chunks`, so an in-memory store is
acceptable until the multi-replica milestone (then swap storage, keep API).
"""

from __future__ import annotations

import re
import threading
from itertools import combinations
from typing import Any

__all__ = ["KnowledgeGraphService"]

# Yadea manufacturing domain vocabulary (>= 20 terms) used by the Chinese
# noun-phrase heuristic below.
DOMAIN_WORDS: tuple[str, ...] = (
    "电池", "石墨烯电池", "锂电池", "电机", "轮毂电机", "控制器", "充电器",
    "车架", "车身", "轮胎", "刹车", "制动器", "减震器", "车灯", "仪表盘",
    "座垫", "线束", "产线", "生产线", "工艺", "质检", "焊接", "冲压", "注塑",
    "涂装", "喷涂", "装配", "物料", "模具", "夹具", "检具", "老化", "返修",
)

# Sentence terminators (Chinese + ASCII + newlines).
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")

# Capitalised English multi-word phrase, each word >= 2 chars total. ASCII
# lookaround instead of \b: Chinese characters are \w in Python re, so \b does
# not fire between a Chinese char and an English word start ("采用TTFAR").
_ENGLISH_ENTITY = re.compile(r"(?<![A-Za-z])[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*(?![A-Za-z])")

# Book-title / quoted spans (Chinese and ASCII quotes).
_QUOTED_SPANS = re.compile(r"《([^《》]{1,40})》|[“\"]([^“”\"]{1,40})[”\"]")

# Characters allowed inside a domain-word phrase extension (Chinese + digits).
_PHRASE_CHARS = re.compile(r"[\u4e00-\u9fff0-9]")

# Left/right extension budget around a domain word.
_MAX_PAD = 6

# Particles, function words and trigger-verb characters that terminate phrase
# expansion (trigger verbs must stay outside entity phrases or the dependency
# pattern below could never fire).
_BOUNDARY_CHARS = set(
    "的了是在和与及或者对被把用将需应可会能已且但之地得对于其该各每有无不也还就"
    "使让受到从到向给跟比以及采导属包含生检负责执完通按因虽并够由致要维护运转"
)

# Dependency-pattern (simplified) trigger verbs -> relation name.
_RELATION_VERBS: tuple[str, ...] = ("采用", "使用", "导致", "属于", "包含", "需要", "生产", "检测")

_VERB_GAP_LEFT = 12
_VERB_GAP_RIGHT = 6

_MAX_SENTENCE_CHARS = 4000

# Classification keyword tables (checked in order; first match wins).
_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("设备", ("设备", "产线", "生产线", "线体", "机器人", "焊机", "夹具", "模具", "检具", "工装", "机床")),
    ("工艺", ("工艺", "焊接", "冲压", "注塑", "涂装", "喷涂", "装配", "热处理", "机加工", "老化", "流程")),
    ("质量", ("质检", "质量", "不良", "缺陷", "检测", "合格", "返修", "返工", "审核", "故障")),
    ("部门", ("部", "车间", "班组", "科室", "中心", "委员会", "小组")),

)


def _classify(entity: str) -> str:
    """Heuristic entity typing: 设备/工艺/质量/部门/物料/通用."""
    for type_name, keywords in _TYPE_KEYWORDS:
        if any(k in entity for k in keywords):
            return type_name
    if any(k in entity for k in DOMAIN_WORDS):
        return "物料"
    return "通用"


def _extend_phrase(text: str, start: int, end: int) -> tuple[int, int]:
    ls = start
    while ls > 0 and (start - ls) < _MAX_PAD and _PHRASE_CHARS.match(text[ls - 1]) and text[ls - 1] not in _BOUNDARY_CHARS:
        ls -= 1
    le = end
    while le < len(text) and (le - end) < _MAX_PAD and _PHRASE_CHARS.match(text[le]) and text[le] not in _BOUNDARY_CHARS:
        le += 1
    return ls, le


def _extract_entities(text: str) -> dict[str, int]:
    """Deterministic mixed-language entity extraction for one text block.

    Returns ``{entity: occurrence_count}``.
    """
    if not isinstance(text, str) or not text:
        return {}
    found: dict[str, int] = {}

    def _add(name: str) -> None:
        name = name.strip()
        if len(name) >= 2:
            found[name] = found.get(name, 0) + 1

    for match in _ENGLISH_ENTITY.finditer(text):
        _add(match.group(0))

    for match in _QUOTED_SPANS.finditer(text):
        span = match.group(1) or match.group(2)
        if span:
            _add(span)

    for word in DOMAIN_WORDS:
        for match in re.finditer(re.escape(word), text):
            ls, le = _extend_phrase(text, *match.span())
            _add(text[ls:le])

    # Noise reduction: drop phrases fully contained in a longer extracted
    # phrase from the same block ("电池" inside "石墨烯电池").
    names = list(found)
    for name in names:
        if name in found and any(name != other and name in other for other in names):
            del found[name]
    return found


def _sentence_entities(sentence: str) -> dict[str, int]:
    return _extract_entities(sentence)


class KnowledgeGraphService:
    """In-process knowledge graph with deterministic build + query API."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[frozenset[str], dict[str, Any]] = {}

    # -- build ----------------------------------------------------------------

    def build_from_chunks(self, chunks: list[dict[str, Any]] | None) -> dict[str, Any]:
        """Merge entities/relations from ``chunks`` (each needs ``content``).

        Incremental: calling again accumulates mentions and edge weights, so
        repeated builds over the same corpus double-count intentionally only
        when the caller passes duplicate chunks. Returns current counts.
        """
        if not chunks or not isinstance(chunks, list):
            return self._count_report()
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            content = chunk.get("content")
            if not isinstance(content, str) or not content:
                continue
            source = chunk.get("source") or chunk.get("chunk_id") or ""
            for sentence in _SENTENCE_SPLIT.split(content):
                if not sentence or len(sentence) > _MAX_SENTENCE_CHARS:
                    continue
                self._ingest_sentence(sentence, source)
        return self._count_report()

    def _ingest_sentence(self, sentence: str, source: str) -> None:
        entities = _sentence_entities(sentence)
        with self._lock:
            for entity, count in entities.items():
                node = self._nodes.setdefault(entity, {"type": _classify(entity), "mentions": 0})
                node["mentions"] += count
            names = list(entities)
            for a, b in combinations(names, 2):
                rel_ab = self._pattern_relation(sentence, a, b)
                rel_ba = self._pattern_relation(sentence, b, a)
                if rel_ab is not None:
                    self._add_edge(a, b, rel_ab, source)
                elif rel_ba is not None:
                    self._add_edge(b, a, rel_ba, source)
                else:
                    self._add_edge(a, b, "co_occurs", source)

    @staticmethod
    def _pattern_relation(sentence: str, a: str, b: str) -> str | None:
        for verb in _RELATION_VERBS:
            pattern = (
                re.escape(a)
                + r".{0," + str(_VERB_GAP_LEFT) + r"}"
                + verb
                + r".{0," + str(_VERB_GAP_RIGHT) + r"}"
                + re.escape(b)
            )
            if re.search(pattern, sentence):
                return verb
        return None

    def _add_edge(self, a: str, b: str, relation: str, source: str) -> None:
        key = frozenset((a, b))
        edge = self._edges.get(key)
        if edge is None:
            edge = {"relation": relation, "weight": 0, "sources": set(), "pair": [a, b]}
            self._edges[key] = edge
        edge["weight"] += 1
        if relation != "co_occurs":
            edge["relation"] = relation
        if source:
            edge["sources"].add(source)

    # -- query ----------------------------------------------------------------

    def neighbors(self, entity: str | None, hops: int = 1) -> dict[str, Any]:
        """Multi-hop BFS around ``entity``; hops clamped to [1, 3]."""
        try:
            hops = max(1, min(3, int(hops)))
        except (TypeError, ValueError):
            hops = 1
        with self._lock:
            result: dict[str, Any] = {"entity": entity or "", "hops": hops, "nodes": [], "edges": []}
            if not entity or entity not in self._nodes:
                return result
            adjacency: dict[str, list[str]] = {}
            for key, _edge in self._edges.items():
                pair = list(key)
                if len(pair) < 2:
                    continue
                a, b = pair
                adjacency.setdefault(a, []).append(b)
                adjacency.setdefault(b, []).append(a)
            visited = {entity: 0}
            frontier = [entity]
            for depth in range(1, hops + 1):
                next_frontier: list[str] = []
                for current in frontier:
                    for neighbor in adjacency.get(current, []):
                        if neighbor not in visited:
                            visited[neighbor] = depth
                            next_frontier.append(neighbor)
                frontier = next_frontier
                if not frontier:
                    break
            for name, hop in sorted(visited.items()):
                node = self._nodes.get(name, {"type": "通用", "mentions": 0})
                result["nodes"].append({"entity": name, "type": node["type"], "mentions": node["mentions"], "hop": hop})
            for edge in self._edges.values():
                a, b = edge["pair"]
                if a in visited and b in visited:
                    result["edges"].append(self._dump_edge(a, b, edge))
            return result

    def search(self, keyword: str | None, top_k: int = 20) -> list[dict[str, Any]]:
        """Substring (case-insensitive) node search ordered by mentions."""
        if not keyword or not isinstance(keyword, str):
            return []
        try:
            top_k = max(1, min(100, int(top_k)))
        except (TypeError, ValueError):
            top_k = 20
        needle = keyword.lower()
        with self._lock:
            matches = [
                {"entity": name, "type": node["type"], "mentions": node["mentions"]}
                for name, node in self._nodes.items()
                if needle in name.lower()
            ]
        matches.sort(key=lambda item: (-item["mentions"], item["entity"]))
        return matches[:top_k]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return self._count_report(extra=True)

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()

    # -- internals -------------------------------------------------------------

    @staticmethod
    def _dump_edge(a: str, b: str, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": a,
            "target": b,
            "relation": edge["relation"],
            "weight": edge["weight"],
            "sources": sorted(edge["sources"]),
        }

    def _count_report(self, extra: bool = False) -> dict[str, Any]:
        relations: dict[str, int] = {}
        for edge in self._edges.values():
            relations[edge["relation"]] = relations.get(edge["relation"], 0) + 1
        report: dict[str, Any] = {"nodes": len(self._nodes), "edges": len(self._edges)}
        if extra:
            report["total_mentions"] = sum(node["mentions"] for node in self._nodes.values())
            report["relations"] = relations
        return report
