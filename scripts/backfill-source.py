#!/usr/bin/env python3
"""One-shot D9 backfill: write a `source:` provenance line into every existing
KB concept. Re-runnable: an existing source line is overwritten.

Assignment precedence:
1. Reference concepts (expert-roster, expert-master-index) — generated.
2. mot/cmp cohorts — exact per-chunk citation via the runs' survivor+chunk-map
   artifacts (deterministic joins).
3. Everything else — first-add commit time bucketed into run blocks whose
   boundaries were verified against the known cohort sizes (adds-per-hour
   histogram matches the pipeline README table nearly exactly; see the
   source-backfill run report). The pre-SC morning separates onboarding from
   ambient work-session captures by topic keywords; TBD inside the MAW/TBD
   window is picked by work-sensitivity or TimeBack keywords.

File surgery only (source line after sensitivity; updated/timestamp NOT
bumped). Caller commits, reindexes, reviews the report.
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from agent_memory.okf import slugify  # noqa: E402

import yaml  # noqa: E402

KB = Path.home() / ".agent-memory"
LS = Path.home() / "projects/learning-science/pipeline/runs"
REPORT_DIR = LS / "source-backfill-2026-07-24"
REPORT_DIR.mkdir(exist_ok=True)

ONBOARD = "Alpha onboarding slide decks (5 PDFs; ingested 2026-07-21/22)"
SC = "WF brain lift — Sarah Cottinghatt (Ausubel / assimilation theory; ingested 2026-07-22)"
ZG = "WF brain lift — Zach Groshell (explicit instruction; ingested 2026-07-22)"
BA = "WF brain lift — Becky Allen (assessment design & measurement; ingested 2026-07-22)"
LS_BL = "WF brain lift — Learning Scientist collection (multi-author; ingested 2026-07-22/23)"
TOI = "Engelmann & Carnine, Theory of Instruction (ingested 2026-07-23)"
MAW = "Skycak, The Math Academy Way (ingested 2026-07-23)"
TBD = "TimeBack + Playcademy product documentation (ingested 2026-07-23)"
SOR = "Science of Reading corpus — NRP (2000) + The Reading League defining guide (ingested 2026-07-23)"
CAS = 'Castles, Rastle & Nation (2018) "Ending the Reading Wars" (ingested 2026-07-23)'

# onboarding decks are employer material: alpha/timeback/edtech-operations vocabulary
ONBOARD_KEYWORDS = re.compile(
    r"alpha|timeback|2.?h(ou)?r|1edtech|oneroster|caliper|qti|edtech|coach|campus|"
    r"guide(s)?\b|life.?skills|academics", re.I)
TBD_KEYWORDS = re.compile(r"timeback|playcademy|alpha|2hr|two-hour", re.I)


def first_add_times():
    out = subprocess.run(
        ["git", "-C", str(KB), "log", "--diff-filter=A", "--reverse",
         "--format=@%ad", "--date=format:%Y-%m-%d %H:%M", "--name-only", "--", "concepts/*.md"],
        capture_output=True, text=True, check=True).stdout
    times, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = line[1:]
        elif line.startswith("concepts/") and line.endswith(".md"):
            times.setdefault(line[len("concepts/"):-3], cur)
    return times


def artifact_map(run_dir, survivors_file):
    cmap = {c["chunk"]: c["citation"] for c in json.loads((run_dir / "chunk-map.json").read_text())}
    m = {}
    for c in json.loads((run_dir / survivors_file).read_text()):
        cite = re.sub(r"\s*\(NOTE:.*?\)", "", cmap[c["_chunk"]])
        m[slugify(c["title"])] = cite.strip()
    return m


mot_map = artifact_map(LS / "mot-2026-07-24", "mot-survivors.json")
cmp_map = artifact_map(LS / "cmp-2026-07-24", "cmp-survivors.json")
times = first_add_times()

frontmatters = {}
for path in sorted((KB / "concepts").glob("*.md")):
    head, fm, body = path.read_text(encoding="utf-8").split("---\n", 2)
    frontmatters[path.stem] = yaml.safe_load(fm)

# chronological, first-add order
chrono = sorted((t, s) for s, t in times.items() if s in frontmatters)

assign, review = {}, []
pre_sc = []        # 07-21 through 07-22 14:59 — onboarding + ambient + SC(last 36)
maw_tbd = []       # 07-23 14:00-16:59 — MAW(first 115) + TBD(33)
for t, slug in chrono:
    if slug in ("expert-roster", "expert-master-index"):
        assign[slug] = "generated reference (expert census pipeline)"
    elif slug in mot_map:
        assign[slug] = mot_map[slug]
    elif slug in cmp_map:
        assign[slug] = cmp_map[slug]
    elif t < "2026-07-22 15:00":
        pre_sc.append(slug)
    elif t < "2026-07-22 16:00":
        assign[slug] = ZG
    elif t < "2026-07-22 17:00":
        assign[slug] = BA
    elif t < "2026-07-23 00:00":
        assign[slug] = LS_BL
    elif t < "2026-07-23 11:00":
        assign[slug] = LS_BL          # stage 4
    elif t < "2026-07-23 14:00":
        assign[slug] = TOI
    elif t < "2026-07-23 17:00":
        maw_tbd.append(slug)
    elif t < "2026-07-23 18:00":
        assign[slug] = SOR
    elif t < "2026-07-24 00:00":
        assign[slug] = CAS
    else:
        assign[slug] = f"ambient capture ({t[:10]})"   # 07-24 non-cohort leftovers

# pre-SC morning: last 36 chronologically = Sarah Cottinghatt; the rest split
# onboarding vs ambient by keyword, ambient flagged for review
for i, slug in enumerate(pre_sc):
    if i >= len(pre_sc) - 36:
        assign[slug] = SC
    elif times[slug].startswith("2026-07-21"):
        assign[slug] = ONBOARD        # onboarding ingestion day, pre-pipeline
    else:
        front = frontmatters[slug]
        text = slug + " " + str(front.get("title", "")) + " " + " ".join(front.get("topics") or [])
        if ONBOARD_KEYWORDS.search(text) or front.get("sensitivity") == "work":
            assign[slug] = ONBOARD
        else:
            assign[slug] = f"ambient capture ({times[slug][:10]})"
            review.append({"slug": slug, "assigned": "ambient", "window": "pre-SC 07-22 morning"})

# MAW/TBD window: work-sensitivity or TimeBack keywords pick TBD; else first 115 = MAW
tbd_hits = [s for s in maw_tbd
            if frontmatters[s].get("sensitivity") == "work"
            or TBD_KEYWORDS.search(s + " " + str(frontmatters[s].get("title", "")))]
for i, slug in enumerate(maw_tbd):
    assign[slug] = TBD if slug in tbd_hits or i >= 115 else MAW

missing = [s for s in frontmatters if s not in assign]
assert not missing, missing[:5]

patched = 0
for slug, cite in assign.items():
    path = KB / "concepts" / f"{slug}.md"
    text = path.read_text(encoding="utf-8")
    head, fm, body = text.split("---\n", 2)
    line = yaml.safe_dump({"source": cite}, allow_unicode=True, width=1000).rstrip("\n")
    if re.search(r"^source:", fm, flags=re.M):
        fm = re.sub(r"^source: .*$", line, fm, count=1, flags=re.M)
    else:
        fm = re.sub(r"^(sensitivity: .*)$", rf"\1\n{line}", fm, count=1, flags=re.M)
    assert "source:" in fm, slug
    path.write_text(f"{head}---\n{fm}---\n{body}", encoding="utf-8")
    patched += 1

counts = Counter(assign.values())
report = {"patched": patched, "total": len(frontmatters),
          "ambient_reassignments_for_review": review,
          "tbd_keyword_hits": len(tbd_hits),
          "cohort_counts": {k: v for k, v in counts.most_common()}}
(REPORT_DIR / "backfill-report.json").write_text(json.dumps(report, indent=1))
print(f"patched {patched}/{len(frontmatters)}")
print(f"pre-SC ambient flagged for review: {len(review)}; TBD keyword/sensitivity hits: {len(tbd_hits)}")
for k, v in counts.most_common(14):
    print(f"  {v:5d}  {k[:78]}")
