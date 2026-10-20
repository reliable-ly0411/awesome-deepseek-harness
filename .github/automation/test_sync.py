import importlib.util
from pathlib import Path
import subprocess
import tempfile
import os
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sync_policy', HERE/'sync.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class SyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.prev=Path.cwd()
  self.up=self.base/'up';self.down=self.base/'down'
  subprocess.run(['git','init','-b','main',str(self.up)],check=True,capture_output=True)
  self.g(self.up,'config','user.name','Test');self.g(self.up,'config','user.email','test@example.invalid')
  (self.up/'source.txt').write_text('v1\n');(self.up/'.github/workflows').mkdir(parents=True)
  (self.up/'.github/workflows/build.yml').write_text('upstream original\n')
  self.commit(self.up,'base')
  subprocess.run(['git','clone',str(self.up),str(self.down)],check=True,capture_output=True)
  self.g(self.down,'config','user.name','Test');self.g(self.down,'config','user.email','test@example.invalid')
  self.g(self.down,'config','url.'+self.up.as_uri()+'.insteadOf','https://github.com/fixture/up.git')
  (self.down/'.github/workflows/build.yml').write_text('local gated\n');(self.down/'local.txt').write_text('keep me\n');self.commit(self.down,'local policy')
  os.chdir(self.down)
  self.config={'upstream_repository':'fixture/up','upstream_branch':'main','sync_branch':'main'}
 def tearDown(self):
  os.chdir(self.prev);self.tmp.cleanup()
 def g(self,p,*a):return subprocess.run(['git','-C',str(p),*a],check=True,capture_output=True,text=True).stdout.strip()
 def commit(self,p,m):self.g(p,'add','.');self.g(p,'commit','-m',m)
 def test_noop_does_not_push(self):
  self.assertFalse(mod.sync(self.config)['changed'])
 def test_source_changes_preserve_local_policy(self):
  (self.up/'source.txt').write_text('v2\n');(self.up/'.github/workflows/new.yml').write_text('do not activate\n');self.commit(self.up,'new source and workflow')
  result=mod.sync(self.config)
  self.assertTrue(result['changed']);self.assertEqual((self.down/'source.txt').read_text(),'v2\n')
  self.assertEqual((self.down/'.github/workflows/build.yml').read_text(),'local gated\n')
  self.assertFalse((self.down/'.github/workflows/new.yml').exists());self.assertEqual((self.down/'local.txt').read_text(),'keep me\n')
 def test_conflict_aborts_without_ref_change(self):
  (self.up/'source.txt').write_text('upstream\n');self.commit(self.up,'up')
  (self.down/'source.txt').write_text('downstream\n');self.commit(self.down,'down')
  before=self.g(self.down,'rev-parse','HEAD')
  with self.assertRaises(RuntimeError):mod.sync(self.config)
  self.assertEqual(self.g(self.down,'rev-parse','HEAD'),before);self.assertFalse((self.down/'.git/MERGE_HEAD').exists())
 def test_rejects_dirty_worktree(self):
  (self.down/'local.txt').write_text('changed')
  with self.assertRaises(RuntimeError):mod.sync(self.config)
 def test_rejects_unsafe_branch(self):
  self.config['upstream_branch']='--upload-pack=bad'
  with self.assertRaises(ValueError):mod.sync(self.config)

if __name__=='__main__':unittest.main()
