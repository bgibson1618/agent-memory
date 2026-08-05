"""`mem extract` - the deterministic half of extract-knowledge.

Candidate concepts (JSON) come in; each is validated item-wise, embedded, and
deduped against the KB's vectors by cosine similarity against the calibrated
threshold (config.DEFAULT_DEDUP_THRESHOLD, recorded with its measurement in
research/dedup-calibration.md). Novel candidates are saved through the same
mechanics as `mem save` (atomic write + one commit per concept + in-line
lexical index) and their already-computed embeddings are stored directly.
Dedup requires embeddings: with Ollama unreachable the whole batch is refused
with a one-line error before anything is saved. All embedding happens up
front (queue drain + one batched embed call), so a daemon failure can never
leave the batch partially saved.

The agent-side half - the extract-knowledge choreography (fresh-eyed extractor
fan-out, fresh-eyed review, disposition review) - ships as package data and is
printed by `mem extract --procedure`.
"""

import json
import re
import sys
from pathlib import Path

from agent_memory import blocks, config, gitkb, lexical, okf, ollama, store, vector

# Mirrors graph._WIKILINK_RE, but captures the |alias / #heading tail so a
# remap preserves it: [[target]], [[target|alias]], [[target#heading]].
_LINK_RE = re.compile(r"\[\[([^\[\]#|]+)([#|][^\[\]]*)?\]\]")

CANDIDATE_FIELDS = {
    "title", "body", "description", "topics", "type", "sensitivity", "related", "slug",
    "source",
}


class ExtractError(Exception):
    """A one-line, agent-actionable extract refusal."""


def _load_candidates(raw: str) -> list:
    """Accept a file path, '-' for stdin, or inline JSON. The payload is a JSON
    array of candidate objects (or an object with a 'candidates' array)."""
    if raw == "-":
        text = sys.stdin.read()
    else:
        path = Path(raw)
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if is_file:
            text = path.read_text(encoding="utf-8")
        elif raw.lstrip().startswith(("[", "{")):
            text = raw
        else:
            raise ExtractError(f"no such candidates file: {raw}")
    try:
        data = json.loads(text)
    except ValueError as e:
        reason = str(e).splitlines()[0]
        raise ExtractError(f"candidates are not valid JSON: {reason}") from e
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        data = data["candidates"]
    if not isinstance(data, list):
        raise ExtractError(
            "candidates JSON must be an array of objects (or {\"candidates\": [...]})"
        )
    return data


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return store._split_csv(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise okf.OKFError(f"expected a list or comma-separated string, got {type(value).__name__}")


def _to_concept(item) -> okf.Concept:
    """Validate one candidate into an OKF concept; okf.OKFError is the
    item-wise rejection reason."""
    if not isinstance(item, dict):
        raise okf.OKFError("candidate is not a JSON object")
    unknown = sorted(set(item) - CANDIDATE_FIELDS)
    if unknown:
        raise okf.OKFError(f"unknown field(s): {', '.join(unknown)}")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise okf.OKFError("missing required field: title")
    body = item.get("body")
    if not isinstance(body, str) or not body.strip():
        raise okf.OKFError("missing required field: body")
    stamp = okf.now_stamp()
    return okf.Concept(
        slug=okf.slugify(str(item.get("slug") or title)),
        title=title.strip(),
        description=str(item.get("description") or "").strip()
        or store._derive_description(body),
        type=str(item.get("type") or okf.TYPE_DEFAULT),
        topics=_as_list(item.get("topics")),
        sensitivity=str(item.get("sensitivity") or "normal"),
        created=stamp,
        updated=stamp,
        related=[okf.slugify(r) for r in _as_list(item.get("related"))],
        source=str(item.get("source") or "").strip() or f"extract ({stamp[:10]})",
        body=body,
    ).validate()


def _kb_vectors(con, dims: int) -> list:
    """[(slug, unit vector)] for every stored embedding of matching dims."""
    import numpy as np  # deferred, like vector.top_k

    entries = []
    for slug, blob in con.execute("SELECT slug, vec FROM vectors WHERE dims = ?", (dims,)):
        v = np.frombuffer(blob, dtype=np.float32)
        norm = float(np.linalg.norm(v))
        if norm > 0.0:
            entries.append((slug, v / norm))
    return entries


def _best_match(vec, entries):
    """(slug, cosine) of the nearest stored vector, or (None, 0.0)."""
    import numpy as np

    q = np.asarray(vec, dtype=np.float32)
    qnorm = float(np.linalg.norm(q))
    if qnorm == 0.0 or not entries:
        return None, 0.0
    q = q / qnorm
    best_slug, best = None, -1.0
    for slug, unit in entries:
        score = float(unit @ q)
        if score > best:
            best_slug, best = slug, score
    return best_slug, best


def _save_novel(root: Path, concept: okf.Concept) -> tuple:
    """Save with the same mechanics as `mem save` (lock, atomic write, one
    commit, in-line lexical index). extract never overwrites: a taken slug
    gets the first free -N suffix, chosen under the lock. Returns
    (concept, suffixed: bool)."""
    with store.write_lock(root):
        base = concept.slug
        slug, n = base, 2
        while store.concept_path(root, slug).exists():
            slug, n = f"{base}-{n}", n + 1
        concept.slug = slug
        text = okf.serialize(concept)
        path = store.concept_path(root, slug)
        store._sweep_dead_temps(store.concepts_dir(root))
        store.atomic_write(path, text)
        gitkb.commit_path(root, f"concepts/{slug}.md", f"mem extract: {slug}")
        lexical.record_save(root, concept, path)
    return concept, slug != base


def _remap_links(concept: okf.Concept, rename: dict) -> int:
    """Rewrite the concept's wikilinks and related entries whose (slugified)
    target is a batch-mate that landed elsewhere. Returns rewritten count."""
    count = 0

    def sub(m):
        nonlocal count
        try:
            slug = okf.slugify(m.group(1))
        except okf.OKFError:
            return m.group(0)
        new = rename.get(slug)
        if not new or new == slug:
            return m.group(0)
        count += 1
        return f"[[{new}{m.group(2) or ''}]]"

    concept.body = _LINK_RE.sub(sub, concept.body)
    related = []
    for entry in concept.related:
        new = rename.get(entry, entry)
        if new != entry:
            count += 1
        if new not in related:
            related.append(new)
    concept.related = related
    return count


def _store_vector(con, slug: str, text: str, vec: list) -> None:
    """Store the candidate's already-computed embedding (meta was verified
    against the current model before the batch started)."""
    from array import array

    if vector.get_meta(con) is None:
        model = config.embed_model()
        vector._stamp_meta(
            con, model, ollama.model_digest(config.ollama_base_url(), model), len(vec)
        )
    con.execute(
        "INSERT OR REPLACE INTO vectors(slug, model, dims, content_hash, vec, updated)"
        " VALUES(?, ?, ?, ?, ?, ?)",
        (
            slug, config.embed_model(), len(vec), vector.content_hash(text),
            array("f", vec).tobytes(), okf.now_stamp(),
        ),
    )
    con.execute("DELETE FROM embed_queue WHERE slug = ?", (slug,))
    con.commit()


def cmd_extract(args) -> int:
    if args.procedure:
        # The agent-side choreography, shipped as package data. Printing it
        # needs neither a KB nor the daemon.
        sys.stdout.write(blocks.render_block(blocks.EXTRACT_PROCEDURE))
        return 0
    if not args.candidates:
        print("error: extract requires --candidates (or --procedure)", file=sys.stderr)
        return 1
    try:
        return _extract(args)
    except (ExtractError, store.StoreError, okf.OKFError, vector.VectorError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ollama.OllamaError as e:
        vector.mark_daemon_unhealthy()
        print(f"error: cannot dedup without embeddings: {e}", file=sys.stderr)
        return 1


def _extract(args) -> int:
    root = config.kb_root()
    store.require_kb(root)
    store.warn_if_remote(root)
    threshold = config.dedup_threshold()

    items = _load_candidates(args.candidates)
    results: list = [None] * len(items)
    valid = []  # (index, concept)
    for i, item in enumerate(items):
        try:
            valid.append((i, _to_concept(item)))
        except okf.OKFError as e:
            title = item.get("title") if isinstance(item, dict) else None
            results[i] = {
                "index": i,
                "title": title if isinstance(title, str) else None,
                "disposition": "invalid",
                "reason": str(e),
            }

    if valid:
        # Dedup requires a complete vector index: drain any queued embeds
        # first, then embed the whole batch in one call - any daemon trouble
        # refuses the batch here, before a single save.
        _, _, error = vector.drain_fully(root)
        if error is not None:
            raise error
        texts = [vector.embed_text(c) for _, c in valid]
        vecs = ollama.embed(
            config.ollama_base_url(), config.embed_model(), texts,
            timeout=vector.FULL_DRAIN_TIMEOUT,
        )

        con = vector.connect(root)
        try:
            vector.check_meta(
                vector.get_meta(con), config.embed_model(), len(vecs[0]), "cannot dedup"
            )
            entries = _kb_vectors(con, len(vecs[0]))

            import numpy as np

            # Links to batch-mates follow the batch-mate wherever it lands
            # (D12): a skipped duplicate's slug remaps to its match, a
            # suffixed save's intended slug to the actual one - so an extract
            # can never mint a link to a slug it decided not to create.
            rename = {}  # never-landed candidate slug -> slug carrying the concept
            saved = []   # (result index, concept) saved this batch, for the remap
            for (i, concept), text, vec in zip(valid, texts, vecs):
                match, similarity = _best_match(vec, entries)
                if match is not None and similarity >= threshold:
                    rename[concept.slug] = match
                    results[i] = {
                        "index": i,
                        "title": concept.title,
                        "disposition": "skipped-duplicate",
                        "match": match,
                        "similarity": round(similarity, 4),
                    }
                    continue
                intended = concept.slug
                concept, suffixed = _save_novel(root, concept)
                _store_vector(con, concept.slug, text, vec)
                q = np.asarray(vec, dtype=np.float32)
                entries.append((concept.slug, q / float(np.linalg.norm(q))))
                results[i] = {
                    "index": i,
                    "title": concept.title,
                    "disposition": "added",
                    "slug": concept.slug,
                    "path": str(store.concept_path(root, concept.slug)),
                }
                if suffixed:
                    rename[intended] = concept.slug
                    results[i]["note"] = "slug taken by a distinct concept - saved under a fresh slug"
                saved.append((i, concept))

            remapped = []  # (slug, new embed text) - vectors must follow bodies
            for i, concept in saved:
                if not rename:
                    break
                changed = _remap_links(concept, rename)
                if changed == 0:
                    continue
                path = store.concept_path(root, concept.slug)
                with store.write_lock(root):
                    store.atomic_write(path, okf.serialize(concept))
                    gitkb.commit_path(
                        root, f"concepts/{concept.slug}.md",
                        f"mem extract: link remap {concept.slug}",
                    )
                    lexical.record_save(root, concept, path)
                results[i]["remapped_links"] = changed
                remapped.append((concept.slug, vector.embed_text(concept)))
            if remapped:
                # Re-embed rewritten bodies so stored content hashes stay
                # true; on daemon trouble fall back to the durable queue.
                try:
                    revecs = ollama.embed(
                        config.ollama_base_url(), config.embed_model(),
                        [text for _, text in remapped],
                        timeout=vector.FULL_DRAIN_TIMEOUT,
                    )
                    for (slug, text), vec in zip(remapped, revecs):
                        _store_vector(con, slug, text, vec)
                except ollama.OllamaError:
                    for slug, _ in remapped:
                        vector.enqueue(con, slug)
                    con.commit()
        finally:
            con.close()

    counts = {"added": 0, "skipped-duplicate": 0, "invalid": 0}
    for r in results:
        counts[r["disposition"]] += 1
    links_remapped = sum(r.get("remapped_links", 0) for r in results if r)

    if args.json:
        print(json.dumps(
            {
                "threshold": threshold,
                "added": counts["added"],
                "skipped_duplicate": counts["skipped-duplicate"],
                "invalid": counts["invalid"],
                "links_remapped": links_remapped,
                "results": results,
            },
            indent=2, ensure_ascii=False,
        ))
    else:
        for r in results:
            if r["disposition"] == "added":
                note = f" [{r['note']}]" if "note" in r else ""
                print(f"added: {r['slug']} ({r['title']}){note}")
            elif r["disposition"] == "skipped-duplicate":
                print(
                    f"skipped-duplicate: {r['title']} - matches '{r['match']}'"
                    f" (similarity {r['similarity']:.2f} >= threshold {threshold:.2f})"
                )
            else:
                who = f"candidate #{r['index'] + 1}" + (f" ({r['title']})" if r["title"] else "")
                print(f"invalid: {who} - {r['reason']}")
        summary = (
            f"extract: {counts['added']} added, {counts['skipped-duplicate']}"
            f" skipped-duplicate, {counts['invalid']} invalid"
        )
        if links_remapped:
            summary += f", {links_remapped} link(s) remapped to dedup/suffix targets"
        print(summary)
    return 0
