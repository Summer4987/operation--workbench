import copy
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('longxia_config',ROOT/'inventory-board/app/longxia_config.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class LongxiaConfigTests(unittest.TestCase):
 def test_caps_and_projection(self):
  c=m.validate(m.DEFAULT);d=m.project({'stores':{'unrelated':{'美团':{'lunchBudget':5}}},'longxia':c})
  for name,lunch,daily in [('万象城店',72,120),('朝阳门店',140,200),('保利中心店',84,120),('安贞店',105,150)]:
   self.assertEqual(d['stores'][name]['美团']['lunchBudget'],lunch);self.assertEqual(d['stores'][name]['美团']['dinnerBudget'],daily)
  self.assertEqual(d['stores']['unrelated']['美团']['lunchBudget'],5)
  self.assertEqual(m.validate(c),c)
 def test_reject_invalid_config(self):
  for patch in [lambda c:c['stores'][0].update(key='wrong'),lambda c:c['stores'][0].update(dailyBudget=20100),lambda c:c['templates'][0].update(shares=[1]*6),lambda c:c['stores'][0].update(templateId='missing'),lambda c:c['templates'][0].update(minBid=25)]:
   c=copy.deepcopy(m.DEFAULT);patch(c)
   with self.assertRaises(ValueError):m.validate(c)
 def test_revision_changes_with_assignment(self):
  c=copy.deepcopy(m.DEFAULT);before=m.validate(c)['revision'];c['stores'][0]['templateId']=c['templates'][1]['id'];self.assertNotEqual(m.validate(c)['revision'],before)
if __name__=='__main__': unittest.main()
