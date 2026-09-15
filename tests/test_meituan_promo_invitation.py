import json
import subprocess
import unittest
from unittest.mock import Mock
from tests.test_meituan_budget_cdp import load_module


class InvitationOverlayTests(unittest.TestCase):
    def test_only_marketing_invitation_is_hidden_without_clicks(self):
        module = load_module()
        frame = Mock()
        module.hide_promo_invitation_overlay(Mock(frames=[frame]))
        javascript = frame.evaluate.call_args.args[0]
        harness = '''
const hidden = [];
const texts = ['站外推广活动邀请您参加 放弃资格 立即领取', '请完成安全验证', '预算设置 确定', '其他活动 立即领取'];
global.document = {querySelectorAll: () => texts.map((innerText, i) => ({innerText, style: {setProperty: (...args) => hidden.push([i, ...args])}}))};
(''' + javascript + ''')();
process.stdout.write(JSON.stringify(hidden));
'''
        result = subprocess.run(['/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node', '-e', harness], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [[0, 'display', 'none', 'important']])
