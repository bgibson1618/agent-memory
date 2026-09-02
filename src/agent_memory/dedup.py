"""D18 S2 - dedup detector core: claim-grain containment, directional
coverage, the `relation` table, and greedy union set-cover.

research/d18-dedup-detection-design-2026-09-02.md S4.2/S4.4 is the spec. This
module ships the SCORING core only - S1's claims.py segmentation/tokenization
plus this file's pure functions over already-segmented claim text. No
retrieval wiring (the four fused legs), no `mem dedup` command, no
extract/save changes: those land in S3/S4/S6 once the four legs exist to
feed a `detect()` entry point. What ships here anticipates that surface -
`Claim`/`build_claims` is the exact shape a future `detect()` needs for each
retrieved hit - but there is no `detect()` yet (see output.md's judgment-call
note on scope).

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

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from agent_memory import claims, config

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
    weighting over plain counts)."""

    text: str
    tokens: frozenset
    weight: float


def build_claims(texts: Iterable[str], idf: IdfLookup) -> list:
    """One Claim per text unit (already segmented - callers pass
    `claims.segment(body)`'s output, not raw bodies)."""
    out = []
    for text in texts:
        tokens = frozenset(claims.tokenize(text))
        weight = sum(idf(t) for t in tokens)
        out.append(Claim(text=text, tokens=tokens, weight=weight))
    return out


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
    reference_claims: Sequence[Claim], other_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float
) -> float:
    """IDF-mass-weighted fraction of `reference_claims` that have some match
    in `other_claims`. `coverage_of_candidate`/`coverage_of_card` are this
    function with the two argument roles swapped - `matched()`'s first
    argument is always the containment denominator, so swapping which claim
    list plays "reference" correctly re-derives the asymmetric direction
    without duplicating the loop."""
    total = sum(c.weight for c in reference_claims)
    if total <= 0:
        return 0.0
    covered = sum(
        c.weight
        for c in reference_claims
        if any(matched(c.tokens, d.tokens, idf, lex_threshold) for d in other_claims)
    )
    return covered / total


def coverage_of_candidate(
    candidate_claims: Sequence[Claim], card_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float
) -> float:
    """S4.2: fraction of the candidate's IDF mass that the card covers."""
    return _directional_coverage(candidate_claims, card_claims, idf, lex_threshold)


def coverage_of_card(
    candidate_claims: Sequence[Claim], card_claims: Sequence[Claim], idf: IdfLookup, lex_threshold: float
) -> float:
    """S4.2: fraction of the card's IDF mass that the candidate covers -
    coverage_of_candidate with the roles swapped."""
    return _directional_coverage(card_claims, candidate_claims, idf, lex_threshold)


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
) -> UnionResult:
    """S4.2: greedy set-cover over `cards` (a `[(slug, card_claims)]` list,
    the deep-K hit list in the eventual retrieval-wired form), ranked each
    round by marginal candidate-claim-mass gain, capped at `m` picks.
    Coverage is submodular, so greedy is (1-1/e)-optimal (S4.2's stated
    justification over exhaustive pairs). Returns the picked slugs in
    marginal-gain order, the final cumulative coverage, and the step-by-step
    curve - each entry's own cumulative_coverage, so a consumer can see the
    diminishing returns rather than only the endpoint."""
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
                if not covered[i] and any(matched(c.tokens, d.tokens, idf, lex_threshold) for d in card_claims)
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
