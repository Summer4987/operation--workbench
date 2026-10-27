import copy,importlib.util,json,sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('budget_settings_test');pkg.__path__=[str(ROOT/'inventory-board/app')];sys.modules[pkg.__name__]=pkg
for name in ['longxia_config','budget_settings']:
 spec=importlib.util.spec_from_file_location(pkg.__name__+'.'+name,ROOT/'inventory-board/app'/f'{name}.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);setattr(pkg,name,module)
m=pkg.budget_settings;c=pkg.longxia_config
class BudgetSettingsTests(unittest.TestCase):
 def data(self):
  config=c.validate(c.DEFAULT);return {'stores':{},'longxia':config,'budgetSettings':m.validate(None,config)}
 def test_all_stores_two_platforms_two_day_types_keep_original_totals(self):
  d=self.data();self.assertEqual(len(d['budgetSettings']['entries']),16)
  for row in d['budgetSettings']['entries']:
   for days in row['platforms'].values():
    for v in days.values():v['templateId']=d['longxia']['templates'][1]['id']
  d['budgetSettings']=m.validate(d['budgetSettings'],d['longxia']);m.project(d)
  for row in m.BASELINE['stores']:
   for platform,days in row['platforms'].items():
    self.assertEqual(d['stores'][row['sourceStore']][platform]['dinnerBudget']*100,days['weekday']['dailyBudget'])
    self.assertEqual(d['stores'][row['sourceStore']][platform]['weekendDinnerBudget']*100,days['weekend']['dailyBudget'])
  self.assertEqual(c.validate(d['longxia']),d['longxia'])
 def test_budget_is_readonly_and_all_stores_required(self):
  d=self.data();bad=copy.deepcopy(d['budgetSettings']);bad['entries'][0]['platforms']['美团']['weekend']['dailyBudget']+=100
  with self.assertRaisesRegex(ValueError,'总预算已锁定'):m.validate(bad,d['longxia'])
  bad=copy.deepcopy(d['budgetSettings']);bad['entries'].pop()
  with self.assertRaises(ValueError):m.validate(bad,d['longxia'])
 def test_restore_holiday_amounts_and_preserve_weekday(self):
  d=m.project(self.data());r=next(r for r in d['longxia']['stores'] if r['name']=='朝阳门店');self.assertEqual(r['dayTypes']['weekday']['dailyBudget'],20000);self.assertEqual(r['dayTypes']['weekend']['dailyBudget'],10000)
  self.assertEqual(d['stores']['朝阳门店']['美团']['weekendDinnerBudget'],100);self.assertEqual(d['stores']['朝阳门店']['美团']['dinnerBudget'],200)
 def test_rounding_keeps_118_yuan_and_choice_changes_revision(self):
  d=self.data();a=m.amounts(11800,d['longxia']['templates'][1]['shares']);self.assertEqual(sum(a),11800);self.assertEqual(sum(a[:3]),7100);self.assertTrue(all(v%100==0 for v in a))
  before=d['budgetSettings']['revision'];r=next(r for r in d['budgetSettings']['entries'] if r['name']=='光谷店');r['platforms']['饿了么']['weekend']['templateId']=d['longxia']['templates'][0]['id'];self.assertNotEqual(m.validate(d['budgetSettings'],d['longxia'])['revision'],before)
if __name__=='__main__':unittest.main()
