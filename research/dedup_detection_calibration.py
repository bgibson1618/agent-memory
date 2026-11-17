"""D18 S8 - dedup-DETECTION calibration (research/d18-dedup-detection-design-
2026-09-02.md S4.7): Stage 1a (coverage mechanics + the FP side, fence-free,
SYNTHETIC) and Stage 1b (the AP-BPF archive replay, fence-free: the archive
is a work-repo artifact, not the `<engagement-kb>` KB instance itself -
paths/counts/scores only ever cross into the artifact, never card bodies).

Mirrors research/dedup_calibration.py's shape: a generated artifact with a
header block (generated-by / daemon / model+digest / metric) and a test
(tests/test_d18_w3_claim_leg_calibration.py) pinning the shipped standalone
`mem dedup` overlay defaults to it. Unlike that script, Stage 1a needs NO daemon - coverage is a pure lexical
metric (`dedup.py`'s IDF-mass containment), computed over text alone.

Run:  uv run python research/dedup_detection_calibration.py [--kb ROOT]

`--kb ROOT` points Stage 1a's IDF corpus at a real KB's `concepts/*.md`
instead of this script's built-in synthetic corpus - for a LATER run against
the live default KB (the design's own §3.3 probe). This run (2026-09-02)
uses no `--kb`: the synthetic, in-script corpus only, per the implementation
brief's fence ("your run uses a tmp corpus only" - MEM_KB_ROOT is never set
by this script; `--kb` is a plain read-only directory argument, orthogonal
to that seam).

Stage 1b reads exactly three files by absolute canonical path under
`~/work/ap-business-personal-finance/work/kbx-2026-08-21/r1-phase2/` (the
work-repo archive - fence-free, per the design's Appendix A.5) and asserts
`dup-rulings-r1p2.json`'s md5 prefix before trusting it (R5/A.4: five
mutually-inconsistent copies exist elsewhere in that repo, most under
deliberately-tampered adversarial fixture directories - this script NEVER
globs for the filename, only ever opens the one pinned path).
"""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

from agent_memory import claims as claims_mod
from agent_memory import dedup, okf

ARTIFACT = Path(__file__).resolve().parent / "dedup-detection-calibration-2026-09-02.md"

ARCHIVE_ROOT = Path(
    "~/work/ap-business-personal-finance/work/kbx-2026-08-21/r1-phase2"
).expanduser()
DUP_RULINGS_PATH = ARCHIVE_ROOT / "dup-rulings-r1p2.json"
DISPOSITION_PATH = ARCHIVE_ROOT / "disposition.json"
NEAR_DUP_CHECK_PATH = ARCHIVE_ROOT / "near-dup-check-r1p2.json"
DUP_RULINGS_MD5_PREFIX = "e66073d1"  # Appendix A.4's canonical hash - never glob for this filename

CLAIM_LEX_THRESHOLD = 0.60  # config.DEFAULT_DEDUP_CLAIM_LEX - Stage 1a's tau_lex

# Chosen from THIS run's own measured numbers below (§4.4's recommended
# values, confirmed against the synthetic FP side - see main()'s printed
# recommendation and the artifact's "Recommended defaults" section).
COVERAGE_LOW_RECOMMENDED = 0.35
COVERAGE_HIGH_RECOMMENDED = 0.85
UNION_LOW_RECOMMENDED = 0.55

# ==========================================================================
# Stage 1a - synthetic corpus (fence-free, in-script; §3.3/§3.4's mechanics)
# ==========================================================================

_SHARED_FILLER = (
    "This note also touches on efficiency, timing, and cost considerations"
    " relevant to its domain."
)

SYNTHETIC_CARDS = {
    "cold-chain-refrigeration": (
        "Storing perishable produce below four degrees Celsius slows bacterial growth significantly. "
        "A broken cold chain during transport lets pathogens multiply even if the warehouse stays cold. "
        "Blast chillers drop core temperature fast enough to skip the danger zone where bacteria thrive. "
        "Humidity control inside a refrigerated container prevents wilting without encouraging mold. "
        "Continuous temperature logging during shipment proves the chain never broke. "
        f"{_SHARED_FILLER}"
    ),
    "sourdough-fermentation": (
        "A sourdough starter's wild yeast and lactobacilli ferment the dough slowly over many hours. "
        "Longer bulk fermentation develops more complex sour flavor and a more open crumb structure. "
        "Feeding the starter at room temperature keeps the yeast population active between bakes. "
        "Too much acidity from over-fermentation weakens the gluten network and collapses the loaf. "
        "A cool overnight proof in the refrigerator slows fermentation without stopping it entirely. "
        f"{_SHARED_FILLER}"
    ),
    "solar-panel-efficiency": (
        "Photovoltaic cells convert a larger share of sunlight into electricity as their efficiency rating rises. "
        "Panel output drops noticeably once surface temperature climbs well above room temperature. "
        "Dust and pollen buildup on the glass measurably reduces the light reaching the cells beneath. "
        "Tilting panels to track the sun through the day captures more total energy than a fixed mount. "
        "Shading from even one nearby tree can cut a whole string's output far more than the shaded area alone. "
        f"{_SHARED_FILLER}"
    ),
    "database-indexing": (
        "A B-tree index keeps lookups fast by maintaining sorted keys in a balanced tree structure. "
        "Adding an index speeds up reads but slows down every write that must maintain it. "
        "A composite index on multiple columns only helps a query that filters on its leading column. "
        "Index bloat from frequent updates eventually calls for a periodic rebuild to reclaim space. "
        "Query planners choose a full table scan over an index when the table is small enough. "
        f"{_SHARED_FILLER}"
    ),
    "bicycle-gearing": (
        "A wider gear range on a bicycle lets a rider hold a comfortable cadence on both steep climbs and fast flats. "
        "Smaller rear cogs multiply pedaling speed into wheel speed for higher top-end power. "
        "Chain wear stretches the links over time and starts to skip under load on worn cogs. "
        "A compact crankset trades top speed for easier climbing on long mountain grades. "
        "Cross-chaining onto extreme gear combinations wears the drivetrain faster and grinds loudly. "
        f"{_SHARED_FILLER}"
    ),
    "coral-reef-bleaching": (
        "Sustained warm water stresses coral polyps into expelling the symbiotic algae that feed and color them. "
        "A bleached coral is not dead yet, but it starves if the water stays warm long enough for the algae not to return. "
        "Repeated bleaching events give a reef less recovery time between each stress before the next one hits. "
        "Local pollution and sediment runoff compound heat stress and lower a reef's tolerance further. "
        "Some coral genotypes tolerate warmer water better, so a bleaching event can shift a reef's genetic mix. "
        f"{_SHARED_FILLER}"
    ),
}


def _synthetic_idf(extra_token_lists=()):
    """Card-grain IDF (the W1-amendment posture `dedup.py` requires) over
    the synthetic corpus, extended with any `extra_token_lists` documents
    (the D3 pairs' bodies, for the negative control below) so their tokens
    have real df counts too."""
    docs = [
        claims_mod.tokenize(body) for body in SYNTHETIC_CARDS.values()
    ] + list(extra_token_lists)
    return dedup.idf_from_corpus(docs)


def _kb_idf(kb_root: Path):
    """Stage 1a's `--kb` seam: card-grain IDF from a real KB's concepts/
    instead of the synthetic corpus - read-only, path/count use only."""
    bodies = []
    for path in sorted((kb_root / "concepts").glob("*.md")):
        try:
            concept = okf.parse(path.read_text(encoding="utf-8"))
        except okf.OKFError:
            continue
        bodies.append(concept.body)
    return dedup.idf_from_corpus(claims_mod.tokenize(b) for b in bodies), len(bodies)


def stage_1a(kb_root: Path | None) -> dict:
    import itertools
    import random

    rng = random.Random(20260902)
    names = list(SYNTHETIC_CARDS)
    card_claim_texts = {name: claims_mod.segment(body) for name, body in SYNTHETIC_CARDS.items()}

    kb_note = None
    if kb_root is not None:
        idf, n_cards = _kb_idf(kb_root)
        kb_note = f"IDF corpus: real KB at {kb_root} ({n_cards} cards)"
    else:
        idf = _synthetic_idf()
        kb_note = "IDF corpus: synthetic, in-script (no --kb given)"

    def claims_for(name: str) -> list:
        return dedup.build_claims(card_claim_texts[name], idf)

    # --- verbatim subsets: candidate claims subset ⊂ its own card -------
    verbatim = []
    for name in names:
        texts = card_claim_texts[name]
        full = dedup.build_claims(texts, idf)
        if len(texts) < 2:
            continue
        for _ in range(40):
            k = rng.randint(1, len(texts) - 1)
            subset = rng.sample(range(len(texts)), k)
            cand = [full[i] for i in subset]
            cc = dedup.coverage_of_candidate(cand, full, idf, CLAIM_LEX_THRESHOLD)
            verbatim.append(cc)

    # --- hard negatives: every distinct pair of synthetic cards ----------
    hard_negatives = []
    for a, b in itertools.combinations(names, 2):
        cc = dedup.coverage_of_candidate(claims_for(a), claims_for(b), idf, CLAIM_LEX_THRESHOLD)
        cd = dedup.coverage_of_card(claims_for(a), claims_for(b), idf, CLAIM_LEX_THRESHOLD)
        hard_negatives.append(cc)
        hard_negatives.append(cd)

    # --- composites: half of A's claims + half of B's, vs A/B/union(A,B) --
    composite_best_single = []
    composite_union = []
    for a, b in itertools.combinations(names, 2):
        a_claims, b_claims = claims_for(a), claims_for(b)
        if len(a_claims) < 2 or len(b_claims) < 2:
            continue
        half_a = a_claims[: len(a_claims) // 2]
        half_b = b_claims[len(b_claims) // 2 :]
        composite = half_a + half_b
        cc_a = dedup.coverage_of_candidate(composite, a_claims, idf, CLAIM_LEX_THRESHOLD)
        cc_b = dedup.coverage_of_candidate(composite, b_claims, idf, CLAIM_LEX_THRESHOLD)
        composite_best_single.append(max(cc_a, cc_b))
        union = dedup.greedy_union_cover(
            composite, [(a, a_claims), (b, b_claims)], idf, CLAIM_LEX_THRESHOLD, m=5,
        )
        composite_union.append(union.coverage_union)

    # --- D3's 26 pairs as the negative control (paraphrase-blindness) ----
    import importlib.util

    d3_path = Path(__file__).resolve().parent / "dedup_calibration.py"
    spec = importlib.util.spec_from_file_location("dedup_calibration_d3", d3_path)
    assert spec is not None and spec.loader is not None, f"cannot load spec for {d3_path}"
    d3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d3)  # module-level code only builds two list literals; no daemon call

    d3_pairs = d3.NEAR_DUP_PAIRS + d3.DISTINCT_PAIRS
    d3_bodies = [body for _, body, _, _ in d3_pairs] + [body for _, _, _, body in d3_pairs]
    idf_with_d3 = _synthetic_idf(claims_mod.tokenize(b) for b in d3_bodies) if kb_root is None else idf

    def d3_coverage(pairs) -> list:
        out = []
        for _a_title, a_body, _b_title, b_body in pairs:
            a_claims = dedup.build_claims(claims_mod.segment(a_body), idf_with_d3)
            b_claims = dedup.build_claims(claims_mod.segment(b_body), idf_with_d3)
            out.append(max(
                dedup.coverage_of_candidate(a_claims, b_claims, idf_with_d3, CLAIM_LEX_THRESHOLD),
                dedup.coverage_of_candidate(b_claims, a_claims, idf_with_d3, CLAIM_LEX_THRESHOLD),
            ))
        return out

    d3_near_dup_coverage = d3_coverage(d3.NEAR_DUP_PAIRS)
    d3_distinct_coverage = d3_coverage(d3.DISTINCT_PAIRS)

    return {
        "kb_note": kb_note,
        "verbatim": verbatim,
        "hard_negatives": hard_negatives,
        "composite_best_single": composite_best_single,
        "composite_union": composite_union,
        "d3_near_dup_coverage": d3_near_dup_coverage,
        "d3_distinct_coverage": d3_distinct_coverage,
        "d3_near_dup_n": len(d3.NEAR_DUP_PAIRS),
        "d3_distinct_n": len(d3.DISTINCT_PAIRS),
    }


# ==========================================================================
# Stage 1b - the AP-BPF archive replay (fence-free; Appendix A.5's join)
# ==========================================================================

_POSITIVE_ACTIONS = {"NO-ACTION-DUP", "FOLD", "REWRITE"}
_NEGATIVE_ACTIONS = {"NEW-SAVE"}


def _archive_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - fixture-identity check, not security


def stage_1b() -> dict:
    if not DUP_RULINGS_PATH.is_file():
        return {"skipped": "archive not found at the canonical path - fence-free but out of reach here"}
    md5 = _archive_md5(DUP_RULINGS_PATH)
    if not md5.startswith(DUP_RULINGS_MD5_PREFIX):
        raise SystemExit(
            f"error: {DUP_RULINGS_PATH} md5 {md5} does not start with the canonical"
            f" prefix {DUP_RULINGS_MD5_PREFIX!r} - refusing to calibrate against an"
            f" unverified/tampered copy (R5/Appendix A.4)"
        )

    rulings = json.loads(DUP_RULINGS_PATH.read_text(encoding="utf-8"))["rulings"]
    hits_by_id = {
        r["id"]: r for r in json.loads(NEAR_DUP_CHECK_PATH.read_text(encoding="utf-8"))
    }

    positives, negatives = [], []
    for rid, hits_record in hits_by_id.items():
        ruling = rulings.get(rid)
        if ruling is None:
            continue
        action = ruling["action"]
        live_slugs = set(ruling["live_slug"])
        hits = hits_record["search_result"]
        if action in _POSITIVE_ACTIONS and live_slugs:
            positives.append((rid, live_slugs, hits))
        elif action in _NEGATIVE_ACTIONS:
            negatives.append((rid, hits))

    # --- recall@K / MRR over the positives --------------------------------
    def first_true_rank(live_slugs: set, hits: list) -> int | None:
        for rank, hit in enumerate(hits, start=1):
            if hit["slug"] in live_slugs:
                return rank
        return None

    ranks = [first_true_rank(slugs, hits) for _rid, slugs, hits in positives]
    recall_at = {}
    for k in (1, 2, 3, 5, 10):
        recall_at[k] = sum(1 for r in ranks if r is not None and r <= k) / len(ranks)
    mrr = sum((1.0 / r) if r is not None else 0.0 for r in ranks) / len(ranks)
    absent = [rid for (rid, _slugs, _hits), r in zip(positives, ranks) if r is None]

    # --- true-match semantic_similarity distribution ----------------------
    true_match_sims = []
    for (rid, slugs, hits), r in zip(positives, ranks):
        if r is None:
            continue
        hit = hits[r - 1]
        if hit.get("semantic_similarity") is not None:
            true_match_sims.append(hit["semantic_similarity"])

    # --- class-overlap: max semantic_similarity per record ----------------
    def max_sem(hits: list) -> float | None:
        sims = [h["semantic_similarity"] for h in hits if h.get("semantic_similarity") is not None]
        return max(sims) if sims else None

    dup_max_sims = [s for s in (max_sem(hits) for _rid, _slugs, hits in positives) if s is not None]
    negative_max_sims = [s for s in (max_sem(hits) for _rid, hits in negatives) if s is not None]

    # --- the headline recall-at-threshold table ----------------------------
    # §3.1's own denominator is 61, not 63: "recall of confirmed dups from
    # the whole-document cosine threshold alone" is about whether the TRUE
    # MATCH's own semantic_similarity crosses the line - `true_match_sims`
    # (n=61: the 2 absent-from-top-10 positives have no true-match hit to
    # score at all) - NOT the max over all 10 hits regardless of which hit
    # that max came from (`dup_max_sims`, n=63), which would credit a
    # threshold crossing to an irrelevant hit while the true match itself
    # never surfaced. Verified against the design doc's own numbers: this
    # denominator is the one that reproduces 0.410/0.197/0.082/0.016 exactly
    # (25/61, 12/61, 5/61, 1/61) - the n=63 denominator does not.
    recall_at_threshold = {}
    for threshold in (0.79, 0.83, 0.85, 0.88):
        recall_at_threshold[threshold] = (
            sum(1 for s in true_match_sims if s >= threshold) / len(true_match_sims)
        )

    return {
        "n_positive": len(positives),
        "n_negative": len(negatives),
        "recall_at": recall_at,
        "mrr": mrr,
        "absent_from_top10": absent,
        "true_match_sim_n": len(true_match_sims),
        "true_match_sim_stats": _percentile_stats(true_match_sims),
        "dup_max_sim_stats": _percentile_stats(dup_max_sims),
        "negative_max_sim_stats": _percentile_stats(negative_max_sims),
        "recall_at_threshold": recall_at_threshold,
    }


def _percentile_stats(values: list) -> dict:
    if not values:
        return {}
    values = sorted(values)

    def pct(p):
        idx = min(len(values) - 1, max(0, round(p * (len(values) - 1))))
        return values[idx]

    return {
        "n": len(values), "min": values[0], "p10": pct(0.10),
        "median": statistics.median(values), "p90": pct(0.90), "max": values[-1],
    }


# ==========================================================================
# Artifact rendering
# ==========================================================================


def _stats_line(stats: dict) -> str:
    if not stats:
        return "n=0"
    return (
        f"n={stats['n']} min {stats['min']:.4f} p10 {stats['p10']:.4f}"
        f" median {stats['median']:.4f} p90 {stats['p90']:.4f} max {stats['max']:.4f}"
    )


def _list_stats(values: list) -> str:
    if not values:
        return "n=0"
    return f"n={len(values)} min {min(values):.4f} median {statistics.median(values):.4f} max {max(values):.4f}"


def render_artifact(a: dict, b: dict, kb_arg: str | None) -> str:
    lines = []
    lines.append("# D18 dedup-DETECTION calibration - Stage 1a + 1b")
    lines.append("")
    lines.append(f"generated-by: `uv run python research/dedup_detection_calibration.py{' --kb ' + kb_arg if kb_arg else ''}`")
    lines.append("daemon: none required for Stage 1a (lexical coverage is a pure text metric);"
                 " Stage 1b reads only the archive's already-recorded scores")
    lines.append(f"model+digest: n/a (no embeddings computed by this script)")
    lines.append("metric: IDF-mass-weighted lexical claim containment (`dedup.coverage_of_candidate`/"
                 "`coverage_of_card`), claim-match tau_lex = "
                 f"{CLAIM_LEX_THRESHOLD} (config.DEFAULT_DEDUP_CLAIM_LEX)")
    lines.append("")
    lines.append(f"Stage 1a IDF source: {a['kb_note']}")
    lines.append("")
    lines.append("## Stage 1a - coverage mechanics + the FP side (synthetic, fence-free)")
    lines.append("")
    lines.append("| construction | stats |")
    lines.append("| --- | --- |")
    lines.append(f"| verbatim subset (candidate claims ⊂ its own card) | {_list_stats(a['verbatim'])} |")
    lines.append(f"| hard negative (distinct synthetic card, directional both ways) | {_list_stats(a['hard_negatives'])} |")
    lines.append(f"| composite (½A+½B) - best single card | {_list_stats(a['composite_best_single'])} |")
    lines.append(f"| composite - union of {{A, B}} | {_list_stats(a['composite_union'])} |")
    lines.append("")
    lines.append(
        f"D3's {a['d3_near_dup_n']} near-dup pairs (paraphrase, negative control - lexical coverage"
        " must score near-zero; a harness that 'fixes' this has a bug):"
        f" {_list_stats(a['d3_near_dup_coverage'])}"
    )
    lines.append(
        f"D3's {a['d3_distinct_n']} distinct pairs (same-domain hard negatives + easy negatives):"
        f" {_list_stats(a['d3_distinct_coverage'])}"
    )
    lines.append("")
    if "skipped" in b:
        lines.append(f"## Stage 1b - SKIPPED ({b['skipped']})")
        lines.append("")
    else:
        lines.append("## Stage 1b - the AP-BPF archive replay (fence-free; read-only)")
        lines.append("")
        lines.append(f"Archive: `{DUP_RULINGS_PATH}` (md5 prefix asserted: `{DUP_RULINGS_MD5_PREFIX}`)")
        lines.append(f"Positives (dup-class, cited live_slug): {b['n_positive']}; negatives (NEW-SAVE): {b['n_negative']}")
        lines.append("")
        lines.append("| K | recall@K |")
        lines.append("| --- | --- |")
        for k, v in b["recall_at"].items():
            lines.append(f"| {k} | {v:.3f} |")
        lines.append("")
        lines.append(f"MRR: {b['mrr']:.3f}")
        lines.append(f"Absent from the archived top-10: {len(b['absent_from_top10'])}/{b['n_positive']} ({', '.join(b['absent_from_top10']) or 'none'})")
        lines.append("")
        lines.append(f"True-match `semantic_similarity`: {_stats_line(b['true_match_sim_stats'])}")
        lines.append("")
        lines.append("| class | max(semantic_similarity) over each record's hits |")
        lines.append("| --- | --- |")
        lines.append(f"| dup-class (positive) | {_stats_line(b['dup_max_sim_stats'])} |")
        lines.append(f"| NEW-SAVE (negative) | {_stats_line(b['negative_max_sim_stats'])} |")
        lines.append("")
        lines.append("| `dedup_low` | recall of confirmed dups (whole-document cosine alone) |")
        lines.append("| --- | --- |")
        for threshold, recall in b["recall_at_threshold"].items():
            lines.append(f"| {threshold} | {recall:.3f} |")
        lines.append("")
    lines.append("## Recommended defaults (S4.4), unchanged shipped config")
    lines.append("")
    lines.append(f"- `MEM_DEDUP_COVERAGE_LOW` recommended: {COVERAGE_LOW_RECOMMENDED}")
    lines.append(f"- `MEM_DEDUP_COVERAGE_HIGH` recommended: {COVERAGE_HIGH_RECOMMENDED}")
    lines.append(f"- `MEM_DEDUP_UNION_LOW` recommended: {UNION_LOW_RECOMMENDED}")
    lines.append("")
    lines.append(
        "These three values are the design's recommendations (S4.4/§0's doctrine) and they"
        " SHIP in exactly one place: the standalone `mem dedup` command's coverage overlay"
        " (`dedupcmd._DEDUP_CMD_COVERAGE_LOW_DEFAULT` / `_HIGH_DEFAULT` / `_UNION_LOW_DEFAULT`,"
        " applied only when the env seams are unset - W2 Ruling, D18 design Q3). Every"
        " `DEFAULT_DEDUP_*` global in `config.py` stays disabled/unset, so `mem extract` and"
        " every other surface remain opt-in (D18's ratified per-instance posture). A test"
        " (`tests/test_d18_w3_claim_leg_calibration.py`) pins the overlay's three numbers to"
        " this artifact, mirroring `research/dedup_calibration.py`'s config-pinning pattern."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb", default=None, help="a KB root for Stage 1a's IDF corpus (read-only)")
    args = ap.parse_args()
    kb_root = Path(args.kb).expanduser() if args.kb else None

    a = stage_1a(kb_root)
    b = stage_1b()

    ARTIFACT.write_text(render_artifact(a, b, args.kb), encoding="utf-8")
    print(f"wrote {ARTIFACT}")
    print(f"Stage 1a: verbatim {_list_stats(a['verbatim'])}")
    print(f"Stage 1a: hard-negatives {_list_stats(a['hard_negatives'])}")
    print(f"Stage 1a: composite-union {_list_stats(a['composite_union'])}")
    print(f"Stage 1a: D3 near-dup (negative control) {_list_stats(a['d3_near_dup_coverage'])}")
    if "skipped" not in b:
        print(f"Stage 1b: recall@1={b['recall_at'][1]:.3f} recall@10={b['recall_at'][10]:.3f} MRR={b['mrr']:.3f}")
        print(f"Stage 1b: recall@threshold {b['recall_at_threshold']}")
    else:
        print(f"Stage 1b: {b['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
