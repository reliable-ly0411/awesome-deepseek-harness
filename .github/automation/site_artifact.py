#!/usr/bin/env python3
"""Package static output once; verify a successful manual run before promotion."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile


def sha256(p):
    with open(p, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def package(source):
    root = Path(source).resolve()
    source_sha = os.environ['SOURCE_SHA']
    if not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError('A full source SHA is required')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if actual != source_sha:
        raise ValueError('Checkout does not match requested source SHA')
    if not (root / 'index.html').is_file():
        raise ValueError('Built site has no index.html')
    dest = Path(os.environ['RUNNER_TEMP']) / 'site-candidate'
    dest.mkdir(exist_ok=True)
    with tarfile.open(dest / 'artifact.tar', 'w', format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('Only ordinary files and directories may be deployed')
            if path.is_file():
                info = tar.gettarinfo(str(path), path.relative_to(root).as_posix())
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                with path.open('rb') as f:
                    tar.addfile(info, f)
    data = {'schema': 1, 'repository': os.environ['GITHUB_REPOSITORY'], 'source_sha': source_sha,
            'tooling_sha': os.environ['GITHUB_SHA'], 'run_id': int(os.environ['GITHUB_RUN_ID']),
            'tar_sha256': sha256(dest / 'artifact.tar')}
    (dest / 'provenance.json').write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(data, indent=2))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write('Built only, not published.\n\n' + json.dumps(data, indent=2) + '\n')


def check_run():
    run_id = os.environ['BUILD_RUN_ID']
    if not run_id.isdigit() or not re.fullmatch('[0-9a-f]{40}', os.environ['SOURCE_SHA']):
        raise ValueError('Invalid build identity')
    repo = os.environ['GITHUB_REPOSITORY']
    run = api(f'repos/{repo}/actions/runs/{run_id}')
    policy = json.loads(Path('.github/automation/policy.json').read_text())
    if (run['status'] != 'completed' or run['conclusion'] != 'success' or
        run['event'] != 'workflow_dispatch' or
        run['path'].split('@')[0] != '.github/workflows/' + policy['site_build_workflow'] or
        run['head_repository']['full_name'] != repo or
        run['head_branch'] != policy['default_branch']):
        raise ValueError('Only successful manual builds using the trusted default-branch workflow can be promoted')
    Path(os.environ['RUNNER_TEMP'], 'verified-run.json').write_text(json.dumps(run))


def verify():
    data = json.loads(Path('candidate/provenance.json').read_text())
    run = json.loads(Path(os.environ['RUNNER_TEMP'], 'verified-run.json').read_text())
    expected = os.environ['ARTIFACT_SHA256']
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('A full artifact SHA256 is required')
    if (data['source_sha'] != os.environ['SOURCE_SHA'] or data['run_id'] != int(os.environ['BUILD_RUN_ID']) or
        data['tooling_sha'] != run['head_sha'] or data['repository'] != os.environ['GITHUB_REPOSITORY'] or
        data['tar_sha256'] != expected or sha256('candidate/artifact.tar') != expected):
        raise ValueError('Candidate provenance/hash mismatch')
    with tarfile.open('candidate/artifact.tar') as tar:
        names = set()
        for m in tar.getmembers():
            name = PurePosixPath(m.name)
            if not m.isfile() or name.is_absolute() or '..' in name.parts or m.name in names:
                raise ValueError('Unsafe archive member')
            names.add(m.name)
        if 'index.html' not in names:
            raise ValueError('Missing site entry point')
    print('Verified original site bytes; no build is performed during promotion.')


if __name__ == '__main__':
    {'package': lambda: package(sys.argv[2]), 'check-run': check_run, 'verify': verify}[sys.argv[1]]()
