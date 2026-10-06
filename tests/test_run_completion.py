"""Completion requires a run-tagged public note commit, pushed after run start."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'run_completion.py'

def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

@pytest.fixture
def run(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'user.name', 'Synthetic Operator')
    git(repo, 'config', 'user.email', 'operator@example.invalid')
    (repo / '.gitignore').write_text('personal/\n')
    (repo / 'README.md').write_text('Synthetic workflow\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'Initial reusable workflow')
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(origin)], check=True)
    git(repo, 'remote', 'add', 'origin', str(origin))
    git(repo, 'push', '-qu', 'origin', 'main')
    directory = repo / 'personal' / 'runs' / 'synthetic'
    directory.mkdir(parents=True)
    return repo, directory

def command(run, action, *args):
    repo, directory = run
    return subprocess.run([sys.executable, str(TOOL), action, '--repo', str(repo),
                           '--run-dir', str(directory), *args], capture_output=True, text=True)

def start(run):
    result = command(run, 'start')
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)

def note_commit(run, run_id=None):
    repo, _ = run
    (repo / 'docs').mkdir(exist_ok=True)
    (repo / 'docs' / 'run-lessons.md').write_text('Verify saved rows after a refresh.\n')
    git(repo, 'add', 'docs/run-lessons.md')
    message = 'Document a reusable workflow lesson'
    if run_id:
        message += '\n\nExpense-Run: ' + run_id
    git(repo, 'commit', '-qm', message)
    return git(repo, 'rev-parse', 'HEAD')

def finish(run):
    return command(run, 'finish', '--public-note', 'docs/run-lessons.md')

def test_start_records_the_anchor_without_committing_run_data(run):
    repo, directory = run
    anchor = git(repo, 'rev-parse', 'HEAD')
    state = start(run)
    assert state['base_commit'] == anchor
    assert len(state['run_id']) == 36
    assert git(repo, 'status', '--porcelain') == ''
    assert (directory / '.expense-run-start.json').exists()

def test_no_commit_cannot_report_completion(run):
    start(run)
    result = finish(run)
    assert result.returncode != 0
    assert 'no new commit' in result.stderr.lower()
    assert not (run[1] / '.expense-run-completion.json').exists()

def test_unrelated_fresh_commit_does_not_belong_to_this_run(run):
    start(run)
    note_commit(run)
    git(run[0], 'push', '-q')
    result = finish(run)
    assert result.returncode != 0
    assert 'run-tagged' in result.stderr.lower()

def test_commit_of_private_run_data_does_not_count_as_public_notes(run):
    state = start(run)
    repo, directory = run
    (directory / 'STATE.md').write_text('Synthetic private state\n')
    git(repo, 'add', '-f', 'personal/runs/synthetic/STATE.md')
    git(repo, 'commit', '-qm', 'Private state\n\nExpense-Run: ' + state['run_id'])
    git(repo, 'push', '-q')
    result = finish(run)
    assert result.returncode != 0
    assert not (directory / '.expense-run-completion.json').exists()

def test_local_only_commit_cannot_claim_the_public_repo_was_updated(run):
    state = start(run)
    note_commit(run, state['run_id'])
    result = finish(run)
    assert result.returncode != 0
    assert 'push' in result.stderr.lower()

def test_tagged_public_note_pushed_from_this_run_passes(run):
    state = start(run)
    head = note_commit(run, state['run_id'])
    git(run[0], 'push', '-q')
    result = finish(run)
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof['completion'] == 'verified'
    assert proof['run_id'] == state['run_id']
    assert proof['commit'] == head
    assert proof['public_note'] == 'docs/run-lessons.md'
    assert json.loads((run[1] / '.expense-run-completion.json').read_text()) == proof

def test_repeated_start_preserves_the_run_anchor(run):
    first = start(run)
    note_commit(run, first['run_id'])
    second = start(run)
    assert second['base_commit'] == first['base_commit']
    assert second['run_id'] == first['run_id']

def test_old_success_cannot_satisfy_a_new_run_in_the_same_directory(run):
    state = start(run)
    note_commit(run, state['run_id'])
    git(run[0], 'push', '-q')
    assert finish(run).returncode == 0
    blocked = command(run, 'start')
    assert blocked.returncode != 0
    new = command(run, 'start', '--new')
    assert new.returncode == 0, new.stderr
    assert json.loads(new.stdout)['run_id'] != state['run_id']
    assert finish(run).returncode != 0
    assert not (run[1] / '.expense-run-completion.json').exists()

def test_changing_the_remote_cannot_substitute_another_repository(run, tmp_path):
    state = start(run)
    note_commit(run, state['run_id'])
    other = tmp_path / 'other.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(other)], check=True)
    git(run[0], 'remote', 'set-url', 'origin', str(other))
    git(run[0], 'push', '-qu', 'origin', 'main')
    result = finish(run)
    assert result.returncode != 0
    assert 'remote' in result.stderr.lower()

@pytest.mark.parametrize('path', ['personal/STATE.md', '../private.md', '/tmp/note.md'])
def test_public_note_cannot_point_to_private_or_external_files(run, path):
    start(run)
    result = command(run, 'finish', '--public-note', path)
    assert result.returncode != 0
    assert 'public note' in result.stderr.lower()
