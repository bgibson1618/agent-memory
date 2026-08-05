#!/usr/bin/env python3
"""One-shot D12 backfill: repair the KB's existing dangling wikilink/related
targets (accumulated before extract learned to remap batch-mate links).

Run from the repo with its venv:  uv run python scripts/repair-dangling-links.py
Dry-run by default (writes the report, touches nothing); --apply rewrites.

Per dangling target:
- numeric-only targets (e.g. [[91]]) are citation dirt from one extraction
  lens: DELINK - brackets stripped in bodies, entries dropped from related.
- everything else embeds as a search query (de-kebabed) and cosine-matches
  against the KB's stored vectors, POOL-RESTRICTED to `concept`/`reference`
  types (a dangling link in vetted material must never be repointed at an
  sb-position hypothesis - the D10 credence boundary applies to edges too).
  top1 >= --floor with top1-top2 >= --margin: AUTO-repair, rewriting
  [[target]] -> [[match|<original display text>]] so the rendered text is
  unchanged while the link resolves; below the bar: REVIEW (left dangling,
  listed in the report for curation).

Repairs preserve `updated:` stamps (a link repair is not a content update -
the backfill-source precedent), are committed to the KB git in one commit,
and require `mem reindex` afterward (bodies changed -> vectors must follow;
the script runs it unless --no-reindex).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from agent_memory import config, graph, okf, ollama, vector

REPORT_DIR = Path.home() / "projects/learning-science/pipeline/runs/link-repair-2026-08-05"
POOL_TYPES = {"concept", "reference"}
NUMERIC = re.compile(r"^\d+$")
# graph._WIKILINK_RE with the display tail captured (extract.py uses the same)
LINK_RE = re.compile(r"\[\[([^\[\]#|]+)([#|][^\[\]]*)?\]\]")
EMBED_BATCH = 64


def kb_vectors_by_type(root: Path):
    """[(slug, unit vec)] for concepts whose type is in POOL_TYPES."""
    import numpy as np

    con = vector.connect(root)
    try:
        rows = con.execute("SELECT slug, vec FROM vectors").fetchall()
    finally:
        con.close()
    pool = []
    for slug, blob in rows:
        path = root / "concepts" / f"{slug}.md"
        try:
            concept = okf.parse(path.read_text(encoding="utf-8"))
        except (OSError, okf.OKFError):
            continue
        if concept.type not in POOL_TYPES:
            continue
        v = np.frombuffer(blob, dtype="float32")
        norm = float(np.linalg.norm(v))
        if norm > 0.0:
            pool.append((slug, v / norm))
    return pool


def match_targets(targets: list, pool) -> dict:
    """{target: (best_slug, top1, top2)} via batched query embeds."""
    import numpy as np

    base, model = config.ollama_base_url(), config.embed_model()
    out = {}
    mat = np.vstack([u for _, u in pool])
    slugs = [s for s, _ in pool]
    for i in range(0, len(targets), EMBED_BATCH):
        chunk = targets[i:i + EMBED_BATCH]
        queries = ["search_query: " + t.replace("-", " ") for t in chunk]
        vecs = ollama.embed(base, model, queries, timeout=vector.FULL_DRAIN_TIMEOUT)
        for target, q in zip(chunk, vecs):
            q = np.asarray(q, dtype="float32")
            qn = float(np.linalg.norm(q))
            if qn == 0.0:
                out[target] = (None, 0.0, 0.0)
                continue
            scores = mat @ (q / qn)
            order = np.argsort(-scores)
            top1 = float(scores[order[0]])
            top2 = float(scores[order[1]]) if len(order) > 1 else 0.0
            out[target] = (slugs[order[0]], top1, top2)
        print(f"  matched {min(i + EMBED_BATCH, len(targets))}/{len(targets)}", file=sys.stderr)
    return out


def rewrite_file(path: Path, repairs: dict, delink: set) -> int:
    """Apply this file's repairs; returns rewritten reference count.
    Writes directly (no updated: bump) - link repair is not a content edit."""
    concept = okf.parse(path.read_text(encoding="utf-8"))
    count = 0

    def sub(m):
        nonlocal count
        try:
            slug = okf.slugify(m.group(1))
        except okf.OKFError:
            return m.group(0)
        if slug in delink:
            count += 1
            return m.group(1)  # strip brackets, keep the literal text
        new = repairs.get(slug)
        if new is None:
            return m.group(0)
        count += 1
        if m.group(2) and m.group(2).startswith("|"):
            return f"[[{new}{m.group(2)}]]"       # keep the existing alias
        return f"[[{new}|{m.group(1)}]]"          # display text unchanged

    concept.body = LINK_RE.sub(sub, concept.body)
    related = []
    for entry in concept.related:
        if entry in delink:
            count += 1
            continue
        new = repairs.get(entry, entry)
        if new != entry:
            count += 1
        if new not in related:
            related.append(new)
    concept.related = related
    if count:
        path.write_text(okf.serialize(concept), encoding="utf-8")
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite files (default: dry-run)")
    ap.add_argument("--floor", type=float, default=0.75, help="min top-1 cosine for auto-repair")
    ap.add_argument("--margin", type=float, default=0.03, help="min top1-top2 gap for auto-repair")
    ap.add_argument("--no-reindex", action="store_true", help="skip mem reindex after apply")
    args = ap.parse_args()

    root = config.kb_root()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True,
    ).stdout.strip()
    if args.apply and dirty:
        print("error: KB git is dirty - commit or clean before --apply", file=sys.stderr)
        return 1

    dangling = graph.load(root).dangling()
    if not dangling:
        print("nothing dangling - done")
        return 0
    delink = {t for t in dangling if NUMERIC.match(t)}
    to_match = sorted(t for t in dangling if t not in delink)
    print(f"{len(dangling)} dangling targets: {len(delink)} numeric (delink), "
          f"{len(to_match)} to match", file=sys.stderr)

    pool = kb_vectors_by_type(root)
    print(f"match pool: {len(pool)} {'/'.join(sorted(POOL_TYPES))} vectors", file=sys.stderr)
    matches = match_targets(to_match, pool)

    auto, review = {}, []
    for target, (slug, top1, top2) in matches.items():
        entry = {
            "target": target, "match": slug, "top1": round(top1, 4),
            "top2": round(top2, 4), "referrers": dangling[target],
        }
        if slug and top1 >= args.floor and (top1 - top2) >= args.margin:
            auto[target] = slug
            entry["action"] = "auto"
        else:
            entry["action"] = "review"
            review.append(entry)
        matches[target] = entry

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "floor": args.floor, "margin": args.margin, "applied": args.apply,
        "delink": sorted(delink),
        "auto": [m for m in matches.values() if m["action"] == "auto"],
        "review": review,
    }
    report_path = REPORT_DIR / "repair-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"auto: {len(auto)}  review: {len(review)}  delink: {len(delink)}"
          f"  -> {report_path}")

    if not args.apply:
        print("dry-run: nothing written (rerun with --apply)")
        return 0

    touched, refs = 0, 0
    referrers = set()
    for target, slugs_ in dangling.items():
        if target in auto or target in delink:
            referrers.update(slugs_)
    for slug in sorted(referrers):
        n = rewrite_file(root / "concepts" / f"{slug}.md", auto, delink)
        if n:
            touched += 1
            refs += n
    print(f"rewrote {refs} reference(s) in {touched} concept(s)")

    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m",
         f"link repair (D12 backfill): {refs} refs in {touched} concepts;"
         f" {len(auto)} targets matched, {len(delink)} delinked"],
        check=True, capture_output=True,
    )
    print("KB committed")

    if not args.no_reindex:
        print("reindexing (bodies changed -> vectors must follow)...", file=sys.stderr)
        subprocess.run(["mem", "reindex"], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
