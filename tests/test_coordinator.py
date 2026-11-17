"""Shared-writer transactions use synthetic concepts and isolated repositories."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from agent_memory import coordinator, gitkb, okf


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def root(tmp_path):
    path = tmp_path / 'kb'
    path.mkdir(mode=0o700)
    (path / 'concepts').mkdir()
    (path / '.gitignore').write_text('.index/\n')
    gitkb.init_repo(path)
    git(path, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    gitkb.commit_all(path, 'fixture')
    return path


def content(slug='one', body='synthetic content'):
    return okf.serialize(okf.Concept(slug=slug, title='Synthetic', description='Fixture',
        type='concept', topics=[], sensitivity='normal', created='2026-10-20T00:00:00Z',
        updated='2026-10-20T00:00:00Z', body=body))


def mutation(slug='one', expected=None, body='synthetic content', delete=False):
    return {'slug': slug, 'expected_version': expected,
            'content': None if delete else content(slug, body)}


def request(*mutations, **extra):
    return {'protocol': 1, 'operation_id': str(uuid.uuid4()),
            'mutations': list(mutations), **extra}


def version(root, slug='one'):
    return hashlib.sha256((root / f'concepts/{slug}.md').read_bytes()).hexdigest()


def test_create_update_delete_and_noop(root):
    initial = git(root, 'rev-list', '--count', 'HEAD')
    created = coordinator.handle(root, request(mutation()))
    assert created['status'] == 'applied'
    assert created['versions'] == {'one': version(root)}
    updated = coordinator.handle(root, request(mutation(expected=version(root), body='New')))
    assert updated['status'] == 'applied'
    assert updated['commit'] != created['commit']
    unchanged = coordinator.handle(root, request(mutation(expected=version(root), body='New')))
    assert unchanged['status'] == 'applied'
    assert unchanged['commit'] == updated['commit']
    deleted = coordinator.handle(root, request(mutation(expected=version(root), delete=True)))
    assert deleted['status'] == 'applied'
    assert deleted['versions'] == {'one': None}
    assert not (root / 'concepts/one.md').exists()
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == int(initial) + 3
    assert not git(root, 'status', '--porcelain')


def test_stale_batch_is_all_or_none_and_replay_conflict_stays_rejected(root):
    coordinator.handle(root, request(mutation()))
    old = version(root)
    coordinator.handle(root, request(mutation(expected=old, body='Another writer')))
    proposal = request(mutation(expected=old, body='Stale'), mutation('two'))
    before = git(root, 'rev-parse', 'HEAD')
    result = coordinator.handle(root, proposal)
    assert result['status'] == 'conflict'
    assert git(root, 'rev-parse', 'HEAD') == before
    assert not (root / 'concepts/two.md').exists()
    assert coordinator.handle(root, proposal)['replayed'] is True


def test_identical_retry_returns_original_commit_after_later_writes(root):
    proposal = request(mutation())
    first = coordinator.handle(root, proposal)
    coordinator.handle(root, request(mutation('two')))
    replay = coordinator.handle(root, proposal)
    assert replay['status'] == 'applied'
    assert replay['commit'] == first['commit']
    assert replay['replayed'] is True
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == 3


def test_same_id_different_payload_rejected(root):
    proposal = request(mutation())
    coordinator.handle(root, proposal)
    proposal['mutations'][0]['content'] = content(body='Changed retry')
    assert coordinator.handle(root, proposal)['code'] == 'operation_id_reused'
    assert version(root) == hashlib.sha256(content().encode()).hexdigest()


def test_expected_head_and_empty_extract_decision(root):
    old = git(root, 'rev-parse', 'HEAD')
    assert coordinator.handle(root, request(expected_head=old))['status'] == 'applied'
    coordinator.handle(root, request(mutation()))
    assert coordinator.handle(root, request(expected_head=old))['status'] == 'conflict'
    assert coordinator.handle(root, request(mutation('two'), expected_head=old))['status'] == 'conflict'


@pytest.mark.parametrize('mut', [
    {'slug': '../escape', 'expected_version': None, 'content': content()},
    {'slug': 'one', 'expected_version': 'wrong', 'content': content()},
    {'slug': 'one', 'expected_version': None, 'content': content('two')},
    {'slug': 'one', 'expected_version': None, 'content': None},
])
def test_invalid_mutation_never_changes_source(root, mut):
    old = git(root, 'rev-parse', 'HEAD')
    assert coordinator.handle(root, request(mut))['status'] == 'error'
    assert git(root, 'rev-parse', 'HEAD') == old
    assert not list((root / 'concepts').iterdir())


def test_preexisting_dirty_files_are_preserved(root):
    path = root / 'concepts/one.md'
    path.write_text('uncommitted user text')
    assert coordinator.handle(root, request(mutation()))['code'] == 'dirty_repository'
    assert path.read_text() == 'uncommitted user text'


def test_duplicate_mutations_refused(root):
    assert coordinator.handle(root, request(mutation(), mutation()))['status'] == 'error'


def test_publish_failure_durable_retry_blocks_later_mutation(root):
    proposal = request(mutation())
    calls = []
    def fail(root, commit):
        calls.append(commit)
        raise OSError('offline')
    result = coordinator.handle(root, proposal, publish_callback=fail)
    assert result['status'] == 'pending'
    committed = result['commit']
    blocked = coordinator.handle(root, request(mutation('two')), publish_callback=fail)
    assert blocked['status'] == 'pending'
    assert not (root / 'concepts/two.md').exists()
    good = coordinator.handle(root, proposal, publish_callback=lambda r, c: calls.append(c))
    assert good['status'] == 'applied'
    assert good['commit'] == committed
    assert len(set(calls)) == 1
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == 2


def crash(root, proposal, stage):
    code = ('import json,sys; from pathlib import Path; from agent_memory import coordinator; '
            'coordinator.handle(Path(sys.argv[1]),json.load(sys.stdin))')
    env = dict(os.environ, MEM_COORDINATOR_FAULT=stage)
    return subprocess.run([sys.executable, '-c', code, str(root)],
        input=json.dumps(proposal), text=True, capture_output=True, env=env, timeout=20)


@pytest.mark.parametrize('stage', ['after_prepare', 'after_ref', 'after_first_file',
                                  'after_materialize', 'after_publish', 'after_receipt'])
def test_crash_retry_commits_exactly_once(root, stage):
    proposal = request(mutation(), mutation('two'))
    assert crash(root, proposal, stage).returncode == 91
    result = coordinator.handle(root, proposal)
    assert result['status'] == 'applied'
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == 2
    assert not git(root, 'status', '--porcelain')
    assert version(root) == hashlib.sha256(content().encode()).hexdigest()
    assert version(root, 'two') == hashlib.sha256(content('two').encode()).hexdigest()


def test_recovery_refuses_unexpected_user_edit(root):
    proposal = request(mutation())
    assert crash(root, proposal, 'after_ref').returncode == 91
    path = root / 'concepts/one.md'
    path.write_text('unexpected user edit')
    result = coordinator.handle(root, proposal)
    assert result['code'] == 'recovery_conflict'
    assert path.read_text() == 'unexpected user edit'
    assert (root / '.index/coordinator/active.json').exists()


def test_lock_is_bounded_and_shared_with_legacy_writer(root):
    import fcntl
    path = root / '.index/write.lock'
    path.parent.mkdir()
    with path.open('w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        result = coordinator.handle(root, request(mutation()), lock_timeout=0.02)
    assert result['status'] == 'busy'


def test_journal_receipt_permissions_and_no_content_in_commit_message(root):
    result = coordinator.handle(root, request(mutation(body='secret synthetic body')))
    for path in (root / '.index/coordinator').rglob('*'):
        assert path.stat().st_mode & 0o077 == 0
    assert 'secret synthetic body' not in git(root, 'log', '-1', '--format=%B')
    assert '.index/' not in git(root, 'ls-tree', '-r', '--name-only', result['commit'])


def test_host_preflight_runs_under_lock_before_creating_transaction(root):
    def refuse(root):
        raise RuntimeError('private endpoint mismatch')
    result = coordinator.handle(root, request(mutation()), preflight_callback=refuse)
    assert result['code'] == 'preflight_failed'
    assert not list((root / 'concepts').iterdir())


def test_unexpected_index_edit_during_recovery_is_preserved(root):
    proposal = request(mutation())
    assert crash(root, proposal, 'after_ref').returncode == 91
    (root / 'extra.txt').write_text('unexpected index edit')
    git(root, 'add', 'extra.txt')
    assert coordinator.handle(root, proposal)['code'] == 'recovery_conflict'
    assert git(root, 'show', ':extra.txt') == 'unexpected index edit'


def test_parallel_updates_accept_only_one_version(root):
    coordinator.handle(root, request(mutation()))
    original = version(root)
    commands = [request(mutation(expected=original, body=f'Writer {i}')) for i in range(2)]
    code = ('import json,sys; from pathlib import Path; from agent_memory import coordinator; '
            'print(json.dumps(coordinator.handle(Path(sys.argv[1]),json.load(sys.stdin))))')
    processes = [subprocess.Popen([sys.executable, '-c', code, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in commands]
    for process, command in zip(processes, commands):
        process.stdin.write(json.dumps(command))
        process.stdin.close()
        process.stdin = None
    results = [json.loads(process.communicate(timeout=20)[0]) for process in processes]
    assert sorted(result['status'] for result in results) == ['applied', 'conflict']
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == 3


def test_parallel_identical_retry_commits_once(root):
    proposal = request(mutation())
    code = ('import json,sys; from pathlib import Path; from agent_memory import coordinator; '
            'print(json.dumps(coordinator.handle(Path(sys.argv[1]),json.load(sys.stdin))))')
    processes = [subprocess.Popen([sys.executable, '-c', code, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)]
    for process in processes:
        process.stdin.write(json.dumps(proposal))
        process.stdin.close()
        process.stdin = None
    results = [json.loads(process.communicate(timeout=20)[0]) for process in processes]
    assert all(result['status'] == 'applied' for result in results)
    assert len({result['commit'] for result in results}) == 1
    assert sorted(result['replayed'] for result in results) == [False, True]
    assert int(git(root, 'rev-list', '--count', 'HEAD')) == 2


def test_read_snapshot_refuses_pending_source_transaction(root):
    assert crash(root, request(mutation()), 'after_ref').returncode == 91
    with pytest.raises(coordinator.CoordinatorError, match='transaction_pending'):
        with coordinator.read_lock(root):
            pytest.fail('pending partial source was exposed as a stable snapshot')


@pytest.mark.parametrize('tamper', ['content', 'digest', 'commit', 'versions'])
def test_corrupt_journal_fails_closed(root, tamper):
    proposal = request(mutation())
    assert crash(root, proposal, 'after_prepare').returncode == 91
    path = root / '.index/coordinator/active.json'
    journal = json.loads(path.read_text())
    if tamper == 'content':
        journal['request']['mutations'][0]['content'] = content(body='Corrupted')
    elif tamper == 'digest':
        journal['digest'] = '0' * 64
    elif tamper == 'commit':
        journal['commit'] = journal['parent']
    else:
        journal['versions']['one'] = '0' * 64
    path.write_text(json.dumps(journal))
    assert coordinator.handle(root, proposal)['status'] == 'pending'
    assert not list((root / 'concepts').iterdir())


def test_private_directory_creation_fsyncs_parent(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(coordinator, '_fsync_dir', lambda p: observed.append(p))
    target = tmp_path / 'private'
    coordinator._private_dir(target)
    assert tmp_path in observed
    assert target in observed


def test_materialization_failure_reports_durable_pending_commit(root, monkeypatch):
    proposal = request(mutation())
    original = coordinator._atomic
    def fail_concept(path, data, temporary_dir=None):
        if path.name == 'one.md':
            raise OSError('synthetic failure')
        return original(path, data, temporary_dir)
    monkeypatch.setattr(coordinator, '_atomic', fail_concept)
    result = coordinator.handle(root, proposal)
    assert result['status'] == 'pending'
    assert result['terminal'] is False
    assert result['action_required'] is True
    assert result['source_committed'] is True
    assert result['commit'] == git(root, 'rev-parse', 'HEAD')
    monkeypatch.setattr(coordinator, '_atomic', original)
    resumed = coordinator.handle(root, proposal)
    assert resumed['status'] == 'applied'
    assert resumed['commit'] == result['commit']


def test_corrupt_receipt_never_claims_success(root):
    proposal = request(mutation())
    coordinator.handle(root, proposal)
    receipt = root / '.index/coordinator/receipts' / (proposal['operation_id'] + '.json')
    saved = json.loads(receipt.read_text())
    saved['result']['commit'] = '0' * 40
    receipt.write_text(json.dumps(saved))
    result = coordinator.handle(root, proposal)
    assert result['status'] == 'pending'
    assert result['terminal'] is False
    assert result['code'] == 'invalid_receipt'
