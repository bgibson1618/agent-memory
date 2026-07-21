"""RRF fusion - F6: one `mem search` fuses lexical, semantic, and graph evidence.

Three legs, one ranked list: FTS5 BM25 (lexical), cosine over local embeddings
(vector), and 1-hop expansion from the lexical∪vector seeds through wikilink/
related/backlink and topic-node edges (graph). Reciprocal-rank fusion (k=60,
unweighted - ARCHITECTURE's settled design, capstone D021/D023/D045) turns
per-leg ranks into one score; exact ties break toward the more literal leg
(lexical > vector > graph), then the slug. The rerank seam is a deliberate
no-op in v1 - reranking would slot in between rrf() and the caller.
"""

RRF_K = 60

# Graph-leg edge weights: an explicit link is stronger evidence than sharing
# a tag, and a better-ranked seed passes more weight to its neighbors.
LINK_WEIGHT = 1.0
TOPIC_WEIGHT = 0.5


def graph_leg(g, seeds: list) -> list:
    """Rank the seeds' 1-hop neighborhood - pure expansion, seeds excluded
    (their own legs already speak for them). Each neighbor scores by its
    edges back into the seed list; link edges outweigh topic co-membership,
    earlier seeds outweigh later ones."""
    seed_set = set(seeds)
    scores = {}

    def add(slug: str, weight: float) -> None:
        if slug not in seed_set:
            scores[slug] = scores.get(slug, 0.0) + weight

    for position, seed in enumerate(seeds):
        seed_weight = 1.0 / (position + 1)
        neighborhood = g.neighbors(seed)
        for link in neighborhood["links"]:
            add(link["slug"], seed_weight * LINK_WEIGHT)
        for entry in neighborhood["topics"]:
            for member in entry["neighbors"]:
                add(member["slug"], seed_weight * TOPIC_WEIGHT)

    return [slug for slug, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def rrf(legs: list) -> list:
    """Fuse ordered slug lists (most literal leg first) into [(slug, score)],
    best first: score = sum over legs of 1/(RRF_K + rank), rank starting at 1."""
    fused = {}
    for leg_index, leg in enumerate(legs):
        for rank, slug in enumerate(leg, start=1):
            score, first_leg = fused.get(slug, (0.0, leg_index))
            fused[slug] = (score + 1.0 / (RRF_K + rank), first_leg)
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))
    return [(slug, score) for slug, (score, _) in ordered]
