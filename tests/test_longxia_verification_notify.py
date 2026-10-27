import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import longxia_verification_notify as notify

NOW = 1793091600000


def status():
    return {'schema': 1, 'generatedAt': NOW, 'stores': [
        {'id': str(i), 'name': f'门店{i}', 'paused': False, 'message': '正常巡检', 'resultAt': NOW} for i in range(8)]}


def challenge(value, index=0, current=True):
    value['stores'][index].update(paused=True, message='本店当前显示美团安全验证' if current else '本店曾发生安全验证跳转')


class VerificationAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'notify.json'
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, text):
        self.sent.append(text)
        return True

    def test_batch_dedup_and_restart(self):
        value = status()
        challenge(value)
        challenge(value, 1, current=False)
        value['stores'][2].update(paused=True, message='本店已人工暂停')
        original = copy.deepcopy(value)
        first = notify.process_status(value, self.path, self.send, NOW)
        self.assertEqual(first['attempted'], 2)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('当前显示验证码', self.sent[0])
        self.assertIn('曾发生验证跳转，需检查当前页面', self.sent[0])
        self.assertIn('恢复本店', self.sent[0])
        self.assertNotIn('门店2', self.sent[0])
        value['generatedAt'] += 15000
        value['stores'][0]['resultAt'] += 15000
        self.assertEqual(notify.process_status(value, self.path, self.send, NOW + 15000)['attempted'], 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(original['stores'][0]['paused'], True)

    def test_recovery_rearms_and_new_store_alerts(self):
        value = status();challenge(value)
        notify.process_status(value, self.path, self.send, NOW)
        value['stores'][0]['paused'] = False
        value['generatedAt'] = NOW + 15000
        notify.process_status(value, self.path, self.send, NOW + 15000)
        challenge(value);challenge(value, 3)
        value['generatedAt'] = NOW + 30000
        self.assertEqual(notify.process_status(value, self.path, self.send, NOW + 30000)['attempted'], 2)
        self.assertEqual(len(self.sent), 2)

    def test_failure_retries_without_marking_delivered(self):
        value = status();challenge(value)
        result = notify.process_status(value, self.path, lambda _: False, NOW)
        self.assertFalse(result['delivered'])
        value['generatedAt'] = NOW + 15000
        self.assertEqual(notify.process_status(value, self.path, self.send, NOW + 15000)['attempted'], 0)
        value['generatedAt'] = NOW + 30000
        self.assertTrue(notify.process_status(value, self.path, self.send, NOW + 30000)['delivered'])
        self.assertEqual(json.loads(self.path.read_text())['incidents']['0']['attempts'], 2)

    def test_stale_invalid_and_nonverification_status_do_not_send_or_clear_state(self):
        value = status();challenge(value)
        notify.process_status(value, self.path, self.send, NOW)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            notify.process_status(status(), self.path, self.send, NOW + 100000)
        self.assertEqual(self.path.read_bytes(), before)
        invalid = status();invalid['stores'][1]['id'] = '0'
        with self.assertRaises(ValueError):
            notify.process_status(invalid, self.path, self.send, NOW)
        healthy = status();healthy['stores'][0].update(paused=False, message='历史安全验证已恢复')
        healthy['stores'][1].update(paused=True, message='午餐预算达到，推广暂停')
        self.assertEqual(notify.process_status(healthy, self.path, self.send, NOW)['attempted'], 0)
        self.assertEqual(len(self.sent), 1)

    def test_manual_verification_blocker_also_alerts_without_pause_flag(self):
        value = status()
        value['stores'][0].update(status='error', message='页面出现验证或访问限制，请人工接管')
        value['stores'][1].update(status='running', message='历史安全验证已恢复')
        result = notify.process_status(value, self.path, self.send, NOW)
        self.assertEqual(result['attempted'], 1)
        self.assertIn('检测到验证或访问限制，需人工检查', self.sent[0])
        self.assertNotIn('门店1', self.sent[0])


if __name__ == '__main__':
    unittest.main()
