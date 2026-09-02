"""D18 S5 - the durable dedup log: `.index/dedup-log.jsonl`.

Append-only JSONL, explicitly NOT derived (the D8 `usage.jsonl` precedent:
`mem reindex` must leave it alone - it is not knowledge and not rebuildable
from the markdown). Two record types share the file, joined on
`(run_id, candidate_content_hash)`: a `detection` record written by
`mem dedup` (and, in a later wave, `mem extract`), and an `adjudication`
record appended later by `mem dedup --adjudicate` once a human/reviewer has
looked at the flagged candidate. `config` is embedded in every detection
record so a later recalibration never has to guess which thresholds
produced it - the exact failure mode the AP-BPF archive's three-file,
three-vocabulary join (research/d18-dedup-detection-design-2026-09-02.md S3)
suffered from.

Confidentiality: slugs, hashes, numbers, and the candidate/hit TITLE only -
never a card body. `MEM_DEDUP_LOG_TITLES=0` drops even the title, for a
paranoid instance.

Atomicity: each line is kept strictly under `PIPE_BUF` (4,096 bytes,
INCLUDING its trailing newline) and written with one `os.write()` to an
`O_APPEND` file descriptor, which POSIX guarantees is atomic for concurrent
appenders - `mem dedup` standalone takes no write lock (S4.5's Open
Question 2's ratified default); only the extract/save path (a later wave)
writes under the lock it already holds for other reasons. Gate finding 4:
this bound is an INVARIANT, not advisory - every variable-length,
input-controlled field (candidate/hit slug and title, run id, `by`, note
ref, flag-reason/union slug references) is elided to a fixed cap before
serialization, and if no contract-valid representation still fits, the
append is REFUSED (`DedupLogError`), never written oversize.
"""

import json
import os
import random
from pathlib import Path

from agent_memory import okf

LINE_LIMIT = 4096
MAX_INLINE_HITS = 5
MAX_FIELD_CHARS = 200  # bound for elided presentational fields (title/slug/…)
MAX_RUN_ID_CHARS = 256  # run_id is a (run_id, content_hash) JOIN KEY - refuse
                         # rather than elide it, since eliding would silently
                         # break a later --adjudicate's exact-match lookup


class DedupLogError(Exception):
    """A one-line, agent-actionable dedup-log refusal (`--adjudicate` misses,
    or gate finding 4's line-too-long / run-id-too-long refusals)."""


def log_path(root: Path) -> Path:
    return root / ".index" / "dedup-log.jsonl"


def new_run_id() -> str:
    """`MEM_RUN_ID` lets an orchestrated batch (many `mem dedup`/`mem extract`
    calls) share one id so their records join under one run; unset,
    generate a fresh one per invocation. `run_id` is a literal (run_id,
    content_hash) JOIN KEY (S4.5) - refuse a pathologically long forced
    value outright (gate finding 4) rather than elide it, since an elided
    copy stored in a detection record would silently stop matching a later
    `--adjudicate`'s raw argument."""
    forced = os.environ.get("MEM_RUN_ID", "").strip()
    if forced:
        if len(forced) > MAX_RUN_ID_CHARS:
            raise DedupLogError(
                f"MEM_RUN_ID exceeds {MAX_RUN_ID_CHARS} characters - choose a shorter run id"
            )
        return forced
    return f"{okf.now_stamp().replace(':', '').replace('-', '')[:-1]}-{random.randbytes(3).hex()}"


def _encoded_line_len(obj: dict) -> int:
    """The FINAL serialized line's byte length, INCLUDING the trailing
    newline `_append_line` writes - gate finding 4: sizing the bare object
    under-counted by one byte per line, the exact margin that can matter at
    a hard 4,096B boundary."""
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8")) + 1


def _elide(value: str | None, max_chars: int = MAX_FIELD_CHARS) -> str | None:
    """Bound a variable-length, input-controlled field (title/slug/…) to a
    fixed max so no single field can blow the LINE_LIMIT budget - the
    marker's own length is fixed, so the bound holds regardless of how long
    the original string is (gate finding 4: an unbounded 5,000-char title
    produced a 5,000-char slug and a 5,521-byte line)."""
    if value is None or len(value) <= max_chars:
        return value
    return value[:max_chars] + "…[elided]"


def _hit_line(hit: dict, log_titles: bool) -> dict:
    line = {
        "slug": _elide(hit["slug"]),
        "fusion_rank": hit["fusion_rank"],
        "cosine_document": hit["cosine_document"],
        "cosine_best_chunk": hit["cosine_best_chunk"],
        "coverage_of_candidate": hit["coverage_of_candidate"],
        "coverage_of_card": hit["coverage_of_card"],
        "relation": hit["relation"],
    }
    if log_titles:
        line["title"] = _elide(hit["title"])
    return line


def _elide_flag_reasons(reasons: list) -> list:
    out = []
    for fr in reasons:
        fr = dict(fr)
        if fr.get("against"):
            fr["against"] = _elide(fr["against"])
        out.append(fr)
    return out


def build_detection_record(
    *, run_id: str, command: str, detector_version: str,
    embed_model: str, embed_digest: str, config: dict,
    report: dict, log_titles: bool, disposition: str | None = None,
) -> dict:
    """One `report` (a `dedup.detect()` return value) -> one size-bounded
    detection record. Hits are inlined top-5 first (per S4.5); if the
    record is still over `LINE_LIMIT` (a pathologically long title/slug),
    the hit count is progressively cut - `hits_truncated` is set whenever
    fewer hits are inlined than the report actually found, at ANY cut
    depth, since the full deep-K list is always recomputable from a rerun."""
    candidate = {
        "slug_intended": _elide(report["slug_intended"]),
        "content_hash": report["content_hash"],
        "claim_count": report["claim_count"],
    }
    if log_titles:
        candidate["title"] = _elide(report["title"])

    full_hits = report["hits"]
    flag_reasons = _elide_flag_reasons(report["flag_reasons"])
    member_slugs = [_elide(s) for s in report["union"]["member_slugs"]]

    def _record(n_hits: int) -> dict:
        included = full_hits[:n_hits]
        return {
            "record_version": 1,
            "type": "detection",
            "ts": okf.now_stamp(),
            "run_id": run_id,
            "command": command,
            "detector_version": detector_version,
            "embed_model": embed_model,
            "embed_digest": embed_digest,
            "config": config,
            "candidate": candidate,
            "verdict": report["verdict"],
            "flagged": report["flagged"],
            "flag_reasons": flag_reasons,
            "disposition": disposition,
            "hits": [_hit_line(h, log_titles) for h in included],
            "union": {
                "member_slugs": member_slugs,
                "coverage_union": (
                    report["union"]["coverage_curve"][-1]["cumulative_coverage"]
                    if report["union"]["coverage_curve"] else None
                ),
            },
            "hits_truncated": len(included) < len(full_hits),
        }

    for n in (MAX_INLINE_HITS, 3, 1, 0):
        record = _record(n)
        if _encoded_line_len(record) < LINE_LIMIT:
            return record
    # Every variable field is already elided above; the only further lever
    # is dropping the title outright. If even THAT doesn't fit, no
    # contract-valid representation exists - refuse rather than write an
    # oversize line (gate finding 4: never write oversize).
    record["candidate"].pop("title", None)
    if _encoded_line_len(record) < LINE_LIMIT:
        return record
    raise DedupLogError(
        f"detection record for candidate {report.get('content_hash')!r} has no"
        f" representation under {LINE_LIMIT}B even after eliding/truncation - refusing to log it"
    )


def _append_line(root: Path, record: dict) -> None:
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    if len(line) >= LINE_LIMIT:
        # gate finding 4: the atomicity invariant is never advisory - a
        # caller that reaches this (both callers below already elide/bound
        # every variable field first) gets a clean refusal, not a
        # silently-written oversize line that breaks PIPE_BUF atomicity.
        raise DedupLogError(
            f"dedup-log line for run_id={record.get('run_id')!r} would be {len(line)}B,"
            f" over the {LINE_LIMIT}B atomic-append limit - refusing to write it"
        )
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def append_detection(root: Path, record: dict) -> None:
    _append_line(root, record)


def read_records(root: Path) -> list:
    path = log_path(root)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn/corrupt line must not break the reader
    return records


def find_detection(root: Path, run_id: str, candidate_content_hash: str) -> dict | None:
    for record in read_records(root):
        if (
            record.get("type") == "detection"
            and record.get("run_id") == run_id
            and record.get("candidate", {}).get("content_hash") == candidate_content_hash
        ):
            return record
    return None


def append_adjudication(
    root: Path, *, run_id: str, candidate_content_hash: str, label: str,
    by: str | None = None, note_ref: str | None = None,
) -> dict:
    """Append an adjudication record. Refuses (DedupLogError) unless a
    matching detection record already exists to join against - an
    orphan adjudication (typo'd run-id/hash) can never join anything, so
    accepting it silently would corrupt exactly the mechanical-recalibration
    property S4.5 exists to provide."""
    if find_detection(root, run_id, candidate_content_hash) is None:
        raise DedupLogError(
            f"no detection record found for run_id={run_id!r}"
            f" candidate={candidate_content_hash!r} in {log_path(root)}"
        )
    record = {
        "record_version": 1,
        "type": "adjudication",
        "ts": okf.now_stamp(),
        "run_id": run_id,
        "candidate_content_hash": candidate_content_hash,
        "label": label,
        "by": _elide(by),
        "note_ref": _elide(note_ref),
    }
    _append_line(root, record)
    return record
