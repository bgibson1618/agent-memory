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


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(r)], check=True, env=env)
    subprocess.run(["git", "-C", str(r), "remote", "add", "synthetic-host",
                    "ssh://synthetic@host.invalid/srv/git/kb.git"], check=True, env=env)
    subprocess.run(["git", "-C", str(r), "remote", "set-url", "--push", "synthetic-host",
                    "ssh://synthetic@host.invalid/srv/git/kb-push.git"], check=True, env=env)
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
    assert Path(restored["restore_receipt"]).is_file()
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


def test_remove_remote_is_recorded_and_reversible(repo, tmp_path):
    receipts = tmp_path / "receipts"
    plan = hold.remove_remote(repo, "synthetic-host", receipts, dry_run=True)
    assert plan["dry_run"] and "synthetic-host" in subprocess.run(
        ["git", "-C", str(repo), "remote"], capture_output=True, text=True).stdout
    done = hold.remove_remote(repo, "synthetic-host", receipts, dry_run=False)
    assert done["fetch_url"].endswith("/kb.git") and done["push_url"].endswith("/kb-push.git")
    assert done["fetch_refspecs"] == ["+refs/heads/*:refs/remotes/synthetic-host/*"]
    assert subprocess.run(["git", "-C", str(repo), "remote"], capture_output=True, text=True).stdout == ""
    with pytest.raises(hold.HoldError, match="not configured"):
        hold.remove_remote(repo, "synthetic-host", receipts, dry_run=False)
    hold.restore_remote(Path(done["receipt"]), dry_run=False)
    urls = subprocess.run(["git", "-C", str(repo), "remote", "-v"], capture_output=True, text=True).stdout
    assert "ssh://synthetic@host.invalid/srv/git/kb.git (fetch)" in urls
    assert "ssh://synthetic@host.invalid/srv/git/kb-push.git (push)" in urls
    refspec = subprocess.run(["git", "-C", str(repo), "config", "--get-all", "remote.synthetic-host.fetch"],
                             capture_output=True, text=True).stdout.split()
    assert refspec == ["+refs/heads/*:refs/remotes/synthetic-host/*"]
    with pytest.raises(hold.HoldError, match="already exists"):
        hold.restore_remote(Path(done["receipt"]), dry_run=False)


def test_cli_dry_run_changes_nothing(profile, tmp_path):
    out = subprocess.run([sys.executable, str(SCRIPT), "hold-profile", "--profile", str(profile),
                          "--receipts", str(tmp_path / "r"), "--dry-run"], capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["dry_run"] is True
    assert profile.exists() and not (tmp_path / "r").exists()
