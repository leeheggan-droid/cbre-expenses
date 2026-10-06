"""Gate an expense-run handover on a fresh, run-tagged, pushed public note.

This verifies repository housekeeping, not financial correctness or submission.
Run state and the completion receipt stay inside an ignored private directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import uuid

START = '.expense-run-start.json'
PROOF = '.expense-run-completion.json'


class GuardError(Exception):
    pass


def git(repo: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(['git', '-C', str(repo), *args], input=input_text,
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Remote errors can contain credentials in a URL; never echo stderr.
        raise GuardError(f'Git {args[0]} failed; check repository access/configuration.')
    return result.stdout.strip()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def remote_fingerprint(repo: Path) -> str:
    url = git(repo, 'remote', 'get-url', '--push', 'origin')
    return hashlib.sha256(url.encode()).hexdigest()


def private_directory(repo: Path, directory: Path) -> Path:
    directory = directory.resolve()
    try:
        relative = directory.relative_to(repo).as_posix()
    except ValueError:
        raise GuardError('Run directory must be inside this repository.') from None
    if relative == '.':
        raise GuardError('Run directory must be an ignored private subdirectory.')
    directory.mkdir(parents=True, exist_ok=True)
    for name in (START, PROOF):
        target = directory / name
        if target.is_symlink():
            raise GuardError('Run guard state cannot be a symbolic link.')
        git(repo, 'check-ignore', '--no-index', '--', f'{relative}/{name}')
    if git(repo, 'ls-files', '--', relative):
        raise GuardError('Run directory contains tracked private data; do not publish it.')
    return directory


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    if temporary.is_symlink():
        raise GuardError('Run guard temporary file cannot be a symbolic link.')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def start_guard(repo: Path, directory: Path, new: bool = False) -> dict:
    repo = Path(git(repo, 'rev-parse', '--show-toplevel')).resolve()
    directory = private_directory(repo, directory)
    state_path, proof_path = directory / START, directory / PROOF
    if state_path.exists() and not new:
        if proof_path.exists():
            raise GuardError('This run is completed; use start --new for a new run.')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['repo'] != str(repo) or state['remote_fingerprint'] != remote_fingerprint(repo):
            raise GuardError('Run repository or remote changed since start.')
        return state
    state = {'run_id': str(uuid.uuid4()), 'started_at': now(), 'repo': str(repo),
             'base_commit': git(repo, 'rev-parse', 'HEAD'),
             'branch': git(repo, 'symbolic-ref', '--short', 'HEAD'),
             'remote_fingerprint': remote_fingerprint(repo)}
    proof_path.unlink(missing_ok=True)
    write_json(state_path, state)
    return state


def public_note_path(note: str) -> str:
    path = PurePosixPath(note.replace('\\', '/'))
    if (path.is_absolute() or '..' in path.parts or ':' in note
            or path.suffix.lower() != '.md'
            or not (path.as_posix() in ('README.md', 'RUNBOOK.md')
                    or (len(path.parts) > 1 and path.parts[0] == 'docs'))):
        raise GuardError('Public note must be Markdown under docs/, README.md or RUNBOOK.md.')
    return path.as_posix()


def finish_guard(repo: Path, directory: Path, note: str) -> dict:
    repo = Path(git(repo, 'rev-parse', '--show-toplevel')).resolve()
    directory = private_directory(repo, directory)
    # A failed recheck must never leave an old success receipt behind.
    (directory / PROOF).unlink(missing_ok=True)
    note = public_note_path(note)
    state_path = directory / START
    if not state_path.exists():
        raise GuardError('Run has no start anchor; start before doing the expense work.')
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state['repo'] != str(repo) or state['remote_fingerprint'] != remote_fingerprint(repo):
        raise GuardError('Run repository or remote changed since start.')
    branch = git(repo, 'symbolic-ref', '--short', 'HEAD')
    if branch != state['branch']:
        raise GuardError('Run branch changed since start; restore it before completion.')
    head = git(repo, 'rev-parse', 'HEAD')
    base = state['base_commit']
    if head == base:
        raise GuardError('No new commit from this run; update the public reusable notes first.')
    git(repo, 'merge-base', '--is-ancestor', base, head)
    note_commit = None
    for commit in git(repo, 'rev-list', f'{base}..{head}').splitlines():
        body = git(repo, 'show', '-s', '--format=%B', commit)
        trailers = git(repo, 'interpret-trailers', '--parse', input_text=body)
        if f"Expense-Run: {state['run_id']}" not in trailers.splitlines():
            continue
        changed = git(repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-m', commit).splitlines()
        if note in changed:
            note_commit = commit
            break
    if note_commit is None:
        raise GuardError('No run-tagged commit changed the public note; add the Expense-Run trailer.')
    # Require a normal tracked Markdown file in the final committed tree.
    entry = git(repo, 'ls-tree', head, '--', note)
    if not entry.startswith(('100644 blob ', '100755 blob ')):
        raise GuardError('Public note must exist as a regular committed file.')
    remote = git(repo, 'ls-remote', '--exit-code', 'origin', f'refs/heads/{branch}')
    if remote.split()[0] != head:
        raise GuardError('Push the current run commit to origin before reporting completion.')
    proof = {'completion': 'verified', 'run_id': state['run_id'], 'commit': head,
             'note_commit': note_commit, 'public_note': note, 'branch': branch,
             'verified_at': now()}
    write_json(directory / PROOF, proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--new', action='store_true', help='start a new run in a reused directory')
    parser.add_argument('--public-note', help='scrubbed reusable Markdown note changed in this run')
    args = parser.parse_args()
    try:
        directory = args.run_dir if args.run_dir.is_absolute() else args.repo / args.run_dir
        if args.action == 'start':
            value = start_guard(args.repo, directory, args.new)
        else:
            if not args.public_note or args.new:
                raise GuardError('Finish requires --public-note and does not accept --new.')
            value = finish_guard(args.repo, directory, args.public_note)
        print(json.dumps(value))
        return 0
    except (GuardError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        # Do not emit arbitrary OS/Git exception text (could contain private paths/URLs).
        message = str(error) if isinstance(error, GuardError) else 'Run guard state or Git operation failed.'
        print(f'Completion blocked: {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
