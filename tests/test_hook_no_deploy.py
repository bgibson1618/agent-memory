"""The post-commit hook never deploys (Stage 1, 2026-11): a commit that touches
src/, pyproject.toml or uv.lock prints one informational line and installs
nothing; a docs-only commit prints nothing. Proved in a scratch clone with fake
`uv` and `mem` programs on PATH that record every invocation."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "git-hooks" / "post-commit"


def _git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True, env=env)


@pytest.fixture
def scratch(tmp_path):
    """A repo wired to the candidate hook, with fake uv/mem on PATH."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    hooks = repo / "scripts" / "git-hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOK, hooks / "post-commit")
    (hooks / "post-commit").chmod(0o755)
    _git(repo, "config", "core.hooksPath", "scripts/git-hooks", env=env)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / "README.md").write_text("docs\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "seed", env=env)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "calls.log"
    for name in ("uv", "mem"):
        script = fake_bin / name
        script.write_text(f"#!/bin/sh\necho \"{name} $*\" >> '{log}'\n"
                          + ("echo 'mem 9.9.9 (fake)'\n" if name == "mem" else "") + "exit 0\n")
        script.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    log.write_text("")
    return repo, env, log


def test_source_commit_installs_nothing_and_names_the_runtime(scratch):
    repo, env, log = scratch
    (repo / "src" / "a.py").write_text("x = 2\n")
    _git(repo, "add", "-A", env=env)
    r = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "src change"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "NOT deployed" in out and "mem 9.9.9 (fake)" in out
    calls = log.read_text().splitlines()
    assert not any(c.startswith("uv") for c in calls), calls      # no installer, ever
    assert calls == ["mem --version"]                              # identity only


def test_docs_commit_is_silent(scratch):
    repo, env, log = scratch
    (repo / "README.md").write_text("docs 2\n")
    _git(repo, "add", "-A", env=env)
    r = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "docs"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and (r.stdout + r.stderr).strip() == ""
    assert log.read_text() == ""


def test_hook_text_has_no_installer_invocation():
    text = HOOK.read_text()
    assert "uv tool install" not in text and "MEM_HOOK_NO_REINSTALL" not in text
