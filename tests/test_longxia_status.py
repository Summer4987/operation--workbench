import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
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
 def test_learning_summary_keeps_new_status_online(self):
  learning={'mode':'shadow','status':'collecting','message':'学习积累中','samples':1,'days':1,'responseSamples':0,'averageDailySpend':None,'completeDays':0,'suggestedBid':30,'referenceBid':40,'suggestedStep':10,'suggestedWaitMinutes':5,'note':''}
  self.data['stores'][0]['learning']=learning;self.write()
  result=m.read(self.file,NOW)
  self.assertTrue(result['available']);self.assertTrue(result['online']);self.assertEqual(result['stores'][0]['learning'],learning)
  self.data['generatedAt']=NOW+15000;self.data['stores'][0]['spend']=1234;self.write()
  result=m.read(self.file,NOW+15000);self.assertEqual(result['generatedAt'],NOW+15000);self.assertEqual(result['stores'][0]['spend'],1234)
 def test_learning_rejects_unknown_fields_and_invalid_types(self):
  for learning in [{'mode':'shadow','cookie':'secret'},{'mode':'shadow','rawSnapshot':{}},{'mode':'live'},{'mode':'shadow','samples':True},{'mode':'shadow','samples':-1},{'mode':'shadow','note':{}},[],{'mode':'shadow','note':'x'*1201}]:
   self.data['stores'][0]['learning']=learning;self.write();self.assertFalse(m.read(self.file,NOW)['available'])
 def test_new_row_is_visible_without_authorizing_platform_actions(self):
  # A partial historical authorization must still display newly added local rows.
  known=m.DEFAULT['stores'][:9];self.data['stores']=self.data['stores'][:9]
  self.data['stores'].append({'id':'not-yet-authorized','name':'新门店','bound':False,'dailyBudget':None})
  self.write()
  with patch.object(m,'DEFAULT',{'stores':known}):
   self.assertTrue(m.read(self.file,NOW)['online'])
   self.assertEqual(len(m.read(self.file,NOW)['stores']),10)
if __name__=='__main__':unittest.main()
