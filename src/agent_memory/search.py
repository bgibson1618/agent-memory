"""`mem search` - fused retrieval over the KB (F3 lexical leg + F6 fusion).

One query fans out to three legs - FTS5 BM25, cosine over local embeddings,
1-hop graph expansion seeded from the lexical∪vector hits - and RRF fuses them
into one ranked list (fusion.py). Hits keep the agent-parseable contract
(slug/title/score/snippet), one screen by default; non-`normal` sensitivities
are marked `[work]`/`[sensitive]` in text and carry a sensitivity field in
--json; `--no-work` / `--no-sensitive` drop their tier entirely (D16). Retrieval is credence-blind by design (cosine
has no epistemics), so a non-`concept` type is marked `[<type>]` in text and
carried in --json - an `sb-position` hypothesis never reads as vetted
`concept` knowledge at recall time (D10); `--type a,b` restricts results to an
allow-list of types (e.g. `--type concept` to ground only in vetted knowledge).
Hits the semantic leg scored also carry
`semantic_similarity` in --json (raw cosine; absent for lexical/graph-only
hits and on degraded searches) - RRF says which hits agree across legs, the
cosine says how close the best semantic evidence actually is. A daemon that
cannot embed the query costs
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

    type_filter = {t.strip() for t in (getattr(args, "type", None) or "").split(",") if t.strip()}
    # Post-fusion filters eat leg candidates: with a filter active, the top of
    # every leg can be entirely filtered types while real matches sit at rank
    # 11+ (the 2026-08-05 quality-review recall cliff). Widen the pools so
    # filtering selects from a deeper field instead of starving the result.
    no_sensitive = getattr(args, "no_sensitive", False)  # same tolerance as `type`
    pool = max(args.limit, LEG_POOL) * (
        3 if type_filter or args.no_work or no_sensitive else 1)

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
    except sqlite3.Error as e:
        # a corrupt/locked derived index must degrade like a dead daemon, not
        # traceback: it is recoverable state (mem reindex), same contract
        print(
            f"warning: semantic leg skipped (vector index unreadable: {e} - run: mem reindex)",
            file=sys.stderr,
        )

    lex_slugs = [hit["slug"] for hit in lex_hits]
    vec_slugs = [slug for slug, _ in vec_hits]
    # Raw cosine per semantically-scored hit: RRF encodes rank agreement, not
    # similarity magnitude, so downstream thresholding (is this item actually
    # CLOSE to anything in the KB?) needs the leg's own score surfaced. Only
    # the vector leg's pool carries cosines: a hit outside the top `pool`
    # positive-cosine results has none, and that absence is itself signal.
    vec_scores = dict(vec_hits)
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
        if no_sensitive and concept.sensitivity == "sensitive":
            continue
        if type_filter and concept.type not in type_filter:
            continue
        hit = {
            "slug": slug,
            "title": concept.title,
            "type": concept.type,
            "score": round(score, 4),
            # non-lexical hits have no FTS5 snippet; the description stands in
            "snippet": snippets.get(slug) or concept.description,
        }
        if slug in vec_scores:
            hit["semantic_similarity"] = round(vec_scores[slug], 4)
        if concept.sensitivity != "normal":
            hit["sensitivity"] = concept.sensitivity
        hits.append(hit)

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        if not hits:
            print(f"no matches: {args.query}", file=sys.stderr)
    elif not hits:
        print(f"no matches: {args.query}")
    else:
        for hit in hits:
            marks = ""
            if hit["type"] != okf.TYPE_DEFAULT:
                marks += f"  [{hit['type']}]"
            if hit.get("sensitivity"):
                marks += f"  [{hit['sensitivity']}]"
            print(f"{hit['slug']}  {hit['score']:.2f}  {hit['title']}{marks}")
            print(f"    {hit['snippet']}")
    return 0
