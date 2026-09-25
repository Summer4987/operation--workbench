import ast
import unittest
from pathlib import Path

class MinimumBudgetTest(unittest.TestCase):
    def test_invalid_target_never_opens_platform(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'store-inspection/meituan_budget_cdp.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute_task')
        scope={}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'budget_function','exec'),scope)
        for target in [35,42,49]:
            result=scope['execute_task'](None,'',{'targetBudget':target,'store':'test'},commit=True)
            self.assertTrue(result['skipped'])
            self.assertEqual(result['failure_type'],'below_platform_minimum')
            self.assertEqual(result['targetBudget'],target)
