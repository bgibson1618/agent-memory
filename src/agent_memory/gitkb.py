"""Git plumbing for the KB repository.

The KB repo's remotes are confined for life: nothing here can add a remote, and
the only remotes permitted are the URLs listed in the KB root's `.allowed-remotes`
file (one URL per line, `#` comments; D1 2026-10-15: the work host over Tailscale).
Doctor fails on any other remote and every write path warns about it.
"""

import subprocess
from pathlib import Path


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True, check=True)
    # Local identity + no signing, so auto-commits never depend on global config.
    _git(root, "config", "user.name", "agent-memory")
    _git(root, "config", "user.email", "agent-memory@localhost")
    _git(root, "config", "commit.gpgsign", "false")


def remotes(root: Path) -> list[str]:
    return _git(root, "remote").stdout.split()


ALLOWED_REMOTES_FILE = ".allowed-remotes"


def allowed_remotes(root: Path) -> set[str]:
    """URLs listed in <root>/.allowed-remotes (D1). Missing file = nothing allowed."""
    path = root / ALLOWED_REMOTES_FILE
    if not path.is_file():
        return set()
    urls: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.add(line)
    return urls


def disallowed_remotes(root: Path) -> list[tuple[str, str]]:
    """(name, url) for every configured remote whose URL is not in .allowed-remotes."""
    allowed = allowed_remotes(root)
    out: list[tuple[str, str]] = []
    for name in remotes(root):
        url = remote_url(root, name) or "no url"
        if url not in allowed:
            out.append((name, url))
    return out


def remote_url(root: Path, name: str) -> str:
    result = _git(root, "remote", "get-url", name, check=False)
    return result.stdout.strip()


def commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    staged = _git(root, "diff", "--cached", "--quiet", check=False)
    if staged.returncode != 0:
        _git(root, "commit", "-q", "-m", message)


def commit_path(root: Path, rel_path: str, message: str) -> bool:
    """Stage and commit exactly one path - one save, one commit, nothing swept in."""
    _git(root, "add", "--", rel_path)
    staged = _git(root, "diff", "--cached", "--quiet", "--", rel_path, check=False)
    if staged.returncode == 0:
        return False
    _git(root, "commit", "-q", "-m", message, "--", rel_path)
    return True
