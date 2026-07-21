"""F1 - initialized, verified KB home.

Proof for FEATURES.md F1: `mem init` creates the layout + managed blocks
(idempotently, with zero remotes), and `mem doctor` diagnoses truthfully -
including the for-life no-remote invariant and Ollama up/down/wrong states,
all via the sanctioned MEM_OLLAMA_URL seam against an isolated HOME.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path

BEGIN_MARK = "<!-- BEGIN AGENT-MEMORY BLOCK"
END_MARK = "<!-- END AGENT-MEMORY BLOCK -->"
SPAN_RE = re.compile(r"<!-- BEGIN AGENT-MEMORY BLOCK.*?<!-- END AGENT-MEMORY BLOCK -->", re.DOTALL)


def git_kb(kb, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(kb.kb), *args],
        capture_output=True,
        text=True,
        env=kb.env,
        check=True,
    )


def tree_snapshot(root: Path) -> dict:
    """Content hash of everything under the KB home, .git excluded."""
    snap = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if ".git" in rel.parts:
            continue
        snap[str(rel)] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "dir"
        )
    return snap


def doctor_checks(mem, **kwargs):
    result = mem("doctor", "--json", **kwargs)
    data = json.loads(result.stdout)
    return result, {check["name"]: check for check in data["checks"]}


def test_init_creates_layout_with_zero_remotes(mem, kb):
    result = mem("init")
    assert result.returncode == 0, result.stderr
    assert (kb.kb / "concepts").is_dir()
    assert (kb.kb / ".index").is_dir()
    assert (kb.kb / ".git").is_dir()
    assert git_kb(kb, "remote").stdout.strip() == ""


def test_init_is_idempotent(mem, kb):
    assert mem("init").returncode == 0
    snap_before = tree_snapshot(kb.kb)
    log_before = git_kb(kb, "log", "--oneline").stdout

    second = mem("init")
    assert second.returncode == 0, second.stderr
    assert tree_snapshot(kb.kb) == snap_before
    assert git_kb(kb, "log", "--oneline").stdout == log_before
    assert git_kb(kb, "remote").stdout.strip() == ""


def test_init_installs_blocks_preserving_existing_content(mem, kb):
    kb.claude_md.parent.mkdir(parents=True)
    kb.claude_md.write_text("# my existing rules\n\nkeep me\n", encoding="utf-8")

    assert mem("init").returncode == 0

    claude_text = kb.claude_md.read_text(encoding="utf-8")
    assert "keep me" in claude_text
    assert claude_text.count(BEGIN_MARK) == 1
    assert claude_text.count(END_MARK) == 1
    assert "employer-specific" in claude_text

    agents_text = kb.agents_md.read_text(encoding="utf-8")
    assert agents_text.count(BEGIN_MARK) == 1
    assert "Antigravity" in agents_text
    assert "excluded from memory work" in agents_text
    assert "employer-proprietary" in agents_text


def test_init_refresh_never_duplicates_blocks(mem, kb):
    assert mem("init").returncode == 0
    assert mem("init").returncode == 0
    claude_text = kb.claude_md.read_text(encoding="utf-8")
    assert claude_text.count(BEGIN_MARK) == 1

    # Even a corrupted double block heals to exactly one on refresh.
    match = SPAN_RE.search(claude_text)
    assert match is not None
    span = match.group(0)
    kb.claude_md.write_text(claude_text + "\n" + span + "\n", encoding="utf-8")
    assert mem("init").returncode == 0
    healed = kb.claude_md.read_text(encoding="utf-8")
    assert healed.count(BEGIN_MARK) == 1
    assert healed.count(END_MARK) == 1


def test_doctor_all_green_with_daemon_up(mem, kb, fake_ollama):
    env = {"MEM_OLLAMA_URL": fake_ollama.url}
    assert mem("init", env_extra=env).returncode == 0

    result, checks = doctor_checks(mem, env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("kb-home", "git-repo", "no-remote", "blocks-claude", "blocks-agents", "fts5", "ollama", "embed-model"):
        assert checks[name]["status"] == "ok", checks[name]

    text = mem("doctor", env_extra=env)
    assert text.returncode == 0
    assert "doctor: ok" in text.stdout


def test_doctor_ollama_down_one_line_others_still_pass(mem, kb):
    assert mem("init").returncode == 0

    text = mem("doctor")
    assert text.returncode != 0
    fail_lines = [line for line in text.stdout.splitlines() if line.startswith("FAIL")]
    assert len(fail_lines) == 1
    assert "ollama" in fail_lines[0]
    assert "unreachable" in fail_lines[0]

    result, checks = doctor_checks(mem)
    assert result.returncode != 0
    assert checks["ollama"]["status"] == "fail"
    assert checks["embed-model"]["status"] == "skip"
    for name, check in checks.items():
        if name in ("ollama", "embed-model"):
            continue
        assert check["status"] == "ok", check


def test_no_remote_invariant_holds_for_life(mem, kb):
    assert mem("init").returncode == 0
    git_kb(kb, "remote", "add", "origin", "https://github.com/example/leak.git")

    # Doctor fails loudly, naming the remote.
    text = mem("doctor")
    assert text.returncode != 0
    assert "origin" in text.stdout
    _, checks = doctor_checks(mem)
    assert checks["no-remote"]["status"] == "fail"
    assert "origin" in checks["no-remote"]["detail"]

    # Write commands warn until it is removed (init is F1's write surface).
    rerun = mem("init")
    assert rerun.returncode == 0
    assert "origin" in rerun.stderr
    assert "remote" in rerun.stderr.lower()

    git_kb(kb, "remote", "remove", "origin")
    _, checks = doctor_checks(mem)
    assert checks["no-remote"]["status"] == "ok"


def test_doctor_flags_wrong_embedding_dims(mem, kb, fake_ollama_factory):
    server = fake_ollama_factory(dims=512)
    env = {"MEM_OLLAMA_URL": server.url}
    assert mem("init", env_extra=env).returncode == 0

    result, checks = doctor_checks(mem, env_extra=env)
    assert result.returncode != 0
    assert checks["embed-model"]["status"] == "fail"
    assert "512" in checks["embed-model"]["detail"]
    assert "768" in checks["embed-model"]["detail"]


def test_doctor_flags_missing_embedding_model(mem, kb, fake_ollama_factory):
    server = fake_ollama_factory(model="some-other-model:latest")
    env = {"MEM_OLLAMA_URL": server.url}
    assert mem("init", env_extra=env).returncode == 0

    result, checks = doctor_checks(mem, env_extra=env)
    assert result.returncode != 0
    assert checks["ollama"]["status"] == "ok"
    assert checks["embed-model"]["status"] == "fail"
    assert "nomic-embed-text:v1.5" in checks["embed-model"]["detail"]


def test_doctor_before_init_points_at_mem_init(mem, kb):
    result = mem("doctor")
    assert result.returncode != 0
    assert "mem init" in result.stdout


def test_doctor_detects_stale_block_and_init_refreshes(mem, kb):
    assert mem("init").returncode == 0
    text = kb.claude_md.read_text(encoding="utf-8")
    kb.claude_md.write_text(
        text.replace("AGENT-MEMORY BLOCK v1", "AGENT-MEMORY BLOCK v0"), encoding="utf-8"
    )

    result, checks = doctor_checks(mem)
    assert result.returncode != 0
    assert checks["blocks-claude"]["status"] == "fail"

    assert mem("init").returncode == 0
    _, checks = doctor_checks(mem)
    assert checks["blocks-claude"]["status"] == "ok"
    assert kb.claude_md.read_text(encoding="utf-8").count(BEGIN_MARK) == 1
