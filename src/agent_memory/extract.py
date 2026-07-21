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
"""

import json
import sys
from pathlib import Path

from agent_memory import config, gitkb, lexical, okf, ollama, store, vector

CANDIDATE_FIELDS = {
    "title", "body", "description", "topics", "type", "sensitivity", "related", "slug",
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
            meta = vector.get_meta(con)
            model = config.embed_model()
            if meta is not None and meta.get("model") != model:
                raise vector.VectorError(
                    f"index built with model {meta.get('model')}, current model is {model}"
                    " - cannot dedup; run: mem reindex"
                )
            if meta is not None and int(meta.get("dims", 0)) != len(vecs[0]):
                raise vector.VectorError(
                    f"embedding dims {len(vecs[0])} != index dims {meta.get('dims')}"
                    " - cannot dedup; run: mem reindex"
                )
            entries = _kb_vectors(con, len(vecs[0]))

            import numpy as np

            for (i, concept), text, vec in zip(valid, texts, vecs):
                match, similarity = _best_match(vec, entries)
                if match is not None and similarity >= threshold:
                    results[i] = {
                        "index": i,
                        "title": concept.title,
                        "disposition": "skipped-duplicate",
                        "match": match,
                        "similarity": round(similarity, 4),
                    }
                    continue
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
                    results[i]["note"] = "slug taken by a distinct concept - saved under a fresh slug"
        finally:
            con.close()

    counts = {"added": 0, "skipped-duplicate": 0, "invalid": 0}
    for r in results:
        counts[r["disposition"]] += 1

    if args.json:
        print(json.dumps(
            {
                "threshold": threshold,
                "added": counts["added"],
                "skipped_duplicate": counts["skipped-duplicate"],
                "invalid": counts["invalid"],
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
        print(
            f"extract: {counts['added']} added, {counts['skipped-duplicate']}"
            f" skipped-duplicate, {counts['invalid']} invalid"
        )
    return 0
