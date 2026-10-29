import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module
config=load('registration_config',ROOT/'inventory-board/app/longxia_config.py')
settings=load('registration_settings',ROOT/'inventory-board/app/budget_settings.py')
deploy=load('registration_deploy',ROOT/'scripts/deploy_longxia_settings.py')

class RegistrationTests(unittest.TestCase):
    def fixture(self):
        full=config.validate(config.DEFAULT)
        data={'longxia':full,'stores':{'unrelated':{'美团':{'dinnerBudget':5}}},'budgetSettings':settings.validate(None,full)}
        settings.project(data)
        data['longxia']['stores']=data['longxia']['stores'][:9]
        for row in data['budgetSettings']['entries']:
            if row['sourceStore'] not in {r['sourceStore'] for r in data['longxia']['stores']}:
                for value in row['platforms']['美团'].values():value['templateId']=None
        return data
    def test_register_seven_only_fill_missing_templates_preserve_all_totals(self):
        before=self.fixture();data=deploy.register_missing_stores(before,config.DEFAULT)
        self.assertEqual(len(data['longxia']['stores']),16)
        self.assertEqual(data['longxia']['stores'][:9],before['longxia']['stores'])
        self.assertEqual(len(before['longxia']['stores']),9)
        for old,row in zip(before['budgetSettings']['entries'],data['budgetSettings']['entries']):
            self.assertEqual(row['platforms']['饿了么'],old['platforms']['饿了么'])
            for day in ['weekday','weekend']:
                self.assertEqual(row['platforms']['美团'][day]['dailyBudget'],old['platforms']['美团'][day]['dailyBudget'])
                self.assertEqual(row['platforms']['美团'][day]['lunchBudget'],old['platforms']['美团'][day]['lunchBudget'])
        data['longxia']=config.validate(data['longxia'])
        data['budgetSettings']=settings.validate(data['budgetSettings'],data['longxia'])
        settings.project(data)
        names={t['id']:t['name'] for t in data['longxia']['templates']}
        for row in data['longxia']['stores'][9:]:
            expected='住宅混合区' if row['name']=='五一广场店' else '白领工作区'
            self.assertEqual(names[row['templateId']],expected)
            for value in row['dayTypes'].values():self.assertEqual(names[value['templateId']],expected)
        self.assertEqual(deploy.register_missing_stores(data,config.DEFAULT),data)
    def test_explicit_existing_choice_is_not_overwritten_and_unknown_binding_rejected(self):
        data=self.fixture()
        row=next(r for r in data['budgetSettings']['entries'] if r['name']=='五一广场店')
        row['platforms']['美团']['weekend']['templateId']=config.DEFAULT['templates'][0]['id']
        updated=deploy.register_missing_stores(data,config.DEFAULT)
        row=next(r for r in updated['longxia']['stores'] if r['name']=='五一广场店')
        self.assertEqual(row['dayTypes']['weekend']['templateId'],config.DEFAULT['templates'][0]['id'])
        row['key']='other|store|cpc'
        with self.assertRaises(ValueError):config.validate(updated['longxia'])

if __name__=='__main__':unittest.main()
