"""D19 - `mem save --update` merge semantics (DECISION_LOG D19).

`--update` MERGES into the stored concept: a field the invocation omits keeps
its stored value (description is never re-derived from a new body just
because it was omitted); a field passed explicitly replaces the stored value
and is reported on stderr before the write; `--clear FIELD` blanks a
clearable field (description, topics, related) instead of keeping it.
Replays the AP-BPF r5b incident that motivated the change (DECISION_LOG D19)
as a regression test.
"""

import fcntl
import json
import subprocess
import sys
import time
from contextlib import contextmanager

SLUG = "current-and-noncurrent-balance-sheet-classifications"

BODY = (
    "Current and noncurrent balance-sheet classifications separate assets and"
    " liabilities by operating-cycle horizon.\n\n"
    "See [[balance-sheet-basics]].\n"
)


def get_json(mem, slug: str) -> dict:
    result = mem("get", slug, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def save_seed(mem, **overrides):
    args = {
        "title": "Current And Noncurrent Balance Sheet Classifications",
        "body": BODY,
        "description": "Balance sheet items split by operating-cycle horizon.",
        "topics": "accounting, balance-sheet",
        "related": "balance-sheet-basics, ced-3-7",
        "source": "GAAP Codification 210-10",
    }
    args.update(overrides)
    argv = ["save"]
    for key, value in args.items():
        if value is True:
            argv.append(f"--{key}")
        elif value is not None:
            argv.extend([f"--{key}", value])
    return mem(*argv)


def read_version(mem, slug: str) -> str:
    """Every update carries the version of the read it is based on (Stage 1,
    2026-11): a missing or stale --expected-version is refused."""
    return get_json(mem, slug)["version"]


def last_err_line(result) -> str:
    return result.stderr.strip().splitlines()[-1]


# --- merge is the default -----------------------------------------------


def test_bare_update_keeps_every_field_and_only_bumps_updated(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0
    before = get_json(mem, SLUG)
    time.sleep(1.1)  # created/updated carry second precision

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), input="")
    assert result.returncode == 0, result.stderr
    assert result.stderr.strip() == ""  # nothing explicit changed - no warnings

    after = get_json(mem, SLUG)
    assert after["title"] == before["title"]
    assert after["description"] == before["description"]
    assert after["topics"] == before["topics"]
    assert after["type"] == before["type"]
    assert after["sensitivity"] == before["sensitivity"]
    assert after["related"] == before["related"]
    assert after["source"] == before["source"]
    assert after["body"].strip() == before["body"].strip()
    assert after["created"] == before["created"]
    assert after["updated"] > before["updated"]


def test_type_and_sensitivity_kept_when_omitted_explicit_replaces(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem, type="position", sensitivity="work").returncode == 0

    kept = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--topics", "x", input="")
    assert kept.returncode == 0, kept.stderr
    after = get_json(mem, SLUG)
    assert after["type"] == "position"
    assert after["sensitivity"] == "work"

    replaced = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--type", "concept",
                    "--sensitivity", "normal", input="")
    assert replaced.returncode == 0, replaced.stderr
    assert "warning: --update replaces type:" in replaced.stderr
    assert "warning: --update replaces sensitivity:" in replaced.stderr
    after2 = get_json(mem, SLUG)
    assert after2["type"] == "concept"
    assert after2["sensitivity"] == "normal"


def test_d19_incident_replay_partial_update_does_not_clobber_fields(mem, kb):
    """Regression test for the AP-BPF r5b incident (DECISION_LOG D19): a
    partial-field --update meaning only to touch the body must not silently
    reset title, description, related, or topics to derived/empty defaults.

    --title is supplied (the stored title) so this replays the real clobber
    against pre-D19 code: the old parser required --title unconditionally, so
    without it pre-change code fails on argparse alone and never reaches the
    merge logic this test is meant to pin."""
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0
    before = get_json(mem, SLUG)
    assert "ced-3-7" in before["related"]  # the R5-era retag

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--title", before["title"],
                 "--body", "Revised wording for clarity.\n")
    assert result.returncode == 0, result.stderr

    after = get_json(mem, SLUG)
    assert after["title"] == before["title"]
    assert after["description"] == before["description"]
    assert after["related"] == before["related"]
    assert "ced-3-7" in after["related"]
    assert after["topics"] == before["topics"]
    assert after["body"].strip() == "Revised wording for clarity."


# --- explicit replaces, loud warning; identical value is silent ----------


def test_explicit_field_replaces_and_warns(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--title", "Renamed Title", input="")
    assert result.returncode == 0, result.stderr
    assert "warning: --update replaces title:" in result.stderr
    assert get_json(mem, SLUG)["title"] == "Renamed Title"


def test_explicit_topics_and_related_replace_and_warn(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG),
                 "--topics", "new-topic", "--related", "other-concept", input="")
    assert result.returncode == 0, result.stderr
    assert "warning: --update replaces topics:" in result.stderr
    assert "warning: --update replaces related:" in result.stderr
    after = get_json(mem, SLUG)
    assert after["topics"] == ["new-topic"]
    assert after["related"] == ["other-concept"]


def test_identical_explicit_value_emits_no_warning(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG),
                 "--topics", "accounting, balance-sheet", input="")
    assert result.returncode == 0, result.stderr
    assert result.stderr.strip() == ""


# --- --clear -------------------------------------------------------------


def test_clear_description_rederives_from_body(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "description", input="")
    assert result.returncode == 0, result.stderr
    assert "warning: --update replaces description:" in result.stderr
    after = get_json(mem, SLUG)
    assert after["description"] != "Balance sheet items split by operating-cycle horizon."
    assert after["description"]  # non-empty, derived from the body's first line


def test_clear_topics_empties_the_list(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "topics", input="")
    assert result.returncode == 0, result.stderr
    assert get_json(mem, SLUG)["topics"] == []


def test_clear_related_empties_the_list(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "related", input="")
    assert result.returncode == 0, result.stderr
    assert get_json(mem, SLUG)["related"] == []


def test_clear_accepts_repeated_and_comma_separated_fields(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "topics,related", input="")
    assert result.returncode == 0, result.stderr
    after = get_json(mem, SLUG)
    assert after["topics"] == []
    assert after["related"] == []


def test_clear_source_is_refused(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "source", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")
    assert get_json(mem, SLUG)["source"] == "GAAP Codification 210-10"


def test_clear_body_is_refused(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "body", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_clear_title_is_refused(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "title", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_clear_on_fresh_save_is_refused(mem, kb):
    assert mem("init").returncode == 0

    result = save_seed(mem, title="Fresh Clear Probe", clear="topics")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_clear_empty_value_on_fresh_save_is_refused(mem, kb):
    """D19 fix: _parse_clear drops empty CSV pieces before the update-only
    check ran, so `--clear ""` looked like "no --clear" and slipped through
    on a fresh save. Must check the raw --clear argument, not the parsed
    (possibly-empty) field list."""
    assert mem("init").returncode == 0

    result = save_seed(mem, title="Empty Clear Fresh Probe", clear="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_clear_empty_value_on_update_is_refused(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", "", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")
    assert get_json(mem, SLUG)["topics"] == ["accounting", "balance-sheet"]  # untouched


def test_clear_comma_only_value_on_update_is_refused(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--clear", ",", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_clear_conflicts_with_explicit_value(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG),
                 "--clear", "topics", "--topics", "new-topic", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")
    assert get_json(mem, SLUG)["topics"] == ["accounting", "balance-sheet"]


# --- --title optionality ---------------------------------------------------


def test_title_optional_on_update_with_slug(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--topics", "new-topic", input="")
    assert result.returncode == 0, result.stderr
    assert get_json(mem, SLUG)["title"] == "Current And Noncurrent Balance Sheet Classifications"


def test_title_required_on_update_without_slug(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--update", "--expected-version", "0" * 64, "--topics", "new-topic", input="")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


def test_title_required_on_fresh_save(mem, kb):
    assert mem("init").returncode == 0

    result = mem("save", "--body", "Some body.\n")
    assert result.returncode != 0
    assert last_err_line(result).startswith("error:")


# --- body-keep rule ---------------------------------------------------------


def test_body_kept_when_stdin_empty_on_update(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0
    before = get_json(mem, SLUG)

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), "--topics", "new-topic", input="")
    assert result.returncode == 0, result.stderr
    assert get_json(mem, SLUG)["body"].strip() == before["body"].strip()


def test_piped_body_replaces_on_update(mem, kb):
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0

    result = mem("save", "--slug", SLUG, "--update", "--expected-version", read_version(mem, SLUG), input="Piped replacement body.\n")
    assert result.returncode == 0, result.stderr
    assert "warning: --update replaces body:" in result.stderr
    assert get_json(mem, SLUG)["body"].strip() == "Piped replacement body."


# --- fresh-save defaults: unchanged, explicit pin ---------------------------


def test_fresh_save_defaults_are_unchanged(mem, kb):
    assert mem("init").returncode == 0

    result = mem("save", "--title", "Fresh Defaults Probe", "--body", "Body line one.\nMore.\n")
    assert result.returncode == 0, result.stderr
    data = get_json(mem, "fresh-defaults-probe")
    assert data["type"] == "concept"
    assert data["sensitivity"] == "normal"
    assert data["description"] == "Body line one."
    assert data["topics"] == []
    assert data["related"] == []


def test_fresh_save_explicit_empty_description_is_derived(mem, kb):
    """D19 fix: distinguishing omitted-vs-explicit for --update (`is not
    None`) must not change the fresh-save path, which pre-change derived the
    description on any falsey value including an explicit empty string.
    Fresh-save behavior must stay byte-identical to pre-change code."""
    assert mem("init").returncode == 0

    result = mem("save", "--title", "Empty Description Probe",
                 "--body", "Derived body line.\nMore.\n", "--description", "")
    assert result.returncode == 0, result.stderr
    data = get_json(mem, "empty-description-probe")
    assert data["description"] == "Derived body line."


# --- loud warning: field-aware elision (Ruling 5) ---------------------------


def test_long_source_replacement_warns_with_full_values(mem, kb):
    """Ruling 5 elides only long bodies - source (and every other non-body
    field) must show the full old and new values, however long, since that
    is exactly what an audit needs."""
    assert mem("init").returncode == 0
    old_source = "A" * 100
    new_source = "B" * 100
    seed = mem("save", "--title", "Long Source Probe", "--body", "Body.\n", "--source", old_source)
    assert seed.returncode == 0, seed.stderr

    result = mem("save", "--slug", "long-source-probe", "--update", "--expected-version", read_version(mem, "long-source-probe"), "--source", new_source, input="")
    assert result.returncode == 0, result.stderr
    assert old_source in result.stderr
    assert new_source in result.stderr
    assert "..." not in result.stderr


def test_long_body_replacement_warning_is_elided(mem, kb):
    assert mem("init").returncode == 0
    seed = mem("save", "--title", "Long Body Probe", "--body", "Original body.\n")
    assert seed.returncode == 0, seed.stderr

    long_body = "Line " * 40 + "\n"  # well over the 80-char elision threshold
    result = mem("save", "--slug", "long-body-probe", "--update", "--expected-version", read_version(mem, "long-body-probe"), input=long_body)
    assert result.returncode == 0, result.stderr
    assert "warning: --update replaces body:" in result.stderr
    assert "..." in result.stderr


# --- pre-lock merge race (D19 headline fix) ---------------------------------


@contextmanager
def held_write_lock(kb):
    """Hold the KB's write lock (the same flock `mem save` takes) so spawned
    savers pile up behind it; releasing starts the race for real. Mirrors
    tests/test_f7_concurrency.py's fixture of the same name."""
    lock_path = kb.kb / ".index" / "write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def spawn_save(kb, *args) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "agent_memory", "save", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=kb.env,
    )


def test_concurrent_partial_updates_from_one_read_have_one_winner(mem, kb):
    """Stage 1 (2026-11) replaces D19's both-land race. Every update carries
    the version of the read it is based on, so two writers racing from the
    SAME read cannot both land: exactly one wins, the other is refused as
    stale with nothing written, and the loser's partial change never silently
    overwrites the winner's. Both are provably queued on the write lock; the
    loser then succeeds by re-reading and resubmitting with the new version."""
    assert mem("init").returncode == 0
    assert save_seed(mem).returncode == 0
    before = get_json(mem, SLUG)
    token = before["version"]

    with held_write_lock(kb):
        p1 = spawn_save(kb, "--slug", SLUG, "--update", "--expected-version", token,
                        "--topics", "race-topic")
        p2 = spawn_save(kb, "--slug", SLUG, "--update", "--expected-version", token,
                        "--related", "race-related")
        time.sleep(2.5)  # let both processes boot and block on the lock

    outcomes = []
    for proc in (p1, p2):
        out, err = proc.communicate(timeout=60)
        outcomes.append((proc.returncode, out, err))
    assert sorted(rc for rc, _, _ in outcomes) == [0, 1], outcomes
    loser_err = next(err for rc, _, err in outcomes if rc != 0)
    assert "stale local read version" in loser_err

    after = get_json(mem, SLUG)
    assert after["version"] != token
    if outcomes[0][0] == 0:  # topics writer won
        assert after["topics"] == ["race-topic"] and after["related"] == before["related"]
        retry = mem("save", "--slug", SLUG, "--update", "--expected-version", after["version"],
                    "--related", "race-related", input="")
    else:  # related writer won
        assert after["related"] == ["race-related"] and after["topics"] == before["topics"]
        retry = mem("save", "--slug", SLUG, "--update", "--expected-version", after["version"],
                    "--topics", "race-topic", input="")
    assert retry.returncode == 0, retry.stderr
    final = get_json(mem, SLUG)
    assert final["topics"] == ["race-topic"] and final["related"] == ["race-related"]
    # everything neither writer touched survives the race untouched
    assert final["title"] == before["title"]
    assert final["description"] == before["description"]


