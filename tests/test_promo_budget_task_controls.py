import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = '/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'


class BudgetTaskControlTests(unittest.TestCase):
    def test_pause_only_changes_wanxiangcheng_meituan_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {**os.environ, 'OPERATION_BUDGET_RUNTIME_ROOT': folder, 'PROMO_BUDGET_DATE': '2026-10-14'}
            subprocess.run(['/bin/zsh', str(ROOT / 'scripts/install_promo_budget_runtime.zsh')], env=env, check=True, capture_output=True)
            runtime = Path(folder)
            def preview():
                subprocess.run([NODE, str(runtime / 'scripts/build_promo_budget_preview.mjs')], env=env, check=True, capture_output=True)
                return json.loads((runtime / 'outputs/promo_budget_preview/latest.json').read_text())
            paused = preview()
            control_path = runtime / 'config/promo_budget_task_controls.json'
            controls = json.loads(control_path.read_text())
            controls['meituanStores']['万象城店'].pop('pausedFrom')
            control_path.write_text(json.dumps(controls, ensure_ascii=False))
            baseline = preview()
            for key in ['eleme_lunch', 'eleme_dinner']:
                self.assertEqual(paused[key], baseline[key])
                self.assertEqual(len(paused[key]), 16)
            for key in ['meituan_lunch', 'meituan_dinner']:
                self.assertEqual(len([r for r in paused[key] if r['status'] == 'auto']), 15)
                for a, b in zip(paused[key], baseline[key]):
                    if a['sourceStore'] != '万象城店':
                        self.assertEqual(a, b)
                    else:
                        self.assertEqual(a['status'], 'paused')
                        self.assertEqual(a['targetBudget'], b['targetBudget'])

    def test_restricted_skip_is_explicit_in_result_message(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from scripts import build_promo_budget_result as result
        row = result.summarize_platform('meituan', [{'keyword': '雅宝'}], [{'mode': 'commit', 'results': [{'keyword': '雅宝', 'ok': True, 'skipped': True, 'failure_type': 'promotion_restricted'}]}])
        self.assertEqual(row['skipped_stores'], ['雅宝'])
        message = result.build_message('午餐', {'meituan': row, 'eleme': row})
        self.assertIn('按规则跳过', message)
        self.assertNotIn('全部门店均已完成真实提交', message)


if __name__ == '__main__':
    unittest.main()
