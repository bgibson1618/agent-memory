"""Stage 1 (2026-11) regressions the acceptance reviewer asked for by name:

- local update-token rejection: a missing, malformed or stale
  --expected-version is refused on an unconfigured local KB with nothing
  written and no commit; the current token succeeds;
- the extraction link-remap race: a competing write that lands on a card
  between its extract save and the remap is detected under the writer lock;
  the remap is refused, the competing content survives, and the earlier
  extract commits remain.
"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_memory import cli, extract, gitkb, okf


# ----------------------------------------------------- update tokens ----

def _commits(kb) -> list:
    return subprocess.run(["git", "-C", str(kb.kb), "log", "--format=%s"], capture_output=True,
                          text=True, env=kb.env, check=True).stdout.strip().splitlines()


def _get(mem, slug) -> dict:
    r = mem("get", slug, "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_local_update_token_rejections_and_acceptance(mem, kb):
    assert mem("init").returncode == 0
    assert mem("save", "--title", "Token probe", "--body", "Original body.\n").returncode == 0
    before = _get(mem, "token-probe")
    commits = _commits(kb)

    missing = mem("save", "--slug", "token-probe", "--update", "--body", "No token.\n")
    assert missing.returncode == 1 and "require" in missing.stderr and "--expected-version" in missing.stderr
    malformed = mem("save", "--slug", "token-probe", "--update", "--expected-version", "abc",
                    "--body", "Bad token.\n")
    assert malformed.returncode == 1 and "must be the read version" in malformed.stderr
    assert _get(mem, "token-probe")["body"] == before["body"] and _commits(kb) == commits

    ok = mem("save", "--slug", "token-probe", "--update", "--expected-version", before["version"],
             "--body", "Second body.\n")
    assert ok.returncode == 0, ok.stderr
    after = _get(mem, "token-probe")
    assert after["body"].strip() == "Second body." and after["version"] != before["version"]
    assert len(_commits(kb)) == len(commits) + 1

    stale = mem("save", "--slug", "token-probe", "--update", "--expected-version", before["version"],
                "--body", "Stale attempt.\n")
    assert stale.returncode == 1 and "stale local read version" in stale.stderr
    assert _get(mem, "token-probe") == after and len(_commits(kb)) == len(commits) + 1


# --------------------------------------------------- remap race ----

class RemapRace(unittest.TestCase):
    """In-process `mem extract` on an unconfigured local KB with a fake
    embedder; a competing writer edits a just-saved card before the remap."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / ".agent-memory"
        (self.root / "concepts").mkdir(parents=True)
        (self.root / ".index").mkdir()
        gitkb.init_repo(self.root)
        (self.root / ".gitignore").write_text(".index/\n")
        existing = okf.Concept(
            slug="fixture", title="Fixture", description="Synthetic", type="concept", topics=[],
            sensitivity="normal", created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
            related=[], source="test fixture", body="A synthetic fixture.",
        )
        (self.root / "concepts/fixture.md").write_text(okf.serialize(existing))
        gitkb.commit_all(self.root, "fixture")
        env = patch.dict(os.environ, {"HOME": str(self.home), "MEM_KB_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch("agent_memory.vector.opportunistic_drain"):
            rc = cli.main(args)
        return rc, out.getvalue(), err.getvalue()

    def _log(self):
        return subprocess.run(["git", "-C", str(self.root), "log", "--format=%s"], capture_output=True,
                              text=True, check=True).stdout.strip().splitlines()

    def test_competing_write_between_save_and_remap_is_refused_and_preserved(self):
        candidates = [
            {"slug": "fixture", "title": "Different fixture", "body": "Orthogonal A."},
            {"slug": "linked", "title": "Linked", "body": "See [[fixture]]."},
        ]
        linked = self.root / "concepts/linked.md"
        original_remap = extract._remap_links
        competing = {"done": False}

        def remap_after_competitor(concept, rename):
            if concept.slug == "linked" and not competing["done"]:
                competing["done"] = True
                # Another writer lands on the card after its extract save and
                # before the remap, exactly as a concurrent `mem save --update`
                # with a current token would.
                linked.write_text(linked.read_text() + "\nCompeting edit.\n")
                gitkb.commit_path(self.root, "concepts/linked.md", "competing writer")
            return original_remap(concept, rename)

        with patch.object(extract.vector, "drain_fully", return_value=(0, 0, None)), \
                patch.object(extract.ollama, "embed", return_value=[[1.0, 0.0], [0.0, 1.0]]), \
                patch.object(extract.vector, "check_meta"), \
                patch.object(extract, "_kb_vectors", return_value=[]), \
                patch.object(extract, "_store_vector"), \
                patch.object(extract.vector, "embed_batch_or_queue", create=True), \
                patch.object(extract, "_remap_links", remap_after_competitor):
            rc, out, err = self.call("extract", "--candidates", json.dumps(candidates), "--json")

        self.assertEqual(rc, 1, (out, err))
        self.assertIn("changed during extraction", err)
        self.assertTrue(competing["done"])
        text = linked.read_text()
        self.assertIn("Competing edit.", text)          # the competitor's content survives
        self.assertIn("[[fixture]]", text)              # the remap did NOT land
        self.assertNotIn("[[fixture-2]]", text)
        log = self._log()
        self.assertIn("competing writer", log)
        self.assertTrue(any(s.startswith("mem extract") and "fixture-2" in s for s in log), log)
        self.assertTrue(any(s.startswith("mem extract") and "linked" in s for s in log), log)
        self.assertTrue((self.root / "concepts/fixture-2.md").is_file())
        clean = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True,
                               text=True, check=True).stdout
        self.assertEqual(clean, "")                     # nothing half-written


if __name__ == "__main__":
    unittest.main()
