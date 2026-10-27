import json,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NODE=os.environ.get('TEST_NODE','/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
class FixedTotalsPreviewTests(unittest.TestCase):
 def test_four_date_cases_all_stores_both_platforms(self):
  baseline=json.loads((ROOT/'inventory-board/app/budget_totals_baseline.json').read_text());known={r['sourceStore']:r for r in baseline['stores']}
  canonical=lambda name:'丽泽门店' if '丽泽' in name else name
  with tempfile.TemporaryDirectory() as folder:
   env={**os.environ,'OPERATION_BUDGET_RUNTIME_ROOT':folder}
   subprocess.run(['/bin/zsh',str(ROOT/'scripts/install_promo_budget_runtime.zsh')],env=env,check=True,capture_output=True)
   for date,kind in [('2026-10-27','weekday'),('2026-10-31','weekend'),('2026-10-01','weekend'),('2026-10-10','weekday')]:
    subprocess.run([NODE,str(Path(folder)/'scripts/build_promo_budget_preview.mjs')],env={**env,'PROMO_BUDGET_DATE':date},check=True,capture_output=True)
    result=json.loads((Path(folder)/'outputs/promo_budget_preview/latest.json').read_text())
    for key,platform in [('meituan_dinner','美团'),('eleme_dinner','饿了么')]:
     self.assertEqual(len(result[key]),16)
     for row in result[key]:
      name=canonical(row.get('sourceStore') or row['store']);expected=known[name]['platforms'][platform][kind]['dailyBudget']/100
      self.assertEqual(row['targetBudget'],expected,(date,platform,name))
if __name__=='__main__':unittest.main()
