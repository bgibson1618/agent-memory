"""Private shared-write client checks; all payloads are synthetic."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from agent_memory import cli, extract, gitkb, okf, shared, store


class SharedWrites(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / ".agent-memory"
        (self.root / "concepts").mkdir(parents=True)
        (self.root / ".index").mkdir()
        gitkb.init_repo(self.root)
        (self.root / ".gitignore").write_text(".index/\n")
        gitkb.commit_all(self.root, "fixture")
        self.profile = {
            "version": 1,
            "machine": "laptop",
            "roots": {
                "default": str(self.root),
                "personal": str(self.home / ".agent-memory-personal"),
            },
            "receiver": "/opt/synthetic/agent-sync/privatekb_receiver.py",
            "receiver_python": "/opt/synthetic/uv/tools/agent-memory/bin/python",
            "refresh": "/opt/synthetic/agent-sync/privatekb_refresh.py",
            "transport": {"alias": "synthetic-host", "hostname": "192.0.2.10",
                          "user": "synthetic", "port": 2222},
        }
        profile = self.home / ".config/agent-sync/shared-kb.json"
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps(self.profile))
        profile.chmod(0o600)
        env = patch.dict(os.environ, {"HOME": str(self.home), "MEM_KB_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def mutation(self, body="A synthetic fixture."):
        concept = okf.Concept(
            slug="fixture", title="Fixture", description="Synthetic",
            type="concept", topics=[], sensitivity="normal",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
            related=[], source="test fixture", body=body,
        )
        return {"slug": "fixture", "expected_version": None, "content": okf.serialize(concept)}

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch("agent_memory.vector.opportunistic_drain"):
            rc = cli.main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_request_is_durable_private_before_transport_and_retried_unchanged(self):
        operation = str(uuid.uuid4())
        observed = []

        def lost_reply(profile, envelope):
            observed.append(envelope)
            request_file = self.root / ".index/shared-write/requests" / f"{operation}.json"
            self.assertTrue(request_file.is_file())
            self.assertEqual(request_file.stat().st_mode & 0o777, 0o600)
            raise shared.SharedError("network unavailable")

        with patch.object(shared, "transport", lost_reply):
            result = shared.submit(self.root, [self.mutation()], operation_id=operation)
        self.assertEqual(result["status"], "pending")
        self.assertFalse((self.root / "concepts/fixture.md").exists())

        def recovered(profile, envelope):
            observed.append(envelope)
            return {"protocol": 1, "operation_id": operation, "status": "applied",
                    "commit": "a" * 40, "versions": {"fixture": shared.version(
                        envelope["request"]["mutations"][0]["content"].encode())}}

        with patch.object(shared, "transport", recovered), \
                patch.object(shared, "refresh", return_value=True):
            result = shared.retry(self.root, operation)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(shared.pending(self.root), [])

    def test_operation_id_cannot_be_reused_with_changed_content(self):
        operation = str(uuid.uuid4())
        with patch.object(shared, "transport", side_effect=shared.SharedError("offline")):
            shared.submit(self.root, [self.mutation()], operation_id=operation)
            with self.assertRaises(shared.SharedError):
                shared.submit(self.root, [self.mutation("Changed.")], operation_id=operation)

    def test_missing_profile_cannot_disable_marked_shared_kb(self):
        gitkb._git(self.root, "config", shared.MARKER, "true")
        (self.root / ".index").rmdir()
        (self.home / ".config/agent-sync/shared-kb.json").unlink()
        with self.assertRaises(shared.SharedError):
            shared.profile_for(self.root)

    def test_native_save_does_not_write_source_locally(self):
        seen = []

        def capture(root, mutations, **kwargs):
            seen.extend(mutations)
            return {"status": "applied", "operation_id": str(uuid.uuid4()),
                    "commit": "a" * 40, "replica_current": True}

        with patch.object(shared, "submit", capture):
            rc, _, err = self.call("save", "--title", "Fixture", "--body", "Synthetic body")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0]["expected_version"])
        self.assertFalse((self.root / "concepts/fixture.md").exists())

    def test_shared_update_requires_read_version_and_preserves_existing_fields(self):
        mutation = self.mutation()
        path = self.root / "concepts/fixture.md"
        path.write_text(mutation["content"])
        gitkb.commit_path(self.root, "concepts/fixture.md", "fixture")
        with patch.object(shared, "submit") as submit:
            rc, _, err = self.call("save", "--slug", "fixture", "--update", "--body", "New body")
        self.assertEqual(rc, 1)
        self.assertIn("--expected-version", err)
        submit.assert_not_called()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        seen = []
        def capture(root, mutations, **kwargs):
            seen.extend(mutations)
            return {"status": "applied", "operation_id": str(uuid.uuid4()), "replica_current": True}
        with patch.object(shared, "submit", capture):
            rc, _, err = self.call("save", "--slug", "fixture", "--update",
                                  "--expected-version", digest, "--body", "New body")
        self.assertEqual(rc, 0, err)
        self.assertEqual(seen[0]["expected_version"], digest)
        self.assertEqual(okf.parse(seen[0]["content"]).source, "test fixture")
        self.assertEqual(path.read_text(), mutation["content"])

    def test_get_version_matches_exact_displayed_bytes(self):
        mutation = self.mutation()
        path = self.root / "concepts/fixture.md"
        path.write_text(mutation["content"])
        original_bytes = path.read_bytes()
        original_read = Path.read_bytes
        reads = []

        def read_then_change(p):
            raw = original_read(p)
            if p == path:
                reads.append(p)
                path.write_text(self.mutation("Concurrent replacement.")["content"])
            return raw

        with patch.object(Path, "read_bytes", read_then_change):
            rc, out, err = self.call("get", "fixture", "--json")
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        self.assertEqual(reads, [path])
        self.assertEqual(data["version"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(data["body"], okf.parse(mutation["content"]).body)

    def test_extract_prepares_remapped_batch_and_checks_snapshot(self):
        # Existing slug forces the new concept to take a suffix; a batch-mate's
        # link must point to that suffix in the SAME authoritative transaction.
        (self.root / "concepts/fixture.md").write_text(self.mutation()["content"])
        gitkb.commit_path(self.root, "concepts/fixture.md", "fixture")
        base = shared.clean_head(self.root)
        candidates = [
            {"slug": "fixture", "title": "Different fixture", "body": "Orthogonal A."},
            {"slug": "linked", "title": "Linked", "body": "See [[fixture]]."},
        ]
        seen = []

        def capture(root, mutations, **kwargs):
            seen.append((mutations, kwargs))
            return {"status": "applied", "operation_id": str(uuid.uuid4()),
                    "commit": "a" * 40, "replica_current": True}

        with patch.object(extract.vector, "drain_fully", return_value=(0, 0, None)), \
                patch.object(extract.ollama, "embed", return_value=[[1.0, 0.0], [0.0, 1.0]]), \
                patch.object(extract.vector, "check_meta"), \
                patch.object(extract, "_kb_vectors", return_value=[]), \
                patch.object(extract, "_store_vector") as store_vector, \
                patch.object(shared, "submit", capture):
            rc, out, err = self.call("extract", "--candidates", json.dumps(candidates), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(seen), 1)
        mutations, kwargs = seen[0]
        self.assertEqual(kwargs["expected_head"], base)
        self.assertEqual([m["slug"] for m in mutations], ["fixture-2", "linked"])
        self.assertIn("[[fixture-2]]", okf.parse(mutations[1]["content"]).body)
        self.assertFalse((self.root / "concepts/fixture-2.md").exists())
        self.assertEqual(json.loads(out)["added"], 2)
        store_vector.assert_not_called()

    def test_extract_rejects_source_change_during_embedding(self):
        candidates = [{"title": "Fixture", "body": "Synthetic body."}]

        def change_source(*args, **kwargs):
            gitkb._git(self.root, "commit", "--allow-empty", "-m", "Concurrent change")
            return [[1.0, 0.0]]

        with patch.object(extract.vector, "drain_fully", return_value=(0, 0, None)), \
                patch.object(extract.ollama, "embed", change_source), \
                patch.object(extract.vector, "check_meta"), \
                patch.object(extract, "_kb_vectors", return_value=[]), \
                patch.object(shared, "submit") as submit:
            rc, _, err = self.call("extract", "--candidates", json.dumps(candidates))
        self.assertNotEqual(rc, 0)
        self.assertIn("changed", err)
        submit.assert_not_called()

    def test_old_extract_writer_cannot_bypass_shared_profile(self):
        concept = okf.parse(self.mutation()["content"])
        with self.assertRaises(shared.SharedError):
            extract._save_novel(self.root, concept)
        self.assertFalse((self.root / "concepts/fixture.md").exists())

    def test_transport_keeps_payload_in_stdin_and_pins_private_endpoint(self):
        envelope = {"kb": "default", "request": {"operation_id": str(uuid.uuid4())}}
        response = {"protocol": 1, "operation_id": envelope["request"]["operation_id"],
                    "status": "busy"}
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(response), "")) as run:
            shared.transport(self.profile, envelope)
        kwargs = run.call_args.kwargs
        command = run.call_args.args[0]
        self.assertNotIn(json.dumps(envelope), " ".join(command))
        self.assertEqual(json.loads(kwargs["input"]), envelope)
        self.assertIn("HostName=192.0.2.10", command)
        self.assertIn("User=synthetic", command)
        self.assertIn("Port=2222", command)
        self.assertEqual(command[-2], "synthetic-host")
        self.assertIn("ForwardAgent=no", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("/opt/synthetic/agent-sync/privatekb_receiver.py", command[-1])

    def test_package_source_carries_no_private_endpoint_values(self):
        source = Path(shared.__file__).read_text()
        self.assertNotRegex(source, r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
        self.assertNotIn("/home/", source)
        self.assertNotIn("work-host", source)

    def test_laptop_profile_without_transport_fails_closed_for_its_roots_only(self):
        profile = dict(self.profile)
        del profile["transport"]
        path = self.home / ".config/agent-sync/shared-kb.json"
        path.write_text(json.dumps(profile))
        with self.assertRaisesRegex(shared.SharedError, "transport"):
            shared.profile_for(self.root)
        other = self.home / ".agent-memory-elsewhere"
        (other / "concepts").mkdir(parents=True)
        gitkb.init_repo(other)
        self.assertIsNone(shared.profile_for(other))

    def test_refresh_runs_the_profile_refresh_program(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, "", "")) as run, \
                patch.object(shared, "reconcile_refreshed_receipts"):
            shared.refresh(dict(self.profile, kb="default"))
        self.assertEqual(run.call_args.args[0][1:], [self.profile["refresh"], "default"])

    def test_mismatched_response_is_unknown_outcome_and_pending(self):
        operation = str(uuid.uuid4())
        with patch.object(shared, "transport", return_value={
                "protocol": 1, "operation_id": str(uuid.uuid4()), "status": "applied"}):
            result = shared.submit(self.root, [self.mutation()], operation_id=operation)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(shared.pending(self.root)[0]["operation_id"], operation)

    def test_refresh_failure_does_not_turn_committed_save_into_failed_retry(self):
        operation = str(uuid.uuid4())
        with patch.object(shared, "transport", return_value={
                "protocol": 1, "operation_id": operation, "status": "applied",
                "commit": "a" * 40, "versions": {"fixture": shared.version(
                    self.mutation()["content"].encode())}}), \
                patch.object(shared, "refresh", side_effect=shared.SharedError("refresh failed")):
            result = shared.submit(self.root, [self.mutation()], operation_id=operation)
        self.assertEqual(result["status"], "applied")
        self.assertFalse(result["replica_current"])
        self.assertEqual(shared.pending(self.root)[0]["status"], "refresh_pending")

    def test_incomplete_applied_acknowledgment_remains_pending(self):
        for receipt_fields in [{}, {"commit": "a" * 40, "versions": {"fixture": "b" * 64}}]:
            operation = str(uuid.uuid4())
            response = {"protocol": 1, "operation_id": operation, "status": "applied", **receipt_fields}
            with patch.object(shared, "transport", return_value=response), \
                    patch.object(shared, "refresh") as refresh:
                result = shared.submit(self.root, [self.mutation()], operation_id=operation)
            self.assertEqual(result["status"], "pending")
            refresh.assert_not_called()

    def test_recovery_error_stays_visible_for_inspection(self):
        operation = str(uuid.uuid4())
        with patch.object(shared, "transport", return_value={
                "protocol": 1, "operation_id": operation, "status": "error",
                "code": "recovery_conflict"}):
            result = shared.submit(self.root, [self.mutation()], operation_id=operation)
        self.assertEqual(result["status"], "error")
        self.assertEqual(shared.pending(self.root), [{"operation_id": operation, "status": "error"}])

    def test_new_state_directories_fsync_their_parent(self):
        with patch.object(shared, "_sync_dir") as sync:
            shared._directory(self.root, "requests")
        parents = [call.args[0] for call in sync.call_args_list]
        self.assertIn(self.root / ".index", parents)
        self.assertIn(self.root / ".index/shared-write", parents)

    def test_oversize_request_refused_before_persist_or_transport(self):
        with patch.object(shared, "MAX_REQUEST", 256), \
                patch.object(shared, "transport") as transport:
            with self.assertRaisesRegex(shared.SharedError, "16 MiB"):
                shared.submit(self.root, [self.mutation("é" * 200)])
        transport.assert_not_called()
        self.assertFalse((self.root / ".index/shared-write/requests").exists())

    def test_explicit_refresh_clears_only_receipts_present_in_refreshed_history(self):
        operation = str(uuid.uuid4())
        foreign = str(uuid.uuid4())
        for op, commit in [(operation, shared.clean_head(self.root)), (foreign, "b" * 40)]:
            shared._persist(shared._directory(self.root, "receipts") / f"{op}.json", {
                "protocol": 1, "operation_id": op, "status": "applied",
                "commit": commit, "replica_current": False,
            })
        shared.reconcile_refreshed_receipts(self.root)
        receipts = shared._directory(self.root, "receipts")
        self.assertTrue(json.loads((receipts / f"{operation}.json").read_text())["replica_current"])
        self.assertFalse(json.loads((receipts / f"{foreign}.json").read_text())["replica_current"])


if __name__ == "__main__":
    unittest.main()
