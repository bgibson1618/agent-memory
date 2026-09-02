"""`mem reindex` - rebuild every derived index from the markdown alone (F8).

All of `.index/` is disposable EXCEPT `usage.jsonl` (D8) and `dedup-log.jsonl`
(D18 S4.5, the SAME D8 precedent - neither is knowledge, neither is derived,
reindex leaves both alone; gate finding 9 caught this docstring naming only
the newer of the two): the lexical FTS5 tables, the graph cache, the vector
store, and the D18 chunk index are wiped and rebuilt from concepts/*.md in
one command.
Lexical and graph rebuild locally and unconditionally; vectors re-enqueue
every parseable concept and drain fully. The chunk index (D18 S3) is always
dropped (stale sub-card windows must not survive a body edit) but only
eagerly repopulated with `--chunks` - population is opt-in and otherwise
stays lazy/retrieval-driven, per D18's disposable-index posture. A daemon
that is down leaves the embeds queued with one stderr line and exit 0 - they
drain when it returns. Unchanged content rebuilds to equivalent search
results, so reindex is always safe to run.
"""

import sys

from agent_memory import chunks, config, dedup, graph, lexical, ollama, vector


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

    # D18 S3: the chunk index is fully disposable - drop every stale row
    # regardless of --chunks, since a body edit invalidates old chunk
    # vectors; only --chunks pays to eagerly repopulate them.
    chunk_con = chunks.connect(root)
    try:
        chunk_con.execute("DELETE FROM chunks")
        chunk_con.commit()
    finally:
        chunk_con.close()
    chunk_note = ""
    if getattr(args, "chunks", False):
        cfg = dedup.load_config()
        populated, _current, skipped_oversize, chunk_error = chunks.populate_all(
            root, indexed, cfg, vector.FULL_DRAIN_TIMEOUT
        )
        chunk_note = f"; chunks: {populated} populated, {skipped_oversize} skipped-oversize"
        if chunk_error is not None:
            chunk_note += f" ({chunk_error} - remaining chunks drain on a later --chunks run)"

    if remaining == 0:
        print(
            f"reindexed: {len(indexed)} concept(s) - lexical + graph rebuilt,"
            f" {drained} embedding(s) drained{chunk_note}"
        )
        return 0
    if isinstance(error, ollama.OllamaError):
        print(
            f"reindexed: {len(indexed)} concept(s) - lexical + graph rebuilt;"
            f" {drained} embedded, {remaining} queued - {error};"
            f" they drain when the daemon returns{chunk_note}",
            file=sys.stderr,
        )
        return 0
    print(f"error: {error} ({remaining} embedding(s) still queued)", file=sys.stderr)
    return 1
