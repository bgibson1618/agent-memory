```text
VERDICT: PASS
DIMENSIONS:
  - detection design completeness (brief items 1–9): PASS
  - decision traceability (rejected alternatives named): PASS
  - calibration-data catalog (paths/formats/counts): PASS
  - fence compliance (no <engagement-kb> access, no writes): PASS
  - empirical grounding (recommendations measured, not asserted): PASS
BLOCKING:
RIGOR: tuned
```

# D18 — Dedup DETECTION accuracy: implementation-ready design

**Lane:** design-only (read-only seat). **Repo:** `agent-memory`. **Date:** 2026-09-02.
**Implements:** `DECISION_LOG.md` D18 scope (a)–(g) incl. the 2026-08-25 addendum.
**Fence honored:** no read, command, or lock touch against `<engagement-kb>`; no writes anywhere; work-repo citations limited to paths, counts, field names, and score statistics.

---

## 0. Two premise corrections the brief needs before anything else

**(i) The ~90 adjudicated labels are not in the gate runs.** There are **five** gate runs (`r1p2a-gate`, `-gate2`, `-gate3`, `-gate4`, `-gate5` — run 1 has no digit), and each is an agent-roster verifier run whose only artifact is a **markdown prose report**. They adjudicated the pipeline, not the candidates: exactly **3** of the 90 final rulings are attributed to a gate run (`gate-3-ruling` ×2, `gate-4-ruling` ×1), plus 9 `gate-cleared`. The structured labels live in four co-located JSON files under `work/kbx-2026-08-21/r1-phase2/`. Full catalog in Appendix A.

**(ii) The label vocabulary is not DUP/DISTINCT/FOLD.** Those three strings appear **only in prose** — `rg -l '"(DISTINCT|DUP)"'` across the work repo returns zero files. The structured vocabulary is a 6-value action set: `NO-ACTION-DUP` 58, `NEW-SAVE` 22, `FOLD` 4, `CITATION-FIX` 4, `REWRITE` 1, `NO-ACTION` 1. Mapping for calibration: `NO-ACTION-DUP` → DUP, `NEW-SAVE` → DISTINCT, `FOLD` → FOLD.

The good news is much better than the brief assumed: `near-dup-check-r1p2.json` holds **85 labeled records × exactly 10 retrieval hits = 850 hit-level rows**, each carrying both an RRF `score` and (on 467 of 850) a `semantic_similarity`. That is a real, fence-free retrieval-evaluation dataset. I ran it. Everything below is calibrated against it.

---

## 1. What the implementer reads first

In this order, nothing else needed to start:

1. `DECISION_LOG.md` — D18 (scope a–g), D17 (bands + fail-fast precedent), D3 (§55–72, the measured-not-guessed rule), D8 (the `.index/usage.jsonl` "not derived" exception — the storage precedent §5 leans on), D19-implemented (the current save-path state and its lock discipline).
2. **§2 and §3 of this document** — the measured baseline. Every recommendation below is downstream of those numbers; skipping them makes the design look arbitrary.
3. `src/agent_memory/extract.py:140-190` (`_kb_vectors`, `_best_match`, `_save_novel`) and `:261-340` (`_extract`'s dedup loop) — the exact code being replaced.
4. `src/agent_memory/vector.py:72-80` (`embed_text` — note `search_document:` and the 32,000-char truncation) and `:286-327` (`top_k` — note `search_query:`). **The prefix asymmetry in §4.2 is the single most missable fact in this design.**
5. `src/agent_memory/fusion.py` (all 53 lines — `rrf()` is reused verbatim) and `src/agent_memory/search.py:28-100` (the leg-pool/degradation pattern to mirror).
6. `src/agent_memory/lexical.py:125-147` (`match_expr` / `search` — why a body cannot be fed to `match_expr` as-is).
7. `research/dedup-calibration-work-2026-08-19.md` §Caveats, final bullet — the durable-trace gap §5 closes.
8. `tests/test_d17_dedup_bands.py` — the golden-key-set discipline §6 must reproduce. And `tests/test_f12_egress.py:207-220` — **a new subcommand must be added to `tests/f12_netns_driver.py` or the CLI-parity test fails.**
9. Appendix A (calibration data catalog) before touching §7 or §8.

---

## 2. Architecture Summary

Today's save-path detector is one line of signal: `_best_match()` takes the **argmax whole-document cosine** over the KB and compares it to `dedup_low`. Every one of D18's six failure modes is a direct consequence of that shape — an argmax discards rank 2+, a whole-document cosine cannot express containment, a single scalar cannot express "union of two cards," and a truncated whole-card embedding cannot represent a long card.

The design replaces the scalar with a **signal bundle** and splits two jobs that are currently conflated:

> **Retrieval selects the review set. Per-metric scores decide. RRF never decides anything.**

Concretely:

- **A new module `dedup.py`** owns detection: fused retrieval (lexical + document-vector + chunk-vector + graph, fused by the existing `fusion.rrf`), a fixed **deep-K = 50** full hit list, and per-hit **directional coverage** at claim grain against single cards and against **greedy unions of the top-M = 5**.
- **Two new derived indexes** in `.index/mem.db`, both disposable and both leaving `vectors` byte-untouched: `chunks` (sub-card windows — makes multi-topic/spine cards semantically findable) and `claims` (sentence-grain vectors — scoring only, never a retrieval leg).
- **One new durable artifact**: `.index/dedup-log.jsonl`, append-only, explicitly **not** derived (the D8 precedent), carrying every detection and, joined by `(run_id, content_hash)`, every later adjudication. This is what makes recalibration mechanical.
- **`mem dedup <file>`** exposes the detector as a first-class command with an **un-misreadable report**: there is no key named `score` and no key named `semantic_similarity` anywhere in it.
- **`mem extract` consumes the same detector.** The new legs always *run* and always *report*; they only *flag* when an instance sets a coverage threshold. With the new env vars unset, extract's dispositions and its `--json` key set are unchanged — while the durable log accumulates the coverage data that the opt-in decision requires. That resolves the chicken-and-egg problem: you cannot calibrate coverage without coverage data, and you cannot collect coverage data if the leg is off.
- **`mem save` keeps its dedup bypass** (D3 made it the designed recourse). It gains an advisory `--dedup-check` only.

---

## 3. Measured baseline — why each mechanism exists

All numbers computed this session, read-only. Sources: `~/.agent-memory` (3,132 cards) and `work/kbx-2026-08-21/r1-phase2/{dup-rulings,near-dup-check}-r1p2.json` joined on `id`.

### 3.1 The AP-BPF ground truth (63 positives / 22 negatives, 850 hit rows)

Positives = dup-class rulings with a cited `live_slug` (n=63). Ground truth for a hit = `hit.slug ∈ ruling.live_slug`.

| Metric | Value |
|---|---|
| True match present in the archived top-10 | **61 / 63**; absent 2/63 (`os-mis-030` max-sem 0.6765, `os-mis-046` max-sem 0.7731) |
| recall@1 (= what `_best_match`'s argmax can see) | **0.810** (51/63) |
| recall@2 / @3 / @5 / @10 | 0.889 / 0.937 / **0.968** / 0.968 |
| MRR | 0.872 |
| True-match `semantic_similarity` | n=61, min **0.6368**, p10 0.7110, median 0.7750, max **0.8811** |
| Archived hits per record | exactly 10 (the sweep ran at `mem search`'s default `--limit 10`) |

**The headline number.** Recall of confirmed duplicates from the whole-document cosine threshold alone:

| `dedup_low` | recall of the 61 confirmed dups |
|---|---|
| 0.79 (global default) | **0.410** |
| **0.83 (the work instance's actual setting, D17/2026-08-19)** | **0.197** |
| 0.85 | 0.082 |
| 0.88 | 0.016 |

**On this corpus the shipping detector misses 59–92% of confirmed duplicates.** That is D18's failure mode 2, quantified.

### 3.2 The classes do not separate on cosine at all

Max `semantic_similarity` over each record's 10 hits:

| class | n | min | p10 | median | p90 | max |
|---|---|---|---|---|---|---|
| dup-class (positive) | 63 | 0.6509 | 0.7021 | **0.7746** | 0.8417 | 0.8811 |
| `NEW-SAVE` (negative) | 22 | 0.6141 | 0.6470 | **0.7155** | 0.7591 | 0.7762 |

The negative **maximum** (0.7762) sits above the positive **median** (0.7746). Operating points:

| threshold | recall (dup) | flag rate (neg) |
|---|---|---|
| 0.65 | **1.000** | **0.864** |
| 0.70 | 0.905 | 0.636 |
| 0.72 | 0.889 | 0.455 |
| 0.75 | 0.714 | 0.182 |
| 0.79 | 0.413 | 0.000 |

100% recall costs an 86% flag rate. This is the personal-instance signature (D17: 81–100% flag rates, 87–95% FP) in its terminal form. **No cosine threshold is a usable operating point on this corpus.** Coverage is not an enhancement; it is the only remaining lever.

### 3.3 Coverage's operating range (250-sample synthetic probe over the real default KB)

IDF-weighted token containment at claim grain, claim-match τ ∈ {0.5, 0.6, 0.7} — results identical across τ:

| construction | n | min | median | max |
|---|---|---|---|---|
| verbatim subset (claim run ⊂ its own card) | 250 | 1.000 | 1.000 | 1.000 |
| **hard negative (distinct card sharing ≥1 topic)** | 225 | 0.000 | 0.000 | **0.021** |
| composite (½ card A + ½ card B) — best single card | 225 | 0.501 | 0.597 | 0.902 |
| composite — union of {A, B} | 225 | 1.000 | 1.000 | 1.000 |

**The false-positive side of coverage is essentially free**: 225 real, topically-matched, genuinely-distinct card pairs produced a maximum coverage of 0.021. A threshold anywhere in 0.1–0.8 flags zero of them. This inverts cosine's tradeoff and is the strongest argument in the design.

### 3.4 Coverage is paraphrase-blind — measured, not assumed

Same metric against `research/dedup_calibration.py`'s 26 D3 pairs (AST-extracted; corpus IDF from the live default KB):

| set | coverage (max of both directions) | best single-claim containment |
|---|---|---|
| 12 near-dup (deliberate rewordings) | median **0.000**, max 0.294 | min 0.118, median 0.412, max 0.696 |
| 14 distinct | median 0.000, max **0.000** | min 0.000, median 0.033, max 0.271 |

At any threshold ≥ 0.3, lexical coverage catches **0 of 12** reworded duplicates. Best-single-claim containment separates better but the classes still overlap (0.118 vs 0.271).

**Conclusion that drives §4.4:** lexical claim coverage is **high-precision / low-recall**; whole-document cosine on a dense corpus is **low-precision / low-recall**; they fail on *disjoint* classes. OR-ing them — **each leg thresholded for its own precision, recall arriving from the union** — is the correct architecture. This is the precise justification for D18 scope item (c), and it is why the semantic claim leg must be *built* even though it ships disabled: it is the only candidate mechanism for paraphrased subsets.

### 3.5 The misread trap, and failure mode 5's honest status

- `score` (RRF) spans **[0.0154, 0.0328]** across 850 hits; `semantic_similarity` spans **[0.5344, 0.8811]**. Two plausible-sounding names, two orders of magnitude apart. Cost measured: argmax-by-`score` picks the true match 51/63 (0.810), argmax-by-`semantic_similarity` 54/63 (0.857) — they disagree on 13/63.
- `semantic_similarity` is **absent on 383/850 hits (45%)** — it is a leg discriminator, not missing data (absent ⇒ `score` ∈ [0.0154, 0.0164], a tight single-leg RRF floor).
- **Failure mode 5 is not evidenced in this dataset.** The true-match hit carried a `semantic_similarity` in **61/61** cases — zero lexical-only true matches. Chunking's motivation is the gate *prose* plus the structural facts below, not this data. **Scope item (d) is correspondingly the lowest-priority slice.** Structural facts that keep it in scope: `embed_text` truncates at 32,000 chars, and exactly 2 of 3,132 default-KB cards exceed it (`expert-master-index` 1.79 MB, `expert-roster` 3.24 MB — 98%+ of each is literally absent from the vector index); and 253 `type: reference` cards are index/roster-shaped, whose whole-card embedding is a centroid of many topics and therefore near nothing in particular. The 2 top-10-absent positives (§3.1) are the only candidates for being this class, and that is unmeasurable from the archive.

### 3.6 Sizing (default KB, 3,132 cards; AP-BPF is 1,221)

| quantity | measured |
|---|---|
| card body chars | p50 1,749 · p90 2,467 · p99 3,599 · 2 outliers > 32 KB |
| claims (sentence/bullet grain, giants excluded) | **20,558** across 3,130 cards, mean 6.6; 1,990 cards have ≥5 (mean 7.6) |
| chunks at heading/section grain (~1 KB target) | est. **4,537** (1.45/card); 235 cards carry headings |
| chunk-vector space @ 768×f32 | **13.9 MB** (current `mem.db` is 37 MB) |
| claim-vector space, full eager build | **63 MB** — hence lazy, retrieval-scoped population |
| coverage cost per candidate | 7 candidate claims × (50 cards × 6.6) = **~2,300 set-intersections ≈ <10 ms**, no daemon |

---

## 4. The nine designed items

### 4.1 `mem dedup <file>` — CLI contract

**Recommendation.**

```
mem dedup FILE [--json] [--deep-k N] [--top-m N] [--explain] [--no-log]
                [--adjudicate RUN_ID --candidate HASH --label {DUP,DISTINCT,FOLD} [--by WHO]]
```

- `FILE` accepts the same three forms `mem extract --candidates` accepts (path, `-`, inline JSON) **plus** a single markdown file. Content sniff: leading `[`/`{` → candidates JSON; leading `---\n` → an OKF card (parsed by `okf.parse`, so an existing card can be re-checked — the (g) sweep and "is this card a dup" both need this); otherwise plain markdown treated as one candidate whose title is the first heading or `--title`.
  *Reason:* the sweep, the ad-hoc check, and the extract path are the three real callers, and all three inputs already have parsers in the repo.
- **No `--no-work` / `--no-sensitive` filters.** Dedup is a write-integrity check, not a recall surface; a filtered dedup surface under-detects silently, and offering the flag invites exactly that.
  *Rejected:* mirroring `mem search`'s filters — consistency is not worth a detector that can be configured to miss.
- `--deep-k` defaults to **50** and exists only as an escape hatch (see §4.2). `--top-m` defaults to **5**.
- **Exit code 0 on any successful analysis**, nonzero only for operational failure (no KB, band config invalid, daemon down when a semantic leg is required). This follows `graph.cmd_links`' stated precedent: *"Always exits 0: unresolved links are a curation signal, not a failure."*
  *Rejected:* nonzero-on-flag — breaks `set -e` callers and conflates "found duplicates" with "broken."
- Text report by default; `--json` for the machine report. `--explain` adds the per-claim match table to text (it is always present in `--json`).

**Retrieval spec (fused, deep-K, full hit list).**

Four legs, fused by **`fusion.rrf` reused verbatim** (D18 scope (a)):

| leg | source | notes |
|---|---|---|
| `lexical` | FTS5 BM25 | **new query builder** — see below |
| `vector_document` | whole-card cosine | `search_document:` **both sides** — see §4.2 |
| `vector_chunk` | sub-card window cosine | new `chunks` table (§4.5); absent ⇒ leg empty, not an error |
| `graph` | `fusion.graph_leg` seeded from lexical ∪ vector | association only; **never flaggable alone** |

- **Per-leg pool = `deep_k`**; final report = RRF top-`deep_k`.
- **The lexical query cannot be the candidate body.** `lexical.match_expr` quotes and OR-joins *every* token, so a 1,749-char body becomes a ~250-term OR dominated by stopwords (FTS5's default tokenizer applies no stoplist here). Add a sibling `lexical.dedup_match_expr(body, n=24)`: take the 24 highest-IDF content terms and OR them. Get `df` from **`fts5vocab`** — `CREATE VIRTUAL TABLE IF NOT EXISTS lexical_vocab USING fts5vocab(lexical, 'row')` gives `(term, doc, cnt)` directly and costs nothing to create. *Verified available on this host: SQLite 3.46.1, `fts5vocab` returns rows.* Leave `match_expr` untouched — `mem search` must not change.
- **`deep_k = 50`, justified from data, not taste.** The archive ran at 10 and the true match sat at rank 1–5 in 61/63 cases (recall@5 = 0.968) — but **2/63 were absent from the top-10 entirely**, so K must exceed 10 by a wide margin. K=50 is 1.6% of the default KB and 4% of AP-BPF, still a readable report; coverage cost is linear in K and measured at <10 ms; and the vector leg's brute-force scan is whole-KB regardless, so a larger K is free on the retrieval side.
- **The document-cosine flag is evaluated over the WHOLE KB, not the top-K.** `_kb_vectors` already loads every vector, so the whole-KB max cosine costs nothing extra. This closes failure mode 1 completely for the semantic signal: a true dup at cosine 0.90 can never be missed for sitting at rank 9. Coverage is necessarily deep-K-scoped; state that as the residual limit (a composite whose halves sit at ranks 3 and 300 is not caught).
- Free win while rewiring: `_best_match`'s Python loop over 3,132 vectors per candidate becomes a vectorized `np.vstack` scan, as `vector.top_k` already does.

**Making the report un-misreadable.** The 2026-08-24 misread happened because two differently-scaled numbers had equally plausible names (`score` ∈ [0.015, 0.033] vs `semantic_similarity` ∈ [0.53, 0.88]). Five rules:

1. **No key named `score`, and no key named `semantic_similarity`, anywhere in the report — at any depth.** A consumer that copy-pastes either field name gets a `KeyError`, not a wrong number. **Removal beats renaming-with-alias**; an alias preserves the bug.
2. **RRF emits no number at all — only `fusion_rank`, an integer.** There is no fusion score to threshold, so it cannot be thresholded by mistake.
3. **Every metric name states its metric and its scope**: `cosine_document`, `cosine_best_chunk`, `coverage_of_candidate`, `coverage_of_card`, `coverage_union`, `lexical_containment`. (`cosine_document` is also *genuinely* a different quantity from search's `semantic_similarity` — document-document vs query-document embedding — so the distinct name is correct, not merely defensive.)
4. **The decision is precomputed.** Top-level `verdict` ∈ {`novel`, `review-duplicate`, `confident-duplicate`}, plus `flagged`, `recommended_action`, and `flag_reasons[]`. A consumer that reads only `verdict` is correct.
5. **Every threshold is echoed next to the value it gates**, inside a `decisions` block, with an explicit `crossed` boolean and `scope`. Plus `report_version` and `config.legs_run` so a consumer can fail loudly on an unexpected shape and can never mistake a cheap run for a deep one.

JSON shape (abridged; one `candidates[]` entry shown):

```json
{ "report_version": 1, "detector_version": "1.0.0",
  "kb": {"root":"…","concept_count":3132,"embed_model":"nomic-embed-text:v1.5","embed_digest":"0a109f42…","index_dims":768},
  "config": {"deep_k":50,"union_m":5,"cosine_document_low":0.79,"cosine_document_high":null,
             "coverage_low":0.35,"coverage_high":0.85,"coverage_union_low":0.55,
             "claim_match_lexical":0.60,"claim_match_semantic":null,
             "legs_run":["lexical","vector_document","vector_chunk","graph","coverage_lexical"]},
  "candidates": [{
    "index":0,"title":"…","slug_intended":"…","content_hash":"sha256:…","claim_count":7,
    "verdict":"review-duplicate","recommended_action":"review","flagged":true,
    "flag_reasons":[{"signal":"coverage_of_candidate","value":0.62,"threshold":0.35,"against":"some-slug"}],
    "decisions":{
      "cosine_document_max":{"value":0.7123,"threshold":0.79,"crossed":false,"scope":"whole-kb"},
      "cosine_chunk_max":{"value":0.8402,"threshold":0.79,"crossed":true,"scope":"deep-k"},
      "coverage_of_candidate_max":{"value":0.62,"threshold":0.35,"crossed":true,"scope":"deep-k"},
      "coverage_union":{"value":0.91,"threshold":0.55,"crossed":true,"scope":"top-m"}},
    "hits":[{"fusion_rank":1,"slug":"…","title":"…","type":"concept","sensitivity":"normal",
             "legs":["lexical","vector_document"],
             "cosine_document":0.7123,"cosine_best_chunk":0.8402,"best_chunk_ordinal":3,
             "coverage_of_candidate":0.62,"coverage_of_card":0.21,"relation":"candidate-superset",
             "matched_claims":[{"candidate_claim":0,"card_claim":4,"lexical_containment":0.88,"semantic_cosine":null}]}],
    "union":{"member_slugs":["a","b"],
             "coverage_curve":[{"slug":"a","cumulative_coverage":0.62},{"slug":"b","cumulative_coverage":0.91}]},
    "notes":["chunk_index: skipped-oversize for 1 hit"]}],
  "summary":{"total":1,"novel":0,"review_duplicate":1,"confident_duplicate":0,"invalid":0},
  "log":{"path":".index/dedup-log.jsonl","run_id":"20260902T173045Z-a7f3c1","records_written":1}}
```

Text report — one block per candidate, thresholds inline, never a bare number:

```
review-duplicate: <title>   [7 claims]
  why: coverage_of_candidate 0.62 >= coverage_low 0.35  (vs 'some-slug')
       cosine_best_chunk     0.84 >= cosine_document_low 0.79  (vs 'some-slug', chunk 3)
       cosine_document_max   0.71 <  cosine_document_low 0.79  (not crossed)
  relation: candidate-superset -> recommended action: update-existing
  #1 some-slug        cosine_document 0.71  cosine_chunk 0.84  cov(cand) 0.62  cov(card) 0.21  [lexical,vector]
  #2 other-slug       cosine_document 0.69  cosine_chunk 0.70  cov(cand) 0.29  cov(card) 0.11  [vector]
  union(2): some-slug + other-slug -> coverage_union 0.91 >= 0.55
dedup: 1 candidate, 0 novel, 1 review-duplicate, 0 confident-duplicate  (deep-k 50, legs: lexical,vector_document,vector_chunk,graph,coverage_lexical)
```

### 4.2 Containment / coverage scoring

**The prefix trap, first.** `vector.embed_text` prefixes `search_document:`; `vector.top_k` prefixes `search_query:`. D3's and D17's bands were measured document-document (`research/dedup-calibration.md` says so explicitly). **Reusing `search.cmd_search`'s vector leg for dedup would put a query-prefixed vector against document vectors and produce numbers not comparable to the calibrated bands.** Recommendation: add `vector.top_k_doc(root, text, k)` — identical to `top_k` but `search_document:`-prefixed and returning the full ranked list. `extract._best_match` becomes its degenerate `k=1` case.

**Claim segmentation.** A claim = a sentence-or-bullet unit. Deterministic, dependency-free, ~40 lines in a new `claims.py`: split on markdown list-item boundaries, then headings, then blank lines; within each block on sentence-ending punctuation followed by whitespace + capital, with an abbreviation guard list; drop units under 4 content tokens (so `## Why` is not a claim).
*Reason:* the architecture's dependency posture is stdlib + numpy + yaml. *Rejected:* `pysbd`/`nltk`/`spacy` — a new runtime dependency and a model download for a corpus that is Brent's own plain markdown. Honest cost: some mis-splits on nested lists and inline code; §9 pins them with table-driven tests and measures the rate on a 100-card sample.

**Per-claim-pair match.** `matched(c,d) = (lexical_containment(c,d) ≥ τ_lex) OR (semantic_cosine(c,d) ≥ τ_sem)`, mirroring scope (c) at claim grain.

`lexical_containment(c,d) = Σ_{t ∈ tok(c) ∩ tok(d)} idf(t) / Σ_{t ∈ tok(c)} idf(t)` — asymmetric by construction (the denominator is the candidate claim). Tokens: lowercased alnum runs ≥ 3 chars with light suffix stripping (`ing|ed|es|s`). IDF from `fts5vocab`. *Rejected:* character-4-gram Jaccard as a morphology backstop — §3.3 shows the FP side is already at 0.021, so the extra leg buys nothing measurable in v1.

**Directional coverage, IDF-mass-weighted.**

```
coverage_of_candidate(card) = Σ_{c: ∃d∈card, matched(c,d)} w(c) / Σ_c w(c),    w(c) = Σ_{t∈tok(c)} idf(t)
coverage_of_card(candidate) = the same with roles swapped
```

*Reason for IDF-mass weighting over plain claim counts:* three filler sentences would otherwise make a candidate look 40% covered.

**The `relation` field — the most decision-useful output.** From the coverage pair, with `c_low = coverage_low`, `c_high = coverage_high`:

| `coverage_of_candidate` | `coverage_of_card` | relation | recommended_action |
|---|---|---|---|
| ≥ c_high | ≥ c_high | `equivalent` | `skip` |
| ≥ c_high | < c_high | `candidate-subset` | `skip` (safe: candidate adds nothing) |
| < c_high | ≥ c_high | **`candidate-superset`** | **`update-existing`** |
| both in [c_low, c_high) | | `overlapping` | `review` |
| both < c_low | | `unrelated` | `add` |

**A `candidate-superset` must never auto-skip.** The card is contained in the candidate; skipping discards the new material. Recommendation: a superset relation **downgrades `confident-duplicate` to `review-duplicate`** and names `update-existing` (D19's `--update` merge is exactly the landing surface). *Rejected:* auto-skip (silent knowledge loss — today's behavior); auto-update (a write the detector must not make unilaterally). This also gives the `FOLD` label a natural predicted class (§4.7).

**Union coverage.** Greedy set-cover over the deep-K, ranked by marginal claim-mass gain, capped at **M = 5**, reporting the cumulative curve. Coverage is submodular, so greedy is (1−1/e)-optimal and its first two picks are the best pair in practice. *Rejected:* exhaustive pairs — C(50,2) = 1,225 is affordable but strictly less informative than a 5-deep curve, and does not generalize to triples. §3.3 confirms the mechanics: a ½A+½B composite scores 0.50–0.90 on its best single card and **1.000** on the union of {A, B}.

**Complexity, honestly costed.**

| path | cost | verdict |
|---|---|---|
| lexical coverage, per candidate | 7 × (50 × 6.6) ≈ 2,300 set-intersections over ~10-token sets | **< 10 ms**, no daemon. Free. |
| document-vector leg | unchanged whole-KB numpy scan | ~10 ms at the 10k ceiling (ARCHITECTURE) |
| chunk-vector leg | 4,537 rows ≈ 1.45× the card scan | ~15 ms |
| semantic claim leg, cold | ≤ 7 + 330 short embeds, one batched `/api/embed` | seconds; extract already tolerates a 30 s `FULL_DRAIN_TIMEOUT` batch |
| semantic claim leg, warm (cached) | 7 embeds (the candidate's own claims) | negligible |
| claim index at full eager build | 20,558 × 3,072 B = **63 MB** | why it is **lazy and retrieval-scoped**, never whole-KB |
| AP-BPF instance (1,221 cards) | ~8k claims, ~1.8k chunks | ~25 MB / ~5 MB |

**Oversize cards, bounded by one rule.** Coverage for *any* card is scored against **that card's retrieved windows** — for a normal card that is all 1–2 of them; for a card above `MEM_DEDUP_CHUNK_SKIP_CHARS` (default 200,000) it is the lexically-matched window(s), located from FTS5's own `snippet()`. One rule, work bounded by K regardless of card size, and it uses the signal that already found those cards in the evidence. Without it, the 1.79 MB `expert-master-index` alone would contribute ~18k claims to a single candidate's scoring pass.

### 4.3 Reference / spine cards in the surface (scope d)

**Priority: lowest of the seven build items** — §3.5 found 0/61 lexical-only true matches, so this failure mode is evidenced only in gate prose. It stays in scope because two structural facts are certain: `embed_text` truncates at 32,000 chars (2 cards, 98%+ of each invisible to the vector index), and a roster/index card's whole-card embedding is a multi-topic centroid near nothing in particular (253 `type: reference` cards, p90 2,592 chars — *under* the truncation cap, so truncation is not their problem; **dilution is**).

**Recommendation.** Chunk at **markdown-section grain**: split at headings first, then at block boundaries, targeting ~1,000 chars per chunk with a hard cap of 4,000 (comfortably inside nomic's context) and a **50% stride overlap** so a claim straddling a boundary appears whole in at least one window. A card with no internal headings and ≤ 1,000 chars yields exactly one chunk identical to its whole-card text — so `cosine_best_chunk == cosine_document` and there is no special case. Measured: **4,537 chunks, 1.45/card, 13.9 MB.**

- **Storage: a new `chunks` table** `(slug, ordinal, char_start, char_end, content_hash, vec BLOB, updated)`, PK `(slug, ordinal)`.
  *Reason:* `vectors` is load-bearing for `mem search`, `mem reindex`, meta stamping, and D17's band arithmetic. Adding rows to it would silently change search results for every instance. A separate table is the opt-in seam.
  *Rejected:* chunk rows inside `vectors` with a synthetic `slug#N` key — a one-character bug away from chunk hits leaking into `mem search`.
- Whole-card vectors stay in `vectors`, untouched, so `cosine_document` remains bit-comparable to D3/D17's calibration.
- **The chunk grain is a retrieval fix only.** Chunks never carry coverage; the `claims` table is the scoring grain. Three grains, three jobs: `vectors` = whole-card retrieval + the D17 band; `chunks` = sub-card retrieval; `claims` = scoring.
- Population: lazy and retrieval-driven (a card entering deep-K gets chunked on demand), plus `mem reindex --chunks` for an eager build. Cards over `MEM_DEDUP_CHUNK_SKIP_CHARS` are excluded and reported as `chunk_index: skipped-oversize` — so the operator is told the semantic leg is blind there and the lexical leg is carrying it.
- Framing for the decision log: **chunk vectors close the gap between the lexical leg (which finds spine cards — that is the evidence) and the vector leg (which does not).**

### 4.4 Flag policy and its interaction with D17

**The operating-point doctrine — the design's central claim.** §3.2 and §3.4 together say: cosine at 100% recall costs an 86% flag rate; coverage at any threshold in 0.1–0.8 costs a 0% flag rate but catches 0/12 paraphrases. Therefore:

> **Threshold each leg for its own PRECISION. Take recall from the UNION.**

Set cosine where it is precise (0.83 → 0.197 recall at 0.000 measured FP) and let coverage carry the classes cosine cannot see. This is the reading of scope (c) that makes OR-logic a gain rather than a doubling of the flag rate, and it is what the calibration in §4.7 must report per-leg.

**Signals and flags.**

```
semantic_flag = max(cosine_document_max_over_whole_KB, cosine_best_chunk_max_over_deep_K) >= cosine_document_low
coverage_flag = (coverage_of_candidate_max >= coverage_low) OR (coverage_union >= coverage_union_low)
flagged       = semantic_flag OR coverage_flag
```

The `graph` leg contributes ordering only and can never raise a flag on its own.

**Config — `MEM_*` env seams, per-instance, no config file (D15/D17 pattern).**

| var | default | note |
|---|---|---|
| `MEM_DEDUP_LOW` / `MEM_DEDUP_HIGH` | 0.79 / `None` | **unchanged semantics**; `MEM_DEDUP_THRESHOLD` still the back-compat fallback |
| `MEM_DEDUP_COVERAGE_LOW` | `None` (flag disabled) | recommended calibrated value **0.35** — 16× above the measured negative max of 0.021, below the composite single-card floor of 0.50 |
| `MEM_DEDUP_COVERAGE_HIGH` | `None` | recommended **0.85** — below the verbatim-subset 1.0, above the composite band's p90 of 0.755 |
| `MEM_DEDUP_UNION_LOW` / `MEM_DEDUP_UNION_M` | `None` / 5 | recommended union floor **0.55** |
| `MEM_DEDUP_CLAIM_LEX` | 0.60 | claim-match threshold; §3.3 shows 0.5/0.6/0.7 are indistinguishable, so 0.60 is a safe middle |
| `MEM_DEDUP_CLAIM_SEM` | `None` (leg off) | the paraphrase lever; enabling it also enables claim-vector storage |
| `MEM_DEDUP_DEEP_K` / `MEM_DEDUP_CHUNKS` | 50 / off | |
| `MEM_DEDUP_CHUNK_SKIP_CHARS` | 200000 | oversize exclusion |
| `MEM_DEDUP_LOG` / `MEM_DEDUP_LOG_TITLES` | on / on | §4.5 |

**Validated when read, fail-fast, per D17's precedent** (one `error:` line, exit 1, `ExtractError`/`DedupError`): every coverage/cosine value finite and in [0, 1]; `coverage_high > coverage_low` and `dedup_high > dedup_low` strictly; `deep_k ≥ 1`; `union_m ≥ 1`; `claim_match` in (0, 1]. A reversed pair would make the confident band swallow the reviewable one with no visible symptom — the exact hazard D17's gate cycle ruled on.

**Interaction with D17, stated precisely.** D17's bands are a *routing function over one signal*; the detector produces a *bundle*. Routing generalizes to:

```
confident-duplicate  if (cosine_document_max >= dedup_high, when set)
                     OR (coverage_of_candidate_max >= coverage_high, when set)
                     — UNLESS the winning hit's relation is `candidate-superset`, which downgrades to review
review-duplicate     if flagged
novel                otherwise
```

**Disposition strings are unchanged, 1:1:** `novel`→`added`, `review-duplicate`→`skipped-duplicate`, `confident-duplicate`→`skipped-duplicate-confident`. The extract procedure text, the D17 tests, and every downstream consumer keep working. `flag_reasons` appears in extract's JSON **only when coverage config is enabled** — the same additive-only trick D17 proved for `dedup_high`.

**The opt-in seam, exactly.** The new legs **always run and always report**; they only **flag** when a coverage threshold is set. So with the new vars unset: extract's dispositions are identical, its `--json` key set is byte-identical (golden test), and **the durable log accumulates coverage numbers from day one on every instance** — which is what makes the opt-in a data-backed one-line flip rather than a guess. Recommended defaults per surface: coverage flag **ON in `mem dedup`** (a new command, no back-compat surface, deliberate invocation) and **OFF in `mem extract`** until an instance reads its own log. The measured FP evidence (0/225) supports flipping extract's default in a follow-up, once one instance's log confirms it — that follow-up is a decision-log entry, not this slice.

### 4.5 Durable skip / adjudication records (scope e)

Closes the gap `research/dedup-calibration-work-2026-08-19.md` names in its last caveat.

**Location: `.index/dedup-log.jsonl`**, append-only JSONL, **explicitly not derived**, preserved by `mem reindex`, documented in ARCHITECTURE's storage layout with the same "one deliberate exception" language D8 established for `.index/usage.jsonl`.
*Reason:* the record is not knowledge (so not `concepts/`) and not derived (so `reindex` must not delete it); D8 already established both the pattern and the preservation guarantee, and there is a test pattern to copy.
*Rejected:* a `dedup/` directory of per-run JSON files (more files, no append atomicity, harder to scan); git-committing it under the KB root (every dedup run would dirty the KB repo and collide with extract's exactly-one-commit-per-save contract).

**Two record types, one file, joined on `(run_id, candidate_content_hash)`.**

Detection record:
```json
{"record_version":1,"type":"detection","ts":"2026-09-02T17:30:45Z","run_id":"20260902T173045Z-a7f3c1",
 "command":"extract","detector_version":"1.0.0","embed_model":"…","embed_digest":"…",
 "config":{ …every resolved threshold… },
 "candidate":{"title":"…","slug_intended":"…","content_hash":"sha256:…","claim_count":7},
 "verdict":"review-duplicate","flagged":true,"flag_reasons":[…],"disposition":"skipped-duplicate",
 "hits":[{"slug":"…","fusion_rank":1,"cosine_document":0.71,"cosine_best_chunk":0.84,
          "coverage_of_candidate":0.62,"coverage_of_card":0.21,"relation":"candidate-superset"}],
 "union":{"member_slugs":["a","b"],"coverage_union":0.91},"hits_truncated":false}
```

Adjudication record, appended later by `mem dedup --adjudicate`:
```json
{"record_version":1,"type":"adjudication","ts":"…","run_id":"…",
 "candidate_content_hash":"sha256:…","label":"DUP","by":"orchestrator","note_ref":"work/agents/…/output.md"}
```

- **`config` is embedded in every record.** A record must be self-describing or a later recalibration cannot tell which thresholds produced it. This is the difference between "we have logs" and "recalibration is mechanical."
- **The two-record split is the point.** The label arrives minutes-to-hours later, from a different actor. Joining on `(run_id, content_hash)` makes recalibration a two-line join — which is exactly what the AP-BPF archive *failed* to be (§3 required joining three files with three vocabularies and a stale `action` field).
- `MEM_RUN_ID` lets an orchestrated batch share one run id.
- **Atomicity.** Keep each line under `PIPE_BUF` (4,096 bytes) so a single `O_APPEND` `write()` is atomic on POSIX: inline the top **5** hits only and set `hits_truncated: true` if the record would still exceed it (the full deep-K list is recomputable). On the extract/save path the write happens inside the already-held `write_lock`; standalone `mem dedup` relies on append atomicity and does **not** take the write lock — see Open Question 2.
- **Confidentiality.** Slugs, hashes, numbers, and the candidate title only — never card bodies. The log is instance-local by construction, so a work-instance log inherits `work` handling by location. `MEM_DEDUP_LOG_TITLES=0` drops titles for a paranoid instance.
- **Analysis stays out of the CLI.** `research/dedup_detection_calibration.py` reads the log and writes its markdown artifact, mirroring `research/dedup_calibration.py` exactly (that script writes `research/dedup-calibration.md` and a test pins config to it). The CLI stays deterministic and small.

### 4.6 Save-path rewiring (scope f)

- **New module `dedup.py`** with one entry point: `detect(root, con, concept, cfg, precomputed_vec=None) -> DedupReport`. Owns segmentation, retrieval, coverage, routing, and the log write. `mem dedup` and `mem extract` both call it — **same detector, same code; configured leg set and flag policy differ per surface, and `config.legs_run` always says which ran.**
- `extract._extract` replaces `_best_match(vec, entries)` with `dedup.detect(...)`, passing the batch's already-computed candidate vector so nothing is re-embedded. **Preserve the batch invariant**: all embedding still happens up front in one batched call, so a daemon failure refuses the batch before a single save. If the semantic claim leg is enabled, its embeds join that same up-front call.
- The lexical coverage leg needs **no daemon at all** — a useful property worth stating: with Ollama down, extract still refuses (dedup requires embeddings, unchanged contract), but `mem dedup` can run coverage-only and says so in `legs_run`.
- **`mem save` keeps its bypass.** D3 §66-69 made direct `mem save` the *designed recourse* for umbrella/member overrides; silently adding a check would break the recourse and slow every save. Add `mem save --dedup-check` — runs the detector, prints the report to **stderr**, saves anyway. *Rejected:* block-on-flag (breaks D3's recourse); dedup-by-default on save (same, plus a latency cost on the < 1 s perceived-save NFR).
- **D12 link-remap target must be re-specified.** Today `rename[candidate.slug] = match` uses the cosine argmax. New rule, deterministic and documented: the hit with the highest `coverage_of_candidate`, tie-broken by `cosine_document`, then by slug. For a union/composite skip there is no single right target — use the union's first (highest-marginal-gain) member and record `union_members` in the log so the chosen target is auditable. Honest limitation, worth a line in the addendum.

### 4.7 Calibration protocol

**Three stages; only one is fenced.**

**Stage 1a — mechanics + the negative side (fence-free, in-repo).** The harness of §3.3 over the default KB: verbatim subsets, real same-topic hard negatives, synthetic composites. Proves the mechanics (subset → 1.000; composite union → 1.000; composite best-single ∈ [0.50, 0.90]) and measures the **FP side**, which is the side that sets the threshold: max coverage 0.021 over 225 real topical pairs. Add the 26 D3 pairs as a **negative control** — lexical coverage must be expected to score ~0 on pure paraphrase (measured 0/12), and a harness that "fixes" that has a bug.

**Stage 1b — the cosine baseline and the acceptance bar (fence-free).** Replay §3.1/§3.2 from the archive: join `dup-rulings-r1p2.json` (labels) → `disposition.json` (context) → `near-dup-check-r1p2.json` (850 scored hits) on `id`. This yields recall@K, MRR, the class-overlap table, and the 0.410/0.197 recall figures that the acceptance bar is written against. **No coverage numbers exist in the archive** — coverage did not exist when it was made — so this stage cannot fit coverage thresholds. Do not try; regressing archived numbers onto a metric they never measured is the trap here.

**Stage 2 — the full-detector replay (post-fence).** Reconstruct each labeled candidate's body (available fence-free: `report-r1p2.json` carries `body` for all 90 survivors) and score it with the real detector against the AP-BPF KB **at the pin the rulings were made against**.

> **Calibrate against a pinned, read-only copy of the KB — never the live one.** Use `git clone --local <kb> /tmp/engagement-cal-<date>` (hardlinks objects, writes nothing to the source), **not** `git worktree add` (which writes `.git/worktrees/` inside the source repo). Check out the handoff pin `015b5c9`; the live HEAD of record is `a1a5152`, i.e. the KB has moved since. Run `mem reindex` inside the clone with `MEM_KB_ROOT` pointed at it, and record `vector_meta`'s model + digest — if they differ from the original run's, the cosines are not comparable and the run must say so.

**Split and validation.** n = 85 with 63 positives is too small for a single holdout.
- **Stratified 5-fold CV** for threshold selection: report the operating point's mean and range across folds.
- **Leave-one-method-out** as the honest generalization estimate, using `adjudication_method` as the cluster (`prior-cycle` 60 / `exhaustive-r3` 18 / `gate-cleared` 9 / gate rulings 3). Within-cluster leakage is the real risk: a cluster's candidates come from the same source documents and the same adjudicator.
*Reason:* D3 used a full-grid argmin on 26 pairs with no split; D17's study reported descriptive percentiles. Cross-validation is the minimum upgrade the n supports, and clustering by method is the only split that tests generalization rather than memorization.

**Metrics — the asymmetry is the whole design.** A false negative is a permanent KB defect; a false positive is one full-body read. So:

1. **Primary: flag rate at 100% recall of the dup-class.** The smallest review burden that misses nothing.
2. **Per-leg precision at threshold + union recall** — the §4.4 doctrine's own metric. A single ROC over the OR'd signal hides which leg is earning its keep.
3. **`recall@deep_k`** — did the true match reach the report at all? This is the detection-layer metric the prior work never measured (failure mode 1 is a *ranking* failure). Baseline: recall@10 = 0.968.
4. **Relation-vs-label agreement**, scored separately: `FOLD` should predict `candidate-superset`/`overlapping`; `NO-ACTION-DUP` should predict `equivalent`/`candidate-subset`. This validates the `relation` field without conflating detection recall with disposition accuracy.
- Treat `NO-ACTION-DUP` **and** `FOLD` as positives for detection (both require the adjudicator to see the card). `CITATION-FIX` (4) and `NO-ACTION` (1) have no retrieval scores and are excluded with that stated.

**Acceptance bar (the gate for the calibration slice).**
- **Recall of dup-class at the chosen operating point = 1.000** on the labeled set. The baseline is 0.410 at `dedup_low=0.79` and 0.197 at the work instance's 0.83; anything short of near-total recall does not answer D18.
- **Flag rate ≤ 0.60** at that recall. The 2026-08-19 study measured 82–100% flag rates at 96% FP; a detector that does not clearly beat that is not worth shipping.
- **`recall@50` = 1.000.** If the true match is not in the deep-K, no threshold saves it. Note the known risk: 2/63 were absent from the archived top-10 and whether K=50 recovers them is unmeasurable pre-replay.
- **Leave-one-method-out holds**: an operating point chosen on 3 clusters must hold 1.000 recall on the 4th, for every rotation. **If it does not, ship the mechanism with the flag disabled and say so** — the D17 precedent for `dedup_high`.
- **Zero change to `mem extract --json`'s default key set** (golden test).
- **Per-instance, not global.** Both prior studies concluded per-instance calibration; AP-BPF-derived thresholds calibrate the AP-BPF instance, and the global defaults stay disabled.

**Artifact:** `research/dedup-detection-calibration-<date>.md`, generated by `research/dedup_detection_calibration.py`, with the existing header block (generated-by / daemon / model + digest / metric), per-class score tables, the fold table, the chosen operating point, and a test pinning `config` defaults to the artifact — extending the `tests/test_f9_extract.py` / `tests/test_d17_dedup_bands.py` pattern.

### 4.8 The (g) false-suppression sweep — EXECUTION PLAN ONLY

**Preconditions, all three required before step 1.** (1) Brent lifts the `<engagement-kb>` fence — **nothing in this plan may run before that, including the `git clone`**. (2) The detector has passed its own gate and Stage-2 calibration. (3) The **ap agent now owns that KB** (engagement closed and handed off 2026-09-01). Therefore: **the sweep produces a report, never a write.** An overturn is a change request routed through Brent to the ap agent — not a `mem save`.

**Population.** Three defensible cuts; the intended one is the first:

| cut | n |
|---|---|
| `method == "prior-cycle"` | **60** ← D18's "60 prior-cycle rulings" |
| `action ∈ {NO-ACTION-DUP, NO-ACTION, FOLD}` (DUP-class) | 63 |
| intersection | 55 |

56 of the 60 carry archived retrieval scores (the 4 `CITATION-FIX` do not). Run all 60; the 4 without scores get no before/after comparison and are reported as such.

**Steps.**

1. **Pin and clone.** `git -C <engagement-kb> log -1` → record as the sweep's HEAD-of-record. `git clone --local <engagement-kb> /tmp/engagement-sweep-<date>` and check out the handoff pin `015b5c9`. `export MEM_KB_ROOT=/tmp/engagement-sweep-<date>`; `mem reindex` **inside the clone** — a write, but to a throwaway clone, never the live KB. Record `vector_meta` (model + digest) into the sweep artifact.
2. **Pin the input by hash, do not glob.** Use exactly `work/kbx-2026-08-21/r1-phase2/dup-rulings-r1p2.json` and assert its md5 prefix `e66073d1`. **Five mutually-inconsistent versions exist across 40 copies**, and most copies live under `work/agents/r1p2a-gate{3,4}/verifier/scratch-attacks/…` — *deliberately tampered adversarial fixtures* (`corrupt_counts_after_rebuild`, `tamper_after_gate_before_mutation_load`, …). Two of the five generations **lack the `method` field entirely**, so a `method == "prior-cycle"` filter silently returns 0 rows against them. A globbing sweep would quietly calibrate on attack fixtures.
3. **Materialize candidates.** Build one candidates JSON of 60 objects. Bodies come from `report-r1p2.json.survivors[].body`; ids join on `id`. Normalize `live_slug` to list-of-str first — it is polymorphic across the four files (list / str / null for the same 90 records). Do not use `near-dup-check[].action`: it is **stale** (`new_save` 84/85, from before 58 became `NO-ACTION-DUP`) — that staleness is precisely what preserves the archived retrieval results for the dup-labeled records.
4. **Run.** `mem dedup candidates.json --json --deep-k 50 --top-m 5 > sweep-<date>.json` with the Stage-2-calibrated AP-BPF thresholds set in the environment (they are echoed into the report's `config` block, so the run is self-describing).
5. **Join and classify** — the ruling-by-ruling table, one row per ruling:

   `ruling_id | original_action | original_live_slug[] | new_best_match | relation | cosine_document | cosine_best_chunk | coverage_of_candidate | coverage_of_card | coverage_union | verdict | agreement`

   | `agreement` | condition |
   |---|---|
   | `confirm` | new verdict is a duplicate **and** the best match ∈ the originally cited `live_slug` |
   | **`overturn-distinct`** | new verdict `novel`, or `relation` ∈ {`unrelated`, `overlapping`} with coverage below `coverage_low` → **the ruling suppressed a real, distinct concept** |
   | `overturn-different-match` | still a duplicate, but of a different card → right in kind, wrong in target (matters for `related:`/link integrity) |
   | `inconclusive` | coverage inside the review band → needs human adjudication |

6. **Escalation path.**
   - **No writes to the KB.** The ap agent owns it.
   - Every `overturn-distinct` gets a full-body adjudication under the same DUP/DISTINCT/FOLD protocol, and its label is appended via `mem dedup --adjudicate` — **so the sweep itself becomes calibration data.**
   - Confirmed false suppressions are packaged as a **restoration proposal** (candidate texts + the evidence table) handed to Brent, who decides whether to route it to the ap agent as a KB change request.
   - **Class escalation bar, stated up front so it cannot be argued down afterward: ≥ 4 `overturn-distinct` out of 60 (> 5%)** flips the R3 gate's deferred-with-owner disposition from *trusted* to *not trusted*, and the sweep must then extend to every other prior-cycle dup ruling in the engagement — not just these 60.
7. **Deliverables.** `research/false-suppression-sweep-<date>.md` in **this** repo carrying only ruling ids, counts, scores, and verdicts; the full table with card text stays in the work repo. Prior art worth reading first: `work/kbx-2026-08-21/r1-phase2/near_dup_check_r1p2.py` is the original sweep script (it targets the fenced KB root — read the text, do not run it pre-fence).

### 4.9 Test strategy and implementation slices

**Patterns to reuse:** `tests/conftest.py`'s `kb` fixture (scratch `HOME`, closed-port Ollama by default) and `fake_ollama_factory`; `tests/fakes.py`'s parameterized server with a custom `embed_fn` for meaning-shaped embeddings; `tests/test_d17_dedup_bands.py`'s golden-key-set + exact-boundary discipline; `tests/test_f7_concurrency.py`'s hold-the-lock-then-spawn contention pattern; both suite commands (`uv run pytest` and `MEM_REQUIRE_NETNS=1 uv run pytest`). **Do not forget `tests/f12_netns_driver.py`** — the parity test at `tests/test_f12_egress.py:207-220` fails if a new subcommand is missing from it.

| # | Slice | Deliverable | Proof method |
|---|---|---|---|
| **S1** | Claim segmentation + IDF | `claims.py`; `lexical.dedup_match_expr` + the `fts5vocab` shadow table | Table-driven segmentation cases (nested lists, headings, abbreviations, inline code, the <4-token filter); `dedup_match_expr` returns ≤24 terms and never emits an FTS5 operator; measured mis-split rate on a 100-card sample recorded in the slice note |
| **S2** | Detector core | `dedup.py`: containment, directional coverage, `relation`, greedy union; config seams + fail-fast validation | Unit tests on hand-built claim sets: verbatim subset → 1.000; composite → union 1.000 / best-single ∈ [0.5, 0.9]; disjoint → 0.000; every `relation` cell in §4.2's table; IDF-mass weighting changes the answer vs. plain counts. Every invalid config value refused with exit 1 (D17's pattern), incl. `coverage_high <= coverage_low` and non-finite |
| **S3** | Chunk index | `chunks` table; section-grain chunker; lazy population; `mem reindex --chunks`; oversize skip | Synthetic spine card whose true match is invisible to whole-card cosine but found at chunk grain; a ≤1,000-char card yields exactly 1 chunk with `cosine_best_chunk == cosine_document`; **`vectors` and `mem search` output byte-unchanged** before/after chunk population; an oversize card is excluded and reported |
| **S4** | `mem dedup` command | CLI, fused deep-K retrieval, `vector.top_k_doc`, both report shapes | **Un-misreadable contract test: walk the JSON report recursively and assert no key named `score` or `semantic_similarity` at any depth**; `verdict`/`flagged`/`recommended_action` always present; every `decisions` entry carries `value`+`threshold`+`crossed`+`scope`; `fusion_rank` is an int and no RRF float is emitted; exit 0 on flags, nonzero on no-KB; **added to `f12_netns_driver.py`** (parity test green) |
| **S5** | Durable log | `.index/dedup-log.jsonl`, detection + adjudication records, `--adjudicate` | `mem reindex` preserves it (copy D8's `usage.jsonl` test); every line < 4,096 B with `hits_truncated` set when capped; a detection + a later adjudication join on `(run_id, content_hash)`; `MEM_DEDUP_LOG_TITLES=0` omits titles; no card body ever appears in the log |
| **S6** | Extract rewiring | `_best_match` → `dedup.detect`; vectorized KB scan; D12 remap-target rule | **Golden key-set test: `mem extract --json` output byte-identical to the pre-D18 golden with the new vars unset**; identical dispositions across the D17 band cases; `flag_reasons` appears only when coverage is configured; the up-front-batch invariant holds (daemon killed mid-batch ⇒ nothing saved); remap target follows the documented tie-break |
| **S7** | Semantic claim leg | `claims` table, lazy retrieval-scoped population, `MEM_DEDUP_CLAIM_SEM` | Fake-embedding test where two paraphrased claims share no tokens but are cosine-near: lexical coverage 0.000, semantic coverage high, OR-flag fires; cache hit on a second run costs zero embeds; leg absent ⇒ `legs_run` says so |
| **S8** | Calibration Stage 1a + 1b | `research/dedup_detection_calibration.py` + artifact + `mem save --dedup-check` | Harness reproduces §3.1–§3.4 numbers; artifact's chosen values pinned to `config` defaults by test (D3's pattern); D3's 26 pairs pass as the negative control |
| **G1** | *(post-fence)* Stage 2 replay | Per-instance AP-BPF thresholds + artifact | The §4.7 acceptance bar, incl. leave-one-method-out |
| **G2** | *(post-fence, separate gate)* The (g) sweep | Ruling-by-ruling table + `research/false-suppression-sweep-<date>.md` | §4.8 steps 1–7 executed; input md5 asserted; escalation bar applied |

Order: S1 → S2 → {S3, S4} → S5 → S6 → S8, with S7 landable any time after S2 and S4. Each slice follows the repo's delegate → gate → commit pattern (D19's cycle: implementer, verifier gate at `work/agents/<slice>-gate/verifier/output.md`, then a decision-log addendum recording the rulings and any gate FAIL/fix cycle). **S6 is the only slice that can change existing behavior — gate it hardest.**

---

## 5. Interfaces and Data Flow

```
mem dedup FILE                          mem extract --candidates FILE        mem save --dedup-check
      │                                        │                                    │
      └──────────────┬─────────────────────────┴────────────────────────────────────┘
                     ▼
            dedup.detect(root, con, concept, cfg, precomputed_vec?)
                     │
     ┌───────────────┼────────────────────────────────┬──────────────────────┐
     ▼               ▼                                ▼                      ▼
  lexical leg    vector_document leg            vector_chunk leg         graph leg
  FTS5 BM25      cosine, WHOLE KB               cosine over `chunks`    fusion.graph_leg
  dedup_match_   `search_document:` BOTH sides  (lazy, opt-in)          (ordering only,
  expr (top-24   ← the calibrated metric        ← spine-card fix          never flags)
  IDF terms,                                      
  fts5vocab)     
     └───────────────┴────────────────────────────────┴──────────────────────┘
                     ▼
            fusion.rrf([lex, vec_doc, vec_chunk, graph])   ← REUSED VERBATIM
                     │   emits ORDER ONLY; the float is discarded
                     ▼
            deep-K = 50 full hit list
                     ▼
            coverage pass (claims.py + `claims` table when enabled)
              per hit: coverage_of_candidate, coverage_of_card, relation
              greedy set-cover over top-M = 5 → coverage_union + curve
                     ▼
            signal bundle ──► routing (§4.4) ──► verdict / flagged / flag_reasons
                     │                                   │
                     ▼                                   ▼
     .index/dedup-log.jsonl (append)          report (JSON | text)
       + later: --adjudicate record             + extract disposition mapping
                     │                              (novel→added,
                     ▼                               review→skipped-duplicate,
     research/dedup_detection_calibration.py    confident→skipped-duplicate-confident)
                     ▼
     research/dedup-detection-calibration-<date>.md  ──test-pinned──► config defaults
```

Storage delta in `.index/mem.db` (all disposable except the log):

```
vectors      (existing, UNTOUCHED)  whole-card retrieval + the D17 band
chunks       (new, opt-in)          sub-card windows — retrieval only        ~4.5k rows / 14 MB
claims       (new, opt-in, off)     sentence grain — scoring only            lazy; 63 MB if eager
lexical_vocab(new, fts5vocab view)  df/IDF — zero storage
dedup-log.jsonl  (new, NOT derived) preserved by reindex, per the D8 precedent
```

---

## 6. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **Lexical coverage is paraphrase-blind (measured 0/12 on D3's pairs).** With the semantic claim leg shipped disabled, reworded duplicates remain undetected at `dedup_low=0.83`. | **High** — it is the largest residual gap | Build S7 regardless; state the gap in the addendum; the union operating point in §4.7 must report per-leg recall so the gap is visible, not averaged away |
| R2 | Coverage's **positive-side** thresholds are synthetic-only until the fence lifts | High | Ship the flag disabled (D17 precedent); log coverage from day one; Stage 2 sets the real value. The negative side *is* real (0/225) |
| R3 | Claim segmentation without a real sentence splitter mis-splits nested lists / inline code | Medium | Table-driven tests; the <4-token filter; measure and record the mis-split rate on a 100-card sample in S1 |
| R4 | Claim index space (63 MB eager) and first-run embed cost | Medium | Lazy, retrieval-scoped; `MEM_DEDUP_CLAIM_SEM` off by default; `reindex --claims` only for an instance that opts in |
| R5 | **The archive has 5 inconsistent `dup-rulings` versions across 40 copies, most under deliberately-tampered attack-fixture dirs; 2 generations lack `method` entirely** | **High** — a globbing harness silently calibrates on attack fixtures and a `method` filter silently returns 0 rows | Pin the canonical path AND assert md5 prefix `e66073d1`; never glob `**/dup-rulings-r1p2.json`; exclude `scratch-*` and `r1p2a-fix*/implementer/{stage,deliverable}` |
| R6 | The AP-BPF KB has moved past the state the rulings were made against (handoff pin `015b5c9`; HEAD of record `a1a5152`) | High | `git clone --local` at the pin; never `worktree add` (writes into the source repo); record `vector_meta` model+digest and refuse to compare if they differ |
| R7 | `mem dedup` becomes a writer (the log) — lock/contention surprise on a read-feeling command | Low | Append atomicity under `PIPE_BUF`, no write lock for standalone `mem dedup`; `--no-log` escape. See Open Question 2 |
| R8 | The ap agent owns the AP-BPF KB post-handoff; a sweep that writes is a cross-owner mutation | Medium | §4.8 is report-only by construction; overturns route through Brent |
| R9 | `deep_k = 50` is not *proven* to recover the 2/63 true matches absent from the archived top-10 | Medium | Stage 2's `recall@50` is an explicit acceptance criterion; if it is < 1.000, raise K and re-measure rather than adjusting thresholds |
| R10 | Extract batches slow down once the semantic claim leg is enabled | Low | Retrieval-scoped + cached; joins the existing single up-front batched embed; D4's envelope is minutes |
| R11 | S6 is the only slice that can change existing behavior | Medium | Golden byte-identity test as a hard gate criterion; the additive-only key discipline D17 already proved |
| R12 | Three grains (card / chunk / claim) is real added complexity in a small codebase | Medium | Each grain has exactly one job (§4.3), stated in the module docstring; chunks and claims are both opt-in and both disposable |

---

## 7. Verification Plan

Per-slice proofs are in §4.9's table — that is the contract. Repo-level gates:

1. **Both suite commands green** on every slice: `uv run pytest` and `MEM_REQUIRE_NETNS=1 uv run pytest` (166 passing today).
2. **CLI parity**: `tests/test_f12_egress.py`'s driver-parity assertion must pass with `dedup` registered — i.e. `tests/f12_netns_driver.py` exercises it. This proves the new command makes no network call beyond loopback Ollama.
3. **The two byte-identity goldens** (the highest-value tests in the set): `mem extract --json`'s exact key set with the new vars unset, and `mem search`'s output before/after chunk-index population.
4. **The un-misreadable contract test**: recursive walk of the `mem dedup --json` report asserting the absence of `score` and `semantic_similarity` at every depth. This is the regression test for failure mode 6, and it is cheap and permanent.
5. **Real-daemon smoke** (not in CI, recorded in the slice note, following the F3/F5/F9 precedent): one `mem dedup` against the live default KB (3,132 cards) with timing, plus the calibration harness run that generates the artifact.
6. **Calibration acceptance bar** (§4.7) as the gate criterion for G1; the escalation bar (§4.8 step 6) as the gate criterion for G2.
7. **Decision-log discipline**: a D18-implemented addendum recording the implementation-time rulings (Open Questions 1–8 as resolved), any gate FAIL/fix cycle, and the honest statement of R1 and the (d) downgrade — following D19's addendum shape.

---

## 8. Key Decisions (with rejected alternatives)

| Decision | Chosen | Rejected, and why |
|---|---|---|
| What RRF is for | **Ordering the deep-K review set only; its float is never emitted** | RRF as the flag signal — it is the failure-mode-6 trap and its [0.015, 0.033] scale is meaningless as a similarity |
| Report field naming | **Remove `score` and `semantic_similarity` entirely; `fusion_rank` is an int** | Rename with an alias (preserves the bug); a `_note` field explaining the difference (nobody reads it) |
| Cosine prefix for dedup | **`search_document:` on both sides via a new `vector.top_k_doc`** | Reusing `search`'s vector leg — `search_query:` vs document vectors is not comparable to D3/D17's calibrated bands |
| Flag combination | **OR, each leg thresholded for its own PRECISION; recall from the union** | A single tuned cosine threshold (100% recall costs an 86% flag rate — measured); AND (would drop everything cosine misses, i.e. most of it) |
| Coverage grain | **Sentence/bullet claims, IDF-mass-weighted, directional** | Plain claim counts (filler sentences inflate coverage); whole-document containment (cannot express subsets); paragraph grain (too coarse for composites) |
| Union algorithm | **Greedy set-cover over top-M = 5, with the cumulative curve** | Exhaustive pairs (C(50,2) affordable but strictly less informative and does not generalize to triples) |
| Sentence splitter | **~40 lines of stdlib in `claims.py`** | `pysbd`/`nltk`/`spacy` — a new runtime dep + model download for plain markdown; violates the stated dependency posture |
| Chunk storage | **A new `chunks` table; `vectors` untouched** | Chunk rows inside `vectors` under a `slug#N` key — one bug away from leaking chunk hits into `mem search` |
| Log location | **`.index/dedup-log.jsonl`, not derived, preserved by reindex (D8 precedent)** | A `dedup/` dir of per-run files (no append atomicity, harder to scan); git-committed under the KB root (dirties the KB repo, collides with extract's one-commit-per-save) |
| Log schema | **Two record types joined on `(run_id, content_hash)`; `config` embedded in every record** | One record mutated in place (JSONL is append-only); a config-less record (a later recalibration cannot tell which thresholds produced it — exactly why the AP-BPF archive needed a 3-file join) |
| Superset handling | **Downgrade to `review-duplicate`, recommend `update-existing`** | Auto-skip (silent knowledge loss — today's behavior); auto-update (a write the detector must not make unilaterally) |
| `mem save` | **Keeps its bypass; gains advisory `--dedup-check` only** | Dedup-by-default (breaks D3's designed recourse and the < 1 s perceived-save NFR); block-on-flag (same) |
| Opt-in seam | **New legs always run and report; they only flag when a coverage threshold is set** | Legs off by default (no coverage data ⇒ no calibration ⇒ never enabled: the chicken-and-egg); legs on and flagging (breaks byte-identical defaults) |
| Deep-K | **50, fixed, with `--deep-k` as an escape hatch** | The current argmax (discards 19% of true matches — measured recall@1 = 0.810); `--limit`-style tuning (K is a correctness parameter, not a display preference) |
| Semantic flag scope | **Whole-KB max for the document leg; deep-K for chunks and coverage** | Top-K-only for everything — a whole-KB scan is already paid, so restricting it would reintroduce failure mode 1 for free |
| Calibration target | **A pinned `git clone --local` of the KB** | The live KB (races the ap agent, and the KB has moved past the ruling state); `git worktree add` (writes into the source repo) |
| Calibration split | **Stratified 5-fold CV + leave-one-method-out** | A single holdout at n=85 (wastes data); D3's no-split grid argmin (memorizes) |
| Scope-(d) priority | **Lowest of the seven build items, kept for two structural reasons** | Dropping it (the 32,000-char truncation and reference-card centroid dilution are certain); prioritizing it (0/61 lexical-only true matches — the failure mode is not evidenced in the hit-level data) |

---

## Questions

Each has a stated default; the design is complete and buildable under all eight defaults, so none of these blocks S1.

1. **Does `mem save` get a dedup check?** The brief says "`mem extract`/`save` consume the same detector"; D3 §66-69 says the `mem save` bypass is the *designed recourse* for umbrella/member overrides. I read "same detector" as *share the code, not the policy*.
   **Default:** `mem save` keeps its bypass; add advisory `--dedup-check` (report to stderr, save anyway).

2. **Should `mem dedup` write the durable log by default?** It makes a read-feeling command a writer.
   **Default:** yes — producing the audit record is the point (§4.5 exists because skips left no trace). `--no-log` suppresses; no write lock is taken for standalone runs, relying on `PIPE_BUF` append atomicity.

3. **Coverage flag: enabled in `mem dedup`, disabled in `mem extract`?** The FP evidence (0/225 real topical pairs) would support enabling it in extract too, but that breaks byte-identical defaults.
   **Default:** on in `mem dedup` (coverage_low 0.35), off in `mem extract` until one instance's log confirms it; the flip is a follow-up decision-log entry.

4. **Semantic claim leg on or off by default?** On costs up to 63 MB eager / seconds per cold batch; off leaves R1 — the paraphrase gap — wide open.
   **Default:** built in S7, shipped **off** (`MEM_DEDUP_CLAIM_SEM` unset), lazy and retrieval-scoped when enabled. R1 recorded prominently in the addendum.

5. **May `confident-duplicate` ever fire on coverage alone?**
   **Default:** yes when `MEM_DEDUP_COVERAGE_HIGH` is set — but **never** when the winning hit's relation is `candidate-superset`.

6. **Do you want the three-grain index (card / chunk / claim), or should chunks be deferred?** Given scope (d) is the least-evidenced item, deferring S3 would cut real complexity from a small codebase.
   **Default:** build it, lowest priority, opt-in and disposable. Say "defer S3" and everything else lands unchanged.

7. **The (g) escalation bar: ≥ 4 `overturn-distinct` of 60 (> 5%) flips the R3 gate's "trusted" disposition and extends the sweep to every other prior-cycle ruling in the engagement.** Confirming this *before* the sweep runs is the point — a bar set afterward is not a bar.
   **Default:** 4 of 60, and the sweep is report-only (the ap agent owns that KB; overturns route through you as a change request).

8. **The label vocabulary mapping.** The archive has no DUP/DISTINCT/FOLD; I mapped `NO-ACTION-DUP`→DUP, `NEW-SAVE`→DISTINCT, `FOLD`→FOLD, and excluded `CITATION-FIX` (4) and `NO-ACTION` (1) as score-less.
   **Default:** as above, with `FOLD` counted as a positive for detection recall and scored separately for relation agreement.

---

# Appendix A — Calibration-data catalog

Paths, formats, counts, field names, score statistics, and parsing hazards only. No card titles, bodies, or ruling text. Fence honored throughout: `<engagement-kb>` untouched.

**Repo root:** `<engagement-project>/`
**Canonical artifact dir:** `<root>/work/kbx-2026-08-21/r1-phase2/`
**Gate run dirs:** `<root>/work/agents/r1p2a-gate{,2,3,4,5}/verifier/`

### A.1 The gate runs — prose, not labels

Five runs (**run 1 is `r1p2a-gate`, not `gate1`**). Each `verifier/output.md` is a markdown prose gate report with a fixed skeleton (Findings › Blocking › Open Questions › Verification Evidence › Residual Risk › Gate Verdict). Sizes 9,042–20,427 B / 116–175 lines. gate 1 has one markdown table (10 data rows); the rest have none. Sibling files per run: `README.md` (roster boilerplate, **not** a layout doc), `prompt.md`, `last_message.md`, `status` (all `done`), `terminal.log`/`transcript.txt` (byte-identical), `meta.json`, `run.json`, `events.jsonl`, `inbox.jsonl` (0 B), `questions.md` (0 B). All five: `backend: "codex"`, `role: "verifier"`.

Label-token occurrence counts in the prose (argumentative mentions, **not records**): `DUP` 14/11/3/4/5, `DISTINCT` 1/2/0/0/0, `FOLD` 1/5/2/5/4, `NO-ACTION` 2/8/3/3/7 for gates 1–5. Score field names appearing in prose: `semantic_similarity` (gate1 ×4, gate2 ×1), plus "semantic similarity"/"lexical"/"score"/"hybrid"/"leg" as words. **No structured score fields.** Net adjudicative yield: 3 of the 90 rulings (`gate-3-ruling` ×2, `gate-4-ruling` ×1) + 9 `gate-cleared`.

### A.2 The label set — 90 records, id-keyed

Id format `{gov|os}-{mis|rec}-NNN` (10–11 chars). Group cardinality: `os-mis` 62, `os-rec` 16, `gov-mis` 7, `gov-rec` 5. Verified identical key sets across `dup-rulings.rulings`, `join-table[].id`, `submission-r1p2[].id`.

**`dup-rulings-r1p2.json`** — 42,620 B, JSON object, 2-space indent, ASCII, no BOM. Built by `build_dup_rulings_r1p2.py` (rulings hardcoded).
Top-level keys: `rulings`, `action_counts`, `adjudication_method_counts`, `adjudication_method_note`.
**`rulings` is an OBJECT with 90 entries**, keyed by id (`jq 'length'` → 4; `jq '.rulings|length'` → 90).
Per-ruling fields (4, all 90/90): `action`, `rationale`, `live_slug`, `method`.
- `action`: `NO-ACTION-DUP` 58, `NEW-SAVE` 22, `FOLD` 4, `CITATION-FIX` 4, `REWRITE` 1, `NO-ACTION` 1
- `method`: `prior-cycle` **60**, `exhaustive-r3` 18, `gate-cleared` 9, `gate-3-ruling` 2, `gate-4-ruling` 1
- `live_slug`: always a list; lengths `{0:22, 1:58, 2:9, 3:1}`. Empty ⇔ `NEW-SAVE` (verified both directions)
- `rationale`: free text 15–2,045 chars, mean 289, **zero newlines**
- **No score field.** 15/90 rationales carry a bare `0.xxxx` (19 values, 0.6141–0.8619, mean 0.7332); only 6 label it (`max` ×4, `sim` ×3)
- Adjudicator recorded only at run granularity via `method` — no human-vs-agent, no model id, no timestamp

**`near-dup-check-r1p2.json`** — 273,309 B, JSON array, ASCII, no BOM. **The only retrieval-score artifact.**
**85 records**; fields `id`, `action`, `title`, `live_slug`, `search_result`. `search_result` is **exactly 10 hits** on all 85 (**850 hit rows**, zero empty, zero errors). Hit fields: `slug`, `title`, `type`, `score`, `snippet`, `semantic_similarity`.

| field | present on | min | max | mean | median |
|---|---|---|---|---|---|
| `score` (RRF) | 850/850 | 0.0154 | 0.0328 | 0.0227 | 0.0164 |
| `semantic_similarity` | **467/850** | 0.5344 | 0.8811 | 0.6953 | 0.6889 |

Hit `type`: `concept` 745, `reference` 84, `position` 21. Distinct matched slugs: 374. Semantically-scored hits per record: min 3, max 8, mean 5.49, distribution `{3:1, 4:16, 5:28, 6:24, 7:12, 8:4}`. **Retrieval leg is captured implicitly**: hits *with* `semantic_similarity` have `score` ∈ [0.0154, 0.0328] mean 0.0283; hits *without* have `score` ∈ [0.0154, 0.0164] mean 0.0160 (a tight single-leg RRF floor). All 85 ids ∈ the 90-id label set; **85 of 90 labels have retrieval scores** (the 5 without are `CITATION-FIX` ×4 + `NO-ACTION` ×1).

**`disposition.json`** — 73,448 B, JSON object. `candidates` list of **90**; fields (all 90/90): `id`, `group`, `title`, `true_chunk`, `is_recovered`, `is_live`, `live_slug`, `known_miscited`, `review_verdict`, `arbitration_outcome`, `shingle_status`, `phase_2b_action`, `adjudication_method`, `rationale`. `review_verdict`: `fix` 53 / `approve` 37. `shingle_status`: `N/A (no body written)` 63 / `CLEAN` 27. **No numeric score field.** Method × action cross-tab: `prior-cycle` → NO-ACTION-DUP 53, CITATION-FIX 4, FOLD 1, NO-ACTION 1, REWRITE 1; `exhaustive-r3` → NEW-SAVE 13, NO-ACTION-DUP 3, FOLD 2; `gate-cleared` → NEW-SAVE 9; `gate-3-ruling` → NO-ACTION-DUP 1, FOLD 1; `gate-4-ruling` → NO-ACTION-DUP 1.

**`join-table.json`** — 73,670 B, JSON array, **90** records. Carries `live_match_score` (float, 90/90, min 0.0993, max 1.0, mean 0.2453) — **NOT a retrieval similarity.** Per `join.py` (lines 19–24, 67–83, 98–122) it is a local `difflib.SequenceMatcher(...).ratio()` over normalized bodies, thresholds hardcoded at `>= 0.85 → "fuzzy_body"` and `TITLE_ONLY_FLOOR = 0.5`. By method: `exact_body` 6 (all exactly 1.0), `no_match_REJECTED_below_floor` 83 (0.1133–0.2831), `title_match_only_REJECTED_below_floor` 1 (0.0993). Only 6/90 have a non-null `live_match_slug`; `fuzzy_body` never fired.

**`disposition.md`** — 39,850 B. Three lines of Python-`repr` dict dumps (single-quoted keys — **not JSON-parseable**), then one pipe table of **90 data rows** (92 pipe lines). Columns: `id | group | true_chunk | live_slug(s) | review | arbitration | phase-2b action | method | rationale`. No `|` inside any rationale (0/90), so pipe-splitting is safe. **Do not count labels by grep here** — the header dumps and rationale prose inflate every token.

**Candidate bodies (needed for Stage 2 replay):** `report-r1p2.json` → `survivors` (90), each with a `body` field, plus `id`, `group`, `title`, `type`, `true_chunk`, `true_lens`, `buggy_chunk`, `buggy_lens_label`, `src_file`, `is_recovered`, `is_live`, `live_slug`, `live_source_field`, `citation_fix`, `decision`. `dropped` 0, `conflicts` 0, `holds` 0.

**Other artifacts in the same directory:** `submission-r1p2.json` (array, 90: `id`, `action`, `live_slug`, `rationale`, `entry`; + `related`/`related_note` on 22); `phase2b-outcomes.json` (`outcomes` 90: `id`, `action`, `result`, `resulting_slug_or_skip_reason`; + `all_green` true, `gate_submission_sha256`, `post_mutation_check`); `reviews-r1p2.json` (90 keys × exactly 2 reviews = 180; `verdict` approve 109 / fix 71; 18 lens ids, paired `-codex`/`-claude` over 9 chunks); `arb-items-r1p2.json` (18); `citation-fixes-r1p2.json` (4); `shingle-flags-r1p2-advisory.json` (5); `shingle-flags-r1p2-{final,actionset}.json` and `waivers-r1p2.json` (**empty**); `metadata-join-r1p2.json` (`by_id` 30); `related-resolution-r1p2.json` (`by_id` 22); `join-summary.json`; `fanout/fanout-r1p2{arb,rev}-result.json`; `specs/{arb,review}-spec-r1p2.json` (prompt specs, not labels); `near_dup_check_r1p2.py` (the original sweep script — **targets the fenced KB root; read only, do not run pre-fence**).

**Score-field-name census across every `*.json` in that directory** — only four exist: `score` ×850, `semantic_similarity` ×467, `live_match_score` ×90, `shingle_status` ×90 (enum). No `cosine`, `rrf_score`, `lexical_score`, `jaccard*`, `bm25`, or `similarity`.

### A.3 Layout documentation (there is no manifest)

`rg -l -e 'dup-rulings-r1p2' -e 'near-dup-check-r1p2' -e 'join-table.json' --glob '*.md'` → **zero** files. Closest, best first:
1. `<root>/work/kb-extraction-plan-2026-08-21.md` (27,761 B) — **best single doc.** Lines ~112–160 are the Phase 2/2a status block; names the run-dir convention (`r1-phase2a`, `r1p2a-fix*`, `r1p2a-gate*`), states artifacts were promoted to `work/kbx-2026-08-21/r1-phase2/`, pins a submission sha256 prefix, narrates the gate-5 close-out and the gate-4 blocker.
2. `<root>/work/briefs/` — the de-facto layout spec, read in order: `r1-phase2a-brief.md`, `r1-phase2a-gate-brief.md`, `r1p2a-fix-brief.md`, `r1p2a-gate2-brief.md`, `r1p2a-fix2-brief.md`, `r1p2a-gate3-brief.md`, `r1p2a-fix3-brief.md`, `r1p2a-gate4-brief.md`, `r1p2a-fix4-brief.md`, `r1p2a-gate5-brief.md`.
3. `<root>/CONTEXT.md` lines 87, 96–101.
4. `<root>/work/kbx-2026-08-21/EVIDENCE-CONVENTIONS.md` (3,674 B) — the scan-artifact self-description convention (wave id / date / input hash), not the ruling layout.

### A.4 Parsing hazards, ranked by likelihood of silently corrupting a run

1. **`dup-rulings-r1p2.json` exists in 5 mutually-inconsistent versions across 40 copies.** All have 90 rulings; distributions differ materially. **Use only the canonical path and assert the md5.**

   | md5 (8) | copies | top-level keys | ruling fields | NO-ACTION-DUP / NEW-SAVE / FOLD | shortest path |
   |---|---|---|---|---|---|
   | **`e66073d1`** | 5 | 4 | 4 (+`method`) | **58 / 22 / 4** | **`work/kbx-2026-08-21/r1-phase2/dup-rulings-r1p2.json` ← CANONICAL** |
   | `e1031c63` | 21 | 4 | 4 | 57 / 23 / 4 | `work/agents/r1p2a-fix3/implementer/stage/…` |
   | `d936aea6` | 1 | 4 | 4 | 57 / 23 / 4 | `work/agents/r1p2a-gate4/verifier/scratch-guards/…` |
   | `ed4ac907` | 12 | **2** | **3 (no `method`)** | 53 / 30 / 1 | `work/agents/r1p2a-gate3/verifier/scratch/dryrun/…` |
   | `caa84f8c` | 1 | **2** | **3 (no `method`)** | 50 / 33 / 1 | `work/agents/r1p2a-fix/implementer/deliverable/…` |

   Two generations **lack `method` entirely** — a `method == "prior-cycle"` filter silently returns 0 rows. Same multiplicity in `disposition.json` (7 hashes / 41 copies), `phase2b-outcomes.json` (6 / 39), `join-table.json` (3 / 44). Only `near-dup-check-r1p2.json` is stable (1 hash / 39 copies).
2. **Most copies are deliberately-tampered adversarial fixtures.** Dirs include `scratch-attacks/*/`, `scratch-guards/`, `scratch-independent-binding/`, `scratch/dryrun/`, with names like `corrupt_counts_after_rebuild`, `tamper_after_gate_before_mutation_load`, `synthetic_flag_after_scan`, `stale_empty_flags_hide_fresh_flag`. **Never glob `**/dup-rulings-r1p2.json`.** Also exclude `r1p2a-fix*/implementer/{stage,deliverable}/**` (pre-promotion drafts).
3. **`near-dup-check-r1p2.json`'s own `action` field is STALE and is not the label** (`new_save` 84 / `update_live_with_rewrite` 1 — the sweep predates 58 of those becoming `NO-ACTION-DUP`). Join on `id` for the true label. That staleness is exactly why the file still holds the dup-labeled records' full 10-hit retrieval results.
4. **Three incompatible action vocabularies for the same 6 concepts.** UPPER-HYPHEN in `dup-rulings`/`disposition`/`disposition.md`; lower_underscore in `submission`/`phase2b-outcomes`/`near-dup-check` (`NO-ACTION-DUP`↔`no_action_dup`, `NEW-SAVE`↔`new_save`, `FOLD`↔`update_live_with_fold`, `CITATION-FIX`↔`citation_fix_only`, `REWRITE`↔`update_live_with_rewrite`, `NO-ACTION`↔`no_action`); and a third in `phase2b-outcomes[].result` (`not_a_mutation` 59, `added` 22, `folded` 4, `citation_fixed` 4, `rewritten` 1). **`result` is not invertible** — `not_a_mutation` collapses `NO-ACTION-DUP` + `NO-ACTION` (58+1).
5. **`live_slug` is polymorphic.** `dup-rulings` always list; `disposition` list ×59 / str ×9 / null ×22 for the same 90; `near-dup-check` null ×84 / str ×1; `join-table.live_match_slug` null ×84 / str ×6. **Normalize to list-of-str before joining.**
6. **`rulings` is a dict, not an array** — insertion-ordered, not sorted.
7. **Three score fields, three scales, three engines.** `score` ∈ [0.015, 0.033] (RRF), `semantic_similarity` ∈ [0.53, 0.88] (cosine), `live_match_score` ∈ [0.099, 1.0] (`difflib` body diff). **Never pool or threshold them together.** The only calibratable thresholds visible in code are `join.py`'s 0.85 and 0.5, both on the `difflib` scale.
8. **`semantic_similarity` absent on 383/850 hits is the LEG SIGNAL, not missing data.** Do not impute 0; do not drop the rows. Treat absence as "lexical-leg-only hit."
9. **Labels and scores in prose.** The 3 gate-attributed rulings and their similarity values exist only as sentences in gate `output.md` and inside `rationale` strings; 15/90 rationales carry a bare decimal, only 6 label it, no delimiter or units.
10. **`arbitration_outcome` is 89 enum values + 1 free-text sentence** (150+ chars, prefixed `arb agreement: fix0; …`). A strict enum decoder throws on exactly one row.
11. **`disposition.md`'s header block is Python `repr`, not JSON** (single-quoted keys, `True`/`False`); longest line 2,177 chars.
12. **Encoding is clean.** All canonical JSON is pure ASCII, no BOM. gate2/3/5 reports carry a few non-ASCII lines (em-dashes, typographic quotes); no non-UTF8, no BOM anywhere. 27/850 hit `snippet` values contain embedded newlines — a hazard for line-oriented tooling only.
13. **Every path inside every `run.json` / `env.sh` is stale** — they point at `<engagement-project>/`, not the current `work/` location. Do not resolve artifact paths from run metadata.
14. **No JSONL/YAML/CSV label artifact exists.** The only `.jsonl` under the gate runs is roster plumbing (`events.jsonl` ~830 B; `inbox.jsonl` all 0 B).

### A.5 The recommended calibration join

```
labels  := work/kbx-2026-08-21/r1-phase2/dup-rulings-r1p2.json   → .rulings          (dict, 90, key=id; md5 e66073d1)
context := work/kbx-2026-08-21/r1-phase2/disposition.json        → .candidates       (list, 90, join .id)
scores  := work/kbx-2026-08-21/r1-phase2/near-dup-check-r1p2.json                    (list,  85, join .id)
                                                                  → .search_result[0..9].{slug,type,score,semantic_similarity?}
bodies  := work/kbx-2026-08-21/r1-phase2/report-r1p2.json        → .survivors[].body (90, for Stage 2 replay)
```

Yields **85 labeled records with 10 scored hits each = 850 hit-level rows**: `NO-ACTION-DUP` 58, `NEW-SAVE` 22, `FOLD` 4, `REWRITE` 1. Hit-level ground truth = `hit.slug ∈ ruling.live_slug`. Leg is derivable from `semantic_similarity` presence. **Sweep population (g)** = the 60 `method == "prior-cycle"` rulings (55 in the DUP-class intersection); 56 of the 60 carry retrieval scores.
