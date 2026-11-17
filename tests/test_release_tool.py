"""scripts/release.py - stage, activate, rollback and status, exercised ONLY
against disposable prefixes under tmp_path. The live uv prefix (what `uv tool
dir` means in this environment) is fingerprinted before the module runs and
again after; the two must be identical, so a regression that reaches the live
installation fails here instead of being discovered on a real machine.

Installs use uv with an explicit interpreter; the two tests that install a
package need the package index (or a warm cache) and skip loudly when uv
reports the network unavailable."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import release  # noqa: E402

PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"


def _selection_identity(tool_dir: Path, bin_dir: Path) -> dict:
    """The files that decide what the live `mem` imports: every .pth and
    receipt under the tool directory, the contents of its bin/ programs, and
    the bin directory's entries with their symlink targets. (It does not cover
    wrappers or plugin registries outside these two directories.)"""
    out = {}
    if tool_dir.exists():
        for p in sorted(tool_dir.rglob("*")):
            if p.is_file() and (p.suffix == ".pth" or p.name == "uv-receipt.toml"
                                or p.parent.name == "bin"):
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    if bin_dir.exists():
        for p in sorted(bin_dir.iterdir()):
            out[str(p)] = os.readlink(p) if p.is_symlink() else (
                hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir")
    return out


@pytest.fixture(scope="module", autouse=True)
def live_prefix_untouched():
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    live_tool, live_bin = release.live_default()
    before = _selection_identity(live_tool, live_bin)
    yield
    assert _selection_identity(live_tool, live_bin) == before, \
        "a release-tool test changed a selection-identity file in the live uv prefix"


@pytest.fixture
def prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("UV_OFFLINE", raising=False)
    monkeypatch.setenv("UV_TOOL_DIR", "/nonexistent/live-looking-tool-dir")  # must be ignored
    p = {"tool": tmp_path / "tools", "bin": tmp_path / "bin", "releases": tmp_path / "releases"}
    for d in p.values():
        d.mkdir()
    return p


def _install_or_skip(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except release.ReleaseError as error:
        if any(w in str(error).lower() for w in ("network", "offline", "cache", "resolve")):
            pytest.skip(f"uv could not fetch the package index here: {error}")
        raise


# ------------------------------------------------------------------ stage ----

def test_stage_archives_the_revision_read_only_with_a_manifest(prefix):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    manifest = json.loads((dest / "release.json").read_text())
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    assert manifest["rev"] == head and manifest["id"].endswith(head[:12])
    assert "src/agent_memory/__init__.py" in manifest["files"]
    assert "pyproject.toml" in manifest["files"]
    assert release.verify_release(dest) == manifest
    for path in (dest / "source").rglob("*"):
        assert not os.access(path, os.W_OK)
    with pytest.raises(release.ReleaseError, match="already staged"):
        release.stage(REPO, "HEAD", prefix["releases"])


def test_activate_refuses_a_tampered_release(prefix):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    victim = dest / "source" / "pyproject.toml"
    victim.chmod(0o644)
    victim.write_text(victim.read_text() + "# tampered\n")
    with pytest.raises(release.ReleaseError, match="does not match its manifest"):
        release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    assert not (prefix["tool"] / "agent-memory").exists()


# --------------------------------------------------------- prefix guards ----

def test_uv_env_drops_inherited_redirects_but_keeps_offline(prefix, monkeypatch):
    monkeypatch.setenv("UV_OFFLINE", "1")
    env = release.uv_env(prefix["tool"], prefix["bin"])
    assert env["UV_TOOL_DIR"] == str(prefix["tool"]) and env["UV_TOOL_BIN_DIR"] == str(prefix["bin"])
    assert env.get("UV_OFFLINE") == "1"
    assert not any(k.startswith("UV_") and "TOOL_" in k and k not in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR")
                   for k in env)


def test_live_prefix_refused_before_any_install(prefix, monkeypatch):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    monkeypatch.setattr(release, "live_default",
                        lambda: (prefix["tool"].resolve(), prefix["bin"].resolve()))
    calls = []
    monkeypatch.setattr(release, "_reinstall", lambda *a, **k: calls.append(a))
    with pytest.raises(release.ReleaseError, match="live default prefix"):
        release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    with pytest.raises(release.ReleaseError, match="live default prefix"):
        release.rollback(prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    assert calls == [] and not release.state_path(prefix["releases"]).exists()


# ------------------------------------------------- activate / rollback ----

def test_activate_installs_the_release_and_status_measures_it(prefix):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    report = _install_or_skip(release.activate, dest, prefix["releases"], prefix["tool"], prefix["bin"],
                              python=PYTHON)
    manifest = json.loads((dest / "release.json").read_text())
    assert report["installed"] and report["release"] == manifest["id"]
    assert report["imports"] == "release " + manifest["id"]
    assert Path(report["file"]).is_relative_to(dest / "source")
    assert report["receipt"]["kind"] == "directory"
    assert "editable" not in release.receipt_path(prefix["tool"]).read_text()
    assert list(report["selectors"]) == [release.SELECTOR_NAME]
    state = json.loads(release.state_path(prefix["releases"]).read_text())
    assert state["active"] == manifest["id"] and state["previous"]["receipt"] is None
    # the measured identity comes from the prefix's own executable and entry point
    out = subprocess.run([str(prefix["bin"] / "mem"), "--version"], capture_output=True, text=True,
                         env=release.uv_env(prefix["tool"], prefix["bin"]), timeout=60)
    assert out.returncode == 0 and str(dest / "source" / "src" / "agent_memory") in out.stdout
    assert out.stdout.count("\n") == 1


def test_relative_release_path_is_canonicalized_and_imports_from_any_cwd(prefix, monkeypatch):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    monkeypatch.chdir(prefix["releases"].parent)
    relative = Path(os.path.relpath(dest, prefix["releases"].parent))
    assert not relative.is_absolute()
    _install_or_skip(release.activate, relative, Path("releases"), prefix["tool"], prefix["bin"],
                     python=PYTHON)
    selector = release.site_packages(prefix["tool"]) / release.SELECTOR_NAME
    assert str(dest.resolve() / "source" / "src") in selector.read_text()
    state = json.loads(release.state_path(prefix["releases"]).read_text())
    assert state["release_dir"] == str(dest.resolve()) and state["status"] == "active"
    out = subprocess.run([str(prefix["bin"] / "mem"), "--version"], capture_output=True, text=True,
                         cwd="/", env=release.uv_env(prefix["tool"], prefix["bin"]), timeout=60)
    assert out.returncode == 0 and str(dest.resolve() / "source" / "src" / "agent_memory") in out.stdout


def test_activate_journals_the_previous_state_before_any_change(prefix, monkeypatch):
    _install_or_skip(release._reinstall, prefix["tool"], prefix["bin"], ["-e", str(REPO)], PYTHON)
    site = release.site_packages(prefix["tool"])
    pinned = "import sys; sys.path.insert(0, '/opt/synthetic/previous-release')\n"
    (site / "zz_agent_memory_shared.pth").write_text(pinned)
    receipt_before = release.receipt_path(prefix["tool"]).read_text()
    dest = release.stage(REPO, "HEAD", prefix["releases"])

    def boom(*a, **k):
        raise release.ReleaseError("synthetic installer failure")
    monkeypatch.setattr(release, "_reinstall", boom)
    with pytest.raises(release.ReleaseError, match="synthetic installer failure"):
        release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    state = json.loads(release.state_path(prefix["releases"]).read_text())
    assert state["status"] == "activating"                    # journal written first
    assert state["previous"]["receipt"] == receipt_before
    assert state["previous"]["selectors"] == {"zz_agent_memory_shared.pth": pinned}
    assert (site / "zz_agent_memory_shared.pth").read_text() == pinned   # nothing changed yet
    with pytest.raises(release.ReleaseError, match="did not complete"):
        release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    monkeypatch.undo()
    # the interrupted activate is recoverable from its journal
    restored = _install_or_skip(release.rollback, prefix["releases"], prefix["tool"], prefix["bin"],
                                python=PYTHON)
    assert restored["receipt"]["kind"] == "editable"
    assert (site / "zz_agent_memory_shared.pth").read_text() == pinned
    done = json.loads(release.state_path(prefix["releases"]).read_text())
    assert done["status"] == "rolled-back" and done["interrupted"] is True


def test_journal_directory_entry_is_durable_before_any_change(prefix, monkeypatch):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    events = []
    real_fsync = os.fsync

    def fsync(fd):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = "?"
        events.append(("fsync", target))
        real_fsync(fd)
    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release, "_reinstall", lambda *a, **k: events.append(("reinstall", "")))
    monkeypatch.setattr(release, "_write_selectors", lambda *a, **k: events.append(("selectors", "")))
    monkeypatch.setattr(release, "status", lambda tool_dir: {"stub": True})
    release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    first_change = next(i for i, e in enumerate(events) if e[0] == "reinstall")
    before = events[:first_change]
    releases = str(prefix["releases"].resolve())
    assert ("fsync", releases) in before, before                 # journal entry durable first
    assert any(e[0] == "fsync" and e[1].startswith(releases + "/") for e in before)  # the journal file
    assert [e[0] for e in events if e[0] in ("reinstall", "selectors")] == ["reinstall", "selectors"]
    assert ("fsync", releases) in events[first_change:]          # the "active" rewrite too


def test_fresh_releases_directory_and_staged_tree_are_durable_before_any_change(tmp_path, monkeypatch):
    monkeypatch.delenv("UV_OFFLINE", raising=False)
    tool, bins = tmp_path / "tools", tmp_path / "bin"
    tool.mkdir(); bins.mkdir()
    releases = tmp_path / "new" / "deeper" / "releases"          # none of these exist yet
    events = []
    real_fsync = os.fsync

    def fsync(fd):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = "?"
        events.append(("fsync", target))
        real_fsync(fd)
    monkeypatch.setattr(release.os, "fsync", fsync)
    real_rename = os.rename

    def rename(a, b):
        events.append(("rename", str(a)))
        real_rename(a, b)
    monkeypatch.setattr(release.os, "rename", rename)
    dest = release.stage(REPO, "HEAD", releases)
    staged = len(events)
    targets = [e[1] for e in events]
    for ancestor in (tmp_path, tmp_path / "new", tmp_path / "new" / "deeper"):
        assert str(ancestor) in targets                            # each new ancestor's parent
    # Every file and directory of the staged tree is fsynced BEFORE the rename
    # that makes the release appear, and the releases directory AFTER it.
    rename_at = next(i for i, e in enumerate(events) if e[0] == "rename")
    work = events[rename_at][1]
    before_rename = {e[1] for e in events[:rename_at] if e[0] == "fsync"}
    expected = {str(p) for p in Path(dest).rglob("*")}            # same tree, renamed
    expected_as_work = {s.replace(str(dest), work, 1) for s in expected} | {work}
    assert expected_as_work <= before_rename, sorted(expected_as_work - before_rename)[:5]
    assert any(e == ("fsync", str(releases)) for e in events[rename_at + 1:])
    assert str(dest / "release.json").replace(str(dest), "") == "/release.json"
    monkeypatch.setattr(release, "_reinstall", lambda *a, **k: events.append(("reinstall", "")))
    monkeypatch.setattr(release, "_write_selectors", lambda *a, **k: events.append(("selectors", "")))
    monkeypatch.setattr(release, "status", lambda tool_dir: {"stub": True})
    release.activate(dest, releases, tool, bins, python=PYTHON)
    first_change = next(i for i, e in enumerate(events) if e[0] == "reinstall")
    journal_phase = events[staged:first_change]
    assert ("fsync", str(releases.resolve())) in journal_phase        # journal entry before change
    assert any(e[0] == "fsync" and e[1].endswith("/active.json.tmp") for e in journal_phase)


def test_malformed_active_json_is_refused_before_any_change(prefix, monkeypatch):
    dest = release.stage(REPO, "HEAD", prefix["releases"])
    release.state_path(prefix["releases"]).write_text("{not json")
    calls = []
    monkeypatch.setattr(release, "_reinstall", lambda *a, **k: calls.append(a))
    with pytest.raises(release.ReleaseError, match="unreadable"):
        release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    with pytest.raises(release.ReleaseError, match="unreadable"):
        release.rollback(prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    assert calls == []


def test_failed_staging_leaves_no_directory(prefix, monkeypatch):
    def boom(*a, **k):
        raise release.ReleaseError("synthetic archive failure")
    monkeypatch.setattr(release.tarfile, "open", boom)
    with pytest.raises(release.ReleaseError, match="synthetic archive failure"):
        release.stage(REPO, "HEAD", prefix["releases"])
    assert list(prefix["releases"].iterdir()) == []
    monkeypatch.undo()
    release.stage(REPO, "HEAD", prefix["releases"])          # restaging the same revision works


def test_rollback_restores_an_editable_worktree_and_its_selectors(prefix):
    # Previous state: an editable install of this worktree plus a pinned
    # selector, as a wrapper-verified deployment would have.
    _install_or_skip(release._reinstall, prefix["tool"], prefix["bin"], ["-e", str(REPO)], PYTHON)
    site = release.site_packages(prefix["tool"])
    pinned = "import sys; sys.path.insert(0, '/opt/synthetic/previous-release')\n"
    (site / "zz_agent_memory_shared.pth").write_text(pinned)
    before = release.status(prefix["tool"])
    assert before["receipt"]["kind"] == "editable" and "zz_agent_memory_shared.pth" in before["selectors"]

    dest = release.stage(REPO, "HEAD", prefix["releases"])
    after = release.activate(dest, prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    assert after["receipt"]["kind"] == "directory" and list(after["selectors"]) == [release.SELECTOR_NAME]
    state = json.loads(release.state_path(prefix["releases"]).read_text())
    assert state["previous"]["selectors"] == {"zz_agent_memory_shared.pth": pinned}

    restored = release.rollback(prefix["releases"], prefix["tool"], prefix["bin"], python=PYTHON)
    assert restored["receipt"] == before["receipt"]
    assert (site / "zz_agent_memory_shared.pth").read_text() == pinned
    assert list(restored["selectors"]) == ["zz_agent_memory_shared.pth"]
    done = json.loads(release.state_path(prefix["releases"]).read_text())
    assert done["rolled_back_from"] == state["active"] and done["status"] == "rolled-back"
    assert done["history"][-1]["active"] == state["active"]
