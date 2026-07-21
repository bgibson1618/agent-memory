"""Concept graph derived from the markdown - F5.

Body `[[wikilinks]]` and frontmatter `related[]` become direct edges; topics
connect concepts through topic nodes (concept -> topic -> concept), stored as
per-concept memberships and never materialized pairwise - a broad tag stays
O(members), not O(members^2). The cache at .index/graph.json is derived state
keyed by file mtime/size: an external edit invalidates its entry on the next
read, a deleted file drops out, and the whole thing rebuilds from markdown.
Bodies keep plain Obsidian wikilink syntax; node identity is the file stem,
exactly what Obsidian links by.
"""

import json
import os
import re
from pathlib import Path

from agent_memory import okf

CACHE_VERSION = 1
_RECORD_KEYS = ("mtime_ns", "size", "title", "links", "related", "topics")

# Obsidian forms: [[target]], [[target|alias]], [[target#heading]]
_WIKILINK_RE = re.compile(r"\[\[([^\[\]#|]+)(?:[#|][^\[\]]*)?\]\]")


def cache_path(root: Path) -> Path:
    return root / ".index" / "graph.json"


def _safe_slug(text: str):
    try:
        return okf.slugify(text)
    except okf.OKFError:
        return None  # a link like [[???]] names nothing - no edge


def _link_targets(body: str) -> list:
    targets = []
    for raw in _WIKILINK_RE.findall(body):
        slug = _safe_slug(raw)
        if slug and slug not in targets:
            targets.append(slug)
    return targets


def _scan(path: Path):
    """One cache record from one concept file; None if it isn't a concept."""
    try:
        concept = okf.parse(path.read_text(encoding="utf-8"))
    except (OSError, okf.OKFError):
        return None  # unparseable files contribute no nodes or edges
    related = []
    for raw in concept.related:
        slug = _safe_slug(raw)
        if slug and slug not in related:
            related.append(slug)
    return {
        "title": concept.title,
        "links": _link_targets(concept.body),
        "related": related,
        "topics": list(concept.topics),
    }


def _read_cache(root: Path) -> dict:
    try:
        data = json.loads(cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}
    files = data.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        stem: record
        for stem, record in files.items()
        if isinstance(record, dict) and all(key in record for key in _RECORD_KEYS)
    }


def _write_cache(root: Path, records: dict) -> None:
    path = cache_path(root)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"version": CACHE_VERSION, "files": records}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)  # cache is an optimization - never fail a read


def load(root: Path) -> "Graph":
    """The current graph: cached records where mtime/size still match,
    fresh parses where they don't, deleted files gone."""
    cached = _read_cache(root)
    records = {}
    for path in sorted((root / "concepts").glob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue  # deleted between glob and stat
        entry = cached.get(path.stem)
        if entry and entry["mtime_ns"] == stat.st_mtime_ns and entry["size"] == stat.st_size:
            records[path.stem] = entry
            continue
        fresh = _scan(path)
        if fresh is None:
            continue
        fresh["mtime_ns"] = stat.st_mtime_ns
        fresh["size"] = stat.st_size
        records[path.stem] = fresh
    if records != cached:
        _write_cache(root, records)
    return Graph(records)


class Graph:
    """In-memory adjacency over the cache records. 1-hop neighborhoods here;
    multi-hop traversal for the search leg arrives with fusion (F6)."""

    def __init__(self, records: dict):
        self.records = records

    def _title(self, slug: str) -> str:
        return self.records[slug]["title"]

    def neighbors(self, slug: str) -> dict:
        """Link- and topic-neighbors of one concept - existing files only,
        so edges to deleted or dangling targets never surface."""
        me = self.records.get(slug)
        if me is None:
            return {"links": [], "topics": []}

        via = {}  # neighbor slug -> ordered edge kinds

        def add(neighbor: str, kind: str) -> None:
            if neighbor == slug or neighbor not in self.records:
                return
            kinds = via.setdefault(neighbor, [])
            if kind not in kinds:
                kinds.append(kind)

        for target in me["links"]:
            add(target, "wikilink")
        for target in me["related"]:
            add(target, "related")
        for other, record in self.records.items():
            if other != slug and (slug in record["links"] or slug in record["related"]):
                add(other, "backlink")

        links = [
            {"slug": neighbor, "title": self._title(neighbor), "via": kinds}
            for neighbor, kinds in sorted(via.items())
        ]
        topics = []
        for topic in me["topics"]:
            members = sorted(
                other
                for other, record in self.records.items()
                if other != slug and topic in record["topics"]
            )
            if members:
                topics.append(
                    {
                        "topic": topic,
                        "neighbors": [
                            {"slug": member, "title": self._title(member)} for member in members
                        ],
                    }
                )
        return {"links": links, "topics": topics}
