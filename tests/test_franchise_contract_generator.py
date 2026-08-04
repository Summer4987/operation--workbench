from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORMATTER = ROOT / "franchise-contract-generator" / "contract-format.js"


def render_html(text: str) -> str:
    script = f"""
const formatter = require({json.dumps(str(FORMATTER))});
process.stdout.write(formatter.wordHtml('测试合同', {json.dumps(text, ensure_ascii=False)}));
"""
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout


def test_contract_export_uses_real_paragraphs_and_headings():
    html = render_html("第一条 合作内容\n\n1.1 第一项。\n\n（1）具体事项。")

    assert '<h2>第一条 合作内容</h2>' in html
    assert "<p>1.1 第一项。</p>" in html
    assert '<p class="list-item">（1）具体事项。</p>' in html
    assert "white-space:pre-wrap" not in html


def test_contract_export_splits_clauses_flattened_in_source_template():
    html = render_html("3.1 第一项。3.2 第二项。    3.3 第三项。")

    assert "<p>3.1 第一项。</p>" in html
    assert "<p>3.2 第二项。</p>" in html
    assert "<p>3.3 第三项。</p>" in html


def test_bundle_starts_purchase_agreement_on_new_page():
    html = render_html("服务合同正文\n\n采购框架协议\n\n第一条 合作内容")

    assert '<h1 class="part-title page-break-before">采购框架协议</h1>' in html
