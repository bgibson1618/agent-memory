"""Frontmatter-only KB transforms for Obsidian. Two modes, run separately:
  links  - related: block items 'slug' -> '"[[slug]]"'
  kebab  - topics:/tags: block items -> kebab-case, deduped in-list
Bodies are never touched; only lines inside the leading --- block.
"""
import glob, re, sys

MODE = sys.argv[1]
assert MODE in ("links", "kebab")

def kebab(s):
    s = s.strip().strip('"').strip("'").lower()
    s = re.sub(r"[\s_/]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return re.sub(r"-{2,}", "-", s).strip("-")

changed = 0
for path in sorted(glob.glob("/home/brent-gibson/.agent-memory/concepts/*.md")):
    lines = open(path, encoding="utf-8").read().split("\n")
    if not lines or lines[0] != "---":
        continue
    try:
        end = lines.index("---", 1)
    except ValueError:
        continue

    out, i, dirty = lines[:1], 1, False
    while i < end:
        ln = lines[i]
        key = re.match(r"^(related|topics|tags):\s*$", ln)
        if not key:
            out.append(ln)
            i += 1
            continue
        out.append(ln)
        i += 1
        items = []
        while i < end and re.match(r"^- ", lines[i]):
            items.append(lines[i][2:])
            i += 1
        k = key.group(1)
        if MODE == "links" and k == "related":
            new = []
            for it in items:
                v = it.strip().strip('"').strip("'")
                if not v.startswith("[["):
                    v = f"[[{v}]]"
                    dirty = True
                new.append(f'- "{v}"')
            out.extend(new)
        elif MODE == "kebab" and k in ("topics", "tags"):
            new = []
            for it in items:
                v = kebab(it)
                if v and v not in [n[2:] for n in new]:
                    new.append(f"- {v}")
            if new != [f"- {x}" for x in items]:
                dirty = True
            out.extend(new)
        else:
            out.extend(f"- {x}" for x in items)
    out.extend(lines[end:])
    if dirty:
        open(path, "w", encoding="utf-8").write("\n".join(out))
        changed += 1

print(f"{MODE}: rewrote {changed} files")
