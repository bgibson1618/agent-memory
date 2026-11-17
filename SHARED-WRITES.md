# Historical procedure — a held private deployment mode

This documents the host-mediated shared-write mode built on 2026-10-20 for instances
provisioned by an operator profile and a KB marker. As of 2026-11-17 it is **held**
(DECISION_LOG D20): no instance in this repository's tests is provisioned for it; the four
transport commands (`retry`, `pending`, `refresh`, `delete`) refuse on any instance that is not
both marked and configured; endpoint values live only in the operator profile, never in
source; and nothing in this file grants permission to run these commands against a held
replica. The original text follows unchanged for provenance.

---

# Private shared KB writes

Provisioned instances use work-host as the authority. Agents can draft and search
on either machine concurrently. Only the short source transaction is serialized,
independently for each KB. An explicit save invokes the private receiver over SSH;
there is no daemon, hook, timer, or background retry.

## Commands

Create a concept with the normal command:

```sh
mem save --title "A reusable concept" --body "The explanation." --source "A citation"
```

Read a concept before updating it:

```sh
mem get a-reusable-concept --json
mem save --update --slug a-reusable-concept \
  --expected-version <version-from-get> --body "The revised explanation."
```

The token is a SHA-256 digest of the exact source read. A changed target rejects
the update. Refresh, read the new content, and reconcile your proposal before
submitting a new request. Do not refresh the token and blindly replay an obsolete
replacement body.

```sh
mem pending --json
mem retry <operation-id> --json
mem refresh
```

Each save persists its request privately before contacting the host. If delivery
or acknowledgment is interrupted, retry that exact operation ID. Reusing an ID
for a different request is refused. `pending` is not a confirmed save; an applied
save with `replica_current: false` is confirmed on the host but still needs a local
refresh. An `action_required` result means unexpected state needs investigation,
not repeated retries. No command silently falls back to an independent local write.

For the personal instance, prefix any command with
`MEM_KB_ROOT="$HOME/.agent-memory-personal"`. The default is `~/.agent-memory`.

Deletion also requires a read token:

```sh
mem delete a-reusable-concept --expected-version <version-from-get>
```

## Extraction and consistency

`mem extract` prepares a whole batch, including link remapping, before submitting
one transaction. It checks that the source revision used for duplicate decisions
has not changed. If it has, rerun extraction against refreshed data. Extraction
retains its existing requirement for a functioning local embedding service; this
rollout neither starts Ollama nor changes that policy.

The host commits source atomically and records a recoverable journal before
moving the canonical reference. It publishes the validated commit to the fixed
private hub and refreshes derived indexes before acknowledging completion.
Receipts make duplicate delivery harmless. An unfinished transaction is recovered
before another transaction can proceed. Unexpected manual edits stop recovery.

Local search can lag writes made from the other machine until `mem refresh` or
`kb-sync` runs. Reads are not continuous subscriptions. A successful save refreshes
the submitting machine. Other-machine writes cannot silently overwrite an update
based on a stale local read.

## Boundaries

Only the laptop and work-host are approved destinations. Knowledge bases never go
to GitHub or personal cloud storage. Source Git history contains only concepts and
the existing ignore/endpoint policy. Requests, receipts, indexes, usage and dedup
logs stay in private local runtime directories.

Use `mem` for source writes. Direct editor/Git writes do not participate in the
advisory lock. Dirty trees or uncoordinated history stop the reviewed save/sync
paths; a user with filesystem access can still bypass those paths. Do not bypass
them. Laptop sync is pull-only, and host manual sync cannot publish out-of-band
commits. Preserve such edits and reconcile explicitly.

Do not remove `.index/coordinator` or `.index/shared-write` when rebuilding search
indexes: these contain durable transaction state, not disposable caches.
The independent Git marker `agent-memory.sharedWrites=true` makes a missing
profile fail closed. Config resides in `~/.config/agent-sync/shared-kb.json`.

The existing agent-config sync remains separate. Other migration hooks, schedules,
jobs and freshness checks remain paused.

## Verification and rollback

Run `uv run --locked pytest -q` for the package suite. The deployment also has
synthetic end-to-end checks and private install receipts under the migration
recovery directory. Runtime releases are immutable copies selected by one `.pth`
file; previous files and Git configs are backed up before activation.

Before rolling back, stop accepting shared writes on both machines, preserve all
pending requests/journals/receipts, and reconcile canonical source with its hub.
Do not restore legacy independent writers on one machine while the other still
uses shared writes. Rollback does not justify deleting KB source or Git history.
