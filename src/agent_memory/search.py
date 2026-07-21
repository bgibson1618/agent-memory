"""`mem search` - keyword search over the KB, BM25-ranked, Ollama-free.

The lexical leg answers alone in F3: sync the derived FTS5 index against the
markdown, run the literal-term query, and print agent-parseable hits (slug,
title, score, snippet). Empty results are quiet - exit 0, empty list, one line.
"""

import json
import sqlite3
import sys

from agent_memory import config, lexical, store


def cmd_search(args) -> int:
    root = config.kb_root()
    try:
        store.require_kb(root)
    except store.StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        conn = lexical.connect(root)
        try:
            lexical.sync(conn, root)
            hits = lexical.search(conn, args.query, args.limit)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"error: lexical index: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        if not hits:
            print(f"no matches: {args.query}", file=sys.stderr)
    elif not hits:
        print(f"no matches: {args.query}")
    else:
        for hit in hits:
            print(f"{hit['slug']}  {hit['score']:.2f}  {hit['title']}")
            print(f"    {hit['snippet']}")
    return 0
