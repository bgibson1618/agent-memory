"""D18 S1 - claim segmentation + coverage tokenization.

A "claim" is a sentence-or-bullet unit: the grain dedup's coverage scoring
(`dedup.py`) matches at. Segmentation is deterministic and stdlib-only (no
`pysbd`/`nltk`/`spacy` - a runtime dependency and model download this repo's
dependency posture (stdlib + numpy + yaml) doesn't carry, for a corpus that is
Brent's own plain markdown - research/d18-dedup-detection-design-2026-09-02.md
S4.2).

Order: split on markdown list-item boundaries (each item, any nesting depth,
is its own unit before further splitting), then headings (each heading line
is its own unit), then blank lines (paragraph boundaries); within each
resulting block, split on sentence-ending punctuation followed by whitespace
+ a capital letter, guarded against a small abbreviation list so "e.g. Foo"
doesn't split before "Foo". Units under 4 content tokens are dropped (so
"## Why" is not a claim). Text inside inline-code spans is masked from the
sentence splitter (matched positions only) so a code snippet's punctuation
never triggers a split.

Honest cost (S4.2): this is not a real sentence splitter, so nested lists and
inline code carry a nonzero mis-split rate - measured, not assumed, and
pinned by test_d18_w1_claims_coverage.py's 100-card sample.

`tokenize()` is a second, separate tokenizer for coverage scoring only
(never for FTS5 queries, which need the *unstemmed* surface form to match
what's indexed - see `lexical.dedup_match_expr`): lowercased alnum runs >= 3
chars with light suffix stripping (ing|ed|es|s), so morphological variants of
the same word count as the same coverage token.

D18 S7 (2026-09-02) - the `claim_vectors` table, this module's second job:
per-CLAIM embeddings, mirroring `chunks.py`'s table/schema shape but at claim
grain rather than chunk grain. LAZY and retrieval-scoped by construction
(`dedup.detect()` only populates a hit CARD's claim vectors when that card
already reached the deep-K report - never a whole-KB eager pass), plus
`mem reindex --claims` for an instance that opts into an eager build. Off by
construction unless `MEM_DEDUP_CLAIM_SEM` is set (dedup.py's `Corpus.
claim_leg_active`) - the paraphrase lever, R1 in the design, shipped off.
Every row is stamped with the `model`/`digest` it was embedded under, exactly
like `chunks.py`'s identity guard (a model swap must invalidate old claim
vectors, not leave numerically-incomparable ones looking current); a
mismatched/absent row is excluded from a read-time scan, never raised on -
this table is disposable, same posture as `chunks`."""

import hashlib
import re
import sqlite3
from array import array
from pathlib import Path

from agent_memory import config, indexdb, ollama, okf

MIN_CONTENT_TOKENS = 4

_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "st", "no",
    "fig", "eq", "cf", "approx", "jr", "sr", "inc", "ltd", "co", "prof",
    "dept",
}

# D18 W1 fix cycle (gate finding 3): a multi-period initialism ("U.S.",
# "U.S.A.", "a.m.") is not on any finite enumerated list - it is guarded
# structurally instead. `_split_sentences` only ever asks this about the
# token immediately abutting a candidate split point, which is already
# stripped of the boundary's own trailing period (see below), so "U.S."
# arrives here as "U.S": one-or-more single-letter groups joined by
# internal periods, at least one internal period required (a bare "I" or
# "A" is an ordinary word, not an initialism). D18 W1 fix cycle 2 (re-gate
# finding 1): "&" joins count too ("R&D" arrives here the same way "U.S"
# does), so ampersand-delimited initialisms are guarded structurally, not
# by enumeration.
_INITIALISM_RE = re.compile(r"^[A-Za-z](?:[.&][A-Za-z])+$")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_SPLIT_RE = re.compile(r"([.!?])\s+(?=[A-Z])")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_LAST_WORD_RE = re.compile(r"(\S+)$")
_WORD_RE = re.compile(r"[a-z0-9]+")
_SUFFIXES = ("ing", "ed", "es", "s")
# D18 W1 fix cycle (gate finding 4): how far back of a candidate split point
# to look for the abutting word. Bounded so `_split_sentences` never copies
# or rescans the accumulated prefix (was O(n) per boundary => O(n^2) - see
# below); real words and abbreviations are always far shorter than this.
_ABBREV_LOOKBACK = 64


def _is_guarded_abbreviation(word: str) -> bool:
    if _INITIALISM_RE.match(word):
        return True
    return word.rstrip(".").lower() in _ABBREVIATIONS


def _content_token_count(text: str) -> int:
    return len(_WORD_RE.findall(text.lower()))


def _mask_inline_code(text: str) -> str:
    """Replace inline-code spans with same-length NUL filler so sentence-
    boundary matching never fires inside one, while keeping every other
    character's index identical to the original (masked text is used only
    to find split points; the returned units are sliced from the original)."""
    return _INLINE_CODE_RE.sub(lambda m: "\x00" * len(m.group(0)), text)


def _split_sentences(text: str) -> list:
    text = text.strip()
    if not text:
        return []
    masked = _mask_inline_code(text)
    parts = []
    start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(masked):
        boundary = m.start(1)
        # Bounded window, not `masked[:boundary]`: the old code copied and
        # re-scanned the whole accumulated prefix on every boundary, making
        # segmentation quadratic on punctuation-dense text (gate finding 4).
        # The word abutting a split point is always a handful of characters,
        # so a fixed lookback finds it in O(1) regardless of document size.
        window = masked[max(0, boundary - _ABBREV_LOOKBACK) : boundary]
        last_word = _LAST_WORD_RE.search(window)
        word = last_word.group(1) if last_word else ""
        if _is_guarded_abbreviation(word):
            continue
        parts.append(text[start : m.end(1)])
        start = m.end()
    parts.append(text[start:])
    parts = [p.strip() for p in parts if p.strip()]
    # D18 W1 fix cycle 2 (re-gate finding 1): sentence-level splitting is
    # LOSS-PROOF by construction. No guard list or shape regex can enumerate
    # every abbreviation ("Sen.", "Rev.", novel initialisms), so any fragment
    # below the claim floor is MERGED into its neighbor instead of being
    # dropped later by segment()'s unit filter - a residual mis-split is at
    # worst cosmetic (both sides survive whole). Only block-level units
    # (e.g. a bare "## Why" heading) may still be dropped by that filter.
    merged = []
    for part in parts:
        if merged and _content_token_count(merged[-1]) < MIN_CONTENT_TOKENS:
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    if len(merged) >= 2 and _content_token_count(merged[-1]) < MIN_CONTENT_TOKENS:
        tail = merged.pop()
        merged[-1] = merged[-1] + " " + tail
    return merged


def _split_blocks(text: str) -> list:
    """First pass: list-item boundaries, then headings, then blank lines.
    Returns [(kind, block_text)] with kind in {"para", "list_item", "heading"};
    block_text has continuation lines joined with a single space (markdown
    line-wrap, not a real paragraph break)."""
    blocks = []
    kind = None
    buf = []

    def flush():
        if buf:
            blocks.append((kind, " ".join(line.strip() for line in buf if line.strip())))

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            buf.clear()
            kind = None
            continue
        heading_m = _HEADING_RE.match(line)
        if heading_m:
            flush()
            buf.clear()
            blocks.append(("heading", heading_m.group(2).strip()))
            kind = None
            continue
        if _LIST_ITEM_RE.match(line):
            flush()
            buf.clear()
            kind = "list_item"
            buf.append(line)
            continue
        if kind in ("list_item", "para"):
            buf.append(line)
        else:
            kind = "para"
            buf = [line]
    flush()
    return blocks


def segment(text: str) -> list:
    """Split `text` into claim units per the module docstring's ordering.
    Units under MIN_CONTENT_TOKENS content tokens are dropped."""
    units = []
    for kind, block in _split_blocks(text):
        if not block:
            continue
        if kind == "heading":
            units.append(block)
            continue
        if kind == "list_item":
            block = _LIST_ITEM_RE.sub("", block, count=1)
        units.extend(_split_sentences(block))
    return [u for u in units if _content_token_count(u) >= MIN_CONTENT_TOKENS]


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list:
    """Coverage-grain tokens: lowercased alnum runs >= 3 chars, light suffix
    stripping. Not the FTS5-aligned tokenizer - see the module docstring."""
    return [_stem(w) for w in _WORD_RE.findall(text.lower()) if len(w) >= 3]


# ==========================================================================
# D18 S7 - the `claim_vectors` table: per-claim embeddings, lazy and
# retrieval-scoped (module docstring). Mirrors `chunks.py`'s schema/identity
# pattern at claim grain instead of chunk grain.
# ==========================================================================

_SCHEMA = """CREATE TABLE IF NOT EXISTS claim_vectors (
    slug TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
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


def _existing_identity(con: sqlite3.Connection, slug: str) -> list:
    return con.execute(
        "SELECT text_hash, model, digest FROM claim_vectors WHERE slug = ? ORDER BY ordinal", (slug,)
    ).fetchall()


def is_current(
    con: sqlite3.Connection, slug: str, claim_texts: list, model: str, digest: str | None = None,
) -> bool:
    """Whether `slug`'s stored claim rows already match `claim_texts` under
    `model` (ordinal-for-ordinal text hash AND model, `digest` compared only
    when given - mirrors `chunks.is_current`/`vector.check_meta`'s posture
    exactly)."""
    wanted = [content_hash(t) for t in claim_texts]
    existing = _existing_identity(con, slug)
    if len(existing) != len(wanted):
        return False
    for (existing_hash, existing_model, existing_digest), wanted_hash in zip(existing, wanted):
        if existing_hash != wanted_hash or existing_model != model:
            return False
        if digest is not None and existing_digest != digest:
            return False
    return True


def _store(con: sqlite3.Connection, slug: str, claim_texts: list, vecs: list, model: str, digest: str) -> None:
    con.execute("DELETE FROM claim_vectors WHERE slug = ?", (slug,))
    stamp = okf.now_stamp()
    for ordinal, (text, vec) in enumerate(zip(claim_texts, vecs)):
        con.execute(
            "INSERT INTO claim_vectors(slug, ordinal, text_hash, model, digest, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (slug, ordinal, content_hash(text), model, digest, array("f", vec).tobytes(), stamp),
        )
    con.commit()


def populate_one(
    con: sqlite3.Connection, slug: str, claim_texts: list, timeout: float,
    model: str | None = None, digest: str | None = None,
) -> str:
    """(Re)embed one card's claim vectors if not already current. Returns
    "populated" | "current" | "empty". Raises ollama.OllamaError on daemon
    trouble - callers degrade the leg exactly like `chunks.populate_one`'s
    already-ratified pattern (`dedup.detect()`'s chunk leg: turn the leg off
    for the rest of the run, never abort a batch already in flight).

    `model`/`digest`: same default-to-current-config / skip-if-None posture
    as `chunks.populate_one` - a caller that resolved a digest once per
    invocation passes it through every call; a caller that hasn't resolved
    one gets a same-instance-consistent model-only identity."""
    model = model or config.embed_model()
    if not claim_texts:
        con.execute("DELETE FROM claim_vectors WHERE slug = ?", (slug,))
        con.commit()
        return "empty"
    if is_current(con, slug, claim_texts, model, digest):
        return "current"
    base = config.ollama_base_url()
    texts = ["search_document: " + t for t in claim_texts]
    vecs = ollama.embed(base, model, texts, timeout=timeout)
    stamp_digest = digest if digest is not None else ollama.model_digest(base, model)
    _store(con, slug, claim_texts, vecs, model, stamp_digest)
    return "populated"


def vectors_for(
    con: sqlite3.Connection, slug: str, model: str | None = None, digest: str | None = None,
) -> list | None:
    """[vec_array, ...] ordinal-ordered for `slug`'s stored claim vectors, or
    None when no rows exist, OR when any row's `model`/`digest` (when given)
    doesn't match - a stale/foreign identity is excluded wholesale, not
    partially trusted (mirrors `chunks.all_rows`'s exclude-not-corrupt
    posture: this table is disposable, so a caller that gets None just
    proceeds without the semantic leg for that card)."""
    import numpy as np

    rows = con.execute(
        "SELECT ordinal, model, digest, vec FROM claim_vectors WHERE slug = ? ORDER BY ordinal", (slug,)
    ).fetchall()
    if not rows:
        return None
    out = []
    for _ordinal, row_model, row_digest, blob in rows:
        if model is not None and row_model != model:
            return None
        if digest is not None and row_digest != digest:
            return None
        out.append(np.frombuffer(blob, dtype=np.float32))
    return out


def populate_all(root: Path, concepts: list, timeout: float) -> tuple:
    """Eager build (`mem reindex --claims`): (re)populate every concept's
    claim vectors, segmenting from `concept.body` alone (the same grain
    `dedup.detect()` scores at). Returns (populated, current, empty, error) -
    `error` (an ollama.OllamaError, or None) stops the loop early exactly
    like `chunks.populate_all`/`vector.drain_fully`, leaving the remainder
    for a later run. Resolves model/digest identity ONCE for the whole
    build, like `chunks.populate_all`."""
    con = connect(root)
    try:
        model = config.embed_model()
        digest = ollama.model_digest(config.ollama_base_url(), model)
        populated = current = empty = 0
        error = None
        for _slug, concept in concepts:
            texts = segment(concept.body)
            try:
                status = populate_one(con, concept.slug, texts, timeout, model=model, digest=digest)
            except ollama.OllamaError as e:
                error = e
                break
            if status == "populated":
                populated += 1
            elif status == "current":
                current += 1
            else:
                empty += 1
        return populated, current, empty, error
    finally:
        con.close()
