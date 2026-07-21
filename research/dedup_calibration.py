"""Dedup-threshold calibration for `mem extract` (capstone D024: measured, not guessed).

Embeds representative concept pairs with the real local daemon using the exact
document composition the index stores (vector.embed_text: title + description +
topics + body, search_document prefix), measures cosine similarity for
near-duplicate pairs (same knowledge, reworded - must be SKIPPED) and distinct
pairs (mostly same-domain hard negatives - must be SAVED), picks the threshold
that minimizes errors, and writes the committed calibration artifact
research/dedup-calibration.md. The test suite asserts
config.DEFAULT_DEDUP_THRESHOLD equals the artifact's recorded choice.

Run:  uv run python research/dedup_calibration.py
"""

import math
import sys
from pathlib import Path

from agent_memory import config, okf, ollama, store, vector

ARTIFACT = Path(__file__).resolve().parent / "dedup-calibration.md"

# Pairs are shaped like Brent's KB: AI education, agents/tooling, learning
# science, local-first dev. Each entry: (title_a, body_a, title_b, body_b).
NEAR_DUP_PAIRS = [
    ("Spaced repetition scheduling",
     "Reviewing material at increasing intervals produces far better long-term retention than cramming the night before.",
     "Why spacing beats cramming",
     "Long-term memory improves when reviews are spread out over growing gaps of time instead of massed into one session."),
    ("Retrieval practice",
     "Actively recalling an answer from memory strengthens learning more than re-reading the material.",
     "Testing effect",
     "Trying to pull facts from your own memory beats passively rereading notes for durable learning."),
    ("RAG grounds LLM answers",
     "Retrieval-augmented generation fetches relevant documents at query time so the model can answer from real sources instead of hallucinating.",
     "Retrieval-augmented generation",
     "By retrieving supporting passages before generating, RAG systems anchor model output in actual documents and cut hallucination."),
    ("Embedding models map text to vectors",
     "An embedding model turns text into a dense vector so that semantically similar passages end up close together in vector space.",
     "What text embeddings do",
     "Text embeddings encode meaning as high-dimensional vectors, placing passages with similar meaning near each other."),
    ("Prompt few-shot examples",
     "Including a handful of worked examples in the prompt reliably steers a model toward the desired output format and style.",
     "Few-shot prompting",
     "Showing the model two or three example input-output pairs in the prompt is one of the most reliable ways to control format and tone."),
    ("Docker layer caching",
     "Docker reuses unchanged image layers between builds, so ordering Dockerfile commands from least to most volatile keeps builds fast.",
     "Fast Docker builds via layer reuse",
     "Because each Dockerfile instruction produces a cacheable layer, putting rarely-changing steps first makes rebuilds much faster."),
    ("Cosine similarity for embeddings",
     "Cosine similarity compares two vectors by the angle between them, which makes it robust to differences in vector magnitude.",
     "Angle-based vector comparison",
     "Measuring the angle between embedding vectors (cosine similarity) ignores their lengths and captures how aligned their meanings are."),
    ("SQLite WAL mode",
     "Write-ahead logging lets SQLite readers keep reading while a writer commits, removing most reader-writer blocking.",
     "Why WAL helps concurrency in SQLite",
     "In WAL mode, SQLite appends writes to a log so readers are never blocked by an in-progress commit."),
    ("Local-first knowledge base",
     "Keeping notes as plain markdown files on disk means no vendor lock-in and every tool - editor, git, grep - can work with them.",
     "Markdown files as the source of truth",
     "A knowledge base stored as local markdown stays portable and inspectable: git tracks history and any editor can open it."),
    ("Agent tool-use loop",
     "An LLM agent works by repeatedly choosing a tool, observing the result, and deciding the next step until the task is done.",
     "How agents iterate with tools",
     "Agents operate in a loop: pick an action, run the tool, read what came back, then plan the next call until finished."),
    ("Interleaving practice",
     "Mixing different problem types within one study session improves discrimination and transfer compared with blocked practice.",
     "Mixed practice beats blocked drills",
     "Alternating among topics during practice, rather than drilling one type at a time, strengthens the ability to tell problems apart."),
    ("uv manages Python environments",
     "uv resolves dependencies and creates project virtualenvs fast enough that per-project isolated environments become the default workflow.",
     "Fast Python project isolation with uv",
     "With uv's quick dependency resolution and venv creation, every Python project can cheaply get its own isolated environment."),
]

DISTINCT_PAIRS = [
    # Hard negatives: same domain, genuinely different concepts.
    ("Spaced repetition scheduling",
     "Reviewing material at increasing intervals produces far better long-term retention than cramming the night before.",
     "Interleaving practice",
     "Mixing different problem types within one study session improves discrimination and transfer compared with blocked practice."),
    ("Retrieval practice",
     "Actively recalling an answer from memory strengthens learning more than re-reading the material.",
     "Elaborative encoding",
     "Connecting new material to things you already know, by asking how and why it works, makes it easier to remember later."),
    ("RAG grounds LLM answers",
     "Retrieval-augmented generation fetches relevant documents at query time so the model can answer from real sources instead of hallucinating.",
     "LLM context window limits",
     "A model can only attend to a bounded number of tokens at once, so long inputs must be truncated, summarized, or chunked."),
    ("Embedding models map text to vectors",
     "An embedding model turns text into a dense vector so that semantically similar passages end up close together in vector space.",
     "BM25 lexical ranking",
     "BM25 scores documents by weighted term overlap with the query, rewarding rare terms and normalizing for document length."),
    ("Prompt few-shot examples",
     "Including a handful of worked examples in the prompt reliably steers a model toward the desired output format and style.",
     "Chain-of-thought prompting",
     "Asking a model to reason step by step before answering improves accuracy on multi-step problems."),
    ("Docker layer caching",
     "Docker reuses unchanged image layers between builds, so ordering Dockerfile commands from least to most volatile keeps builds fast.",
     "Docker bind mounts",
     "Bind mounts map a host directory into a container so code edits on the host are visible inside immediately."),
    ("Cosine similarity for embeddings",
     "Cosine similarity compares two vectors by the angle between them, which makes it robust to differences in vector magnitude.",
     "Approximate nearest neighbor indexes",
     "ANN indexes like HNSW trade a little recall for dramatically faster similarity search over large vector collections."),
    ("SQLite WAL mode",
     "Write-ahead logging lets SQLite readers keep reading while a writer commits, removing most reader-writer blocking.",
     "SQLite FTS5 full-text search",
     "FTS5 builds an inverted index over text columns and ranks matches with BM25, all inside the SQLite file."),
    ("Agent tool-use loop",
     "An LLM agent works by repeatedly choosing a tool, observing the result, and deciding the next step until the task is done.",
     "MCP standardizes tool access",
     "The Model Context Protocol gives agents a common interface for discovering and calling external tools and data sources."),
    ("uv manages Python environments",
     "uv resolves dependencies and creates project virtualenvs fast enough that per-project isolated environments become the default workflow.",
     "Python type hints",
     "Type annotations let static checkers catch mismatched arguments and return types before the code ever runs."),
    # Easy negatives: unrelated domains - sanity floor for the distribution.
    ("Spaced repetition scheduling",
     "Reviewing material at increasing intervals produces far better long-term retention than cramming the night before.",
     "Docker layer caching",
     "Docker reuses unchanged image layers between builds, so ordering Dockerfile commands from least to most volatile keeps builds fast."),
    ("Git commits are snapshots",
     "Each git commit stores a full snapshot of the tree plus parent pointers, not a diff - diffs are computed on demand.",
     "Sourdough fermentation",
     "A sourdough starter's wild yeast and lactobacilli ferment the dough slowly, developing flavor and an open crumb."),
    ("WSL2 runs a real Linux kernel",
     "WSL2 ships an actual Linux kernel in a lightweight VM, so containers and system calls behave like native Linux.",
     "Attention is quadratic",
     "Transformer self-attention compares every token pair, so compute and memory grow with the square of sequence length."),
    ("Obsidian wikilinks",
     "Double-bracket wikilinks connect notes into a graph that Obsidian renders and traverses natively.",
     "GPU embedding throughput",
     "Running an embedding model on a local GPU turns per-note latency from hundreds of milliseconds into a few."),
]


def _concept(title: str, body: str) -> okf.Concept:
    stamp = okf.now_stamp()
    return okf.Concept(
        slug="calibration-probe", title=title,
        description=store._derive_description(body),
        type="concept", topics=[], sensitivity="normal",
        created=stamp, updated=stamp, body=body,
    )


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _errors(threshold: float, dup_sims: list, distinct_sims: list) -> tuple:
    fn = sum(1 for s in dup_sims if s < threshold)   # near-dup wrongly saved
    fp = sum(1 for s in distinct_sims if s >= threshold)  # distinct wrongly skipped
    return fp, fn


def main() -> int:
    base, model = config.ollama_base_url(), config.embed_model()
    try:
        version = ollama.check_version(base)
    except ollama.OllamaError as e:
        print(f"error: calibration needs the real daemon: {e}", file=sys.stderr)
        return 1
    digest = ollama.model_digest(base, model)

    texts = []
    for a_title, a_body, b_title, b_body in NEAR_DUP_PAIRS + DISTINCT_PAIRS:
        texts.append(vector.embed_text(_concept(a_title, a_body)))
        texts.append(vector.embed_text(_concept(b_title, b_body)))
    vecs = ollama.embed(base, model, texts, timeout=120.0)

    dup_sims = [_cosine(vecs[2 * i], vecs[2 * i + 1]) for i in range(len(NEAR_DUP_PAIRS))]
    off = len(NEAR_DUP_PAIRS)
    distinct_sims = [
        _cosine(vecs[2 * (off + i)], vecs[2 * (off + i) + 1])
        for i in range(len(DISTINCT_PAIRS))
    ]

    grid = [round(0.50 + 0.01 * i, 2) for i in range(50)]  # 0.50 .. 0.99
    scored = [(sum(_errors(t, dup_sims, distinct_sims)), t) for t in grid]
    least = min(err for err, _ in scored)
    band = [t for err, t in scored if err == least]
    chosen = band[len(band) // 2]  # middle of the minimal-error band
    fp, fn = _errors(chosen, dup_sims, distinct_sims)

    def stats(sims):
        return f"min {min(sims):.3f} / mean {sum(sims) / len(sims):.3f} / max {max(sims):.3f}"

    def table(pairs, sims, verdict):
        lines = ["| pair | cosine | correct at threshold |", "| --- | --- | --- |"]
        for (a_title, _, b_title, _), s in zip(pairs, sims):
            ok = (s >= chosen) if verdict == "skip" else (s < chosen)
            lines.append(f"| {a_title} ~ {b_title} | {s:.3f} | {'yes' if ok else 'NO'} |")
        return "\n".join(lines)

    ARTIFACT.write_text(
        f"""# Dedup-threshold calibration (`mem extract`)

generated-by: `uv run python research/dedup_calibration.py`
daemon: Ollama {version} at {base}
model: {model} (digest {digest})
metric: cosine similarity over document embeddings, composed exactly as the
index stores them (`vector.embed_text`: title + description + topics + body,
`search_document:` prefix)

chosen-threshold: {chosen:.2f}

Chosen as the middle of the minimal-error band over a 0.50-0.99 grid
(step 0.01). At this threshold:

- false-positives (distinct pairs at/above threshold, wrongly skipped): {fp} / {len(distinct_sims)}
- false-negatives (near-dup pairs below threshold, wrongly saved): {fn} / {len(dup_sims)}
- minimal-error band: {band[0]:.2f} - {band[-1]:.2f}
- near-duplicate similarities: {stats(dup_sims)}
- distinct-pair similarities: {stats(distinct_sims)}

`config.DEFAULT_DEDUP_THRESHOLD` must equal the chosen-threshold line above;
the test suite asserts it (capstone D024: measured, not guessed). Re-run this
script after changing the embed model, then update the config value to match.

## Near-duplicate pairs (same knowledge reworded -> must skip)

{table(NEAR_DUP_PAIRS, dup_sims, "skip")}

## Distinct pairs (mostly same-domain hard negatives -> must save)

{table(DISTINCT_PAIRS, distinct_sims, "save")}
""",
        encoding="utf-8",
    )

    print(f"wrote {ARTIFACT}")
    print(f"chosen-threshold: {chosen:.2f} (band {band[0]:.2f}-{band[-1]:.2f}, fp {fp}, fn {fn})")
    print(f"near-dup sims: {stats(dup_sims)}")
    print(f"distinct sims: {stats(distinct_sims)}")
    if chosen != config.DEFAULT_DEDUP_THRESHOLD:
        print(
            f"MISMATCH: set config.DEFAULT_DEDUP_THRESHOLD = {chosen:.2f}"
            f" (currently {config.DEFAULT_DEDUP_THRESHOLD})",
            file=sys.stderr,
        )
        return 1
    print(f"config.DEFAULT_DEDUP_THRESHOLD = {config.DEFAULT_DEDUP_THRESHOLD} matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
