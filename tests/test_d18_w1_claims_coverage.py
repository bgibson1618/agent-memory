"""D18 Wave 1 (S1 claim segmentation/IDF plumbing + S2 detector core) -
research/d18-dedup-detection-design-2026-09-02.md S4.2/S4.4/S4.9.

No CLI/retrieval wiring exists yet (that's S3/S4/S6), so every test here
drives the modules directly: `claims.segment`/`tokenize` are pure functions;
`lexical.dedup_match_expr` needs a real FTS5 index, built here via
`okf.serialize` + `lexical.connect`/`sync` against a scratch `tmp_path` root
(no `mem` subprocess - S1/S2 add no CLI surface); `dedup.py`'s scoring
functions are pure over hand-built `Claim`/idf-lookup values, per S4.9's
"unit tests on hand-built claim sets" proof method.
"""

import pytest

from agent_memory import claims, config, dedup, lexical, okf

# --------------------------------------------------------------------------
# S1 - claims.segment(): table-driven segmentation cases
# --------------------------------------------------------------------------

SEGMENTATION_CASES = {
    "nested_list": (
        "- Top level item with enough words to pass the filter here.\n"
        "  - Nested item that also has plenty of content words inside.\n"
        "- Another top level item following right after that one.",
        [
            "Top level item with enough words to pass the filter here.",
            "Nested item that also has plenty of content words inside.",
            "Another top level item following right after that one.",
        ],
    ),
    "heading_then_paragraph": (
        "## A Heading With Enough Words To Pass\n\n"
        "Some paragraph text that follows the heading and has enough words.",
        [
            "A Heading With Enough Words To Pass",
            "Some paragraph text that follows the heading and has enough words.",
        ],
    ),
    "abbreviation_guard": (
        "Dr. Smith wrote the report. It was published last year in a journal.",
        [
            "Dr. Smith wrote the report.",
            "It was published last year in a journal.",
        ],
    ),
    "abbreviation_guard_e_g": (
        "See e.g. Ostrowski for a detailed treatment of this particular case.",
        ["See e.g. Ostrowski for a detailed treatment of this particular case."],
    ),
    "inline_code_masked": (
        "Run `Init(). Configure()` carefully before the very first deploy. "
        "Then check the output for errors please.",
        [
            "Run `Init(). Configure()` carefully before the very first deploy.",
            "Then check the output for errors please.",
        ],
    ),
    "short_heading_dropped": (
        "## Why\n\n"
        "This is a heading with a short title but a full paragraph below "
        "with enough content words to pass the filter easily.",
        [
            "This is a heading with a short title but a full paragraph below "
            "with enough content words to pass the filter easily."
        ],
    ),
    "short_list_item_dropped": ("- ok", []),
    # D18 W1 fix cycle (gate finding 3), pinned exactly: a multi-period
    # initialism must not be split and dropped, losing the claim's subject.
    "initialism_us": (
        "The U.S. Policy team published the complete report yesterday.",
        ["The U.S. Policy team published the complete report yesterday."],
    ),
    "initialism_us_a": (
        "Visit the U.S.A. embassy before your appointment next week please.",
        ["Visit the U.S.A. embassy before your appointment next week please."],
    ),
    "title_prof": (
        "Prof. Smith published the definitive study on this topic last year. "
        "Later work confirmed every one of the original findings in full.",
        [
            "Prof. Smith published the definitive study on this topic last year.",
            "Later work confirmed every one of the original findings in full.",
        ],
    ),
}


@pytest.mark.parametrize("name", sorted(SEGMENTATION_CASES))
def test_segmentation_case(name):
    text, expected = SEGMENTATION_CASES[name]
    assert claims.segment(text) == expected


def test_min_content_token_filter_is_four():
    # exactly 3 content tokens -> dropped; add a 4th -> kept
    assert claims.segment("## One two three") == []
    assert claims.segment("## One two three four") == ["One two three four"]


# --------------------------------------------------------------------------
# S1 - segmentation is near-linear on punctuation-dense text > 32 KiB
# (gate finding 4: the old code copied/rescanned the whole accumulated
# prefix per boundary, giving quadratic blowup)
# --------------------------------------------------------------------------


def _punctuation_dense_text(n_sentences: int) -> str:
    # "Word0. Word1. Word2. ..." - every period is followed by whitespace
    # and a capital, so every one is a candidate split point; this is what
    # the gate's reproduction used to force maximum boundary density.
    return " ".join(f"Word{i}." for i in range(n_sentences))


def test_segmentation_scales_near_linearly_above_32kib():
    import time

    base_n = 6_000  # ~40 KiB, comfortably above the 32 KiB floor
    text_2x = _punctuation_dense_text(base_n)
    text_4x = _punctuation_dense_text(base_n * 2)
    assert len(text_2x) > 32_768

    def timed(text):
        start = time.perf_counter()
        claims.segment(text)
        return time.perf_counter() - start

    timed(text_2x)  # warm-up: exclude import/regex-compile one-time cost
    t_2x = min(timed(text_2x) for _ in range(3))
    t_4x = min(timed(text_4x) for _ in range(3))

    # Quadratic would give ~4x runtime for a 2x input; generous margin (not
    # tight wall-clock) so this stays robust on a loaded/slow host while
    # still failing on a real quadratic regression.
    assert t_4x < 3 * t_2x, f"t_2x={t_2x:.4f}s t_4x={t_4x:.4f}s - looks quadratic"


# --------------------------------------------------------------------------
# S1 - mis-split-rate measurement, 100-card fixed corpus (Class-2 fix cycle)
# --------------------------------------------------------------------------
#
# The gate's Class-2 finding: the old measurement rotated six authored
# templates, deliberately inserted one KNOWN-BROKEN family ("Prof. NAME"),
# and bounded the rate loosely (<=25%/15%) - a bound wide enough to hide the
# real number rather than report it. This replaces that with:
#
#   1. A DETERMINISTIC, committed 100-card corpus - ten template families
#      rotated over i in range(100) (`_full_corpus()`, reproducible by
#      construction: no wall-clock, no RNG seed to drift).
#   2. A FIXED 20-card subset (indices 0-19, two of each family) with the
#      claim boundaries HAND-LABELED to the semantically correct
#      segmentation - i.e. what `segment()` SHOULD return, decided by
#      reading each card, not by running the buggy implementation and
#      copying its output.
#   3. An EXACT numerator/denominator assertion against that subset - no
#      loose bound.
#
# "Prof." and "U.S." are now fixed (gate finding 3) and are included as
# now-PASSING regression cases, not adversarial ones. Fix cycle 2 (re-gate
# finding 1) made sentence splitting LOSS-PROOF: a fragment below the claim
# floor merges into its neighbor instead of being dropped, so even a title
# abbreviation on no list ("Sen.", "Rev.") can no longer lose text - the
# `_unguarded_title` family flips from the disclosed residual mismatch to
# byte-exact, and the measured rate below is exactly 0/20 and 0/100. The
# residual cost is now cosmetic only (a rare mid-claim split where both
# halves clear the floor), not data loss.

_SUBJECTS = [
    "The pipeline", "Our team", "This module", "The service", "A worker",
    "The scheduler", "Each request", "The daemon", "This function", "The index",
]
_WORDS = [
    "timeout", "buffer", "retry", "cache", "queue", "socket", "token",
    "session", "thread", "lock",
]
_NAMES = [
    "Alvarez", "Chen", "Okafor", "Petrov", "Singh", "Larsson", "Nakamura", "Osei",
]


def _clean_pair(i):
    s1 = f"{_SUBJECTS[i % len(_SUBJECTS)]} processes the incoming batch quickly because latency matters here."
    s2 = f"{_SUBJECTS[(i + 3) % len(_SUBJECTS)]} retries automatically whenever the upstream call fails once."
    return f"{s1} {s2}", [s1, s2]


def _nested_list_card(i):
    a = f"Configure the {_WORDS[i % len(_WORDS)]} setting before starting the service."
    b = f"Double check the nested {_WORDS[(i + 1) % len(_WORDS)]} value for correctness too."
    c = "Restart the process once every setting has been confirmed correct."
    return f"- {a}\n  - {b}\n- {c}", [a, b, c]


def _heading_and_paragraph(i):
    heading = f"Overview Of The {_WORDS[i % len(_WORDS)].capitalize()} Subsystem"
    s1 = f"This subsystem handles {_WORDS[(i + 1) % len(_WORDS)]} requests from every client."
    s2 = "It logs every failure so operators can review the history later."
    return f"## {heading}\n\n{s1} {s2}", [heading, s1, s2]


def _guarded_abbreviation(i):
    name = _NAMES[i % len(_NAMES)]
    s1 = f"See e.g. {name} for a detailed treatment of this particular case."
    s2 = "Also refer to the appendix for the full derivation of the result."
    return f"{s1} {s2}", [s1, s2]


def _title_prof(i):
    """Fixed this cycle: "prof" is now in the enumerated abbreviation list."""
    name = _NAMES[i % len(_NAMES)]
    s1 = f"Prof. {name} published the definitive study on this topic last year."
    s2 = "Later work confirmed every one of the original findings in full."
    return f"{s1} {s2}", [s1, s2]


def _inline_code_card(i):
    s1 = "Run `Init(). Configure()` carefully before the very first deploy."
    s2 = f"Then verify the {_WORDS[i % len(_WORDS)]} output matches what was expected."
    return f"{s1} {s2}", [s1, s2]


def _initialism_us(i):
    """Fixed this cycle: multi-period initialisms are guarded structurally."""
    s1 = f"The U.S. {_WORDS[i % len(_WORDS)].capitalize()} team published the complete report yesterday."
    s2 = "Every reviewer signed off on the final version without any changes."
    return f"{s1} {s2}", [s1, s2]


def _short_heading_dropped(i):
    heading = "## Why"
    s1 = f"This is a heading with a short title but a full paragraph about {_WORDS[i % len(_WORDS)]} below."
    return f"{heading}\n\n{s1}", [s1]


def _numbered_list(i):
    a = f"Restart the {_WORDS[i % len(_WORDS)]} service before the next deploy window."
    b = f"Confirm the {_WORDS[(i + 1) % len(_WORDS)]} value matches the expected configuration."
    return f"1. {a}\n2. {b}", [a, b]


def _unguarded_title(i):
    """"Sen" is on no finite list and is not initialism-shaped, so the split
    guard misses it - but fix cycle 2's merge rule makes the miss lossless:
    the sub-floor "Sen." fragment merges into its continuation and the
    hand-labeled claim comes back byte-exact. This family is the regression
    case for the loss-proofing rule itself."""
    name = _NAMES[i % len(_NAMES)]
    s1 = f"Sen. {name} proposed a new bill in committee earlier this week."
    s2 = "It passed by a narrow margin after several hours of debate today."
    return f"{s1} {s2}", [s1, s2]


_FAMILIES = [
    _clean_pair, _nested_list_card, _heading_and_paragraph,
    _guarded_abbreviation, _title_prof, _inline_code_card,
    _initialism_us, _short_heading_dropped, _numbered_list, _unguarded_title,
]


def _full_corpus(n=100):
    """The committed, deterministic 100-card corpus (Class-2 fix cycle):
    reproducible by construction (`i % len(_FAMILIES)` rotation, no RNG, no
    wall-clock), so re-running this function always yields byte-identical
    cards. The subset test below hand-labels indices 0-19."""
    return [_FAMILIES[i % len(_FAMILIES)](i) for i in range(n)]


HAND_LABELED_SUBSET = range(20)  # two cards of each of the ten families


def test_mis_split_rate_hand_labeled_20_card_subset():
    """Class-2 fix cycle: exact numerator/denominator over a fixed,
    hand-labeled subset, not a loose bound over an unlabeled sample."""
    corpus = _full_corpus(100)
    subset = [corpus[i] for i in HAND_LABELED_SUBSET]

    card_mismatches = 0
    claim_mismatches = 0
    total_expected = 0
    broken_texts = []
    for text, expected in subset:
        actual = claims.segment(text)
        total_expected += len(expected)
        if actual != expected:
            card_mismatches += 1
            claim_mismatches += sum(1 for e in expected if e not in actual)
            broken_texts.append(text)

    # Measured after fix cycle 2 (recorded in output.md): 0/20 cards, 0/42
    # claims - the merge rule flipped the last mismatching family ("Sen.")
    # to byte-exact, and nothing else regressed.
    assert card_mismatches == 0
    assert total_expected == 42
    assert claim_mismatches == 0
    assert broken_texts == []


def test_mis_split_rate_full_100_card_corpus_matches_the_disclosed_family_only():
    """Extends the hand-labeled subset's exact accounting to the full
    committed 100-card corpus: after fix cycle 2 every family is byte-exact
    (the rotation used to guarantee 10 "Sen." mismatches per 100; the merge
    rule flipped them all)."""
    corpus = _full_corpus(100)
    card_mismatches = sum(1 for text, expected in corpus if claims.segment(text) != expected)
    assert card_mismatches == 0
    for text, expected in corpus:
        assert claims.segment(text) == expected


def test_regate_ampersand_initialism_cluster_survives_whole():
    """Re-gate finding 1 pins (fix cycle 2): ampersand initialisms are guarded
    structurally, "dept" is enumerated, and the whole cluster stays one claim."""
    for text in (
        "The R&D. Dept. team published the complete report yesterday.",
        "The Q.A. Dept. Leaders published the complete report yesterday.",
    ):
        assert claims.segment(text) == [text]


def test_regate_unenumerated_abbreviation_is_lossless_via_merge():
    """A title abbreviation on no list ("Rev.") still splits at the guard, but
    the sub-floor fragment merges forward - text is never dropped."""
    text = "Rev. Okafor spoke at the annual conference about resilience patterns."
    assert claims.segment(text) == [text]


def test_regate_short_sentence_merges_forward_not_dropped():
    """The loss-proofing rule in general: a genuine short sentence inside a
    paragraph merges into its neighbor instead of vanishing."""
    text = "It failed. The retry succeeded after the timeout elapsed as expected."
    (unit,) = claims.segment(text)
    assert "It failed." in unit and unit.endswith("as expected.")


def test_regate_sentence_split_is_loss_proof_over_the_full_corpus():
    """Property over all 100 corpus cards: every content token of every
    hand-labeled claim appears in segment()'s joined output - block-level
    drops (short headings) are the only permitted omission, and the corpus
    labels already exclude those."""
    for text, expected in _full_corpus(100):
        joined = " ".join(claims.segment(text))
        for e in expected:
            for tok in claims.tokenize(e):
                assert tok in joined.lower() or tok in claims.tokenize(joined)


# --------------------------------------------------------------------------
# S1 - lexical.dedup_match_expr
# --------------------------------------------------------------------------


def _write_concept(root, slug, title, body):
    (root / "concepts").mkdir(exist_ok=True)
    text = okf.serialize(
        okf.Concept(
            slug=slug, title=title, description="d", type="concept", topics=[],
            sensitivity="normal", created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z", body=body,
        )
    )
    (root / "concepts" / f"{slug}.md").write_text(text, encoding="utf-8")


def _lexical_conn(root):
    conn = lexical.connect(root)
    lexical.sync(conn, root)
    return conn


def test_dedup_match_expr_prefers_high_idf_terms(tmp_path):
    for i in range(5):
        _write_concept(tmp_path, f"widget-doc-{i}", f"Widget doc {i}", f"widget widget filler filler filler {i}")
    _write_concept(tmp_path, "gadget-doc", "Gadget doc", "gadget filler filler filler filler")
    conn = _lexical_conn(tmp_path)

    body = "widget widget gadget filler filler filler filler"
    expr = lexical.dedup_match_expr(conn, body, n=2)

    # gadget: df=1 (rarest -> highest idf). widget: df=5. filler: df=6 (in
    # every doc -> lowest idf) - at n=2 the two highest-idf INDEXED terms
    # survive; filler never does.
    assert '"gadget"' in expr
    assert '"widget"' in expr
    assert '"filler"' not in expr
    rows = conn.execute("SELECT slug FROM lexical WHERE lexical MATCH ?", (expr,)).fetchall()
    assert {slug for (slug,) in rows} == {"gadget-doc", *(f"widget-doc-{i}" for i in range(5))}


def test_dedup_match_expr_excludes_unseen_terms_and_recovers_the_indexed_one(tmp_path):
    """D18 W1 fix cycle (gate finding 1), pinned exactly: a df=0 term cannot
    retrieve any row, so scoring it at the (formerly unbounded) maximum idf
    let 24 unseen terms crowd the one real, retrievable term out of the
    top-24 entirely, starving the query to zero recall. df=0 terms are now
    excluded before ranking, so the indexed term survives regardless of how
    much novel vocabulary surrounds it."""
    _write_concept(tmp_path, "needle-card", "Needle card", "needle appears somewhere in this card body")
    conn = _lexical_conn(tmp_path)

    body = " ".join(f"novelterm{i}" for i in range(24)) + " needle"
    expr = lexical.dedup_match_expr(conn, body, n=24)

    assert '"needle"' in expr
    for i in range(24):
        assert f'"novelterm{i}"' not in expr
    rows = conn.execute("SELECT slug FROM lexical WHERE lexical MATCH ?", (expr,)).fetchall()
    assert rows == [("needle-card",)]


def test_dedup_match_expr_all_terms_unseen_is_empty_string(tmp_path):
    _write_concept(tmp_path, "seed", "Seed", "seed content for the index")
    conn = _lexical_conn(tmp_path)
    # every term in this body is out-of-corpus - nothing here could ever
    # retrieve a row, so the query must be empty, not a max-idf query over
    # terms that will always MATCH zero rows.
    assert lexical.dedup_match_expr(conn, "zephyr wombat quokka", n=24) == ""


def test_dedup_match_expr_caps_at_n_and_never_emits_a_bare_operator(tmp_path):
    # and/or/not/near placed first so they always survive the n=24 cap
    # regardless of tie-break order - this test must exercise their quoting.
    body = "and or not near " + " ".join(f"term{i}" for i in range(30))
    _write_concept(tmp_path, "seed", "Seed", body)
    conn = _lexical_conn(tmp_path)

    expr = lexical.dedup_match_expr(conn, body, n=24)

    parts = expr.split(" OR ")
    assert len(parts) <= 24
    assert all(p.startswith('"') and p.endswith('"') for p in parts)
    # Every FTS5-operator-shaped word (and/or/not/near) is quoted wherever it
    # appears, so the query string can never be parsed as an operator.
    for op in ("and", "or", "not", "near"):
        assert f'"{op}"' in parts
    # and it is a syntactically valid MATCH query, not just quote-shaped
    conn.execute("SELECT slug FROM lexical WHERE lexical MATCH ?", (expr,)).fetchall()


def test_dedup_match_expr_clamps_n_outside_1_to_24(tmp_path):
    """D18 W1 fix cycle (gate finding 7): `n` is a bound this function exists
    to enforce, so an out-of-range caller value is corrected, not trusted -
    `n=100` still caps at 24; `n<=0` still emits at least 1 term rather than
    silently disabling the query."""
    body = " ".join(f"term{i}" for i in range(40))
    _write_concept(tmp_path, "seed", "Seed", body)
    conn = _lexical_conn(tmp_path)

    assert len(lexical.dedup_match_expr(conn, body, n=100).split(" OR ")) <= 24
    assert len(lexical.dedup_match_expr(conn, body, n=-1).split(" OR ")) == 1
    assert len(lexical.dedup_match_expr(conn, body, n=0).split(" OR ")) == 1


def test_dedup_match_expr_empty_body_is_empty_string(tmp_path):
    _write_concept(tmp_path, "seed", "Seed", "seed content")
    conn = _lexical_conn(tmp_path)
    assert lexical.dedup_match_expr(conn, "   ", n=24) == ""


# --------------------------------------------------------------------------
# S2 - lexical_containment / matched
# --------------------------------------------------------------------------


def test_lexical_containment_is_asymmetric():
    idf = lambda _t: 1.0
    a = frozenset({"alpha", "bravo", "charlie"})
    b = frozenset({"alpha", "bravo"})  # subset of a
    # b's tokens are fully inside a -> containment(b, a) = 1.0
    assert dedup.lexical_containment(b, a, idf) == pytest.approx(1.0)
    # a's tokens are only 2/3 covered by b -> containment(a, b) < 1.0
    assert dedup.lexical_containment(a, b, idf) == pytest.approx(2 / 3)


def test_lexical_containment_empty_candidate_is_zero():
    idf = lambda _t: 1.0
    assert dedup.lexical_containment(frozenset(), frozenset({"x"}), idf) == 0.0


def test_matched_ors_lexical_and_semantic_legs():
    idf = lambda _t: 1.0
    disjoint_c, disjoint_d = frozenset({"a"}), frozenset({"b"})
    # neither leg crosses its threshold -> not matched
    assert not dedup.matched(disjoint_c, disjoint_d, idf, 0.5)
    # semantic leg alone crosses -> matched, even with zero lexical overlap
    assert dedup.matched(disjoint_c, disjoint_d, idf, 0.5, semantic_cosine=0.9, sem_threshold=0.8)
    # semantic leg present but below its own threshold -> still not matched
    assert not dedup.matched(disjoint_c, disjoint_d, idf, 0.5, semantic_cosine=0.5, sem_threshold=0.8)
    # S2 ships the semantic leg as a None-disabled seam: absent semantic
    # score never raises a spurious match on its own
    assert not dedup.matched(disjoint_c, disjoint_d, idf, 0.5, semantic_cosine=None, sem_threshold=0.8)


# --------------------------------------------------------------------------
# S2 - coverage mechanics on hand-built claim sets (S4.9's proof rows)
# --------------------------------------------------------------------------


def test_coverage_verbatim_subset_is_1000():
    idf = dedup.idf_from_corpus([["alpha", "bravo", "charlie"], ["delta", "echo", "foxtrot"]])
    verbatim = "Alpha bravo charlie appears in the card verbatim right here."
    filler = "Delta echo foxtrot is unrelated filler content in this card."
    candidate_claims = dedup.build_claims([verbatim], idf)
    card_claims = dedup.build_claims([verbatim, filler], idf)

    cov_candidate = dedup.coverage_of_candidate(candidate_claims, card_claims, idf, 0.6)
    assert cov_candidate == pytest.approx(1.0)


def test_coverage_disjoint_is_0000():
    idf = dedup.idf_from_corpus(
        [claims.tokenize("Completely unrelated topic about zebra migration patterns in savanna.")]
    )
    d1 = "Completely unrelated topic about zebra migration patterns in savanna."
    d2 = "Totally different subject regarding quarterly tax filing procedures."
    idf = dedup.idf_from_corpus([claims.tokenize(d1), claims.tokenize(d2)])
    candidate_claims = dedup.build_claims([d1], idf)
    card_claims = dedup.build_claims([d2], idf)

    assert dedup.coverage_of_candidate(candidate_claims, card_claims, idf, 0.6) == pytest.approx(0.0)
    assert dedup.coverage_of_card(candidate_claims, card_claims, idf, 0.6) == pytest.approx(0.0)


def test_coverage_composite_union_1000_best_single_in_range():
    half_a = "The bakery orders fresh flour and yeast every single morning without fail."
    half_b = "The server restarts the database connection pool after every failed deploy."
    idf = dedup.idf_from_corpus([claims.tokenize(half_a), claims.tokenize(half_b)])
    candidate_claims = dedup.build_claims([half_a, half_b], idf)
    card_a_claims = dedup.build_claims([half_a], idf)
    card_b_claims = dedup.build_claims([half_b], idf)

    best_single = max(
        dedup.coverage_of_candidate(candidate_claims, card_a_claims, idf, 0.6),
        dedup.coverage_of_candidate(candidate_claims, card_b_claims, idf, 0.6),
    )
    assert 0.5 <= best_single <= 0.9

    union = dedup.greedy_union_cover(
        candidate_claims, [("card-a", card_a_claims), ("card-b", card_b_claims)], idf, 0.6, m=5
    )
    assert union.coverage_union == pytest.approx(1.0)
    assert set(union.member_slugs) == {"card-a", "card-b"}
    # cumulative curve is monotonically non-decreasing and ends at the total
    assert [step.cumulative_coverage for step in union.curve] == sorted(
        step.cumulative_coverage for step in union.curve
    )


def test_greedy_union_cover_caps_at_m_and_stops_on_zero_gain():
    text = "The onboarding flow validates every new account before activation today."
    idf = dedup.idf_from_corpus([claims.tokenize(text)])
    candidate_claims = dedup.build_claims([text], idf)
    matching_card = dedup.build_claims([text], idf)
    # six identical-content candidate cards: after the first pick, every
    # further pick has zero marginal gain, so greedy must stop early.
    cards = [(f"card-{i}", matching_card) for i in range(6)]

    union = dedup.greedy_union_cover(candidate_claims, cards, idf, 0.6, m=5)
    assert len(union.member_slugs) == 1
    assert union.coverage_union == pytest.approx(1.0)


def test_idf_mass_weighting_changes_coverage_vs_plain_counts():
    """S4.9: IDF-mass weighting must demonstrably change the answer vs plain
    claim counts - the design's own motivating example (three filler claims
    inflate plain-count coverage while the one substantive claim is missed)."""
    substantive = dedup.Claim(text="substantive", tokens=frozenset({"substantive"}), weight=30.0)
    fillers = [
        dedup.Claim(text=f"filler{i}", tokens=frozenset({f"filler{i}"}), weight=1.0) for i in range(3)
    ]
    candidate_claims = [substantive, *fillers]
    # card covers all 3 filler claims but not the substantive one
    card_claims = [dedup.Claim(text=f"c{i}", tokens=frozenset({f"filler{i}"}), weight=1.0) for i in range(3)]

    idf = lambda _t: 1.0  # matched() re-derives containment fresh per token pair; irrelevant here
    idf_mass_coverage = dedup.coverage_of_candidate(candidate_claims, card_claims, idf, 0.99)

    plain_claims = [dedup.Claim(text=c.text, tokens=c.tokens, weight=1.0) for c in candidate_claims]
    plain_count_coverage = dedup.coverage_of_candidate(plain_claims, card_claims, idf, 0.99)

    assert plain_count_coverage == pytest.approx(0.75)  # 3 of 4 claims "look" covered
    assert idf_mass_coverage < 0.20  # the missing substantive claim dominates the true picture
    assert idf_mass_coverage != pytest.approx(plain_count_coverage)


# --------------------------------------------------------------------------
# S2 - idf_from_corpus is CARD-GRAIN ONLY (DECISION_LOG D18-W1 amendment,
# 2026-09-02; gate finding 6)
# --------------------------------------------------------------------------


def test_idf_from_corpus_is_card_grain_reproduces_common_rare_0500():
    """The gate's exact two-card reproduction: 'common' (in card 1's ten
    claims) and 'rare' (in card 1's one claim) co-occur in the SAME single
    card, so card-grain df is 1/2 cards for BOTH terms - identical to what
    `fts5vocab`'s per-row (per-card) document frequency would give. A
    candidate with one equally-weighted 'common' claim and one 'rare' claim,
    matched only on 'common', must cover exactly the design-weighted 0.500 -
    proving card-grain in-memory IDF reproduces the ratified metric."""
    card_1_tokens = {"common", "rare"}  # both terms appear somewhere in this one card
    card_2_tokens = {"unrelated"}
    idf = dedup.idf_from_corpus([card_1_tokens, card_2_tokens])
    assert idf("common") == pytest.approx(idf("rare"))  # both df=1 of 2 cards

    candidate_claims = [
        dedup.Claim(text="common claim", tokens=frozenset({"common"}), weight=idf("common")),
        dedup.Claim(text="rare claim", tokens=frozenset({"rare"}), weight=idf("rare")),
    ]
    matched_card_claims = [
        dedup.Claim(text="card common", tokens=frozenset({"common"}), weight=idf("common"))
    ]
    cc = dedup.coverage_of_candidate(candidate_claims, matched_card_claims, idf, 0.99)
    assert cc == pytest.approx(0.5)

    # Illustrative only - NOT a production path (per-claim grain is banned
    # from this module): treating each of card 1's 11 claims as its own
    # "document" makes 'common' (df=10/12) far less informative than 'rare'
    # (df=1/12), giving an UNRATIFIED, materially different answer (~0.289,
    # matching the gate's own reproduced number) purely from the grain
    # choice - this is exactly why grain must be fixed, not selectable.
    claim_grain_idf = dedup.idf_from_corpus([{"common"}] * 10 + [{"rare"}] + [{"unrelated"}])
    alt_candidate = [
        dedup.Claim(text="c", tokens=frozenset({"common"}), weight=claim_grain_idf("common")),
        dedup.Claim(text="r", tokens=frozenset({"rare"}), weight=claim_grain_idf("rare")),
    ]
    alt_cov = dedup.coverage_of_candidate(alt_candidate, matched_card_claims, claim_grain_idf, 0.99)
    assert alt_cov == pytest.approx(0.289, abs=0.001)
    assert alt_cov < 0.30
    assert alt_cov != pytest.approx(cc)


# --------------------------------------------------------------------------
# S2 - the `relation` table (S4.2), every cell
# --------------------------------------------------------------------------

LOW, HIGH = 0.35, 0.85


@pytest.mark.parametrize(
    "cc,cd,expected",
    [
        (1.00, 1.00, (dedup.EQUIVALENT, "skip")),
        # cc < 1.0: nonzero unmatched candidate claim mass - the label is
        # still "equivalent" per the coverage numbers, but D18 W1's fix cycle
        # (gate finding 2) forbids skip unless that mass is zero.
        (0.90, 0.90, (dedup.EQUIVALENT, "review")),
        (1.00, 0.50, (dedup.CANDIDATE_SUBSET, "skip")),
        (0.90, 0.50, (dedup.CANDIDATE_SUBSET, "review")),
        (0.50, 0.90, (dedup.CANDIDATE_SUPERSET, "update-existing")),
        (0.50, 0.50, (dedup.OVERLAPPING, "review")),
        (0.10, 0.10, (dedup.UNRELATED, "add")),
        # the mixed region S4.2's literal table leaves unstated (one side in
        # [low, high), the other below low) - judgment call, see dedup.relation's
        # docstring: resolved as overlapping/review, never unrelated/add.
        (0.50, 0.10, (dedup.OVERLAPPING, "review")),
        (0.10, 0.50, (dedup.OVERLAPPING, "review")),
    ],
)
def test_relation_table_every_cell(cc, cd, expected):
    assert dedup.relation(cc, cd, LOW, HIGH) == expected


def test_candidate_superset_never_maps_to_skip():
    for cc in (0.0, 0.2, 0.5, 0.84):
        rel, action = dedup.relation(cc, HIGH, LOW, HIGH)
        assert rel == dedup.CANDIDATE_SUPERSET
        assert action != "skip"
        assert action == "update-existing"


def test_equivalent_and_subset_never_skip_with_incomplete_candidate_mass():
    """D18 W1 fix cycle (gate finding 2): `cc >= coverage_high` alone is not
    a safe skip gate - only `cc >= 1.0` (zero unmatched candidate claim
    mass) is. Sweep the whole high band to prove no crack remains."""
    for cc in (0.85, 0.90, 0.95, 0.999):
        rel, action = dedup.relation(cc, 1.0, LOW, HIGH)
        assert rel == dedup.EQUIVALENT
        assert action == "review"
        rel, action = dedup.relation(cc, 0.50, LOW, HIGH)
        assert rel == dedup.CANDIDATE_SUBSET
        assert action == "review"
    for cc in (1.0,):
        assert dedup.relation(cc, 1.0, LOW, HIGH) == (dedup.EQUIVALENT, "skip")
        assert dedup.relation(cc, 0.50, LOW, HIGH) == (dedup.CANDIDATE_SUBSET, "skip")


def test_actual_claim_set_above_coverage_high_with_novel_mass_never_skips():
    """D18 W1 fix cycle (gate finding 2), the gate's exact reproduction
    pinned with a real claim set (not direct numeric arguments): a candidate
    = one claim fully matched (weight 9) plus one unmatched novel claim
    (weight 1), scored against a card containing only the matched claim.
    coverage_of_candidate = 0.9 clears coverage_high (0.85) while still
    discarding 10% of the candidate's claim mass if skipped - so the
    recommended action must never be `skip`."""
    idf = lambda _t: 1.0
    matched_tokens = frozenset(f"m{i}" for i in range(9))  # weight 9 under idf=1/token
    novel_tokens = frozenset({"novel"})  # weight 1
    candidate_claims = [
        dedup.Claim(text="matched claim", tokens=matched_tokens, weight=9.0),
        dedup.Claim(text="novel claim", tokens=novel_tokens, weight=1.0),
    ]
    card_claims = [dedup.Claim(text="card claim", tokens=matched_tokens, weight=9.0)]

    cc = dedup.coverage_of_candidate(candidate_claims, card_claims, idf, 0.99)
    cd = dedup.coverage_of_card(candidate_claims, card_claims, idf, 0.99)
    assert cc == pytest.approx(0.9)
    assert cd == pytest.approx(1.0)

    _, action = dedup.relation(cc, cd, LOW, HIGH)
    assert action != "skip"


def test_relation_on_real_claim_scenarios():
    """Cross-check relation() against coverage numbers derived from actual
    claim sets, not just direct numeric arguments."""
    matching = "The onboarding flow validates every new account before activation."
    extra = "The bakery orders fresh flour and yeast every single morning without fail."
    idf = dedup.idf_from_corpus([claims.tokenize(matching), claims.tokenize(extra)])
    superset_candidate = dedup.build_claims([matching, extra], idf)
    subset_card = dedup.build_claims([matching], idf)

    cc = dedup.coverage_of_candidate(superset_candidate, subset_card, idf, 0.6)
    cd = dedup.coverage_of_card(superset_candidate, subset_card, idf, 0.6)
    assert dedup.relation(cc, cd, LOW, HIGH) == (dedup.CANDIDATE_SUPERSET, "update-existing")

    # roles reversed -> candidate-subset
    cc2 = dedup.coverage_of_candidate(subset_card, superset_candidate, idf, 0.6)
    cd2 = dedup.coverage_of_card(subset_card, superset_candidate, idf, 0.6)
    assert dedup.relation(cc2, cd2, LOW, HIGH) == (dedup.CANDIDATE_SUBSET, "skip")

    shared = "The system uses a shared configuration file for every incoming request."
    cand_only = "The bakery orders fresh flour and yeast every single morning without fail."
    card_only = "The server restarts the database connection pool after every failed deploy."
    idf3 = dedup.idf_from_corpus(
        [claims.tokenize(shared), claims.tokenize(cand_only), claims.tokenize(card_only)]
    )
    overlap_candidate = dedup.build_claims([shared, cand_only], idf3)
    overlap_card = dedup.build_claims([shared, card_only], idf3)
    cc3 = dedup.coverage_of_candidate(overlap_candidate, overlap_card, idf3, 0.6)
    cd3 = dedup.coverage_of_card(overlap_candidate, overlap_card, idf3, 0.6)
    assert dedup.relation(cc3, cd3, LOW, HIGH) == (dedup.OVERLAPPING, "review")


# --------------------------------------------------------------------------
# S2 - config seams: fail-fast validation (D17's exit-1 pattern via DedupError)
# --------------------------------------------------------------------------

_ALL_DEDUP_ENV_VARS = (
    "MEM_DEDUP_LOW", "MEM_DEDUP_HIGH", "MEM_DEDUP_THRESHOLD",
    "MEM_DEDUP_COVERAGE_LOW", "MEM_DEDUP_COVERAGE_HIGH",
    "MEM_DEDUP_UNION_LOW", "MEM_DEDUP_UNION_M",
    "MEM_DEDUP_CLAIM_LEX", "MEM_DEDUP_CLAIM_SEM",
    "MEM_DEDUP_DEEP_K", "MEM_DEDUP_CHUNKS", "MEM_DEDUP_CHUNK_SKIP_CHARS",
    "MEM_DEDUP_LOG", "MEM_DEDUP_LOG_TITLES",
)


@pytest.fixture
def clean_dedup_env(monkeypatch):
    for name in _ALL_DEDUP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_load_config_defaults_when_everything_unset(clean_dedup_env):
    cfg = dedup.load_config()
    assert cfg.dedup_low == config.DEFAULT_DEDUP_LOW
    assert cfg.dedup_high is None
    assert cfg.coverage_low is None
    assert cfg.coverage_high is None
    assert cfg.union_low is None
    assert cfg.union_m == config.DEFAULT_DEDUP_UNION_M
    assert cfg.claim_lex == config.DEFAULT_DEDUP_CLAIM_LEX
    assert cfg.claim_sem is None
    assert cfg.deep_k == config.DEFAULT_DEDUP_DEEP_K
    assert cfg.chunks is False
    assert cfg.chunk_skip_chars == config.DEFAULT_DEDUP_CHUNK_SKIP_CHARS
    assert cfg.log is True
    assert cfg.log_titles is True


def test_load_config_dedup_chunks_is_a_strict_boolean(clean_dedup_env):
    clean_dedup_env.setenv("MEM_DEDUP_CHUNKS", "true")
    assert dedup.load_config().chunks is True
    clean_dedup_env.setenv("MEM_DEDUP_CHUNKS", "0")
    assert dedup.load_config().chunks is False


@pytest.mark.parametrize(
    "env",
    [
        {"MEM_DEDUP_LOW": "0.6", "MEM_DEDUP_HIGH": "0.5"},  # high <= low
        {"MEM_DEDUP_LOW": "0.6", "MEM_DEDUP_HIGH": "0.6"},  # high == low (not strictly greater)
        {"MEM_DEDUP_LOW": "inf"},  # non-finite
        {"MEM_DEDUP_HIGH": "nan", "MEM_DEDUP_LOW": "0.5"},  # non-finite high
        # gate finding 5's four reproduced cases: MEM_DEDUP_LOW/HIGH are
        # document-cosine values and S4.4 says every one is in [0,1] -
        # reversed-pair and non-finite checks alone missed these.
        {"MEM_DEDUP_LOW": "-0.1"},  # out of [0,1]
        {"MEM_DEDUP_LOW": "1.1"},  # out of [0,1]
        {"MEM_DEDUP_HIGH": "1.1"},  # out of [0,1] (clears the low<high check, so range alone catches it)
        {"MEM_DEDUP_CHUNKS": "maybe"},  # invalid boolean
        {"MEM_DEDUP_COVERAGE_LOW": "0.5", "MEM_DEDUP_COVERAGE_HIGH": "0.5"},  # high <= low
        {"MEM_DEDUP_COVERAGE_LOW": "0.9", "MEM_DEDUP_COVERAGE_HIGH": "0.3"},  # high < low
        {"MEM_DEDUP_COVERAGE_LOW": "1.5"},  # out of [0,1]
        {"MEM_DEDUP_COVERAGE_LOW": "-0.1"},  # out of [0,1]
        {"MEM_DEDUP_COVERAGE_HIGH": "nan"},  # non-finite
        {"MEM_DEDUP_UNION_LOW": "1.2"},  # out of [0,1]
        {"MEM_DEDUP_UNION_M": "0"},  # must be >= 1
        {"MEM_DEDUP_UNION_M": "-1"},
        {"MEM_DEDUP_DEEP_K": "0"},  # must be >= 1
        {"MEM_DEDUP_CLAIM_LEX": "0"},  # must be in (0, 1]
        {"MEM_DEDUP_CLAIM_LEX": "1.5"},
        {"MEM_DEDUP_CLAIM_SEM": "0"},  # must be in (0, 1] when set
        {"MEM_DEDUP_CLAIM_SEM": "-0.5"},
        {"MEM_DEDUP_CHUNK_SKIP_CHARS": "0"},  # must be >= 1
        {"MEM_DEDUP_LOG": "maybe"},  # invalid boolean
        {"MEM_DEDUP_LOG_TITLES": "sort-of"},
    ],
)
def test_load_config_refuses_every_invalid_value(clean_dedup_env, env):
    for name, value in env.items():
        clean_dedup_env.setenv(name, value)
    with pytest.raises(dedup.DedupError):
        dedup.load_config()


def test_load_config_accepts_the_recommended_calibrated_values(clean_dedup_env):
    clean_dedup_env.setenv("MEM_DEDUP_COVERAGE_LOW", "0.35")
    clean_dedup_env.setenv("MEM_DEDUP_COVERAGE_HIGH", "0.85")
    clean_dedup_env.setenv("MEM_DEDUP_UNION_LOW", "0.55")
    cfg = dedup.load_config()
    assert cfg.coverage_low == 0.35
    assert cfg.coverage_high == 0.85
    assert cfg.union_low == 0.55
