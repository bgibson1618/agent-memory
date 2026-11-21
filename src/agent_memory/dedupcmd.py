"""D18 S4 - `mem dedup` command: input sniffing (candidates JSON / `-` /
inline JSON / an OKF card / a plain markdown file), a batch embed shared
across every candidate, per-candidate `dedup.detect()`, JSON/text report
rendering, durable-log writes, and `--adjudicate`.

research/d18-dedup-detection-design-2026-09-02.md S4.1 is the CLI contract
this module implements; `dedup.py` owns the detector itself.
"""

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from agent_memory import config, dedup, deduplog, extract, ollama, okf, store, vector

DETECTOR_VERSION = "1.0.0"
REPORT_VERSION = 1


class DedupCliError(Exception):
    """A one-line, agent-actionable `mem dedup` CLI refusal."""


def _read_input(raw: str) -> str:
    if raw == "-":
        return sys.stdin.read()
    path = Path(raw)
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    if is_file:
        return path.read_text(encoding="utf-8")
    if raw.lstrip().startswith(("[", "{")):
        return raw
    raise DedupCliError(f"no such file: {raw}")


def _concept_from_markdown(text: str, title: str | None) -> okf.Concept:
    if not title:
        m = re.search(r"^#{1,6}[ \t]+(.+)$", text, re.M)
        title = m.group(1).strip() if m else None
    if not title:
        raise DedupCliError("plain-markdown input has no heading - pass --title")
    stamp = okf.now_stamp()
    return okf.Concept(
        slug=okf.slugify(title), title=title.strip(),
        description=store._derive_description(text), type=okf.TYPE_DEFAULT,
        topics=[], sensitivity="normal", created=stamp, updated=stamp,
        related=[], source=f"mem dedup ({stamp[:10]})", body=text,
    ).validate()


def _load_candidates_json(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError as e:
        reason = str(e).splitlines()[0]
        raise DedupCliError(f"candidates are not valid JSON: {reason}") from e
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        data = data["candidates"]
    if not isinstance(data, list):
        raise DedupCliError(
            "candidates JSON must be an array of objects (or {\"candidates\": [...]})"
        )
    return data


def _sniff(text: str, title_flag: str | None) -> list:
    """[(item, is_concept)] - the four input forms S4.1 names: leading
    `[`/`{` -> candidates JSON (item = raw dict, validated like `mem
    extract`'s); leading `---` -> an OKF card (item = the already-valid,
    already-parsed Concept - re-checking an existing card needs no second
    validation pass); otherwise plain markdown (one candidate, title from
    the first heading or `--title`)."""
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        return [(item, False) for item in _load_candidates_json(text)]
    if stripped.startswith("---"):
        try:
            return [(okf.parse(text), True)]
        except okf.OKFError as e:
            raise DedupCliError(f"input looks like an OKF card but failed to parse: {e}") from e
    return [(_concept_from_markdown(text, title_flag), True)]


def _to_concepts(items: list) -> tuple:
    """(valid: [(index, Concept)], invalid: [report dict]) - invalid
    entries already carry the always-present verdict/flagged/
    recommended_action/flag_reasons keys (S4.9's un-misreadable-shape proof;
    gate finding 6 added flag_reasons - a shape-safe consumer must not need
    a key-existence branch for an invalid candidate), matching `mem
    extract`'s per-item validation exactly for the candidates-JSON form
    (same `_to_concept`, same rejection reasons)."""
    valid, invalid = [], []
    for i, (item, is_concept) in enumerate(items):
        if is_concept:
            valid.append((i, item))
            continue
        try:
            valid.append((i, extract._to_concept(item)))
        except okf.OKFError as e:
            title = item.get("title") if isinstance(item, dict) else None
            invalid.append({
                "index": i,
                "title": title if isinstance(title, str) else None,
                "verdict": "invalid",
                "flagged": False,
                "recommended_action": None,
                "flag_reasons": [],
                "reason": str(e),
            })
    return valid, invalid


def _config_dict(cfg, legs_run: list) -> dict:
    return {
        "deep_k": cfg.deep_k,
        "union_m": cfg.union_m,
        "cosine_document_low": cfg.dedup_low,
        "cosine_document_high": cfg.dedup_high,
        "coverage_low": cfg.coverage_low,
        "coverage_high": cfg.coverage_high,
        "coverage_union_low": cfg.union_low,
        "claim_match_lexical": cfg.claim_lex,
        "claim_match_semantic": cfg.claim_sem,
        "legs_run": list(legs_run),
    }


def cmd_dedup(args) -> int:
    try:
        return _dedup(args)
    except (
        DedupCliError, dedup.DedupError, store.StoreError, okf.OKFError, deduplog.DedupLogError,
        vector.VectorError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


_ADJUDICATION_LABELS = ("DUP", "DISTINCT", "FOLD")


def _adjudicate(args, root: Path) -> int:
    if not args.candidate or not args.label:
        raise DedupCliError(
            "--adjudicate requires --candidate HASH and --label {DUP,DISTINCT,FOLD}"
        )
    if args.label not in _ADJUDICATION_LABELS:
        # gate note: argparse's own `choices=` would refuse this with its
        # four-line usage block instead of the project's one-line `error:`
        # convention - validated here instead so the refusal is consistent.
        raise DedupCliError(
            f"--label must be one of {', '.join(_ADJUDICATION_LABELS)}, got {args.label!r}"
        )
    store.require_kb(root)
    deduplog.append_adjudication(
        root, run_id=args.adjudicate, candidate_content_hash=args.candidate,
        label=args.label, by=getattr(args, "by", None),
    )
    print(f"adjudicated: run={args.adjudicate} candidate={args.candidate} label={args.label}")
    return 0


# Gate finding 1: the design's ratified coverage-on default (DECISION_LOG
# D18 §4.4: "coverage flag on in `mem dedup`, off in `mem extract`") never
# actually applied to standalone `mem dedup` - `dedup.load_config()` reads
# the same globally-disabled `config.py` defaults `mem extract` does. This
# overlay substitutes the calibrated values ONLY here, ONLY when the
# instance hasn't set its own MEM_DEDUP_COVERAGE_*/MEM_DEDUP_UNION_LOW -
# `mem extract`'s global defaults (config.py) are untouched, so its byte-
# identical-by-default promise (D18 §4.4) still holds.
_DEDUP_CMD_COVERAGE_LOW_DEFAULT = 0.35
_DEDUP_CMD_COVERAGE_HIGH_DEFAULT = 0.85
_DEDUP_CMD_UNION_LOW_DEFAULT = 0.55


def _apply_command_coverage_defaults(cfg):
    updates = {}
    if cfg.coverage_low is None:
        updates["coverage_low"] = _DEDUP_CMD_COVERAGE_LOW_DEFAULT
    if cfg.coverage_high is None:
        updates["coverage_high"] = _DEDUP_CMD_COVERAGE_HIGH_DEFAULT
    if cfg.union_low is None:
        updates["union_low"] = _DEDUP_CMD_UNION_LOW_DEFAULT
    return replace(cfg, **updates) if updates else cfg


def _dedup(args) -> int:
    root = config.kb_root()
    if args.adjudicate:
        return _adjudicate(args, root)
    if not args.file:
        raise DedupCliError("mem dedup requires FILE (or --adjudicate RUN_ID --candidate HASH --label ...)")

    store.require_kb(root)
    cfg = dedup.load_config()
    cfg = _apply_command_coverage_defaults(cfg)
    # Gate finding 7: CLI overrides must be validated too, AFTER they
    # replace the loaded config - `load_config()`'s own >=1 checks ran
    # before these existed and can't see them, so `--deep-k 0 --top-m 0`
    # previously reached corpus construction unvalidated.
    if args.deep_k is not None:
        if args.deep_k < 1:
            raise DedupCliError(f"--deep-k must be >= 1, got {args.deep_k}")
        cfg = replace(cfg, deep_k=args.deep_k)
    if args.top_m is not None:
        if args.top_m < 1:
            raise DedupCliError(f"--top-m must be >= 1, got {args.top_m}")
        cfg = replace(cfg, union_m=args.top_m)

    text = _read_input(args.file)
    items = _sniff(text, args.title)
    okf_card_input = text.lstrip().startswith("---")
    valid, invalid_results = _to_concepts(items)

    corpus = dedup.build_corpus(root, cfg)
    embed_model = config.embed_model()
    embed_digest = "unknown"
    try:
        precomputed = {}
        if valid:
            texts = [vector.embed_text(c) for _, c in valid]
            try:
                vecs = ollama.embed(
                    config.ollama_base_url(), embed_model, texts, timeout=vector.FULL_DRAIN_TIMEOUT,
                )
                precomputed = {i: vec for (i, _c), vec in zip(valid, vecs)}
                embed_digest = ollama.model_digest(config.ollama_base_url(), embed_model)
                # gate finding 3: identity for the document/chunk scans -
                # set once the batch embed (and thus the digest) is known,
                # before any candidate's detect() runs.
                corpus.embed_model = embed_model
                corpus.embed_digest = embed_digest
            except ollama.OllamaError as e:
                # S4.6's stated property: the lexical coverage leg needs no
                # daemon at all - a batch embed failure degrades this run to
                # coverage-only rather than refusing (unlike `mem extract`,
                # whose contract requires embeddings to gate a save).
                corpus.legs_run = [
                    leg for leg in corpus.legs_run if leg not in ("vector_document", "vector_chunk")
                ]
                corpus.chunk_leg_active = False
                print(f"warning: semantic legs skipped ({e})", file=sys.stderr)

        reports = []
        for i, concept in valid:
            # S6 slice A: re-checking an EXISTING card (an OKF card input whose
            # slug is already in the KB) leaves that card out of its own hits;
            # a new candidate is never excluded by its intended slug.
            exclude = concept.slug if okf_card_input and concept.slug in corpus.title_by_slug else None
            report = dedup.detect(corpus, concept, precomputed.get(i), exclude_slug=exclude)
            report["index"] = i
            reports.append(report)
        legs_run = list(corpus.legs_run)
        concept_count = len(corpus.title_by_slug)
    finally:
        corpus.close()

    vec_con = vector.connect(root)
    try:
        meta = vector.get_meta(vec_con)
        index_dims = int(meta["dims"]) if meta else None
    finally:
        vec_con.close()

    all_results = sorted(reports + invalid_results, key=lambda r: r["index"])
    summary = {"total": len(all_results), "novel": 0, "review_duplicate": 0,
               "confident_duplicate": 0, "invalid": 0}
    for r in all_results:
        key = {"novel": "novel", "review-duplicate": "review_duplicate",
               "confident-duplicate": "confident_duplicate", "invalid": "invalid"}[r["verdict"]]
        summary[key] += 1

    config_dict = _config_dict(cfg, legs_run)
    run_id = deduplog.new_run_id()
    records_written = 0
    do_log = cfg.log and not args.no_log
    if do_log:
        for r in reports:  # invalid candidates were never detected - nothing to log
            record = deduplog.build_detection_record(
                run_id=run_id, command="dedup", detector_version=DETECTOR_VERSION,
                embed_model=embed_model, embed_digest=embed_digest, config=config_dict,
                report=r, log_titles=cfg.log_titles, disposition=None,
            )
            deduplog.append_detection(root, record)
            records_written += 1

    if args.json:
        payload = {
            "report_version": REPORT_VERSION,
            "detector_version": DETECTOR_VERSION,
            "kb": {
                "root": str(root), "concept_count": concept_count,
                "embed_model": embed_model, "embed_digest": embed_digest,
                "index_dims": index_dims,
            },
            "config": config_dict,
            "candidates": all_results,
            "summary": summary,
            "log": {
                "path": str(deduplog.log_path(root)), "run_id": run_id,
                "records_written": records_written,
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_text_report(all_results, cfg, summary, args.explain, legs_run)
    return 0


_DECISION_LABELS = (
    ("coverage_of_candidate_max", "coverage_low"),
    ("coverage_of_candidate_confident", "coverage_high"),
    ("cosine_document_max", "cosine_document_low"),
    ("cosine_document_confident", "cosine_document_high"),
    ("cosine_chunk_max", "cosine_document_low"),
    ("coverage_union", "coverage_union_low"),
)


def _why_lines(result: dict) -> list:
    lines = []
    against_by_signal = {fr["signal"]: fr["against"] for fr in result["flag_reasons"]}
    for name, label in _DECISION_LABELS:
        d = result["decisions"][name]
        if d["value"] is None or d["threshold"] is None:
            continue
        cmp_op = ">=" if d["crossed"] else "< "
        tail = f"(vs '{against_by_signal[name]}')" if name in against_by_signal else "(not crossed)"
        lines.append(f"{name:32s} {d['value']:.4f}  {cmp_op}  {label} {d['threshold']:.4f}  {tail}")
    return lines


def _print_text_report(results: list, cfg, summary: dict, explain: bool, legs_run: list) -> None:
    for r in results:
        if r["verdict"] == "invalid":
            who = f"candidate #{r['index'] + 1}" + (f" ({r['title']})" if r.get("title") else "")
            print(f"invalid: {who} - {r['reason']}")
            continue

        print(f"{r['verdict']}: {r['title']}   [{r['claim_count']} claims]")
        why = _why_lines(r)
        if why:
            print(f"  why: {why[0]}")
            for line in why[1:]:
                print(f"       {line}")
        if r["hits"]:
            best = r["hits"][0]
            print(f"  relation: {best['relation']} -> recommended action: {r['recommended_action']}")
        for h in r["hits"]:
            cos_doc = f"{h['cosine_document']:.4f}" if h["cosine_document"] is not None else "-"
            cos_chunk = f"{h['cosine_best_chunk']:.4f}" if h["cosine_best_chunk"] is not None else "-"
            legs = ",".join(h["legs"]) or "-"
            print(
                f"  #{h['fusion_rank']} {h['slug']:24s} cosine_document {cos_doc}"
                f"  cosine_chunk {cos_chunk}  cov(cand) {h['coverage_of_candidate']:.4f}"
                f"  cov(card) {h['coverage_of_card']:.4f}  [{legs}]"
            )
            if explain:
                for m in h["matched_claims"]:
                    print(
                        f"      match: candidate-claim#{m['candidate_claim']} <->"
                        f" card-claim#{m['card_claim']}  lexical_containment"
                        f" {m['lexical_containment']:.4f}"
                    )
        member_slugs = r["union"]["member_slugs"]
        if member_slugs:
            cov = r["union"]["coverage_curve"][-1]["cumulative_coverage"]
            d = r["decisions"]["coverage_union"]
            cmp_op = (">=" if d["crossed"] else "<") if d["threshold"] is not None else "(no union_low set)"
            thresh = f" {d['threshold']:.4f}" if d["threshold"] is not None else ""
            print(
                f"  union({len(member_slugs)}): {' + '.join(member_slugs)}"
                f" -> coverage_union {cov:.4f} {cmp_op}{thresh}"
            )
        for note in r["notes"]:
            print(f"  note: {note}")

    print(
        f"dedup: {summary['total']} candidate(s), {summary['novel']} novel,"
        f" {summary['review_duplicate']} review-duplicate,"
        f" {summary['confident_duplicate']} confident-duplicate,"
        f" {summary['invalid']} invalid  (deep-k {cfg.deep_k}, legs: {','.join(legs_run)})"
    )
