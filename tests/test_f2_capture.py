"""F2 - durable concept capture.

Proof for FEATURES.md F2: `mem save` writes valid OKF markdown that
`mem get`/`mem list` round-trip faithfully; slugs are deterministic and
collision-safe (`--update` to modify); every save is exactly one commit
naming the slug; an interrupted save never leaves a partial file; and the
write path warns while a remote is configured (F1's held-over criterion).
"""

import json
import subprocess
import time

import yaml

BODY = (
    "Spaced repetition schedules reviews at increasing intervals.\n\n"
    "It builds on the [[forgetting-curve]] and pairs well with active recall.\n"
    "Unicode survives: café, naïve, 効率.\n"
)


def git_kb(kb, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(kb.kb), *args],
        capture_output=True,
        text=True,
        env=kb.env,
        check=True,
    )


def commit_subjects(kb) -> list:
    return git_kb(kb, "log", "--format=%s").stdout.strip().splitlines()


def save_fixture(mem, env_extra=None, **overrides):
    args = {
        "title": "Spaced Repetition Scheduling",
        "body": BODY,
        "topics": "learning, memory",
        "related": "forgetting-curve",
    }
    args.update(overrides)
    argv = ["save"]
    for key, value in args.items():
        if value is True:
            argv.append(f"--{key}")
        elif value is not None:
            argv.extend([f"--{key}", value])
    return mem(*argv, env_extra=env_extra)


def get_json(mem, slug: str) -> dict:
    result = mem("get", slug, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_save_writes_valid_okf_and_get_round_trips(mem, kb):
    assert mem("init").returncode == 0
    result = save_fixture(mem)
    assert result.returncode == 0, result.stderr
    assert "spaced-repetition-scheduling" in result.stdout

    path = kb.kb / "concepts" / "spaced-repetition-scheduling.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["id"] == front["slug"] == "spaced-repetition-scheduling"
    assert front["title"] == "Spaced Repetition Scheduling"
    assert front["type"] == "concept"
    assert front["topics"] == ["learning", "memory"]
    assert front["sensitivity"] == "normal"
    assert front["related"] == ["forgetting-curve"]
    assert front["description"]  # derived from the body's first line
    for stamp in (front["created"], front["updated"]):
        assert isinstance(stamp, str) and stamp.endswith("Z"), stamp
    assert "[[forgetting-curve]]" in text  # plain wikilink syntax, Obsidian-openable

    data = get_json(mem, "spaced-repetition-scheduling")
    for key in ("id", "slug", "title", "description", "type", "topics",
                "sensitivity", "created", "updated", "related"):
        assert data[key] == front[key], key
    assert data["body"].strip() == BODY.strip()

    text_out = mem("get", "spaced-repetition-scheduling")
    assert text_out.returncode == 0
    assert "Spaced Repetition Scheduling" in text_out.stdout
    assert "learning, memory" in text_out.stdout
    assert "[[forgetting-curve]]" in text_out.stdout


def test_save_reads_body_from_stdin(mem, kb):
    assert mem("init").returncode == 0
    result = mem("save", "--title", "Stdin Body", "--topics", "io", input=BODY)
    assert result.returncode == 0, result.stderr
    assert get_json(mem, "stdin-body")["body"].strip() == BODY.strip()


def test_work_sensitivity_is_stored(mem, kb):
    assert mem("init").returncode == 0
    result = save_fixture(mem, title="Deploy Runbook", sensitivity="work")
    assert result.returncode == 0, result.stderr
    assert get_json(mem, "deploy-runbook")["sensitivity"] == "work"


def test_slugs_are_deterministic_nfkd_folded(mem, kb):
    assert mem("init").returncode == 0
    result = save_fixture(mem, title="  Café Déjà__Vu!  Über TEST  ")
    assert result.returncode == 0, result.stderr
    assert (kb.kb / "concepts" / "cafe-deja-vu-uber-test.md").is_file()


def test_existing_slug_errors_without_update(mem, kb):
    assert mem("init").returncode == 0
    assert save_fixture(mem).returncode == 0
    path = kb.kb / "concepts" / "spaced-repetition-scheduling.md"
    before_text = path.read_text(encoding="utf-8")
    before_commits = commit_subjects(kb)

    clash = save_fixture(mem, body="Different body entirely.\n")
    assert clash.returncode != 0
    err_lines = clash.stderr.strip().splitlines()
    assert len(err_lines) == 1 and "--update" in err_lines[0], clash.stderr
    assert path.read_text(encoding="utf-8") == before_text
    assert commit_subjects(kb) == before_commits


def test_update_bumps_updated_and_keeps_created(mem, kb):
    assert mem("init").returncode == 0
    assert save_fixture(mem).returncode == 0
    first = get_json(mem, "spaced-repetition-scheduling")

    time.sleep(1.1)  # created/updated carry second precision
    result = save_fixture(mem, body="Revised: intervals should expand ~2.5x.\n", update=True)
    assert result.returncode == 0, result.stderr

    second = get_json(mem, "spaced-repetition-scheduling")
    assert second["created"] == first["created"]
    assert second["updated"] > first["updated"]
    assert "2.5x" in second["body"]


def test_update_requires_an_existing_concept(mem, kb):
    assert mem("init").returncode == 0
    result = save_fixture(mem, title="Never Saved", update=True)
    assert result.returncode != 0
    assert "no concept" in result.stderr


def test_every_save_is_exactly_one_commit_naming_the_slug(mem, kb):
    assert mem("init").returncode == 0
    baseline = len(commit_subjects(kb))

    assert save_fixture(mem).returncode == 0
    assert save_fixture(mem, title="Active Recall").returncode == 0
    assert save_fixture(mem, body="Revised body.\n", update=True).returncode == 0

    subjects = commit_subjects(kb)
    assert len(subjects) == baseline + 3
    assert subjects[0] == "mem update: spaced-repetition-scheduling"
    assert subjects[1] == "mem save: active-recall"
    assert subjects[2] == "mem save: spaced-repetition-scheduling"


def test_list_shows_slugs_titles_and_topics(mem, kb):
    assert mem("init").returncode == 0
    assert save_fixture(mem).returncode == 0
    assert save_fixture(mem, title="Active Recall", topics="learning").returncode == 0

    result = mem("list")
    assert result.returncode == 0
    assert "spaced-repetition-scheduling" in result.stdout
    assert "active-recall" in result.stdout
    assert "learning, memory" in result.stdout

    data = json.loads(mem("list", "--json").stdout)
    by_slug = {item["slug"]: item for item in data}
    assert set(by_slug) == {"spaced-repetition-scheduling", "active-recall"}
    assert by_slug["spaced-repetition-scheduling"]["topics"] == ["learning", "memory"]
    assert "body" not in by_slug["active-recall"]


def test_empty_kb_lists_cleanly(mem, kb):
    assert mem("init").returncode == 0
    result = mem("list")
    assert result.returncode == 0
    assert json.loads(mem("list", "--json").stdout) == []


def test_interrupted_save_leaves_no_partial_file(mem, kb):
    assert mem("init").returncode == 0
    before_commits = commit_subjects(kb)

    crashed = save_fixture(mem, env_extra={"MEM_FAULT": "save-crash-before-rename"})
    assert crashed.returncode != 0
    assert not (kb.kb / "concepts" / "spaced-repetition-scheduling.md").exists()
    assert list((kb.kb / "concepts").glob("*.md")) == []  # no visible debris
    assert commit_subjects(kb) == before_commits

    retry = save_fixture(mem)  # nothing stale blocks the next attempt
    assert retry.returncode == 0, retry.stderr
    assert get_json(mem, "spaced-repetition-scheduling")["body"].strip() == BODY.strip()


def test_save_warns_while_a_remote_is_configured(mem, kb):
    assert mem("init").returncode == 0
    git_kb(kb, "remote", "add", "origin", "https://example.com/should-not-exist.git")

    result = save_fixture(mem)
    assert result.returncode == 0, result.stderr  # save still lands locally
    assert "remote" in result.stderr and "origin" in result.stderr
    assert (kb.kb / "concepts" / "spaced-repetition-scheduling.md").is_file()

    git_kb(kb, "remote", "remove", "origin")
    follow_up = save_fixture(mem, title="After Removal")
    assert follow_up.returncode == 0
    assert follow_up.stderr.strip() == ""


def test_save_before_init_points_at_mem_init(mem, kb):
    result = save_fixture(mem)
    assert result.returncode != 0
    assert "mem init" in result.stderr


def test_save_rejects_empty_body(mem, kb):
    assert mem("init").returncode == 0
    result = save_fixture(mem, body="")
    assert result.returncode != 0
    assert result.stderr.strip().splitlines()[-1].startswith("error:")
