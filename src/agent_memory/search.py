"""`mem search` - fused retrieval over the KB (F3 lexical leg + F6 fusion).

One query fans out to three legs - FTS5 BM25, cosine over local embeddings,
1-hop graph expansion seeded from the lexical∪vector hits - and RRF fuses them
into one ranked list (fusion.py). Hits keep the agent-parseable contract
(slug/title/score/snippet), one screen by default; `sensitivity: work` items
are marked `[work]` in text and carry a sensitivity field in --json, and
`--no-work` drops them entirely. A daemon that cannot embed the query costs
exactly one warning line - lexical + graph still answer, exit 0: degraded,
never broken. Empty results stay quiet - exit 0, empty list, one line.
"""

import json
import sqlite3
import sys

from agent_memory import config, fusion, graph, lexical, okf, ollama, store, vector

LEG_POOL = 10  # minimum per-leg candidate pool feeding the fuse


def cmd_search(args) -> int:
    root = config.kb_root()
    try:
        store.require_kb(root)
    except store.StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    pool = max(args.limit, LEG_POOL)

    try:
        conn = lexical.connect(root)
        try:
            changed, removed = lexical.sync(conn, root)
            lex_hits = lexical.search(conn, args.query, pool)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"error: lexical index: {e}", file=sys.stderr)
        return 1

    # External-edit healing (F8): before the vector leg runs, drop vectors for
    # deleted files and enqueue re-embeds for edited ones - the post-command
    # drain replaces stale vectors without any manual reindex.
    vector.reconcile(root, changed, removed)

    # Vector leg: an unreachable/refusing daemon degrades the search to
    # lexical + graph with exactly one warning line, never an error. Zero or
    # negative cosine is no evidence - such hits must not earn RRF credit.
    vec_hits = []
    try:
        vec_hits = [
            (slug, score)
            for slug, score in vector.top_k(root, args.query, k=pool)
            if score > 0.0
        ]
    except ollama.OllamaError as e:
        vector.mark_daemon_unhealthy()  # skip the post-command drain's re-probe
        print(f"warning: semantic leg skipped ({e})", file=sys.stderr)
    except vector.VectorError as e:
        print(f"warning: semantic leg skipped ({e})", file=sys.stderr)

    lex_slugs = [hit["slug"] for hit in lex_hits]
    vec_slugs = [slug for slug, _ in vec_hits]
    seeds = list(dict.fromkeys(lex_slugs + vec_slugs))
    graph_slugs = fusion.graph_leg(graph.load(root), seeds)

    snippets = {hit["slug"]: hit["snippet"] for hit in lex_hits}
    hits = []
    for slug, score in fusion.rrf([lex_slugs, vec_slugs, graph_slugs]):
        if len(hits) >= args.limit:
            break
        try:
            concept = okf.parse(
                store.concept_path(root, slug).read_text(encoding="utf-8")
            )
        except (OSError, okf.OKFError):
            continue  # deleted or unparseable since the legs ran - no ghost hits
        if args.no_work and concept.sensitivity == "work":
            continue
        hit = {
            "slug": slug,
            "title": concept.title,
            "score": round(score, 4),
            # non-lexical hits have no FTS5 snippet; the description stands in
            "snippet": snippets.get(slug) or concept.description,
        }
        if concept.sensitivity == "work":
            hit["sensitivity"] = "work"
        hits.append(hit)

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        if not hits:
            print(f"no matches: {args.query}", file=sys.stderr)
    elif not hits:
        print(f"no matches: {args.query}")
    else:
        for hit in hits:
            mark = "  [work]" if hit.get("sensitivity") == "work" else ""
            print(f"{hit['slug']}  {hit['score']:.2f}  {hit['title']}{mark}")
            print(f"    {hit['snippet']}")
    return 0
