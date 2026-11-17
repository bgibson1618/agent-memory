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


def _fingerprint(tool_dir: Path) -> dict:
    if not tool_dir.exists():
        return {}
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tool_dir.rglob("*"))
            if p.is_file() and (p.suffix == ".pth" or p.name == "uv-receipt.toml")}


@pytest.fixture(scope="module", autouse=True)
def live_prefix_untouched():
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    live_tool, live_bin = release.live_default()
    before = (_fingerprint(live_tool),
              sorted(p.name for p in live_bin.iterdir()) if live_bin.exists() else [])
    yield
    after = (_fingerprint(live_tool),
             sorted(p.name for p in live_bin.iterdir()) if live_bin.exists() else [])
    assert after == before, "a release-tool test touched the live uv prefix"


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
    assert done["rolled_back_from"] == state["active"]
    assert done["history"][-1]["active"] == state["active"]
