#!/usr/bin/env python3
"""Merge one allowlisted upstream into a source-only branch; never build or publish."""
import argparse
import json
import pathlib
import re
import subprocess
import sys


def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, text=True, capture_output=True)


def sync(config, push=False):
    repo = config['upstream_repository']
    branch = config['upstream_branch']
    target = config['sync_branch']
    for value in (branch, target):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', value) or '..' in value or '@{' in value:
            raise ValueError('Unsafe branch')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Unsafe upstream repository')
    if git('status', '--porcelain').stdout.strip():
        raise RuntimeError('Working tree must be clean')
    before = git('rev-parse', 'HEAD').stdout.strip()
    git('fetch', '--no-recurse-submodules', '--no-tags', 'https://github.com/' + repo + '.git', 'refs/heads/' + branch)
    upstream = git('rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    if git('merge-base', '--is-ancestor', upstream, before, check=False).returncode == 0:
        return {'changed': False, 'source_sha': before, 'upstream_sha': upstream}
    held = git('diff', '--name-only', before + '...' + upstream, '--', '.github').stdout.splitlines()
    result = git('merge', '--no-ff', '--no-commit', upstream, check=False)
    if result.returncode:
        git('merge', '--abort', check=False)
        raise RuntimeError('Upstream conflict; source branch unchanged: ' + result.stderr)
    try:
        # Preserve trusted maintenance code, policy and every local workflow. Upstream
        # CI changes are reported, never automatically granted local token access.
        git('restore', '--source=' + before, '--staged', '--worktree', '--', '.github')
        git('commit', '-m', 'sync: merge upstream source at ' + upstream[:12] + ' (no build or publish)')
        after = git('rev-parse', 'HEAD').stdout.strip()
        if push:
            git('push', 'origin', 'HEAD:refs/heads/' + target)
        return {'changed': True, 'source_sha': after, 'upstream_sha': upstream, 'held_upstream_policy_paths': held}
    except Exception:
        git('merge', '--abort', check=False)
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='.github/automation/policy.json')
    p.add_argument('--push', action='store_true')
    args = p.parse_args()
    print(json.dumps(sync(json.loads(pathlib.Path(args.config).read_text()), args.push), indent=2))


if __name__ == '__main__':
    main()
