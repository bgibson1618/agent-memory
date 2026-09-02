"""D18 S3 - the chunk index: sub-card retrieval windows for reference/spine
cards whose whole-card embedding is invisible or diluted (S4.3).

Three grains, three jobs (S4.3): `vectors` = whole-card retrieval + the D17
band (untouched by this module); `chunks` (this module) = sub-card retrieval
only, never coverage; `claims` (S7, not built here) = scoring. A new table,
not new rows in `vectors` - a synthetic `slug#N` key one bug away from
leaking chunk hits into `mem search` was the rejected alternative (S4.3).

Chunking splits at heading boundaries first, then at markdown BLOCK
boundaries (blank-line-separated paragraphs/list-items) within a section,
grouping whole blocks up to a ~1,000-char target (gate finding 8: the
pre-fix chunker sliced raw character offsets instead, cutting paragraph
interiors even where a blank-line boundary was available to cut at
instead). A block is never split merely because a window is "full" - only
a single block that alone exceeds the 4,000-char hard cap has no finer
boundary available, and falls back to the character-level sliding window
(`_windows`, unchanged) that the whole chunker used before this fix - see
`_group_blocks`. A card with no internal headings and <= 1,000 chars falls
out of the SAME general path as exactly one chunk equal to its whole
document text - `vector.document_text` is reused for both the chunker's
input and `embed_text`'s, so that one chunk's embedded text is byte-identical
to the document embedding and `cosine_best_chunk == cosine_document` holds
exactly, not approximately, with no special case in the chunker itself.

Population is lazy and retrieval-driven (D18 S4.3): `mem dedup`'s chunk leg
chunks-on-demand any concept surfaced by the lexical/vector_document legs
(so the chunk index warms toward exactly the "findable-some-other-way" cards
that most need a semantic sub-card view), plus `mem reindex --chunks` for an
eager whole-KB build. Cards over `MEM_DEDUP_CHUNK_SKIP_CHARS` are excluded
and reported (`chunk_index: skipped-oversize`) - `vectors` and `mem search`
stay byte-unchanged; `chunks` is fully disposable.

Every chunk row is stamped with the `model`/`digest` it was embedded under
(gate finding 3: chunk currency used to check only `content_hash`, so a
model swap left stale, numerically-incomparable chunk vectors looking
"current"). `is_current` treats a model/digest mismatch as stale exactly
like a content change; a read-time scan (`all_rows`/`best_per_card`) filters
to the identity it was asked to score against, so any stale row a caller
forgot to repopulate is silently excluded from that scan rather than
corrupting it - the chunk table is opt-in/disposable, so exclusion (not a
hard refusal) is the proportionate response, unlike the single whole-KB
`vectors` index (`vector.top_k_doc`), which refuses outright.
"""

import hashlib
import sqlite3
from array import array
from pathlib import Path

from agent_memory import config, indexdb, okf, ollama, vector

TARGET_CHARS = 1000
HARD_CAP_CHARS = 4000
STRIDE_OVERLAP = 0.5

_SCHEMA = """CREATE TABLE IF NOT EXISTS chunks (
    slug TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    digest TEXT NOT NULL,
    vec BLOB NOT NULL,
    updated TEXT NOT NULL,
    PRIMARY KEY (slug, ordinal)
)"""


def connect(root: Path) -> sqlite3.Connection:
    con = indexdb.connect(root)
    con.execute(_SCHEMA)
    return con


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_oversize(concept, skip_chars: int) -> bool:
    return len(vector.document_text(concept)) > skip_chars


def _heading_starts(text: str) -> list:
    import re

    starts = [
        m.start() for m in re.finditer(r"^#{1,6}[ \t]+\S", text, re.MULTILINE)
    ]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    return sorted(set(starts))


def _section_spans(text: str) -> list:
    """[(start, end)] - one span per heading-delimited section, or one
    span for the whole text when there are no headings."""
    starts = _heading_starts(text)
    spans = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        if e > s:
            spans.append((s, e))
    return spans or [(0, len(text))]


def _windows(start: int, end: int, target: int) -> list:
    """Fixed-size sliding windows over [start, end) with a 50%-of-target
    stride, clamped to the span - the loop stops the instant a window
    reaches `end`, so no separate tiny tail window is ever produced (a
    clamped final window absorbs whatever remainder is left). The
    character-level fallback for a single block with no finer boundary
    (gate finding 8's "long-single-block fallback") - `_group_blocks` is
    everywhere else now."""
    stride = max(1, int(target * (1 - STRIDE_OVERLAP)))
    spans = []
    pos = start
    while True:
        w_end = min(pos + target, end)
        spans.append((pos, w_end))
        if w_end >= end:
            break
        pos += stride
    return spans


def _block_starts(text: str, start: int, end: int) -> list:
    """Absolute offsets where a new markdown block begins within
    [start, end): `start` itself, then the first non-blank position after
    every blank-line run (the paragraph/list-item separator) - a block
    never straddles a blank line, so grouping whole blocks never cuts one."""
    import re

    starts = [start]
    for m in re.finditer(r"\n[ \t]*\n+", text[start:end]):
        nxt = start + m.end()
        if start <= nxt < end:
            starts.append(nxt)
    return sorted(set(starts))


def _block_spans(text: str, start: int, end: int) -> list:
    """[(start, end)] - one span per block in [start, end), or a single
    span for the whole range when it has no internal blank line (the
    "long-single-block" case `_group_blocks` falls back to character
    windows for, if that one block also exceeds the hard cap)."""
    starts = _block_starts(text, start, end)
    spans = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else end
        if e > s:
            spans.append((s, e))
    return spans or [(start, end)]


def _group_blocks(blocks: list, target: int, hard_cap: int) -> list:
    """[(char_start, char_end)] chunk spans grouping whole `blocks`
    (never splitting one - gate finding 8) up to ~`target` chars each. A
    single block that alone exceeds `hard_cap` has no finer boundary
    available and falls back to `_windows` (the pre-fix character-sliding
    algorithm, unchanged) over just that block.

    Consecutive block-grain chunks resume with a 50%-of-target overlap
    (S4.3's stride guarantee) expressed as whole re-included trailing
    blocks. Zero-overlap advances are never allowed (W2 re-gate finding 2,
    orchestrator-ratified rules): a chunk that would end one block wide
    with more blocks remaining FORCE-INCLUDES the next block when the pair
    fits `hard_cap` (the overlap guarantee outranks the soft `target`);
    when even the pair exceeds `hard_cap` there is no block-aligned
    representation, so the pair falls back to `_windows` character slides
    (the same already-accepted fallback as an oversize single block); and
    when no block start clears the 50% lookback point, resume re-includes
    the trailing block whole rather than skipping past it."""
    spans = []
    n = len(blocks)
    i = 0
    while i < n:
        b_start, b_end = blocks[i]
        if b_end - b_start > hard_cap:
            spans.extend(_windows(b_start, b_end, min(target, hard_cap)))
            i += 1
            continue

        start = b_start
        j = i
        end = b_end
        while j + 1 < n:
            _nxt_start, nxt_end = blocks[j + 1]
            if end > start and nxt_end - start > target:
                break  # adding the next block would overshoot the target
            if nxt_end - start > hard_cap:
                break
            j += 1
            end = nxt_end

        if j == i and j + 1 < n:
            nxt_end = blocks[j + 1][1]
            if nxt_end - start <= hard_cap:
                # Force-include: a single-block chunk with blocks remaining
                # would otherwise advance with zero overlap.
                j += 1
                end = nxt_end
            else:
                # No block-aligned pair fits the cap - ratified fallback to
                # character windows over both blocks (500-char overlap),
                # then resume AT the next block so it is re-included whole.
                spans.extend(_windows(start, nxt_end, min(target, hard_cap)))
                i = j + 1
                continue
        spans.append((start, end))

        if j + 1 >= n:
            break
        # Resume from the earliest block in (i, j] whose own start is
        # already past the 50%-of-target lookback point - re-including it
        # (and everything after) as the overlap; when none clears the
        # lookback, re-include the trailing block whole (never a
        # zero-overlap advance).
        resume_at = end - target * STRIDE_OVERLAP
        r = j
        for idx in range(i + 1, j + 1):
            if blocks[idx][0] >= resume_at:
                r = idx
                break
        i = r
    return spans


def chunk_spans(text: str, target: int = TARGET_CHARS, hard_cap: int = HARD_CAP_CHARS) -> list:
    """[(char_start, char_end)] over `text` per the module docstring's
    algorithm: heading sections first, then markdown block spans within
    each section too small to need splitting stay whole; a section over
    `target` groups its blocks via `_group_blocks`. `hard_cap` bounds a
    single window's size (S4.3's stated bound)."""
    spans = []
    for s, e in _section_spans(text):
        if e - s <= target:
            spans.append((s, e))
        else:
            spans.extend(_group_blocks(_block_spans(text, s, e), target, hard_cap))
    return spans


def build_chunks(concept) -> list:
    """[(ordinal, char_start, char_end, text)] for one concept, over the
    SAME text `vector.document_text` builds (title/description/topics/body
    joined) - see the module docstring for why."""
    text = vector.document_text(concept)
    return [
        (i, s, e, text[s:e]) for i, (s, e) in enumerate(chunk_spans(text))
    ]


def _existing_identity(con: sqlite3.Connection, slug: str) -> list:
    """[(content_hash, model, digest)] for `slug`'s stored chunk rows,
    ordinal-ordered."""
    return con.execute(
        "SELECT content_hash, model, digest FROM chunks WHERE slug = ? ORDER BY ordinal", (slug,)
    ).fetchall()


def is_current(con: sqlite3.Connection, concept, model: str, digest: str | None = None) -> bool:
    """Whether `slug`'s stored chunk rows already match what `build_chunks`
    would produce right now under `model` - ordinal-for-ordinal content
    hash AND model (mirroring `vector.reconcile`'s content-hash comparison,
    extended per gate finding 3: a model swap must invalidate old chunk
    rows exactly like a body edit does, not leave numerically-incomparable
    vectors looking "current" because their bytes happen to be unchanged).
    `digest=None` skips the digest half of the identity check (a caller
    that hasn't resolved one yet), matching `vector.check_meta`'s posture."""
    wanted = [content_hash(text) for _, _, _, text in build_chunks(concept)]
    existing = _existing_identity(con, concept.slug)
    if len(existing) != len(wanted):
        return False
    for (existing_hash, existing_model, existing_digest), wanted_hash in zip(existing, wanted):
        if existing_hash != wanted_hash or existing_model != model:
            return False
        if digest is not None and existing_digest != digest:
            return False
    return True


def _store(con: sqlite3.Connection, slug: str, chunks: list, vecs: list, model: str, digest: str) -> None:
    con.execute("DELETE FROM chunks WHERE slug = ?", (slug,))
    stamp = okf.now_stamp()

    for (ordinal, start, end, text), vec in zip(chunks, vecs):
        con.execute(
            "INSERT INTO chunks(slug, ordinal, char_start, char_end, content_hash, model, digest, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                slug, ordinal, start, end, content_hash(text), model, digest,
                array("f", vec).tobytes(), stamp,
            ),
        )
    con.commit()


def populate_one(
    con: sqlite3.Connection, concept, skip_chars: int, timeout: float,
    model: str | None = None, digest: str | None = None,
) -> str:
    """(Re)chunk + embed one concept if it isn't already current. Returns
    "populated" | "current" | "skipped-oversize". Raises ollama.OllamaError
    on daemon trouble (callers decide how to degrade - `mem dedup`'s chunk
    leg treats this like the vector_document leg's daemon-down case).

    `model`/`digest` (gate finding 3) identify the embedding this call
    stamps/checks against; default `model` to the CURRENT
    `config.embed_model()` so a caller that never resolved one still gets a
    same-instance-consistent identity. `digest=None` (a caller that hasn't
    resolved one, e.g. via a live `ollama.model_digest` call) skips the
    digest half of the currency check rather than forcing a network round
    trip per card - real callers (D18's `Corpus`/`populate_all`) resolve it
    once per invocation and pass it through every call."""
    model = model or config.embed_model()
    if is_oversize(concept, skip_chars):
        con.execute("DELETE FROM chunks WHERE slug = ?", (concept.slug,))
        con.commit()
        return "skipped-oversize"
    if is_current(con, concept, model, digest):
        return "current"
    built = build_chunks(concept)
    if not built:
        con.execute("DELETE FROM chunks WHERE slug = ?", (concept.slug,))
        con.commit()
        return "current"
    base = config.ollama_base_url()
    texts = ["search_document: " + text for _, _, _, text in built]
    vecs = ollama.embed(base, model, texts, timeout=timeout)
    stamp_digest = digest if digest is not None else ollama.model_digest(base, model)
    _store(con, concept.slug, built, vecs, model, stamp_digest)
    return "populated"


def all_rows(
    con: sqlite3.Connection, dims: int | None = None,
    model: str | None = None, digest: str | None = None,
) -> list:
    """[(slug, ordinal, vec_blob)] for every stored chunk, optionally
    filtered to a dims-matching set (mirrors `vector`'s dims guard) AND to a
    model/digest-matching set (gate finding 3): a row stamped under a
    different model can share `dims` by coincidence and is numerically
    incomparable regardless, so `model`/`digest` (when given) are additional
    required-equal filters, not just `dims`. A row that fails the filter is
    simply excluded from the scan (stale-chunk "invalidation" by omission),
    not raised on - the chunk table is opt-in/disposable, so the read side
    degrading quietly is the proportionate response, matched to the write
    side's own "not current, will be repopulated" treatment of the same
    mismatch."""
    clauses, params = [], []
    if dims is not None:
        clauses.append("LENGTH(vec) = ?")
        params.append(dims * 4)
    if model is not None:
        clauses.append("model = ?")
        params.append(model)
    if digest is not None:
        clauses.append("digest = ?")
        params.append(digest)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return con.execute(f"SELECT slug, ordinal, vec FROM chunks{where}", params).fetchall()


def best_per_card(
    con: sqlite3.Connection, qvec: list, k: int | None = None,
    model: str | None = None, digest: str | None = None,
) -> dict:
    """{slug: (best_cosine, best_ordinal)} over every populated chunk row
    matching `model`/`digest` (gate finding 3 - the identity `qvec` was
    itself embedded under), scanned brute-force against `qvec` (deep-K scope
    per D18 S4.4/S8's key decision table - unlike the whole-KB document
    leg). `k=None` scores every matching slug; otherwise only the top-`k`
    slugs by their best chunk's cosine are returned. A dedicated scan (not
    `vector._scan_rows`): the reduction is per-CARD-best-of-many-chunk-rows,
    a different shape than that helper's one-row-per-slug scan."""
    rows = all_rows(con, dims=len(qvec) if qvec else None, model=model, digest=digest)
    if not rows:
        return {}

    import numpy as np

    mat = np.vstack([np.frombuffer(blob, dtype=np.float32) for _, _, blob in rows])
    q = np.asarray(qvec, dtype=np.float32)
    qnorm = float(np.linalg.norm(q))
    if qnorm == 0.0:
        return {}
    norms = np.linalg.norm(mat, axis=1)
    scores = (mat @ q) / (np.where(norms == 0.0, 1.0, norms) * qnorm)

    best: dict = {}
    for (slug, ordinal, _blob), score in zip(rows, scores):
        score = float(score)
        if slug not in best or score > best[slug][0]:
            best[slug] = (score, ordinal)
    if k is None:
        return best
    top = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))[:k]
    return dict(top)


def populate_all(root: Path, concepts: list, cfg, timeout: float) -> tuple:
    """Eager build (`mem reindex --chunks`): (re)populate every concept not
    already current, oversize ones excluded and counted. Returns
    (populated, current, skipped_oversize, error) - `error` (an
    ollama.OllamaError, or None) stops the loop early exactly like
    `vector.drain_fully`, leaving the remainder for a later run.

    Resolves model/digest identity ONCE for the whole eager build (gate
    finding 3) rather than per card - one extra `/api/tags` round trip for
    the entire run, not one per concept."""
    con = connect(root)
    try:
        model = config.embed_model()
        digest = ollama.model_digest(config.ollama_base_url(), model)
        populated = current = skipped_oversize = 0
        error = None
        for _slug, concept in concepts:
            try:
                status = populate_one(
                    con, concept, cfg.chunk_skip_chars, timeout, model=model, digest=digest,
                )
            except ollama.OllamaError as e:
                error = e
                break
            if status == "populated":
                populated += 1
            elif status == "current":
                current += 1
            else:
                skipped_oversize += 1
        return populated, current, skipped_oversize, error
    finally:
        con.close()
