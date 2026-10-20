import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('site_artifact',Path(__file__).with_name('site_artifact.py'))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class SiteArtifactTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.before=Path.cwd();os.chdir(self.root)
  (self.root/'site').mkdir();(self.root/'site/index.html').write_text('<h1>site</h1>')
  self.env=patch.dict(os.environ,{'RUNNER_TEMP':str(self.root),'SOURCE_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GITHUB_REPOSITORY':'fixture/repo','GITHUB_RUN_ID':'123','BUILD_RUN_ID':'123'})
  self.env.start()
 def tearDown(self):self.env.stop();os.chdir(self.before);self.tmp.cleanup()
 def build(self):
  with patch.object(mod.subprocess,'check_output',return_value='a'*40+'\n'):mod.package('site')
  (self.root/'site-candidate').rename(self.root/'candidate')
  data=json.loads((self.root/'candidate/provenance.json').read_text());os.environ['ARTIFACT_SHA256']=data['tar_sha256']
  (self.root/'verified-run.json').write_text(json.dumps({'head_sha':'b'*40}))
  return data
 def test_original_bytes_verified(self):
  data=self.build();mod.verify();self.assertEqual(data['source_sha'],'a'*40)
 def test_tampered_artifact_rejected(self):
  self.build()
  with (self.root/'candidate/artifact.tar').open('ab') as f:f.write(b'changed')
  with self.assertRaises(ValueError):mod.verify()
 def test_other_source_rejected(self):
  self.build();os.environ['SOURCE_SHA']='c'*40
  with self.assertRaises(ValueError):mod.verify()
 def test_other_run_rejected(self):
  self.build();os.environ['BUILD_RUN_ID']='999'
  with self.assertRaises(ValueError):mod.verify()
 def test_symlink_output_rejected(self):
  (self.root/'site/link').symlink_to('/etc/passwd')
  with patch.object(mod.subprocess,'check_output',return_value='a'*40+'\n'):
   with self.assertRaises(ValueError):mod.package('site')
 def test_unsafe_tar_rejected_even_when_hash_matches(self):
  self.build();archive=self.root/'candidate/artifact.tar'
  with tarfile.open(archive,'w') as tar:
   info=tarfile.TarInfo('../escape');info.size=1;tar.addfile(info,io.BytesIO(b'x'))
  data=json.loads((self.root/'candidate/provenance.json').read_text());data['tar_sha256']=mod.sha256(archive)
  (self.root/'candidate/provenance.json').write_text(json.dumps(data));os.environ['ARTIFACT_SHA256']=data['tar_sha256']
  with self.assertRaises(ValueError):mod.verify()
 def test_pr_run_never_promoted(self):
  p=self.root/'.github/automation';p.mkdir(parents=True);(p/'policy.json').write_text(json.dumps({'site_build_workflow':'deploy.yml','default_branch':'main'}))
  run={'status':'completed','conclusion':'success','event':'pull_request','path':'.github/workflows/deploy.yml','head_repository':{'full_name':'fixture/repo'},'head_branch':'main'}
  with patch.object(mod,'api',return_value=run):
   with self.assertRaises(ValueError):mod.check_run()
 def test_manual_run_from_default_accepted(self):
  p=self.root/'.github/automation';p.mkdir(parents=True);(p/'policy.json').write_text(json.dumps({'site_build_workflow':'deploy.yml','default_branch':'main'}))
  run={'status':'completed','conclusion':'success','event':'workflow_dispatch','path':'.github/workflows/deploy.yml','head_repository':{'full_name':'fixture/repo'},'head_branch':'main'}
  with patch.object(mod,'api',return_value=run):mod.check_run()
  self.assertTrue((self.root/'verified-run.json').exists())

if __name__=='__main__':unittest.main()
