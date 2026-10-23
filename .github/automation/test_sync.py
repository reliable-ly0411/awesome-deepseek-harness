import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sync_policy', HERE / 'sync.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base, self.prev = Path(self.tmp.name), Path.cwd()
        self.up, self.down = self.base / 'up', self.base / 'down'
        subprocess.run(['git', 'init', '-b', 'main', str(self.up)],
                       check=True, capture_output=True)
        self.g(self.up, 'config', 'user.name', 'Test')
        self.g(self.up, 'config', 'user.email', 'test@example.invalid')
        self.write(self.up, 'source.txt', 'v1\n')
        self.write(self.up, '.github/workflows/build.yml', 'upstream original\n')
        self.write(self.up, 'scripts/gate.py', 'original\n')
        self.commit(self.up, 'base')
        subprocess.run(['git', 'clone', str(self.up), str(self.down)],
                       check=True, capture_output=True)
        self.g(self.down, 'config', 'user.name', 'Test')
        self.g(self.down, 'config', 'user.email', 'test@example.invalid')
        self.g(self.down, 'config', 'url.' + self.up.as_uri() + '.insteadOf',
               'https://github.com/fixture/up.git')
        self.write(self.down, '.github/workflows/build.yml', 'local gated\n')
        self.write(self.down, 'local.txt', 'keep me\n')
        self.commit(self.down, 'local policy')
        self.g(self.down, 'switch', '-c', 'sync-only/upstream-main')
        os.chdir(self.down)
        self.config = {'upstream_repository': 'fixture/up',
                       'downstream_repository': 'fixture/down',
                       'upstream_branch': 'main', 'default_branch': 'main',
                       'sync_branch': 'sync-only/upstream-main',
                       'upstream_contributions': False,
                       'preserve_local_paths': ['.github']}

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def g(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, root, path, text):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')

    def commit(self, root, message):
        self.g(root, 'add', '.')
        self.g(root, 'commit', '-m', message)

    def assert_unchanged(self, before):
        self.assertEqual(self.g(self.down, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.g(self.down, 'status', '--porcelain'), '')
        self.assertFalse((self.down / '.git/MERGE_HEAD').exists())

    def test_noop_does_not_push(self):
        with patch.object(mod, 'git', wraps=mod.git) as calls:
            self.assertFalse(mod.sync(self.config)['changed'])
        self.assertFalse(any(call.args[0] == 'push' for call in calls.call_args_list))

    def test_source_changes_preserve_local_policy_and_both_parents(self):
        before = self.g(self.down, 'rev-parse', 'HEAD')
        self.write(self.up, 'source.txt', 'v2\n')
        self.write(self.up, '.github/workflows/new.yml', 'do not activate\n')
        self.commit(self.up, 'new source and workflow')
        upstream = self.g(self.up, 'rev-parse', 'HEAD')
        result = mod.sync(self.config)
        self.assertTrue(result['changed'])
        self.assertEqual((self.down / 'source.txt').read_text(), 'v2\n')
        self.assertEqual((self.down / '.github/workflows/build.yml').read_text(), 'local gated\n')
        self.assertFalse((self.down / '.github/workflows/new.yml').exists())
        self.assertEqual((self.down / 'local.txt').read_text(), 'keep me\n')
        self.assertEqual(self.g(self.down, 'show', '-s', '--format=%P').split(), [before, upstream])

    def test_workflow_conflict_is_resolved_using_downstream_policy(self):
        self.write(self.up, '.github/workflows/build.yml', 'new upstream publisher\n')
        self.write(self.up, 'source.txt', 'v2\n')
        self.commit(self.up, 'conflicting workflow')
        result = mod.sync(self.config)
        self.assertEqual(result['resolved_policy_conflicts'], ['.github/workflows/build.yml'])
        self.assertEqual((self.down / '.github/workflows/build.yml').read_text(), 'local gated\n')
        self.assertEqual((self.down / 'source.txt').read_text(), 'v2\n')

    def test_explicit_security_script_conflict_keeps_reviewed_downstream_version(self):
        self.config['preserve_local_paths'].append('scripts/gate.py')
        self.write(self.down, 'scripts/gate.py', 'block high findings\n')
        self.commit(self.down, 'stricter local gate')
        self.write(self.up, 'scripts/gate.py', 'advisory findings\n')
        self.write(self.up, 'source.txt', 'v2\n')
        self.commit(self.up, 'change gate and source')
        result = mod.sync(self.config)
        self.assertIn('scripts/gate.py', result['resolved_policy_conflicts'])
        self.assertEqual((self.down / 'scripts/gate.py').read_text(), 'block high findings\n')
        self.assertEqual((self.down / 'source.txt').read_text(), 'v2\n')

    def test_source_conflict_reports_path_and_aborts_without_push(self):
        self.write(self.up, 'source.txt', 'upstream\n')
        self.commit(self.up, 'up')
        self.write(self.down, 'source.txt', 'downstream\n')
        self.commit(self.down, 'down')
        before = self.g(self.down, 'rev-parse', 'HEAD')
        with patch.object(mod, 'git', wraps=mod.git) as calls:
            with self.assertRaisesRegex(RuntimeError, 'source.txt'):
                mod.sync(self.config)
        self.assert_unchanged(before)
        self.assertFalse(any(call.args[0] == 'push' for call in calls.call_args_list))

    def test_mixed_policy_and_source_conflicts_are_not_silently_resolved(self):
        self.write(self.up, 'source.txt', 'upstream\n')
        self.write(self.up, '.github/workflows/build.yml', 'upstream\n')
        self.commit(self.up, 'up')
        self.write(self.down, 'source.txt', 'downstream\n')
        self.commit(self.down, 'down')
        before = self.g(self.down, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'source.txt'):
            mod.sync(self.config)
        self.assert_unchanged(before)
        self.assertEqual((self.down / '.github/workflows/build.yml').read_text(), 'local gated\n')

    def test_latest_trusted_policy_refreshes_stale_sync_branch_without_source_changes(self):
        before = self.g(self.down, 'rev-parse', 'HEAD')
        self.g(self.down, 'switch', 'main')
        self.write(self.down, '.github/workflows/build.yml', 'new trusted policy\n')
        self.commit(self.down, 'new default branch policy')
        trusted = self.g(self.down, 'rev-parse', 'HEAD')
        self.g(self.down, 'switch', self.config['sync_branch'])
        result = mod.sync(self.config, policy_ref=trusted)
        self.assertTrue(result['changed'])
        self.assertEqual(self.g(self.down, 'show', '-s', '--format=%P'), before)
        self.assertEqual((self.down / '.github/workflows/build.yml').read_text(), 'new trusted policy\n')
        self.assertFalse(mod.sync(self.config, policy_ref=trusted)['changed'])

    def test_rejects_dirty_worktree(self):
        self.write(self.down, 'local.txt', 'changed')
        with self.assertRaisesRegex(RuntimeError, 'clean'):
            mod.sync(self.config)

    def test_rejects_unsafe_branches(self):
        for value in ('--upload-pack=bad', 'bad..ref', 'bad.lock', 'bad/'):
            with self.subTest(branch=value):
                self.config['upstream_branch'] = value
                with self.assertRaises(ValueError):
                    mod.sync(self.config)

    def test_rejects_default_branch_push(self):
        self.config['sync_branch'] = 'main'
        with self.assertRaisesRegex(ValueError, 'default branch'):
            mod.sync(self.config, push=True)

    def test_rejects_upstream_as_downstream(self):
        self.config['downstream_repository'] = self.config['upstream_repository']
        with self.assertRaises(ValueError):
            mod.sync(self.config, push=True)

    def test_rejects_upstream_push_remote_before_merge(self):
        self.g(self.down, 'remote', 'set-url', '--push', 'origin', 'https://github.com/fixture/up.git')
        before = self.g(self.down, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'downstream repository'):
            mod.sync(self.config, push=True)
        self.assert_unchanged(before)

    def test_rejects_multiple_push_destinations(self):
        for url in ('https://github.com/fixture/down.git', 'https://github.com/other/repo.git'):
            self.g(self.down, 'remote', 'set-url', '--add', '--push', 'origin', url)
        with self.assertRaisesRegex(RuntimeError, 'downstream repository'):
            mod.sync(self.config, push=True)

    def test_push_requires_source_only_branch(self):
        self.g(self.down, 'remote', 'set-url', '--push', 'origin', 'https://github.com/fixture/down.git')
        self.g(self.down, 'switch', 'main')
        with self.assertRaisesRegex(RuntimeError, 'source-only branch'):
            mod.sync(self.config, push=True)

    def test_push_is_normal_and_targets_only_downstream_source_branch(self):
        self.g(self.down, 'remote', 'set-url', '--push', 'origin', 'https://github.com/fixture/down.git')
        self.write(self.up, 'source.txt', 'v2\n')
        self.commit(self.up, 'up')
        original, pushes = mod.git, []

        def no_external_push(*args, **kwargs):
            if args[0] == 'push':
                pushes.append(args)
                return subprocess.CompletedProcess(args, 0, '', '')
            return original(*args, **kwargs)

        with patch.object(mod, 'git', side_effect=no_external_push):
            self.assertTrue(mod.sync(self.config, push=True)['changed'])
        self.assertEqual(pushes, [('push', 'origin', 'HEAD:refs/heads/sync-only/upstream-main')])

    def test_rejects_enabled_upstream_contributions(self):
        self.config['upstream_contributions'] = True
        with self.assertRaises(ValueError):
            mod.sync(self.config)

    def test_rejects_unsafe_preserved_path(self):
        self.config['preserve_local_paths'].append('../source.txt')
        with self.assertRaises(ValueError):
            mod.sync(self.config)

    def test_policy_must_preserve_workflows(self):
        self.config['preserve_local_paths'] = ['source.txt']
        with self.assertRaises(ValueError):
            mod.sync(self.config)

    def test_policy_ref_must_be_pinned(self):
        with self.assertRaisesRegex(ValueError, 'full commit SHA'):
            mod.sync(self.config, policy_ref='main')


if __name__ == '__main__':
    unittest.main()
