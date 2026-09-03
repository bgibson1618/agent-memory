"""D18 S2+S4 - dedup detector core (claim-grain containment, directional
coverage, the `relation` table, greedy union set-cover) AND the fused-
retrieval orchestration (`Corpus`/`detect()`) `mem dedup` (S4) drives.

research/d18-dedup-detection-design-2026-09-02.md S4.1/S4.2/S4.4/S5 is the
spec. S2's scoring core is pure functions over already-segmented claim text
(no I/O). S4's `Corpus`/`detect()` (bottom of this file) are the retrieval
wiring: four fused legs (lexical/vector_document/vector_chunk/graph) built
once per `mem dedup` invocation and reused across every candidate in a
batch, `fusion.rrf` reused verbatim, then this module's own S2 functions
score the resulting deep-K hit list. S6 (extract rewiring, a later wave)
reuses `detect()` unchanged; nothing here is extract-specific.

IDF here is a pure, SQLite-free `idf_from_corpus`: build a df/idf table
in-memory from a corpus of already-tokenized claim-lists, decoupled from any
particular corpus source. This keeps the scoring core testable on
hand-built claim sets with no database. `lexical.dedup_match_expr` (S1) is a
different consumer of IDF, for the retrieval query string, sourced from the
real `lexical_vocab`/fts5vocab shadow table - S4/S6 is where the two connect.

DECISION_LOG D18-W1 amendment (2026-09-02): `idf_from_corpus` is CARD-GRAIN
ONLY - production callers pass exactly one token-set per CARD (document =
the whole card body's claim tokens, unioned), never one per claim. §3.3/§3.4's
calibration was itself computed this way (in-memory, card-grain), and
`fts5vocab`'s df is unstemmed and has no lookup path aligned to this stemmed
vocabulary - so card-grain in-memory IDF, not `fts5vocab`, is the coverage-IDF
source of record. There is no selectable "claims as documents" grain in this
module; that alternative gives materially different (and uncalibrated)
answers - see `test_idf_from_corpus_is_card_grain_reproduces_common_rare_0500`.
"""

import hashlib
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from agent_memory import chunks as chunks_mod
from agent_memory import claims, config, fusion, lexical, ollama, store, vector
from agent_memory import graph as graph_mod

IdfLookup = Callable[[str], float]

# research/d18-dedup-detection-design-2026-09-02.md S4.2's relation table.
EQUIVALENT = "equivalent"
CANDIDATE_SUBSET = "candidate-subset"
CANDIDATE_SUPERSET = "candidate-superset"
OVERLAPPING = "overlapping"
UNRELATED = "unrelated"

_RECOMMENDED_ACTION = {
    EQUIVALENT: "skip",
    CANDIDATE_SUBSET: "skip",
    CANDIDATE_SUPERSET: "update-existing",  # never "skip" - a superset must not silently discard the candidate
    OVERLAPPING: "review",
    UNRELATED: "add",
}


class DedupError(Exception):
    """A one-line, agent-actionable dedup config refusal (mirrors extract.ExtractError)."""


@dataclass(frozen=True)
class Claim:
    """One segmented claim unit plus its precomputed scoring state.
    `tokens` is a set (coverage math is defined over token sets, per S4.2's
    Sigma-over-intersection notation); `weight` is its IDF mass, Sigma idf(t)
    for t in tokens - the quantity `coverage_of_candidate`/`coverage_of_card`
    sum over, so filler claims (few/low-idf tokens) can't inflate coverage
    the way a plain claim-count would (S4.2's stated reason for IDF-mass
    weighting over plain counts).

    `vec` (D18 S7, added 2026-09-02): this claim's embedding as a plain
    float tuple, or None when the semantic claim leg is disabled/unresolved
    for this claim - a tuple (not a numpy array) so a frozen dataclass stays
    hashable/comparable without numpy's elementwise `__eq__` ambiguity. Every
    EXISTING caller constructs a `Claim` with no `vec` (defaulting to None),
    so `_claim_cosine` always returns None for them - S1/S2's tests are
    unaffected by this field's addition."""

    text: str
    tokens: frozenset
    weight: float
    vec: Optional[tuple] = None


def build_claims(texts: Iterable[str], idf: IdfLookup, vecs: Optional[Sequence] = None) -> list:
    """One Claim per text unit (already segmented - callers pass
    `claims.segment(body)`'s output, not raw bodies). `vecs[i]` (D18 S7),
    when given and not None, becomes that Claim's `vec` - omit (or pass
    None entries) to build claims with no semantic leg, exactly the S1/S2
    behavior."""
    out = []
    for i, text in enumerate(texts):
        tokens = frozenset(claims.tokenize(text))
        weight = sum(idf(t) for t in tokens)
        vec = None
        if vecs is not None and i < len(vecs) and vecs[i] is not None:
            vec = tuple(float(x) for x in vecs[i])
        out.append(Claim(text=text, tokens=tokens, weight=weight, vec=vec))
    return out


def _claim_cosine(a: Claim, b: Claim) -> Optional[float]:
    """cos(a.vec, b.vec), or None when either side has no embedding (the
    semantic leg is disabled, or embedding this particular claim failed and
    was degraded - D18 S7). Symmetric by construction, so callers never need
    to care which side is the "candidate" claim, unlike `lexical_containment`."""
    if a.vec is None or b.vec is None:
        return None
    import numpy as np

    va = np.asarray(a.vec, dtype=np.float32)
    vb = np.asarray(b.vec, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return None
    return float((va @ vb) / (na * nb))


def idf_from_corpus(card_token_lists: Iterable[Iterable]) -> IdfLookup:
    """A pure, in-memory smoothed IDF: idf(t) = log((N+1)/(df(t)+1)) + 1.
    CARD-GRAIN ONLY (module docstring's DECISION_LOG D18-W1 amendment,
    2026-09-02): each item in `card_token_lists` is one CARD's document - the
    union of that card's claim tokens, not a single claim - and df is the
    number of cards containing the term. Production callers must not pass a
    per-claim entry; that is a different, uncalibrated metric. Always
    positive, monotonically decreasing in df, and defined even for a term
    absent from every card (df=0 gets the maximum score - the least-common
    treatment, not a KeyError or an arbitrary zero)."""
    docs = [frozenset(tokens) for tokens in card_token_lists]
    n = len(docs)
    df: dict = {}
    for doc in docs:
        for t in doc:
            df[t] = df.get(t, 0) + 1

    def lookup(term: str) -> float:
        return math.log((n + 1) / (df.get(term, 0) + 1)) + 1.0

    return lookup


def lexical_containment(candidate_tokens: frozenset, card_tokens: frozenset, idf: IdfLookup) -> float:
    """S4.2: Sigma_{t in tok(c) & tok(d)} idf(t) / Sigma_{t in tok(c)} idf(t).
    Asymmetric by construction - `candidate_tokens` is always the
    denominator, so containment(c, d) != containment(d, c) in general."""
    if not candidate_tokens:
        return 0.0
    denominator = sum(idf(t) for t in candidate_tokens)
    if denominator <= 0:
        return 0.0
    numerator = sum(idf(t) for t in candidate_tokens & card_tokens)
    return numerator / denominator


def matched(
    candidate_tokens: frozenset,
    card_tokens: frozenset,
    idf: IdfLookup,
    lex_threshold: float,
    *,
    semantic_cosine: Optional[float] = None,
    sem_threshold: Optional[float] = None,
) -> bool:
    """S4.2: matched(c,d) = (lexical_containment(c,d) >= tau_lex) OR
    (semantic_cosine(c,d) >= tau_sem). The semantic leg is a seam only in
    S2 - pass `semantic_cosine=None` (S7 wires a real per-claim cosine;
    until then the OR degrades to the lexical leg alone, never raising a
    spurious match)."""
    if lexical_containment(candidate_tokens, card_tokens, idf) >= lex_threshold:
        return True
    return (
        semantic_cosine is not None
        and sem_threshold is not None
        and semantic_cosine >= sem_threshold
    )


def _directional_coverage(
    reference_claims: Sequence[Claim], other_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float,
    *, sem_threshold: Optional[float] = None,
) -> float:
    """IDF-mass-weighted fraction of `reference_claims` that have some match
    in `other_claims`. `coverage_of_candidate`/`coverage_of_card` are this
    function with the two argument roles swapped - `matched()`'s first
    argument is always the containment denominator, so swapping which claim
    list plays "reference" correctly re-derives the asymmetric direction
    without duplicating the loop.

    `sem_threshold` (D18 S7): threaded straight into every `matched()` call
    alongside the per-pair `_claim_cosine` - cosine is symmetric, so it needs
    no directional swap the way lexical containment does. Omitted (the
    default), this degrades to S1/S2's lexical-only behavior exactly, since
    `matched()` itself already treats `sem_threshold=None` as "leg off"."""
    total = sum(c.weight for c in reference_claims)
    if total <= 0:
        return 0.0
    covered = sum(
        c.weight
        for c in reference_claims
        if any(
            matched(c.tokens, d.tokens, idf, lex_threshold,
                    semantic_cosine=_claim_cosine(c, d), sem_threshold=sem_threshold)
            for d in other_claims
        )
    )
    return covered / total


def coverage_of_candidate(
    candidate_claims: Sequence[Claim], card_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float,
    *, sem_threshold: Optional[float] = None,
) -> float:
    """S4.2: fraction of the candidate's IDF mass that the card covers."""
    return _directional_coverage(candidate_claims, card_claims, idf, lex_threshold, sem_threshold=sem_threshold)


def coverage_of_card(
    candidate_claims: Sequence[Claim], card_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float,
    *, sem_threshold: Optional[float] = None,
) -> float:
    """S4.2: fraction of the card's IDF mass that the candidate covers -
    coverage_of_candidate with the roles swapped."""
    return _directional_coverage(card_claims, candidate_claims, idf, lex_threshold, sem_threshold=sem_threshold)


def relation(
    coverage_of_candidate_value: float,
    coverage_of_card_value: float,
    coverage_low: float,
    coverage_high: float,
) -> tuple:
    """S4.2's relation table -> (relation, recommended_action). The table's
    literal rows leave one joint region unstated: one side in
    [coverage_low, coverage_high) while the other is below coverage_low.
    Judgment call (recorded in output.md): resolved as `overlapping`/
    `review`, the same as the "both in [low, high)" row - it is not
    `unrelated` (one side shows genuine coverage above the noise floor) and
    it is none of the >=high rows, so `review` (human-in-the-loop) is the
    conservative reading, never `skip` or `add` by default.

    D18 W1 fix cycle (gate finding 2): `coverage_high` alone is not a safe
    `skip` gate. `coverage_of_candidate_value` (`cc`) IS, by its own
    definition (S4.2), the fraction of the candidate's claim mass matched in
    the card - so "zero unmatched candidate claim mass" is exactly `cc`
    reaching its ceiling of 1.0, not merely crossing `coverage_high`.
    Reproduced bypass: a candidate = one claim fully matched (weight 9) plus
    one unmatched novel claim (weight 1) against a card containing only the
    matched claim scores `cc=0.9, cd=1.0` - `cc` clears `coverage_high` (e.g.
    0.85) while still discarding 10% of the candidate's claim mass if
    skipped. `equivalent` and `candidate-subset` both recommend `skip` in the
    table below; both now require `cc >= 1.0` (candidate claim mass fully
    accounted for) to keep that recommendation - short of that, the relation
    label is unchanged (the coverage numbers still say what they say) but the
    action downgrades to `review`, never silently discarding the novel
    remainder. `candidate-superset` was already never `skip` (D18's ratified
    default); this closes the matching hole on the other two `skip` cells."""
    cc, cd = coverage_of_candidate_value, coverage_of_card_value
    if cc >= coverage_high and cd >= coverage_high:
        rel = EQUIVALENT
    elif cc >= coverage_high and cd < coverage_high:
        rel = CANDIDATE_SUBSET
    elif cc < coverage_high and cd >= coverage_high:
        rel = CANDIDATE_SUPERSET
    elif cc < coverage_low and cd < coverage_low:
        rel = UNRELATED
    else:
        rel = OVERLAPPING
    action = _RECOMMENDED_ACTION[rel]
    if action == "skip" and cc < 1.0:
        action = "review"
    return rel, action


@dataclass(frozen=True)
class UnionStep:
    slug: str
    cumulative_coverage: float


@dataclass(frozen=True)
class UnionResult:
    member_slugs: list = field(default_factory=list)
    coverage_union: float = 0.0
    curve: list = field(default_factory=list)


def greedy_union_cover(
    candidate_claims: Sequence[Claim],
    cards: Sequence[tuple],
    idf: IdfLookup,
    lex_threshold: float,
    m: int = 5,
    *,
    sem_threshold: Optional[float] = None,
) -> UnionResult:
    """S4.2: greedy set-cover over `cards` (a `[(slug, card_claims)]` list,
    the deep-K hit list in the eventual retrieval-wired form), ranked each
    round by marginal candidate-claim-mass gain, capped at `m` picks.
    Coverage is submodular, so greedy is (1-1/e)-optimal (S4.2's stated
    justification over exhaustive pairs). Returns the picked slugs in
    marginal-gain order, the final cumulative coverage, and the step-by-step
    curve - each entry's own cumulative_coverage, so a consumer can see the
    diminishing returns rather than only the endpoint.

    `sem_threshold` (D18 S7): same OR-with-lexical semantics as
    `_directional_coverage` - omitted, the union is lexical-only (S1/S2)."""
    total = sum(c.weight for c in candidate_claims)
    remaining = list(cards)
    covered = [False] * len(candidate_claims)
    members = []
    curve = []
    covered_weight = 0.0

    for _ in range(max(m, 0)):
        best_slug = None
        best_gain = 0.0
        best_newly_covered = ()
        for slug, card_claims in remaining:
            newly = [
                i
                for i, c in enumerate(candidate_claims)
                if not covered[i] and any(
                    matched(c.tokens, d.tokens, idf, lex_threshold,
                            semantic_cosine=_claim_cosine(c, d), sem_threshold=sem_threshold)
                    for d in card_claims
                )
            ]
            gain = sum(candidate_claims[i].weight for i in newly)
            if gain > best_gain:
                best_slug, best_gain, best_newly_covered = slug, gain, newly
        if best_slug is None:
            break
        for i in best_newly_covered:
            covered[i] = True
        covered_weight += best_gain
        members.append(best_slug)
        remaining = [(s, c) for s, c in remaining if s != best_slug]
        curve.append(UnionStep(slug=best_slug, cumulative_coverage=covered_weight / total if total else 0.0))

    return UnionResult(
        member_slugs=members,
        coverage_union=curve[-1].cumulative_coverage if curve else 0.0,
        curve=curve,
    )


@dataclass(frozen=True)
class DedupConfig:
    dedup_low: float
    dedup_high: Optional[float]
    coverage_low: Optional[float]
    coverage_high: Optional[float]
    union_low: Optional[float]
    union_m: int
    claim_lex: float
    claim_sem: Optional[float]
    deep_k: int
    chunk_skip_chars: int
    chunks: bool
    log: bool
    log_titles: bool


def _check_finite(name: str, value: Optional[float]) -> None:
    if value is not None and not math.isfinite(value):
        raise DedupError(f"{name} must be a finite number, got {value}")


def _check_unit_range(name: str, value: Optional[float], *, low_inclusive: bool = True) -> None:
    if value is None:
        return
    lo_ok = value >= 0.0 if low_inclusive else value > 0.0
    if not (lo_ok and value <= 1.0):
        bound = "[0, 1]" if low_inclusive else "(0, 1]"
        raise DedupError(f"{name} must be in {bound}, got {value}")


def load_config() -> DedupConfig:
    """Resolve + fail-fast-validate every D18 config seam (S4.4), one
    `error:`-worthy DedupError per bad value, mirroring extract.ExtractError's
    `_band_config()` pattern. dedup_low/dedup_high are included (unchanged
    semantics, per S4.4's table) since a future detect() needs them
    alongside the new coverage/union/claim seams in one resolved bundle -
    extract.py keeps its own independent `_band_config()` untouched; this is
    not a refactor of that path. D18 W1 fix cycle (gate finding 5): unlike
    `extract._band_config()` - whose own validation semantics this wave does
    not change - this path additionally requires dedup_low/dedup_high to be
    in [0,1], since S4.4 says every coverage/cosine value is; that document-
    cosine range check has no home elsewhere."""
    try:
        dedup_low = config.dedup_low()
        dedup_high = config.dedup_high()
        coverage_low = config.dedup_coverage_low()
        coverage_high = config.dedup_coverage_high()
        union_low = config.dedup_union_low()
        union_m = config.dedup_union_m()
        claim_lex = config.dedup_claim_lex()
        claim_sem = config.dedup_claim_sem()
        deep_k = config.dedup_deep_k()
        chunk_skip_chars = config.dedup_chunk_skip_chars()
        chunks = config.dedup_chunks()
        log = config.dedup_log()
        log_titles = config.dedup_log_titles()
    except ValueError as e:
        raise DedupError(f"invalid dedup config: {e}") from e

    _check_finite("dedup_low", dedup_low)
    _check_finite("MEM_DEDUP_HIGH", dedup_high)
    _check_finite("MEM_DEDUP_COVERAGE_LOW", coverage_low)
    _check_finite("MEM_DEDUP_COVERAGE_HIGH", coverage_high)
    _check_finite("MEM_DEDUP_UNION_LOW", union_low)
    _check_finite("MEM_DEDUP_CLAIM_LEX", claim_lex)
    _check_finite("MEM_DEDUP_CLAIM_SEM", claim_sem)

    if dedup_high is not None and dedup_high <= dedup_low:
        raise DedupError(
            f"MEM_DEDUP_HIGH ({dedup_high}) must be greater than dedup_low ({dedup_low})"
        )

    _check_unit_range("MEM_DEDUP_LOW", dedup_low)
    _check_unit_range("MEM_DEDUP_HIGH", dedup_high)
    _check_unit_range("MEM_DEDUP_COVERAGE_LOW", coverage_low)
    _check_unit_range("MEM_DEDUP_COVERAGE_HIGH", coverage_high)
    _check_unit_range("MEM_DEDUP_UNION_LOW", union_low)
    _check_unit_range("MEM_DEDUP_CLAIM_LEX", claim_lex, low_inclusive=False)
    _check_unit_range("MEM_DEDUP_CLAIM_SEM", claim_sem, low_inclusive=False)

    if coverage_low is not None and coverage_high is not None and coverage_high <= coverage_low:
        raise DedupError(
            f"MEM_DEDUP_COVERAGE_HIGH ({coverage_high}) must be greater than "
            f"MEM_DEDUP_COVERAGE_LOW ({coverage_low})"
        )
    if union_m < 1:
        raise DedupError(f"MEM_DEDUP_UNION_M must be >= 1, got {union_m}")
    if deep_k < 1:
        raise DedupError(f"MEM_DEDUP_DEEP_K must be >= 1, got {deep_k}")
    if chunk_skip_chars < 1:
        raise DedupError(f"MEM_DEDUP_CHUNK_SKIP_CHARS must be >= 1, got {chunk_skip_chars}")

    return DedupConfig(
        dedup_low=dedup_low,
        dedup_high=dedup_high,
        coverage_low=coverage_low,
        coverage_high=coverage_high,
        union_low=union_low,
        union_m=union_m,
        claim_lex=claim_lex,
        claim_sem=claim_sem,
        deep_k=deep_k,
        chunk_skip_chars=chunk_skip_chars,
        chunks=chunks,
        log=log,
        log_titles=log_titles,
    )


# ==========================================================================
# S4 - fused retrieval orchestration: Corpus + detect()
#
# research/d18-dedup-detection-design-2026-09-02.md S4.1 (retrieval spec),
# S4.2 (the prefix trap - `vector.top_k_doc` reused, never `search`'s
# query-prefixed leg), S4.4 (flag policy), S5 (interfaces/data flow).
# ==========================================================================


def content_hash(concept) -> str:
    """A candidate's identity for the durable log's (run_id, content_hash)
    join (S4.5) - hashed from the concept's own text so it never depends on
    whether embedding succeeded this run (dedup must still answer, coverage-
    only, with the daemon down)."""
    return "sha256:" + hashlib.sha256(vector.document_text(concept).encode("utf-8")).hexdigest()


@dataclass
class Corpus:
    """Everything `detect()` needs to score MANY candidates against the same
    KB snapshot, built ONCE per `mem dedup` invocation so a batch doesn't
    re-sync the lexical index or reopen connections per candidate. Owns the
    lexical + chunk connections for the invocation's lifetime; `close()`
    releases them."""

    root: Path
    cfg: DedupConfig
    lex_conn: sqlite3.Connection
    chunk_con: Optional[sqlite3.Connection]
    graph: object
    idf: IdfLookup
    body_by_slug: dict
    title_by_slug: dict
    vector_available: bool
    chunk_leg_active: bool  # cfg.chunks AND the daemon hasn't failed mid-run
    legs_run: list
    claim_con: Optional[sqlite3.Connection] = None  # D18 S7
    claim_leg_active: bool = False  # cfg.claim_sem is not None AND the daemon hasn't failed mid-run
    embed_model: Optional[str] = None  # set by the CLI once the batch embed
    embed_digest: Optional[str] = None  # completes - identity for top_k_doc/chunk scans (gate finding 3)
    _concept_cache: dict = field(default_factory=dict)

    def concept(self, slug: str):
        """Lazily-loaded, memoized `okf.Concept` for a hit slug - None if the
        file vanished since indexing (no ghost hits, mirroring search.py)."""
        if slug not in self._concept_cache:
            try:
                self._concept_cache[slug] = store.load(self.root, slug)
            except store.StoreError:
                self._concept_cache[slug] = None
        return self._concept_cache[slug]

    def close(self) -> None:
        self.lex_conn.close()
        if self.chunk_con is not None:
            self.chunk_con.close()
        if self.claim_con is not None:
            self.claim_con.close()


def build_corpus(root: Path, cfg: DedupConfig) -> Corpus:
    """Sync the lexical index (like `search.cmd_search`), reconcile vectors
    from that change-set, then snapshot title/body/IDF from the now-current
    lexical table - one read pass, reused by every candidate in the batch."""
    lex_conn = lexical.connect(root)
    changed, removed = lexical.sync(lex_conn, root)
    vector.reconcile(root, changed, removed)

    rows = lex_conn.execute("SELECT slug, title, body FROM lexical").fetchall()
    body_by_slug = {slug: body for slug, _title, body in rows}
    title_by_slug = {slug: title for slug, title, _body in rows}
    idf = idf_from_corpus(claims.tokenize(body) for _slug, _title, body in rows)

    vec_con = vector.connect(root)
    try:
        vector_available = vector.get_meta(vec_con) is not None
    finally:
        vec_con.close()

    chunk_con = chunks_mod.connect(root) if cfg.chunks else None
    claim_con = claims.connect(root) if cfg.claim_sem is not None else None
    legs_run = ["lexical", "graph", "coverage_lexical"]
    if vector_available:
        legs_run.insert(1, "vector_document")
    if cfg.chunks:
        legs_run.append("vector_chunk")
    if cfg.claim_sem is not None:
        legs_run.append("claim_semantic")

    return Corpus(
        root=root, cfg=cfg, lex_conn=lex_conn, chunk_con=chunk_con,
        graph=graph_mod.load(root), idf=idf, body_by_slug=body_by_slug,
        title_by_slug=title_by_slug, vector_available=vector_available,
        chunk_leg_active=cfg.chunks, legs_run=legs_run,
        claim_con=claim_con, claim_leg_active=cfg.claim_sem is not None,
    )


def _claims_source(corpus: Corpus, slug: str, concept, snippet_by_slug: dict) -> tuple:
    """(text, note) for scoring a hit card's coverage - the whole body,
    unless it is oversize (S4.2's bound: coverage for an oversize card is
    scored against its lexically-matched window only, located from FTS5's
    own snippet - never the whole body, which for a 1.79 MB card would blow
    the per-candidate coverage budget). `snippet()` is an FTS5 auxiliary
    function that requires a MATCH context to highlight against, so the
    snippet must come from the lexical leg's own MATCH query (`lex_hits`),
    not a fresh plain SELECT; a hit that reached deep-K by a non-lexical leg
    has no snippet, so an oversize card found only that way falls back to a
    leading slice of its body."""
    body = corpus.body_by_slug.get(slug, concept.body if concept else "")
    if len(body) <= corpus.cfg.chunk_skip_chars:
        return body, None
    text = snippet_by_slug.get(slug) or body[: corpus.cfg.chunk_skip_chars]
    return text, "oversize"


def _dedup_seed(seen: list, extra: list) -> list:
    for slug in extra:
        if slug not in seen:
            seen.append(slug)
    return seen


def _cross(value, threshold) -> bool:
    return value is not None and threshold is not None and value >= threshold


# S4.2's `relation` table needs SOME low/high pair to label a hit even on an
# instance that hasn't calibrated (and so hasn't set) MEM_DEDUP_COVERAGE_LOW/
# HIGH - the per-hit `relation`/`recommended_action` fields are descriptive,
# never a flag gate (that gate reads the real, possibly-None cfg thresholds
# via `decisions[...]["crossed"]` directly), so a mislabeled relation on an
# uncalibrated instance costs nothing but a confusing string. Falling back
# to 0/1 here would make "unrelated" nearly unreachable (coverage is never
# negative); the design's own recommended calibrated values (S4.4) are a
# far more useful default label boundary than the unit interval's edges.
_RELATION_LABEL_FALLBACK_LOW = 0.35
_RELATION_LABEL_FALLBACK_HIGH = 0.85


def detect(
    corpus: Corpus, candidate, precomputed_vec: Optional[list] = None,
    precomputed_claim_vecs: Optional[list] = None, strict_claim_leg: bool = False,
) -> dict:
    """The fused-retrieval + coverage + routing pipeline for ONE candidate
    against `corpus`'s KB snapshot (S4.1/S4.2/S4.4). Returns the per-
    candidate report dict (§4.1's shape) - `mem dedup` assembles the `kb`/
    `summary`/`log` wrapper around a list of these; `mem save --dedup-check`
    calls it once, advisory-only. No shipped caller is `mem extract`: S6 (the
    extract rewiring) is DEFERRED as a follow-up decision (2026-09-03).

    `strict_claim_leg` and `precomputed_claim_vecs` are RESERVED, currently
    UNUSED seams kept for that S6 follow-up (its all-or-nothing batch will
    need to re-raise claim-embed daemon failures and to pass the candidate's
    up-front-embedded claim vectors). Every shipped caller leaves them at
    their defaults: a claim-embed daemon failure mid-run turns the leg off
    and keeps going (graceful degradation), and `detect()` embeds the
    candidate's own claims itself with one live call when the semantic claim
    leg is active (degrading the leg off on daemon trouble, exactly like the
    chunk leg).
    """
    cfg = corpus.cfg
    notes: list = []
    self_slug = candidate.slug

    # Ruling A (D18 W2 fix cycle, gate finding 2): a hit's `relation` label
    # is CALIBRATED (and so may drive the confident-duplicate superset
    # downgrade below) only when BOTH coverage bounds are actually
    # configured for this instance. Unconfigured, the label still uses the
    # design's own recommended values as a legible default (never the raw
    # unit interval, which would make `unrelated` nearly unreachable), but
    # it is presentation only - `label_basis` says which, and the routing
    # code below must check `coverage_configured`, never infer it from the
    # label string.
    coverage_configured = cfg.coverage_low is not None and cfg.coverage_high is not None
    if coverage_configured:
        coverage_low_for_labels: float = cfg.coverage_low  # type: ignore[assignment]
        coverage_high_for_labels: float = cfg.coverage_high  # type: ignore[assignment]
        label_basis = "configured"
    else:
        coverage_low_for_labels = _RELATION_LABEL_FALLBACK_LOW
        coverage_high_for_labels = _RELATION_LABEL_FALLBACK_HIGH
        label_basis = "fallback"

    # --- lexical leg -----------------------------------------------------
    expr = lexical.dedup_match_expr(corpus.lex_conn, candidate.body, n=24)
    lex_hits = lexical.search_expr(corpus.lex_conn, expr, cfg.deep_k) if expr else []
    lex_slugs = [h["slug"] for h in lex_hits if h["slug"] != self_slug]
    snippet_by_slug = {h["slug"]: h["snippet"] for h in lex_hits}
    if not expr:
        notes.append("lexical leg: empty query (candidate is entirely unseen vocabulary)")

    # --- vector_document leg (whole-KB scope for the flag) ---------------
    doc_cosines: dict = {}
    vec_slugs: list = []
    if corpus.vector_available and precomputed_vec is not None:
        ranked = vector.top_k_doc(
            corpus.root, vec=precomputed_vec, k=None,
            model=corpus.embed_model, digest=corpus.embed_digest,
        )
        doc_cosines = {slug: score for slug, score in ranked if slug != self_slug}
        vec_slugs = [slug for slug, _ in ranked if slug != self_slug][: cfg.deep_k]
    elif corpus.vector_available and precomputed_vec is None:
        notes.append("vector_document leg skipped: no embedding available this run")

    # --- vector_chunk leg (deep-K scope, lazy retrieval-driven population) --
    chunk_best: dict = {}
    if corpus.chunk_leg_active and precomputed_vec is not None:
        seed_slugs = _dedup_seed(list(lex_slugs), vec_slugs)[: cfg.deep_k]
        oversize_seen = 0
        for slug in seed_slugs:
            concept = corpus.concept(slug)
            if concept is None:
                continue
            try:
                status = chunks_mod.populate_one(
                    corpus.chunk_con, concept, cfg.chunk_skip_chars, vector.FULL_DRAIN_TIMEOUT,
                    model=corpus.embed_model, digest=corpus.embed_digest,
                )
            except ollama.OllamaError:
                corpus.chunk_leg_active = False
                # gate finding 5: a leg that failed mid-run must not still be
                # reported as having run - remove it from the shared
                # per-invocation legs_run list, not just this candidate's
                # local `chunk_leg_active` flag, so `config.legs_run` in the
                # eventual report/log stays truthful for the whole batch.
                if "vector_chunk" in corpus.legs_run:
                    corpus.legs_run.remove("vector_chunk")
                notes.append("vector_chunk leg disabled mid-run: embed daemon unavailable")
                break
            if status == "skipped-oversize":
                oversize_seen += 1
        if oversize_seen:
            notes.append(f"chunk_index: skipped-oversize for {oversize_seen} hit(s)")
        if corpus.chunk_leg_active:
            chunk_best = chunks_mod.best_per_card(
                corpus.chunk_con, precomputed_vec, k=cfg.deep_k,
                model=corpus.embed_model, digest=corpus.embed_digest,
            )
            chunk_best.pop(self_slug, None)
    elif cfg.chunks and precomputed_vec is None:
        notes.append("vector_chunk leg skipped: no embedding available this run")

    # --- graph leg (ordering only - never flags) --------------------------
    seeds = _dedup_seed(list(lex_slugs), vec_slugs)
    graph_slugs = [s for s in fusion.graph_leg(corpus.graph, seeds) if s != self_slug]

    # --- fuse, then cut to the deep-K report ------------------------------
    chunk_slugs = sorted(chunk_best, key=lambda s: (-chunk_best[s][0], s))
    fused = fusion.rrf([lex_slugs, vec_slugs, chunk_slugs, graph_slugs])
    hit_slugs = [slug for slug, _score in fused if slug != self_slug][: cfg.deep_k]

    # --- per-hit coverage scoring ------------------------------------------
    candidate_claim_texts = claims.segment(candidate.body)

    # --- semantic claim leg (S7, off unless MEM_DEDUP_CLAIM_SEM is set) ---
    candidate_claim_vecs = None
    if corpus.claim_leg_active and candidate_claim_texts:
        if precomputed_claim_vecs is not None:
            candidate_claim_vecs = precomputed_claim_vecs
        else:
            try:
                base = config.ollama_base_url()
                model = corpus.embed_model or config.embed_model()
                texts = ["search_document: " + t for t in candidate_claim_texts]
                candidate_claim_vecs = ollama.embed(base, model, texts, timeout=vector.FULL_DRAIN_TIMEOUT)
            except ollama.OllamaError:
                if strict_claim_leg:
                    raise
                corpus.claim_leg_active = False
                if "claim_semantic" in corpus.legs_run:
                    corpus.legs_run.remove("claim_semantic")
                notes.append("claim_semantic leg disabled mid-run: embed daemon unavailable (candidate claims)")

    candidate_claims = build_claims(candidate_claim_texts, corpus.idf, candidate_claim_vecs)

    hits = []
    hit_claims_by_slug = {}
    oversize_claim_hits = 0
    for rank, slug in enumerate(hit_slugs, start=1):
        concept = corpus.concept(slug)
        if concept is None:
            continue
        legs = []
        if slug in lex_slugs:
            legs.append("lexical")
        if slug in doc_cosines and slug in vec_slugs:
            legs.append("vector_document")
        if slug in chunk_best:
            legs.append("vector_chunk")

        source_text, src_note = _claims_source(corpus, slug, concept, snippet_by_slug)
        if src_note == "oversize":
            oversize_claim_hits += 1
        card_claim_texts = claims.segment(source_text)

        card_claim_vecs = None
        if corpus.claim_leg_active and card_claim_texts:
            try:
                status = claims.populate_one(
                    corpus.claim_con, slug, card_claim_texts, vector.FULL_DRAIN_TIMEOUT,
                    model=corpus.embed_model, digest=corpus.embed_digest,
                )
            except ollama.OllamaError:
                if strict_claim_leg:
                    raise
                corpus.claim_leg_active = False
                if "claim_semantic" in corpus.legs_run:
                    corpus.legs_run.remove("claim_semantic")
                notes.append("claim_semantic leg disabled mid-run: embed daemon unavailable")
            else:
                card_claim_vecs = claims.vectors_for(
                    corpus.claim_con, slug, model=corpus.embed_model, digest=corpus.embed_digest,
                )

        card_claims = build_claims(card_claim_texts, corpus.idf, card_claim_vecs)
        hit_claims_by_slug[slug] = card_claims

        cc = coverage_of_candidate(
            candidate_claims, card_claims, corpus.idf, cfg.claim_lex, sem_threshold=cfg.claim_sem,
        )
        cd = coverage_of_card(
            candidate_claims, card_claims, corpus.idf, cfg.claim_lex, sem_threshold=cfg.claim_sem,
        )
        rel, action = relation(cc, cd, coverage_low_for_labels, coverage_high_for_labels)

        matched_claims = []
        for i, cand_c in enumerate(candidate_claims):
            for j, card_c in enumerate(card_claims):
                sem = _claim_cosine(cand_c, card_c)
                if matched(
                    cand_c.tokens, card_c.tokens, corpus.idf, cfg.claim_lex,
                    semantic_cosine=sem, sem_threshold=cfg.claim_sem,
                ):
                    matched_claims.append({
                        "candidate_claim": i, "card_claim": j,
                        "lexical_containment": round(
                            lexical_containment(cand_c.tokens, card_c.tokens, corpus.idf), 4
                        ),
                        "semantic_cosine": round(sem, 4) if sem is not None else None,
                    })

        cos_doc = doc_cosines.get(slug)
        cos_chunk, chunk_ord = chunk_best.get(slug, (None, None))
        hit = {
            "fusion_rank": rank,
            "slug": slug,
            "title": corpus.title_by_slug.get(slug, concept.title),
            "type": concept.type,
            "legs": legs,
            "cosine_document": round(cos_doc, 4) if cos_doc is not None else None,
            "cosine_best_chunk": round(cos_chunk, 4) if cos_chunk is not None else None,
            "best_chunk_ordinal": chunk_ord,
            "coverage_of_candidate": round(cc, 4),
            "coverage_of_card": round(cd, 4),
            "relation": rel,
            "label_basis": label_basis,
            "recommended_action": action,
            "matched_claims": matched_claims,
        }
        if concept.sensitivity != "normal":
            hit["sensitivity"] = concept.sensitivity
        hits.append(hit)
    if oversize_claim_hits:
        notes.append(f"claims: scored from lexically-matched excerpt only for {oversize_claim_hits} hit(s)")

    # --- union (greedy set-cover over the deep-K hit list) ----------------
    union = greedy_union_cover(
        candidate_claims,
        [(h["slug"], hit_claims_by_slug[h["slug"]]) for h in hits],
        corpus.idf, cfg.claim_lex, m=cfg.union_m, sem_threshold=cfg.claim_sem,
    )

    # --- aggregate signals + decisions -------------------------------------
    cosine_document_max = max(doc_cosines.values()) if doc_cosines else None
    cosine_document_slug = (
        max(doc_cosines, key=lambda s: doc_cosines[s]) if doc_cosines else None
    )
    chunk_cosines = {h["slug"]: h["cosine_best_chunk"] for h in hits if h["cosine_best_chunk"] is not None}
    cosine_chunk_max = max(chunk_cosines.values()) if chunk_cosines else None
    cosine_chunk_slug = max(chunk_cosines, key=lambda s: chunk_cosines[s]) if chunk_cosines else None
    coverage_max = max((h["coverage_of_candidate"] for h in hits), default=None)
    coverage_slug = (
        max(hits, key=lambda h: h["coverage_of_candidate"])["slug"] if hits else None
    )
    coverage_union_value = union.coverage_union if union.member_slugs else None

    decisions = {
        "cosine_document_max": {
            "value": round(cosine_document_max, 4) if cosine_document_max is not None else None,
            "threshold": cfg.dedup_low, "scope": "whole-kb",
            "crossed": _cross(cosine_document_max, cfg.dedup_low),
        },
        "cosine_document_confident": {
            "value": round(cosine_document_max, 4) if cosine_document_max is not None else None,
            "threshold": cfg.dedup_high, "scope": "whole-kb",
            "crossed": _cross(cosine_document_max, cfg.dedup_high),
        },
        "cosine_chunk_max": {
            "value": round(cosine_chunk_max, 4) if cosine_chunk_max is not None else None,
            "threshold": cfg.dedup_low, "scope": "deep-k",
            "crossed": _cross(cosine_chunk_max, cfg.dedup_low),
        },
        "coverage_of_candidate_max": {
            "value": round(coverage_max, 4) if coverage_max is not None else None,
            "threshold": cfg.coverage_low, "scope": "deep-k",
            "crossed": _cross(coverage_max, cfg.coverage_low),
        },
        "coverage_of_candidate_confident": {
            "value": round(coverage_max, 4) if coverage_max is not None else None,
            "threshold": cfg.coverage_high, "scope": "deep-k",
            "crossed": _cross(coverage_max, cfg.coverage_high),
        },
        "coverage_union": {
            "value": round(coverage_union_value, 4) if coverage_union_value is not None else None,
            "threshold": cfg.union_low, "scope": "top-m",
            "crossed": _cross(coverage_union_value, cfg.union_low),
        },
    }

    semantic_flag = decisions["cosine_document_max"]["crossed"] or decisions["cosine_chunk_max"]["crossed"]
    coverage_flag = (
        decisions["coverage_of_candidate_max"]["crossed"] or decisions["coverage_union"]["crossed"]
    )
    flagged = semantic_flag or coverage_flag

    hits_by_slug = {h["slug"]: h for h in hits}
    confident_trigger = (
        decisions["coverage_of_candidate_confident"]["crossed"]
        or decisions["cosine_document_confident"]["crossed"]
    )
    winning_hit = None
    if decisions["coverage_of_candidate_confident"]["crossed"] and coverage_slug in hits_by_slug:
        winning_hit = hits_by_slug[coverage_slug]
    elif decisions["cosine_document_confident"]["crossed"] and cosine_document_slug in hits_by_slug:
        winning_hit = hits_by_slug[cosine_document_slug]

    if confident_trigger:
        # S4.4: never auto-confident on a superset - but a confident cosine/
        # coverage threshold crossing still promotes even when the specific
        # winning hit couldn't be resolved into the deep-K list (rare: the
        # whole-KB argmax fell out of the fused report); the downgrade only
        # fires when we can positively identify a superset relation.
        #
        # Ruling A (gate finding 2): that identification is only trustworthy
        # when `coverage_configured` - i.e. the winning hit's `relation` was
        # labeled from CONFIGURED coverage bounds, not the presentation-only
        # fallback. With coverage unconfigured, a cosine-only confident
        # trigger must route on cosine alone; the fallback-labeled relation
        # (whatever it says) may never demote it to review-duplicate.
        if (
            coverage_configured
            and winning_hit is not None
            and winning_hit["relation"] == CANDIDATE_SUPERSET
        ):
            verdict = "review-duplicate"
        else:
            verdict = "confident-duplicate"
    elif flagged:
        verdict = "review-duplicate"
    else:
        verdict = "novel"

    if verdict == "novel":
        recommended_action = "add"
    else:
        # A flagged/confident verdict must never silently inherit "add" from
        # a hit whose OWN relation is `unrelated` (the relation table's
        # "add" cell) - that hit isn't why this candidate flagged (e.g. the
        # semantic leg fired while coverage found nothing on that hit), and
        # surfacing "add" on a review/confident-duplicate would contradict
        # the verdict itself. "review" is the safe fallback whenever no hit
        # we can point to actually explains the flag with a decision-worthy
        # relation (subset/superset/equivalent/overlapping).
        candidate_for_action = winning_hit
        if candidate_for_action is None and coverage_slug in hits_by_slug:
            candidate_for_action = hits_by_slug[coverage_slug]
        if candidate_for_action is not None and candidate_for_action["relation"] != UNRELATED:
            recommended_action = candidate_for_action["recommended_action"]
        else:
            recommended_action = "review"

    flag_reasons = []
    for name, against in (
        ("cosine_document_max", cosine_document_slug),
        ("cosine_chunk_max", cosine_chunk_slug),
        ("coverage_of_candidate_max", coverage_slug),
    ):
        if decisions[name]["crossed"]:
            flag_reasons.append({
                "signal": name, "value": decisions[name]["value"],
                "threshold": decisions[name]["threshold"], "against": against,
            })
    if decisions["coverage_union"]["crossed"]:
        flag_reasons.append({
            "signal": "coverage_union", "value": decisions["coverage_union"]["value"],
            "threshold": decisions["coverage_union"]["threshold"],
            "against": "+".join(union.member_slugs) or None,
        })

    return {
        "title": candidate.title,
        "slug_intended": candidate.slug,
        "content_hash": content_hash(candidate),
        "claim_count": len(candidate_claims),
        "verdict": verdict,
        "recommended_action": recommended_action,
        "flagged": flagged,
        "flag_reasons": flag_reasons,
        "decisions": decisions,
        "hits": hits,
        "union": {
            "member_slugs": union.member_slugs,
            "coverage_curve": [
                {"slug": step.slug, "cumulative_coverage": round(step.cumulative_coverage, 4)}
                for step in union.curve
            ],
        },
        "notes": notes,
    }
