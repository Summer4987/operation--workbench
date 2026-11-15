import copy
import json
from pathlib import Path
from unittest.mock import patch

from scripts import longxia_promo_snapshot as reader

NOW = 1794702000000

def test_snapshot_only_reads_fresh_identity_matched_values_in_cents(tmp_path):
    path, config = tmp_path / 'fleet.json', tmp_path / 'config.json'
    config.write_text(json.dumps({'longxia': {'stores': [{'profileId': 'profile1', 'name': '甲店', 'sourceStore': '甲'}]}}))
    row = {'id': 'profile1', 'name': '甲店', 'day': '2026-11-15', 'snapshotAt': NOW, 'spend': 1234, 'platformBudget': 5000}
    data = {'schema': 1, 'generatedAt': NOW, 'stores': [row]}
    def read(payload):
        path.write_text(json.dumps(payload))
        return reader.read_records([{'sourceStore': '甲'}], path=path, config_path=config, now=NOW)[0]
    record = read(data)
    assert record['ok'] and record['today_spend'] == 12.34 and record['budget'] == 50
    assert record['remaining_budget'] == 37.66
    for changes in [{'day': '2026-11-14'}, {'snapshotAt': NOW - 1800001}, {'spend': None}, {'spend': True}, {'paused': True}, {'id': 'wrong'}]:
        payload = copy.deepcopy(data); payload['stores'][0].update(changes)
        record = read(payload)
        assert not record['ok'] and record['today_spend'] is None
    stale = copy.deepcopy(data); stale['generatedAt'] = NOW - 90001
    assert not read(stale)['ok']
    assert not reader.read_records([{'sourceStore': '甲'}], path=tmp_path/'missing', config_path=config, now=NOW)[0]['ok']


def test_spend_consumer_never_starts_browser_or_workers_even_without_snapshot(tmp_path):
    from scripts import meituan_promo_spend_query as query
    with patch.object(query, 'load_meituan_tasks', return_value=[{'sourceStore': '甲'}]), \
         patch.object(query, 'require_helpers', side_effect=AssertionError('must not browse')), \
         patch.object(query, 'build_payload_parallel', side_effect=AssertionError('must not start workers')), \
         patch.object(reader, 'SNAPSHOT_PATH', tmp_path/'missing'):
        payload = query.build_payload('all', [], None, workers=4)
    assert payload['source'] == 'longxia_snapshot'
    assert payload['status'] == 'failed'
    assert payload['items'][0]['today_spend'] is None
