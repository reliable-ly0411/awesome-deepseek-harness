#!/usr/bin/env python3
"""Merge upstream source, retaining reviewed downstream policy; never publish."""
import argparse
import json
import pathlib
import re
import subprocess


def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, text=True,
                          encoding='utf-8', capture_output=True)


def validate_config(config):
    for key in ('upstream_repository', 'downstream_repository'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', config[key]):
            raise ValueError('Unsafe repository: ' + key)
    if config['upstream_repository'].lower() == config['downstream_repository'].lower():
        raise ValueError('The push destination must be a separate downstream repository')
    if config.get('upstream_contributions') is not False:
        raise ValueError('Upstream contributions must remain disabled')
    for key in ('upstream_branch', 'sync_branch', 'default_branch'):
        value = config[key]
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', value)
                or git('check-ref-format', '--branch', value, check=False).returncode):
            raise ValueError('Unsafe branch: ' + key)
    if config['sync_branch'] == config['default_branch']:
        raise ValueError('Source sync must not push the default branch')
    paths = config['preserve_local_paths']
    if not isinstance(paths, list) or '.github' not in paths:
        raise ValueError('Trusted downstream workflows must be preserved')
    for path in paths:
        if (not isinstance(path, str) or not re.fullmatch(r'[A-Za-z0-9_. /-]+', path)
                or path.startswith('/') or path.endswith('/')
                or any(part in ('', '.', '..') for part in path.split('/'))):
            raise ValueError('Unsafe preserved path')
    return paths


def check_push_destination(config):
    repo = config['downstream_repository']
    allowed = {f'https://github.com/{repo}', f'https://github.com/{repo}.git',
               f'git@github.com:{repo}.git', f'ssh://git@github.com/{repo}.git'}
    urls = git('remote', 'get-url', '--push', '--all', 'origin').stdout.splitlines()
    if len(urls) != 1 or urls[0] not in allowed:
        raise RuntimeError('origin must push only to the configured downstream repository')
    if git('branch', '--show-current').stdout.strip() != config['sync_branch']:
        raise RuntimeError('Push requires the configured source-only branch')


def sync(config, push=False, policy_ref=None):
    paths = validate_config(config)
    if git('status', '--porcelain').stdout.strip():
        raise RuntimeError('Working tree must be clean')
    if push:
        check_push_destination(config)
    before = git('rev-parse', 'HEAD').stdout.strip()
    policy_ref = policy_ref or before
    if not re.fullmatch(r'[0-9a-f]{40}', policy_ref):
        raise ValueError('Trusted policy must be pinned to a full commit SHA')
    git('rev-parse', '--verify', policy_ref + '^{commit}')
    specs = [':(literal)' + path for path in paths]
    for path in paths:
        git('cat-file', '-e', policy_ref + ':' + path)
    repo, branch = config['upstream_repository'], config['upstream_branch']
    git('fetch', '--no-recurse-submodules', '--no-tags',
        'https://github.com/' + repo + '.git', 'refs/heads/' + branch)
    upstream = git('rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    held = git('diff', '--name-only', before + '...' + upstream,
               '--', *specs).stdout.splitlines()
    already_synced = git('merge-base', '--is-ancestor', upstream, before,
                         check=False).returncode == 0
    conflicts = []
    try:
        if not already_synced:
            result = git('merge', '--no-ff', '--no-commit', upstream, check=False)
            conflicts = git('diff', '--name-only', '--diff-filter=U', '-z').stdout.split('\0')
            conflicts = [path for path in conflicts if path]
            source_conflicts = [path for path in conflicts if not any(
                path == kept or path.startswith(kept + '/') for kept in paths)]
            if source_conflicts:
                raise RuntimeError('Upstream source conflict; source branch unchanged: '
                                   + ', '.join(source_conflicts) + '\n'
                                   + result.stdout + result.stderr)
            if result.returncode and not conflicts:
                raise RuntimeError('Upstream merge failed; source branch unchanged:\n'
                                   + result.stdout + result.stderr)
        # Resolve only the explicit downstream policy allowlist, including conflicts.
        # The default-branch policy SHA is captured before selecting the sync branch.
        git('restore', '--source=' + policy_ref, '--staged', '--worktree', '--', *specs)
        merging = git('rev-parse', '--verify', '-q', 'MERGE_HEAD', check=False).returncode == 0
        changed = merging or git('diff', '--cached', '--quiet', check=False).returncode != 0
        if changed:
            message = ('sync: refresh trusted downstream policy' if already_synced else
                       'sync: merge upstream source at ' + upstream[:12])
            git('commit', '-m', message + ' (no build or publish)')
    except Exception:
        if git('rev-parse', '--verify', '-q', 'MERGE_HEAD', check=False).returncode == 0:
            git('merge', '--abort')
        else:
            git('restore', '--source=' + before, '--staged', '--worktree', '--', *specs)
        raise
    after = git('rev-parse', 'HEAD').stdout.strip()
    if push and changed:
        # Recheck immediately before a normal push; never force or target upstream.
        check_push_destination(config)
        git('push', 'origin', 'HEAD:refs/heads/' + config['sync_branch'])
    return {'changed': changed, 'source_sha': after, 'upstream_sha': upstream,
            'policy_sha': policy_ref, 'held_upstream_policy_paths': held,
            'resolved_policy_conflicts': conflicts}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='.github/automation/policy.json')
    p.add_argument('--policy-ref', help='Trusted default-branch policy commit SHA')
    p.add_argument('--push', action='store_true')
    args = p.parse_args()
    config = json.loads(pathlib.Path(args.config).read_text(encoding='utf-8'))
    print(json.dumps(sync(config, args.push, args.policy_ref), indent=2))


if __name__ == '__main__':
    main()
