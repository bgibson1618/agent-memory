"""`mem extract` - the deterministic half of extract-knowledge.

Candidate concepts (JSON) come in; each is validated item-wise, embedded, and
deduped against the KB's vectors by cosine similarity against two calibrated
bands (D17, extends D3): below config.dedup_low() the candidate is novel;
[dedup_low, dedup_high) is the reviewable "skipped-duplicate" band; at/above
dedup_high (disabled by default) is "skipped-duplicate-confident", accepted
without a full-body review. dedup_low is recorded with its measurement in
research/dedup-calibration.md; a per-instance confident band is calibrated in
research/dedup-calibration-personal-2026-08-17.md. Novel candidates are saved
through the same mechanics as `mem save` (atomic write + one commit + in-line
lexical index) and their already-computed embeddings are stored directly.
Dedup requires embeddings: with Ollama unreachable the whole batch is refused
with a one-line error before anything is saved. All embedding happens up
front (queue drain + one batched embed call), so a daemon failure can never
leave the batch partially saved. Decisions use the files' current text (D18
S6 slice A): the batch first refreshes the lexical index from the concept files,
queues every card whose stored vector is missing or stale, drains fully, and
refuses before any save if a card still cannot be embedded; unparseable card
files are reported by name (`unparseable` in --json) and left out.

The agent-side half - the extract-knowledge choreography (fresh-eyed extractor
fan-out, fresh-eyed review, disposition review) - ships as package data and is
printed by `mem extract --procedure`.
"""

import json
import math
import re
import sys
from pathlib import Path

from agent_memory import blocks, config, coordinator, gitkb, lexical, okf, ollama, shared, store, vector

# Mirrors graph._WIKILINK_RE, but captures the |alias / #heading tail so a
# remap preserves it: [[target]], [[target|alias]], [[target#heading]].
_LINK_RE = re.compile(r"\[\[([^\[\]#|]+)([#|][^\[\]]*)?\]\]")

CANDIDATE_FIELDS = {
    "title", "body", "description", "topics", "type", "sensitivity", "related", "slug",
    "source",
}


class ExtractError(Exception):
    """A one-line, agent-actionable extract refusal."""


def _band_config() -> tuple:
    """(dedup_low, dedup_high), validated. A reversed or degenerate pair
    (dedup_high <= dedup_low) would make the piecewise disposition logic
    below silently misclassify every candidate in the gap; a non-finite or
    unparseable value would do the same via a nonsensical comparison. Both
    are refused up front rather than discovered downstream."""
    try:
        low = config.dedup_low()
        high = config.dedup_high()
    except ValueError as e:
        raise ExtractError(f"invalid dedup band config: {e}") from e
    if not math.isfinite(low):
        raise ExtractError(f"dedup_low must be a finite number, got {low}")
    if high is not None:
        if not math.isfinite(high):
            raise ExtractError(f"MEM_DEDUP_HIGH must be a finite number, got {high}")
        if high <= low:
            raise ExtractError(
                f"MEM_DEDUP_HIGH ({high}) must be greater than dedup_low ({low})"
            )
    return low, high


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


def _enqueue_incomplete(root: Path) -> int:
    """Queue every current card whose stored vector is missing or does not
    match its current text (S6 slice A), so the full drain that follows makes
    the index complete before any decision. Returns how many were queued."""
    con = vector.connect(root)
    try:
        current = vector.current_embed_hashes(con) or {}
        stored = dict(con.execute("SELECT slug, content_hash FROM vectors"))
        todo = [slug for slug, h in current.items() if stored.get(slug) != h]
        for slug in todo:
            vector.enqueue(con, slug)
        con.commit()
        return len(todo)
    finally:
        con.close()


def _kb_vectors(con, dims: int) -> list:
    """[(slug, unit vector)] for every current card, each embedding matching
    the card's current text (S6 slice A). Called after the full drain; if any
    current card still has no matching embedding, the batch is refused before
    any save rather than decided against an incomplete index."""
    import numpy as np  # deferred, like vector.top_k

    stale: list = []
    rows = vector.fresh_vector_rows(con, dims, stale)
    current = vector.current_embed_hashes(con)
    unscored = sorted(set(current or ()) - {slug for slug, _ in rows})
    if stale or unscored:
        shown = ", ".join(unscored[:5]) + (" ..." if len(unscored) > 5 else "")
        raise ExtractError(
            f"{len(unscored)} card(s) have no embedding matching their current text after the"
            f" refresh ({shown}); refusing the batch before any save - run: mem reindex"
        )
    entries = []
    for slug, blob in rows:
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
    if shared.profile_for(root):
        raise shared.SharedError("shared extracts must submit the complete prepared batch")
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
    entrypoint = getattr(args, "entrypoint", None)
    if entrypoint is not None and not args.procedure:
        print("error: --entrypoint applies only to --procedure", file=sys.stderr)
        return 1
    if args.procedure:
        # The agent-side choreography, shipped as package data. Printing it
        # needs neither a KB nor the daemon. With --entrypoint (D28) every
        # command names the caller's policy-resolved entrypoint.
        try:
            text = blocks.render_procedure(entrypoint)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0
    if not args.candidates:
        print("error: extract requires --candidates (or --procedure)", file=sys.stderr)
        return 1
    try:
        return _extract(args)
    except (ExtractError, store.StoreError, okf.OKFError, vector.VectorError,
            shared.SharedError, coordinator.CoordinatorError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ollama.OllamaError as e:
        vector.mark_daemon_unhealthy()
        print(f"error: cannot dedup without embeddings: {e}", file=sys.stderr)
        return 1


def _extract(args) -> int:
    root = config.kb_root()
    store.require_kb(root)
    shared_profile = shared.profile_for(root)
    if shared_profile:
        with coordinator.read_lock(root):
            expected_head = shared.clean_head(root)
            taken = {path.stem for path in store.concepts_dir(root).glob("*.md")}
    planned = []
    store.warn_if_remote(root)
    dedup_low, dedup_high = _band_config()

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

    # S6 slice A - decide on current files: refresh the lexical index from the
    # concept files and reconcile vectors from that change-set (as `mem dedup`
    # does), so cards edited or added outside mem are seen; unparseable files
    # are collected and reported by name.
    unparseable: list = []
    lex_conn = lexical.connect(root)
    try:
        changed, removed = lexical.sync(lex_conn, root, unparseable=unparseable)
    finally:
        lex_conn.close()
    vector.reconcile(root, changed, removed)

    if valid:
        # Dedup requires a complete, current vector index: every card whose
        # stored vector is missing or no longer matches its text is queued,
        # the queue is drained fully, then the whole batch is embedded in one
        # call - any daemon trouble refuses the batch here, before a single save.
        _enqueue_incomplete(root)
        _, remaining, error = vector.drain_fully(root)
        if error is not None or remaining:
            raise ExtractError(
                f"{remaining} changed or new card(s) could not be embedded"
                f" ({error if error is not None else 'drain incomplete'});"
                " refusing the batch before any save"
            )
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
                if match is not None and similarity >= dedup_low:
                    disposition = (
                        "skipped-duplicate-confident"
                        if dedup_high is not None and similarity >= dedup_high
                        else "skipped-duplicate"
                    )
                    rename[concept.slug] = match
                    results[i] = {
                        "index": i,
                        "title": concept.title,
                        "disposition": disposition,
                        "match": match,
                        "similarity": round(similarity, 4),
                    }
                    continue
                intended = concept.slug
                if shared_profile:
                    suffix = 2
                    while concept.slug in taken:
                        concept.slug = f"{intended}-{suffix}"
                        suffix += 1
                    taken.add(concept.slug)
                    suffixed = concept.slug != intended
                    planned.append(concept)
                else:
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
                before_remap = shared.version(okf.serialize(concept).encode("utf-8"))
                changed = _remap_links(concept, rename)
                if changed == 0:
                    continue
                path = store.concept_path(root, concept.slug)
                if not shared_profile:
                    with store.write_lock(root):
                        # The card was saved moments ago outside this lock; if
                        # another writer changed it since, do not clobber it.
                        if not path.is_file() or shared.version(path.read_bytes()) != before_remap:
                            raise ExtractError(
                                f"concept '{concept.slug}' changed during extraction; earlier saves "
                                "remain committed; re-read and reconcile before retrying"
                            )
                        store.atomic_write(path, okf.serialize(concept))
                        gitkb.commit_path(
                            root, f"concepts/{concept.slug}.md",
                            f"mem extract: link remap {concept.slug}",
                        )
                        lexical.record_save(root, concept, path)
                results[i]["remapped_links"] = changed
                remapped.append((concept.slug, vector.embed_text(concept)))
            if remapped and not shared_profile:
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

    shared_result = None
    if shared_profile:
        with coordinator.read_lock(root):
            if shared.clean_head(root) != expected_head:
                raise ExtractError(
                    "KB changed during extraction; refresh and repeat dedup before saving"
                )
        shared_result = shared.submit(root, [{
            "slug": concept.slug, "expected_version": None,
            "content": okf.serialize(concept),
        } for concept in planned], expected_head=expected_head,
            operation_id=getattr(args, "operation_id", None))
        if shared_result["status"] != "applied":
            return shared.report(shared_result, json_output=args.json)

    counts = {
        "added": 0, "skipped-duplicate": 0, "skipped-duplicate-confident": 0, "invalid": 0,
    }
    for r in results:
        counts[r["disposition"]] += 1
    links_remapped = sum(r.get("remapped_links", 0) for r in results if r)

    if args.json:
        payload = {
            "threshold": dedup_low,
            "added": counts["added"],
            "skipped_duplicate": counts["skipped-duplicate"],
            "invalid": counts["invalid"],
            "links_remapped": links_remapped,
            "results": results,
        }
        if unparseable:
            # S6 slice A, additive-only (absent when empty, so default output
            # stays byte-identical): card files the refresh could not parse;
            # the batch was decided without them.
            payload["unparseable"] = unparseable
        if shared_result is not None:
            payload["shared_write"] = shared_result
        if dedup_high is not None:
            # Additive-only: these two keys never appear in default (no
            # MEM_DEDUP_HIGH) output, keeping it byte-identical to pre-D17.
            payload["dedup_high"] = dedup_high
            payload["skipped_duplicate_confident"] = counts["skipped-duplicate-confident"]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if shared_result is not None:
            shared.report(shared_result)
        for r in results:
            if r["disposition"] == "added":
                note = f" [{r['note']}]" if "note" in r else ""
                print(f"added: {r['slug']} ({r['title']}){note}")
            elif r["disposition"] == "skipped-duplicate":
                print(
                    f"skipped-duplicate: {r['title']} - matches '{r['match']}'"
                    f" (similarity {r['similarity']:.2f} >= threshold {dedup_low:.2f})"
                )
            elif r["disposition"] == "skipped-duplicate-confident":
                print(
                    f"skipped-duplicate-confident: {r['title']} - matches '{r['match']}'"
                    f" (similarity {r['similarity']:.2f} >= confident threshold {dedup_high:.2f})"
                )
            else:
                who = f"candidate #{r['index'] + 1}" + (f" ({r['title']})" if r["title"] else "")
                print(f"invalid: {who} - {r['reason']}")
        summary = (
            f"extract: {counts['added']} added, {counts['skipped-duplicate']}"
            f" skipped-duplicate, {counts['invalid']} invalid"
        )
        if dedup_high is not None:
            summary = (
                f"extract: {counts['added']} added, {counts['skipped-duplicate']}"
                f" skipped-duplicate, {counts['skipped-duplicate-confident']}"
                f" skipped-duplicate-confident, {counts['invalid']} invalid"
            )
        if links_remapped:
            summary += f", {links_remapped} link(s) remapped to dedup/suffix targets"
        print(summary)
    return 0
