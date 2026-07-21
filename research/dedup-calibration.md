# Dedup-threshold calibration (`mem extract`)

generated-by: `uv run python research/dedup_calibration.py`
daemon: Ollama 0.32.1 at http://127.0.0.1:11434
model: nomic-embed-text:v1.5 (digest 0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f)
metric: cosine similarity over document embeddings, composed exactly as the
index stores them (`vector.embed_text`: title + description + topics + body,
`search_document:` prefix)

chosen-threshold: 0.79

Chosen as the middle of the minimal-error band over a 0.50-0.99 grid
(step 0.01). At this threshold:

- false-positives (distinct pairs at/above threshold, wrongly skipped): 0 / 14
- false-negatives (near-dup pairs below threshold, wrongly saved): 0 / 12
- minimal-error band: 0.77 - 0.81
- near-duplicate similarities: min 0.812 / mean 0.873 / max 0.917
- distinct-pair similarities: min 0.528 / mean 0.658 / max 0.768

`config.DEFAULT_DEDUP_THRESHOLD` must equal the chosen-threshold line above;
the test suite asserts it (capstone D024: measured, not guessed). Re-run this
script after changing the embed model, then update the config value to match.

## Near-duplicate pairs (same knowledge reworded -> must skip)

| pair | cosine | correct at threshold |
| --- | --- | --- |
| Spaced repetition scheduling ~ Why spacing beats cramming | 0.845 | yes |
| Retrieval practice ~ Testing effect | 0.812 | yes |
| RAG grounds LLM answers ~ Retrieval-augmented generation | 0.908 | yes |
| Embedding models map text to vectors ~ What text embeddings do | 0.859 | yes |
| Prompt few-shot examples ~ Few-shot prompting | 0.899 | yes |
| Docker layer caching ~ Fast Docker builds via layer reuse | 0.891 | yes |
| Cosine similarity for embeddings ~ Angle-based vector comparison | 0.917 | yes |
| SQLite WAL mode ~ Why WAL helps concurrency in SQLite | 0.894 | yes |
| Local-first knowledge base ~ Markdown files as the source of truth | 0.843 | yes |
| Agent tool-use loop ~ How agents iterate with tools | 0.864 | yes |
| Interleaving practice ~ Mixed practice beats blocked drills | 0.853 | yes |
| uv manages Python environments ~ Fast Python project isolation with uv | 0.890 | yes |

## Distinct pairs (mostly same-domain hard negatives -> must save)

| pair | cosine | correct at threshold |
| --- | --- | --- |
| Spaced repetition scheduling ~ Interleaving practice | 0.692 | yes |
| Retrieval practice ~ Elaborative encoding | 0.768 | yes |
| RAG grounds LLM answers ~ LLM context window limits | 0.717 | yes |
| Embedding models map text to vectors ~ BM25 lexical ranking | 0.625 | yes |
| Prompt few-shot examples ~ Chain-of-thought prompting | 0.725 | yes |
| Docker layer caching ~ Docker bind mounts | 0.753 | yes |
| Cosine similarity for embeddings ~ Approximate nearest neighbor indexes | 0.737 | yes |
| SQLite WAL mode ~ SQLite FTS5 full-text search | 0.682 | yes |
| Agent tool-use loop ~ MCP standardizes tool access | 0.704 | yes |
| uv manages Python environments ~ Python type hints | 0.590 | yes |
| Spaced repetition scheduling ~ Docker layer caching | 0.600 | yes |
| Git commits are snapshots ~ Sourdough fermentation | 0.528 | yes |
| WSL2 runs a real Linux kernel ~ Attention is quadratic | 0.532 | yes |
| Obsidian wikilinks ~ GPU embedding throughput | 0.563 | yes |
