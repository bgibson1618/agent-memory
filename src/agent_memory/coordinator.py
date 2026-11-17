"""Short, recoverable source transactions for a private authoritative KB.

The caller owns endpoint policy and transport. This module never opens a network
connection. Its journal and receipts are local runtime data, excluded from Git.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from agent_memory import okf


class CoordinatorError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _fault(stage):
    if os.environ.get('MEM_COORDINATOR_FAULT') == stage:
        os._exit(91)


def _git(root, *args, data=None, index=None):
    env = {key: val for key, val in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
    if index is not None:
        env['GIT_INDEX_FILE'] = str(index)
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               '-c', 'core.attributesFile=/dev/null', '-c', 'core.autocrlf=false',
               '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.fsync=all',
               '-c', 'protocol.allow=never', '-c', 'commit.gpgsign=false',
               '-c', 'user.name=agent-memory', '-c', 'user.email=agent-memory@localhost',
               '-C', str(root), *args]
    result = subprocess.run(command, input=data, capture_output=True, env=env, timeout=30)
    if result.returncode:
        raise CoordinatorError('git_failed')
    return result.stdout


def _private_dir(path):
    if path.is_symlink():
        raise CoordinatorError('unsafe_runtime_path')
    created = not path.exists()
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise CoordinatorError('unsafe_runtime_path')
    path.chmod(0o700)
    _fsync_dir(path)
    if created:
        _fsync_dir(path.parent)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path, data, temporary_dir=None):
    if path.is_symlink():
        raise CoordinatorError('unsafe_runtime_path')
    fd, temporary = tempfile.mkstemp(prefix='.coordinator-', dir=temporary_dir or path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _write_json(path, data):
    _atomic(path, _canonical(data) + b'\n')


def _read_json(path):
    if path.is_symlink() or not path.is_file():
        raise CoordinatorError('unsafe_runtime_path')
    return json.loads(path.read_bytes())


@contextmanager
def _lock(root, timeout):
    index = root / '.index'
    _private_dir(index)
    path = index / 'write.lock'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        end = time.monotonic() + max(0, timeout)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise CoordinatorError('writer_busy') from None
                time.sleep(min(0.025, max(0, end - time.monotonic())))
        yield
    finally:
        os.close(fd)


def _validate_request(request):
    if not isinstance(request, dict) or set(request) - {
        'protocol', 'operation_id', 'mutations', 'expected_head'
    }:
        raise CoordinatorError('invalid_request')
    if type(request.get('protocol')) is not int or request['protocol'] != 1:
        raise CoordinatorError('invalid_request')
    operation_id = request.get('operation_id')
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise CoordinatorError('invalid_operation_id') from None
    if request.get('expected_head') is not None and not re.fullmatch(
        r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(request['expected_head'])
    ):
        raise CoordinatorError('invalid_expected_head')
    mutations = request.get('mutations')
    if not isinstance(mutations, list) or len(mutations) > 2048:
        raise CoordinatorError('invalid_mutations')
    seen = set()
    for mutation in mutations:
        if not isinstance(mutation, dict) or set(mutation) != {
            'slug', 'expected_version', 'content'
        }:
            raise CoordinatorError('invalid_mutation')
        slug, expected, content = (mutation[key] for key in
                                   ('slug', 'expected_version', 'content'))
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise CoordinatorError('invalid_slug')
        if slug in seen or slug in okf.RESERVED_SLUGS:
            raise CoordinatorError('invalid_slug')
        seen.add(slug)
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(
                r'[0-9a-f]{64}', expected)):
            raise CoordinatorError('invalid_expected_version')
        if content is None:
            if expected is None:
                raise CoordinatorError('delete_requires_version')
        elif not isinstance(content, str):
            raise CoordinatorError('invalid_content')
        else:
            try:
                concept = okf.parse(content).validate()
                if concept.slug != slug:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError, KeyError):
                raise CoordinatorError('invalid_content') from None
    if len(_canonical(request)) > 32 * 1024 * 1024:
        raise CoordinatorError('request_too_large')


def _validate_repo(root):
    for path in (root, root / '.git', root / 'concepts'):
        if path.is_symlink() or not path.is_dir():
            raise CoordinatorError('invalid_repository')
    if _git(root, 'rev-parse', '--show-toplevel').decode().strip() != str(root.resolve()):
        raise CoordinatorError('invalid_repository')
    if _git(root, 'symbolic-ref', '--quiet', 'HEAD').strip() != b'refs/heads/main':
        raise CoordinatorError('main_required')
    for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-apply', 'rebase-merge'):
        if (root / '.git' / name).exists():
            raise CoordinatorError('git_operation_in_progress')


def _file_version(path):
    if path.is_symlink():
        raise CoordinatorError('unsafe_concept_path')
    if not path.exists():
        return None
    if not path.is_file():
        raise CoordinatorError('unsafe_concept_path')
    return version(path.read_bytes())


def _head(root):
    return _git(root, 'rev-parse', 'HEAD').decode().strip()


def _clean(root):
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise CoordinatorError('dirty_repository')


def _receipt_path(state, operation_id):
    return state / 'receipts' / f'{operation_id}.json'


def _result(request, status, **extra):
    return {'protocol': 1, 'operation_id': request.get('operation_id'),
            'status': status, 'replayed': False, **extra}


def _finish(state, request, digest, result):
    _write_json(_receipt_path(state, request['operation_id']),
                {'digest': digest, 'result': result, 'result_digest': version(_canonical(result))})


def _prepare(root, state, request, digest):
    parent = _head(root)
    current = {m['slug']: _file_version(root / 'concepts' / (m['slug'] + '.md'))
               for m in request['mutations']}
    if (request.get('expected_head') not in (None, parent)
            or any(current[m['slug']] != m['expected_version'] for m in request['mutations'])):
        result = _result(request, 'conflict', code='stale_update',
                         current_head=parent, versions=current)
        _finish(state, request, digest, result)
        return result
    index = state / f'stage-{uuid.uuid4()}.index'
    try:
        _git(root, 'read-tree', parent, index=index)
        for mutation in request['mutations']:
            path = 'concepts/' + mutation['slug'] + '.md'
            if mutation['content'] is None:
                _git(root, 'update-index', '--force-remove', '--', path, index=index)
            else:
                blob = _git(root, 'hash-object', '-w', '--no-filters', '--stdin',
                            data=mutation['content'].encode()).decode().strip()
                _git(root, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{path}',
                     index=index)
        tree = _git(root, 'write-tree', index=index).decode().strip()
        commit = parent
        if tree != _git(root, 'rev-parse', f'{parent}^{{tree}}').decode().strip():
            message = (f"mem shared transaction\n\nOperation-ID: {request['operation_id']}\n"
                       f"Request-SHA256: {digest}\n")
            commit = _git(root, 'commit-tree', tree, '-p', parent, data=message.encode()).decode().strip()
    finally:
        index.unlink(missing_ok=True)
        Path(str(index) + '.lock').unlink(missing_ok=True)
    journal = {'request': request, 'digest': digest, 'parent': parent, 'commit': commit,
               'versions': {m['slug']: None if m['content'] is None else version(m['content'].encode())
                            for m in request['mutations']}}
    _write_json(state / 'active.json', journal)
    _fault('after_prepare')
    return journal


def _tree(root, commit):
    result = {}
    for entry in _git(root, 'ls-tree', '-rz', commit).split(b'\0'):
        if entry:
            metadata, path = entry.split(b'\t', 1)
            result[path.decode()] = tuple(metadata.decode().split())
    return result


def _blob_versions(root, objects):
    if not objects:
        return {}
    raw = _git(root, 'cat-file', '--batch', data=('\n'.join(objects) + '\n').encode())
    result, offset = {}, 0
    for wanted in objects:
        end = raw.index(b'\n', offset)
        actual, kind, size = raw[offset:end].decode().split()
        if actual != wanted or kind != 'blob':
            raise CoordinatorError('invalid_journal')
        offset = end + 1
        result[wanted] = version(raw[offset:offset + int(size)])
        offset += int(size) + 1
    return result


def _validate_journal(root, journal):
    if not isinstance(journal, dict) or set(journal) != {
        'request', 'digest', 'parent', 'commit', 'versions'
    }:
        raise CoordinatorError('invalid_journal')
    request = journal['request']
    _validate_request(request)
    if journal['digest'] != version(_canonical(request)):
        raise CoordinatorError('invalid_journal')
    expected_versions = {m['slug']: None if m['content'] is None else version(m['content'].encode())
                         for m in request['mutations']}
    if journal['versions'] != expected_versions:
        raise CoordinatorError('invalid_journal')
    parent, commit = journal['parent'], journal['commit']
    if request.get('expected_head') not in (None, parent):
        raise CoordinatorError('invalid_journal')
    if any(not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value)
           for value in (parent, commit)):
        raise CoordinatorError('invalid_journal')
    if commit != parent:
        ancestry = _git(root, 'rev-list', '--parents', '-n', '1', commit).decode().split()
        if ancestry != [commit, parent]:
            raise CoordinatorError('invalid_journal')
        message = _git(root, 'log', '-1', '--format=%B', commit).decode().splitlines()
        if (f"Operation-ID: {request['operation_id']}" not in message
                or f"Request-SHA256: {journal['digest']}" not in message):
            raise CoordinatorError('invalid_journal')
    before, after = _tree(root, parent), _tree(root, commit)
    paths = {'concepts/' + m['slug'] + '.md' for m in request['mutations']}
    if {p: v for p, v in before.items() if p not in paths} != {
        p: v for p, v in after.items() if p not in paths
    }:
        raise CoordinatorError('invalid_journal')
    old_objects = [before[p][2] for p in paths if p in before]
    old_versions = _blob_versions(root, old_objects)
    for mutation in request['mutations']:
        path = 'concepts/' + mutation['slug'] + '.md'
        old = before.get(path)
        if old is not None and old[:2] != ('100644', 'blob'):
            raise CoordinatorError('invalid_journal')
        if (None if old is None else old_versions[old[2]]) != mutation['expected_version']:
            raise CoordinatorError('invalid_journal')
        new = after.get(path)
        if mutation['content'] is None:
            if new is not None:
                raise CoordinatorError('invalid_journal')
        else:
            body = mutation['content'].encode()
            hasher = hashlib.sha1 if len(commit) == 40 else hashlib.sha256
            blob = hasher(f'blob {len(body)}\0'.encode() + body).hexdigest()
            if new != ('100644', 'blob', blob):
                raise CoordinatorError('invalid_journal')


def _verify_recovery(root, journal):
    parent, commit = journal['parent'], journal['commit']
    if _head(root) not in (parent, commit):
        raise CoordinatorError('recovery_conflict')
    old_tree = _git(root, 'rev-parse', f'{parent}^{{tree}}').strip()
    new_tree = _git(root, 'rev-parse', f'{commit}^{{tree}}').strip()
    if _git(root, 'write-tree').strip() not in (old_tree, new_tree):
        raise CoordinatorError('recovery_conflict')
    mutations = journal['request']['mutations']
    paths = {'concepts/' + mutation['slug'] + '.md' for mutation in mutations}
    changed = _git(root, 'diff', '--name-only', '-z', parent, '--').decode().split('\0')
    untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    if (set(changed) | set(untracked)) - paths - {''}:
        raise CoordinatorError('recovery_conflict')
    for mutation in mutations:
        current = _file_version(root / 'concepts' / (mutation['slug'] + '.md'))
        if current not in (mutation['expected_version'], journal['versions'][mutation['slug']]):
            raise CoordinatorError('recovery_conflict')


def _continue(root, state, journal, publish_callback, refresh_callback):
    _validate_journal(root, journal)
    _verify_recovery(root, journal)
    parent, commit, request = journal['parent'], journal['commit'], journal['request']
    if _head(root) == parent and parent != commit:
        _git(root, 'update-ref', 'refs/heads/main', commit, parent)
    _fault('after_ref')
    for n, mutation in enumerate(request['mutations']):
        path = root / 'concepts' / (mutation['slug'] + '.md')
        if mutation['content'] is None:
            if path.exists():
                path.unlink()
                _fsync_dir(path.parent)
        elif _file_version(path) != journal['versions'][mutation['slug']]:
            _atomic(path, mutation['content'].encode(), temporary_dir=state)
        if n == 0:
            _fault('after_first_file')
    _git(root, 'read-tree', commit)
    _clean(root)
    _fault('after_materialize')
    result = _result(request, 'applied', commit=commit, versions=journal['versions'])
    try:
        if refresh_callback is not None:
            refresh_callback(root, [m['slug'] for m in request['mutations']])
        if publish_callback is not None:
            publish_callback(root, commit)
    except Exception:
        return {**result, 'status': 'pending', 'code': 'finalization_pending',
                'terminal': False, 'source_committed': True}
    _fault('after_publish')
    _finish(state, request, journal['digest'], result)
    _fault('after_receipt')
    (state / 'active.json').unlink()
    _fsync_dir(state)
    return result


def _error_result(root, state, request, code):
    request = request if isinstance(request, dict) else {}
    result = _result(request, 'error', code=code, terminal=True)
    if code == 'writer_busy':
        return {**result, 'status': 'busy', 'terminal': False}
    if state is None or code == 'operation_id_reused':
        return result
    active = state / 'active.json'
    receipt = _receipt_path(state, request.get('operation_id', 'invalid'))
    if not active.exists() and not receipt.exists():
        return result
    result.update(status='pending', terminal=False, action_required=True, outcome='unknown')
    try:
        journal = _read_json(active)
        _validate_journal(root, journal)
        result['pending_operation_id'] = journal['request']['operation_id']
        if (journal['request']['operation_id'] == request.get('operation_id')
                and journal['digest'] == version(_canonical(request))):
            committed = _head(root) == journal['commit']
            result.update(source_committed=committed, outcome='committed' if committed else 'prepared')
            if committed:
                result['commit'] = journal['commit']
    except (CoordinatorError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return result


def handle(root: Path, request: dict, publish_callback=None, refresh_callback=None,
           lock_timeout: float = 10.0, preflight_callback=None) -> dict:
    """Apply one version-checked batch, or replay its durable receipt.

    Callbacks run under the same writer lock and must not acquire it again.
    A finalization failure is pending (the commit exists); retry the exact request.
    """
    state = None
    try:
        _validate_request(request)
        root = Path(root).absolute()
        _validate_repo(root)
        digest = version(_canonical(request))
        with _lock(root, lock_timeout):
            _validate_repo(root)
            state = root / '.index' / 'coordinator'
            _private_dir(state)
            _private_dir(state / 'receipts')
            active = state / 'active.json'
            replayed = False
            if active.exists():
                journal = _read_json(active)
                _validate_journal(root, journal)
                if journal['request']['operation_id'] == request['operation_id']:
                    if journal['digest'] != digest:
                        raise CoordinatorError('operation_id_reused')
                    replayed = True
                recovered = _continue(root, state, journal, publish_callback, refresh_callback)
                if recovered['status'] == 'pending':
                    if not replayed:
                        return _result(request, 'pending', code='earlier_transaction_pending',
                                       pending_operation_id=journal['request']['operation_id'], terminal=False)
                    return {**recovered, 'replayed': True}
            receipt = _receipt_path(state, request['operation_id'])
            if receipt.exists():
                saved = _read_json(receipt)
                if (not isinstance(saved, dict) or set(saved) != {'digest', 'result', 'result_digest'}
                        or saved['result_digest'] != version(_canonical(saved['result']))
                        or not isinstance(saved['result'], dict)
                        or saved['result'].get('operation_id') != request['operation_id']
                        or saved['result'].get('status') not in ('applied', 'conflict')):
                    raise CoordinatorError('invalid_receipt')
                if saved['digest'] != digest:
                    raise CoordinatorError('operation_id_reused')
                return {**saved['result'], 'replayed': True}
            _clean(root)
            if preflight_callback is not None:
                try:
                    preflight_callback(root)
                except Exception:
                    raise CoordinatorError('preflight_failed') from None
            prepared = _prepare(root, state, request, digest)
            if 'status' in prepared:
                return prepared
            return _continue(root, state, prepared, publish_callback, refresh_callback)
    except CoordinatorError as error:
        return _error_result(root, state, request, error.code)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return _error_result(root, state, request, 'local_state_error')


@contextmanager
def read_lock(root: Path, timeout: float = 10.0):
    """Take a stable source snapshot; refuse an unfinished authoritative write."""
    root = Path(root).absolute()
    with _lock(root, timeout):
        if (root / '.index/coordinator/active.json').exists():
            raise CoordinatorError('transaction_pending')
        yield
