import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('longxia_test_app');package.__path__=[str(ROOT/'inventory-board/app')];sys.modules[package.__name__]=package
spec=importlib.util.spec_from_file_location('longxia_test_app.longxia_status',ROOT/'inventory-board/app/longxia_status.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
NOW=1793079600000
class LongxiaStatusTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.file=Path(self.temp.name)/'status.json'
  self.data={'schema':1,'generatedAt':NOW,'stores':[{'id':s['profileId'],'name':s['name']} for s in m.DEFAULT['stores']]}
 def tearDown(self):self.temp.cleanup()
 def write(self,data=None):self.file.write_text(json.dumps(self.data if data is None else data))
 def test_live_and_stale(self):
  self.write();self.assertTrue(m.read(self.file,NOW)['online']);self.assertFalse(m.read(self.file,NOW+90001)['online']);self.assertTrue(m.read(self.file,NOW+90001)['available'])
 def test_missing_and_invalid(self):
  self.assertFalse(m.read(self.file,NOW)['available'])
  for mutate in [lambda d:d.update(cookie='secret'),lambda d:d['stores'][0].update(rawSnapshot={}),lambda d:d['stores'][0].update(id='wrong'),lambda d:d.update(generatedAt=NOW+60001),lambda d:d['stores'].__setitem__(0,None)]:
   d=copy.deepcopy(self.data);mutate(d);self.write(d);self.assertFalse(m.read(self.file,NOW)['available'])
if __name__=='__main__':unittest.main()
