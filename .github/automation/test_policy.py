"""Lightweight offline policy checks. No compilation, deployment, or external AI."""
import json
import pathlib
import re
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PolicyTests(unittest.TestCase):
    def test_workflow_yaml(self):
        for p in (ROOT / '.github/workflows').glob('*.y*ml'):
            with self.subTest(file=p.name):
                d = yaml.load(p.read_text(), Loader=yaml.BaseLoader)
                self.assertIsInstance(d, dict)
                self.assertIn('on', d)
                self.assertIn('jobs', d)
    def test_no_automatic_heavy_or_publishing_entry(self):
        policy = json.loads((ROOT / '.github/automation/policy.json').read_text())
        for name in policy['manual_workflows']:
            with self.subTest(workflow=name):
                d = yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)
                self.assertEqual(set(d['on']), {'workflow_dispatch'})
                for job in d['jobs'].values():
                    self.assertNotIn('workflow_run', str(job))
    def test_sync_does_not_chain_build_or_publish(self):
        d = yaml.load((ROOT / '.github/workflows/source-sync.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(d['on']), {'schedule', 'workflow_dispatch'})
        self.assertEqual(set(d['jobs']), {'sync'})
        self.assertEqual(d['permissions'], {'contents': 'write'})
        text = (ROOT / '.github/workflows/source-sync.yml').read_text()
        for forbidden in ('repository-dispatch', 'gh workflow run', 'gh release', 'deploy-pages', 'workflow_call'):
            self.assertNotIn(forbidden, text)
    def test_policy_has_explicit_upstream_and_no_backfill(self):
        p = json.loads((ROOT / '.github/automation/policy.json').read_text())
        self.assertRegex(p['upstream_repository'], r'^[\w.-]+/[\w.-]+$')
        self.assertEqual(p['automatic_publish'], False)
        self.assertEqual(p['historical_backfill'], False)
        self.assertTrue(p['preserve_local_workflows'])

    def test_unverified_pages_promotion_fails_before_any_side_effect(self):
        path = ROOT / '.github/workflows/site-promote.yml'
        d = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        job = d['jobs']['promote']
        self.assertEqual(job['permissions']['contents'], 'read')
        self.assertIn('exit 1', job['steps'][0]['run'])
        self.assertNotIn('git push', path.read_text())
        self.assertNotIn('deploy-pages', path.read_text())



    def test_sync_only_destination_and_preserved_paths(self):
        config = json.loads((ROOT / '.github/automation/policy.json').read_text())
        self.assertFalse(config['upstream_contributions'])
        self.assertTrue(config['downstream_repository'].startswith('reliable-ly0411/'))
        self.assertNotEqual(config['downstream_repository'], config['upstream_repository'])
        self.assertNotEqual(config['sync_branch'], config['default_branch'])
        self.assertIn('.github', config['preserve_local_paths'])
        for path in config['preserve_local_paths']:
            self.assertTrue((ROOT / path).exists(), path)

    def test_external_contribution_interfaces_are_inert(self):
        config = json.loads((ROOT / '.github/automation/policy.json').read_text())
        for name in config['disabled_external_workflows']:
            with self.subTest(workflow=name):
                doc = yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)
                self.assertEqual(set(doc['on']), {'workflow_dispatch'})
                self.assertEqual(doc['permissions'], {'contents': 'read'})
                for job in doc['jobs'].values():
                    self.assertNotIn('env', job)
                    self.assertNotIn('permissions', job)
                    for step in job['steps']:
                        self.assertEqual(set(step), {'run'})
                        self.assertTrue(all(line.strip().startswith('echo ')
                                            for line in step['run'].splitlines()))

    def test_source_sync_passes_pinned_default_policy_to_script(self):
        doc = yaml.load((ROOT / '.github/workflows/source-sync.yml').read_text(), Loader=yaml.BaseLoader)
        select = next(step for step in doc['jobs']['sync']['steps'] if step.get('id') == 'trusted')
        self.assertLess(select['run'].index('git rev-parse HEAD'),
                        select['run'].index('git checkout'))
        self.assertIn('"$status" -ne 2', select['run'])
        merge = doc['jobs']['sync']['steps'][-1]
        self.assertEqual(merge['env']['POLICY_REF'], '${{ steps.trusted.outputs.sha }}')
        self.assertIn('--policy-ref "$POLICY_REF"', merge['run'])


if __name__ == '__main__':
    unittest.main()
