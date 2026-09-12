import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_wansongyuan_weekday_weekend_budget_preview():
    node = shutil.which('node')
    assert node
    for date, expected in [('2026-09-14', (100, 150)), ('2026-09-13', (80, 120))]:
        subprocess.run([node, str(ROOT / 'scripts/build_promo_budget_preview.mjs')],
                       cwd=ROOT, env={**os.environ, 'PROMO_BUDGET_DATE': date},
                       check=True, capture_output=True)
        payload = json.loads((ROOT / 'outputs/promo_budget_preview/latest.json').read_text())
        for platform in ['eleme', 'meituan']:
            for period, budget in zip(['lunch', 'dinner'], expected):
                rows = [x for x in payload[f'{platform}_{period}']
                        if (x.get('sourceStore') or x.get('store')) == '万松园店']
                assert len(rows) == 1
                row = rows[0]
                assert row['targetBudget'] == budget
                if platform == 'eleme':
                    assert row['shopId'] == 545830793
                else:
                    assert row['status'] == 'auto'
                    assert row['keyword'] == '万松园'
