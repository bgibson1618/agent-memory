"""scripts/hold-shared-writes.py - reversible profile hold and remote removal,
proved on synthetic files and repositories only. The product behaviour the
hold produces (a marked KB fails closed without a profile, no transport
attempt) is pinned in tests/test_shared_writes.py; here we prove the operator
steps are recorded, reversible and refuse unsafe states."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hold-shared-writes.py"
spec = importlib.util.spec_from_file_location("hold_shared_writes", SCRIPT)
assert spec is not None and spec.loader is not None
hold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hold)


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / ".config" / "agent-sync" / "shared-kb.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"version": 1, "machine": "laptop", "roots": {}}))
    p.chmod(0o600)
    return p


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(repo.parent),
                               "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}).stdout


def _make_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "f").write_text("x\n")
    _git(path, "add", "f")
    _git(path, "commit", "-q", "-m", "seed")
    return path


@pytest.fixture
def repo(tmp_path):
    r = _make_repo(tmp_path / "repo")
    _git(r, "remote", "add", "synthetic-host", "ssh://synthetic@host.invalid/srv/git/kb.git")
    _git(r, "remote", "set-url", "--push", "synthetic-host", "ssh://synthetic@host.invalid/srv/git/kb-push.git")
    return r


def test_hold_profile_is_recorded_and_reversible(profile, tmp_path):
    receipts = tmp_path / "receipts"
    digest = hold.sha256(profile)
    plan = hold.hold_profile(profile, receipts, dry_run=True)
    assert plan["dry_run"] and profile.exists()
    done = hold.hold_profile(profile, receipts, dry_run=False)
    assert not profile.exists() and Path(done["held_as"]).is_file()
    receipt = Path(done["receipt"])
    assert json.loads(receipt.read_text())["sha256"] == digest
    assert receipt.stat().st_mode & 0o777 == 0o600
    with pytest.raises(hold.HoldError):
        hold.hold_profile(profile, receipts, dry_run=False)  # nothing to hold now
    restored = hold.restore_profile(receipt, dry_run=False)
    assert profile.is_file() and hold.sha256(profile) == digest
    assert profile.stat().st_mode & 0o777 == 0o600
    assert Path(restored["receipt"]).is_file() and restored["status"] == "done"
    with pytest.raises(hold.HoldError, match="already exists"):
        hold.restore_profile(receipt, dry_run=False)


def test_restore_profile_refuses_a_changed_held_copy(profile, tmp_path):
    done = hold.hold_profile(profile, tmp_path / "receipts", dry_run=False)
    held = Path(done["held_as"])
    held.write_text(held.read_text() + " ")
    with pytest.raises(hold.HoldError, match="no longer matches"):
        hold.restore_profile(Path(done["receipt"]), dry_run=False)
    assert not profile.exists()


def test_hold_profile_refuses_symlink_and_missing(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(hold.HoldError):
        hold.hold_profile(missing, tmp_path / "r", dry_run=True)
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(hold.HoldError, match="regular file"):
        hold.hold_profile(link, tmp_path / "r", dry_run=True)


def _remote_state(repo, name):
    config = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get-regexp",
                             f"^remote\\.{name}\\."], capture_output=True, text=True).stdout.strip().splitlines()
    refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname) %(symref)",
                f"refs/remotes/{name}/").split()
    return sorted(config), refs


def test_remove_remote_preserves_every_setting_and_tracking_ref(repo, tmp_path):
    receipts = tmp_path / "receipts"
    _git(repo, "config", "--add", "remote.synthetic-host.url", "ssh://synthetic@host.invalid/srv/git/kb-second.git")
    _git(repo, "config", "remote.synthetic-host.tagOpt", "--no-tags")
    _git(repo, "config", "remote.synthetic-host.push", "refs/heads/main:refs/heads/main")
    _git(repo, "config", "remote.synthetic-host.prune", "true")
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/remotes/synthetic-host/main", head)
    _git(repo, "symbolic-ref", "refs/remotes/synthetic-host/HEAD", "refs/remotes/synthetic-host/main")
    before = _remote_state(repo, "synthetic-host")
    assert len(before[0]) >= 6
    assert before[1] == ["refs/remotes/synthetic-host/HEAD", head, "refs/remotes/synthetic-host/main",
                         "refs/remotes/synthetic-host/main", head]

    plan = hold.remove_remote(repo, "synthetic-host", receipts, dry_run=True)
    assert plan["dry_run"] and _remote_state(repo, "synthetic-host") == before
    done = hold.remove_remote(repo, "synthetic-host", receipts, dry_run=False)
    assert done["status"] == "done" and len(done["config"]) == len(before[0])
    assert _git(repo, "remote").strip() == "" and _remote_state(repo, "synthetic-host") == ([], [])
    with pytest.raises(hold.HoldError, match="not configured"):
        hold.remove_remote(repo, "synthetic-host", receipts, dry_run=False)

    restored = hold.restore_remote(Path(done["receipt"]), dry_run=False)
    assert restored["status"] == "done"
    assert _remote_state(repo, "synthetic-host") == before
    assert _git(repo, "symbolic-ref", "refs/remotes/synthetic-host/HEAD").strip() == \
        "refs/remotes/synthetic-host/main"                       # symbolic, not a copied object id
    with pytest.raises(hold.HoldError, match="already exists"):
        hold.restore_remote(Path(done["receipt"]), dry_run=False)


def test_git_environment_overrides_cannot_redirect_the_mutation(repo, tmp_path, monkeypatch):
    other = _make_repo(tmp_path / "other")
    _git(other, "remote", "add", "synthetic-host", "ssh://synthetic@host.invalid/srv/git/other.git")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    done = hold.remove_remote(repo, "synthetic-host", tmp_path / "receipts", dry_run=False)
    assert done["repo"] == str(repo.resolve())
    assert _git(repo, "remote").strip() == ""                     # the named repo changed
    assert _git(other, "remote").strip() == "synthetic-host"       # the override target did not


def test_repo_identity_mismatch_is_refused(repo, tmp_path):
    # A directory that looks like a repository (it has a .git entry) but whose
    # git resolution walks up to the parent repository must be refused.
    sub = repo / "sub"
    (sub / ".git").mkdir(parents=True)
    with pytest.raises(hold.HoldError, match="top level"):
        hold.remove_remote(sub, "synthetic-host", tmp_path / "receipts", dry_run=False)
    assert _git(repo, "remote").strip() == "synthetic-host"


def test_receipt_is_written_before_the_change_and_marks_failure(profile, tmp_path, monkeypatch):
    receipts = tmp_path / "receipts"

    def boom(*a, **k):
        raise OSError("synthetic rename failure")
    monkeypatch.setattr(hold.os, "rename", boom)
    with pytest.raises(OSError, match="synthetic rename failure"):
        hold.hold_profile(profile, receipts, dry_run=False)
    assert profile.exists()
    written = list(receipts.glob("hold-profile-*.json"))
    assert len(written) == 1 and json.loads(written[0].read_text())["status"] == "planned"
    with pytest.raises(hold.HoldError, match="not done"):
        hold.restore_profile(written[0], dry_run=False)


def _trace_fs(monkeypatch, module):
    """Record fsync targets and renames in order (Linux: /proc resolves the fd)."""
    events = []
    real_fsync, real_rename, real_replace = os.fsync, os.rename, os.replace

    def fsync(fd):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = "?"
        events.append(("fsync", target))
        real_fsync(fd)

    def rename(a, b):
        events.append(("rename", str(a)))
        real_rename(a, b)

    def replace(a, b):
        events.append(("replace", str(a)))
        real_replace(a, b)
    monkeypatch.setattr(module.os, "fsync", fsync)
    monkeypatch.setattr(module.os, "rename", rename)
    monkeypatch.setattr(module.os, "replace", replace)
    return events


def test_receipt_directory_entry_is_durable_before_the_mutation(profile, tmp_path, monkeypatch):
    receipts = tmp_path / "receipts"
    events = _trace_fs(monkeypatch, hold)
    hold.hold_profile(profile, receipts, dry_run=False)
    mutation = next(i for i, e in enumerate(events) if e[0] == "rename")
    before = events[:mutation]
    assert ("fsync", str(receipts)) in before, before            # the receipt's directory entry
    assert ("fsync", str(tmp_path)) in before, before            # ...and the new directory's parent
    assert any(e[0] == "fsync" and e[1].startswith(str(receipts) + "/") for e in before)  # the file
    after = events[mutation + 1:]
    assert ("fsync", str(receipts)) in after                     # the "done" rewrite is durable too


def test_nested_receipt_directories_are_created_durably_before_the_mutation(profile, tmp_path, monkeypatch):
    receipts = tmp_path / "a" / "b" / "receipts"
    events = _trace_fs(monkeypatch, hold)
    hold.hold_profile(profile, receipts, dry_run=False)
    mutation = next(i for i, e in enumerate(events) if e[0] == "rename")
    before = events[:mutation]
    for ancestor in (tmp_path, tmp_path / "a", tmp_path / "a" / "b", receipts):
        assert ("fsync", str(ancestor)) in before, (ancestor, before)
    assert receipts.stat().st_mode & 0o777 == 0o700


def test_restore_remote_accepts_a_legacy_two_field_ref_receipt(repo, tmp_path):
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/remotes/synthetic-host/main", head)
    done = hold.remove_remote(repo, "synthetic-host", tmp_path / "receipts", dry_run=False)
    receipt = Path(done["receipt"])
    data = json.loads(receipt.read_text())
    data["refs"] = [entry[:2] for entry in data["refs"]]          # the earlier receipt format
    receipt.write_text(json.dumps(data))
    hold.restore_remote(receipt, dry_run=False)
    assert _git(repo, "rev-parse", "refs/remotes/synthetic-host/main").strip() == head
    bad = json.loads(receipt.read_text())
    bad["refs"] = [["refs/remotes/synthetic-host/main"]]
    receipt.write_text(json.dumps(bad))
    _git(repo, "remote", "remove", "synthetic-host")
    with pytest.raises(hold.HoldError, match="refs entry"):
        hold.restore_remote(receipt, dry_run=False)


def test_slash_in_remote_name_gets_a_safe_receipt_name(repo, tmp_path):
    _git(repo, "remote", "add", "team/host", "ssh://synthetic@host.invalid/srv/git/team.git")
    done = hold.remove_remote(repo, "team/host", tmp_path / "receipts", dry_run=False)
    receipt = Path(done["receipt"])
    assert receipt.parent == tmp_path / "receipts" and "/" not in receipt.name.replace(str(tmp_path), "")
    assert receipt.name.startswith("remove-remote-team_host-")
    hold.restore_remote(receipt, dry_run=False)
    assert "team/host" in _git(repo, "remote").split()


def test_cli_dry_run_changes_nothing(profile, tmp_path):
    out = subprocess.run([sys.executable, str(SCRIPT), "hold-profile", "--profile", str(profile),
                          "--receipts", str(tmp_path / "r"), "--dry-run"], capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["dry_run"] is True
    assert profile.exists() and not (tmp_path / "r").exists()
