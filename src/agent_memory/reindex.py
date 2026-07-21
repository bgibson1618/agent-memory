"""`mem reindex` - rebuild every derived index from the markdown alone (F8).

All of `.index/` is disposable: the lexical FTS5 tables, the graph cache, and
the vector store are wiped and rebuilt from concepts/*.md in one command.
Lexical and graph rebuild locally and unconditionally; vectors re-enqueue
every parseable concept and drain fully. A daemon that is down leaves the
embeds queued with one stderr line and exit 0 - they drain when it returns.
Unchanged content rebuilds to equivalent search results, so reindex is always
safe to run.
"""

import sys

from agent_memory import config, graph, lexical, ollama, vector


def cmd_reindex(args) -> int:
    root = config.kb_root()
    if not (root / "concepts").is_dir():
        print(f"error: no KB home at {root} - run: mem init", file=sys.stderr)
        return 1

    # Lexical: wipe both tables, then a full sync re-indexes every parseable
    # file (unparseable ones warn and are skipped, exactly like search).
    conn = lexical.connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM lexical")
        conn.execute("DELETE FROM lexical_files")
        conn.execute("COMMIT")
        indexed, _removed = lexical.sync(conn, root)
    finally:
        conn.close()

    # Graph: drop the cache; one load rebuilds it from the markdown.
    graph.cache_path(root).unlink(missing_ok=True)
    graph.load(root)

    # Vector: wipe vectors + queue + metadata, enqueue everything the lexical
    # rebuild just parsed, drain fully (the first embed re-stamps the meta).
    con = vector.connect(root)
    try:
        con.execute("DELETE FROM vectors")
        con.execute("DELETE FROM embed_queue")
        con.execute("DELETE FROM vector_meta")
        for slug, _concept in indexed:
            vector.enqueue(con, slug)
        con.commit()
    finally:
        con.close()

    drained, remaining, error = vector.drain_fully(root)
    if remaining == 0:
        print(
            f"reindexed: {len(indexed)} concept(s) - lexical + graph rebuilt,"
            f" {drained} embedding(s) drained"
        )
        return 0
    if isinstance(error, ollama.OllamaError):
        print(
            f"reindexed: {len(indexed)} concept(s) - lexical + graph rebuilt;"
            f" {drained} embedded, {remaining} queued - {error};"
            " they drain when the daemon returns",
            file=sys.stderr,
        )
        return 0
    print(f"error: {error} ({remaining} embedding(s) still queued)", file=sys.stderr)
    return 1
