"""D1 (2026-10-15) - the KB may keep a remote whose URL is listed in <kb root>/.allowed-remotes.

Invariants: (1) a remote not listed still fails doctor's no-remote check, naming the file;
(2) listing its exact URL turns the check ok and names the remote; (3) a second, unlisted
remote fails again; (4) write paths warn only about unlisted remotes; (5) comments and blank
lines in the file are ignored; (6) a missing file allows nothing (the pre-D1 behaviour).
"""

import json
import subprocess


def _doctor_check(mem, name):
    r = mem("doctor", "--json")
    data = json.loads(r.stdout)
    return next(c for c in data["checks"] if c["name"] == name)


def _git(kb, *args):
    return subprocess.run(["git", "-C", str(kb.kb), *args], capture_output=True, text=True,
                          env=kb.env, check=True)


def test_allowlisted_remote_passes_and_unlisted_fails(kb, mem):
    assert mem("init").returncode == 0
    assert _doctor_check(mem, "no-remote")["status"] == "ok"

    _git(kb, "remote", "add", "host", "ssh://user@kb-host/srv/git/agent-memory-kb.git")
    check = _doctor_check(mem, "no-remote")
    assert check["status"] == "fail"
    assert "host" in check["detail"] and ".allowed-remotes" in check["detail"]

    (kb.kb / ".allowed-remotes").write_text(
        "# the work host over Tailscale (D1)\n\nssh://user@kb-host/srv/git/agent-memory-kb.git\n",
        encoding="utf-8",
    )
    check = _doctor_check(mem, "no-remote")
    assert check["status"] == "ok", check
    assert "host" in check["detail"]

    _git(kb, "remote", "add", "cloud", "https://example.invalid/kb.git")
    check = _doctor_check(mem, "no-remote")
    assert check["status"] == "fail"
    assert "cloud" in check["detail"] and "host (" not in check["detail"]


def test_write_path_warns_only_on_unlisted_remotes(kb, mem):
    assert mem("init").returncode == 0
    _git(kb, "remote", "add", "host", "ssh://user@kb-host/srv/git/agent-memory-kb.git")

    r = mem("save", "--title", "Remote probe one", "--body", "A body.",
            "--description", "probe", "--topics", "d1")
    assert r.returncode == 0, r.stderr
    assert "not listed in .allowed-remotes" in r.stderr and "host" in r.stderr

    (kb.kb / ".allowed-remotes").write_text(
        "ssh://user@kb-host/srv/git/agent-memory-kb.git\n", encoding="utf-8")
    r = mem("save", "--title", "Remote probe two", "--body", "A body.",
            "--description", "probe", "--topics", "d1")
    assert r.returncode == 0, r.stderr
    assert "not listed in .allowed-remotes" not in r.stderr


def test_missing_allowlist_allows_nothing(kb, mem):
    assert mem("init").returncode == 0
    _git(kb, "remote", "add", "origin", "/srv/git/agent-memory-kb.git")
    assert not (kb.kb / ".allowed-remotes").exists()
    assert _doctor_check(mem, "no-remote")["status"] == "fail"
