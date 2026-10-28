import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('results',Path(__file__).parents[1]/'scripts/customer_inspection_results.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ReviewedResults(unittest.TestCase):
    def fixture(self,root):
        source=root/'source';files=[]
        for name in ['01-first-screen.png','02-steak-category.png']:
            f=source/'meituan/银泰城店'/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'\x89PNG\r\n\x1a\n'+name.encode());files.append(dict(path=str(f.relative_to(source)),sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        report=dict(date='2026-10-26',records=[dict(platform='meituan',store='银泰城店',status='visually_accepted',files=files),dict(platform='taobao-shangou',store='银泰城店',status='blocked_human_verification',files=files,note='验证码阻塞')])
        (source/'reviewed-progress.json').write_text(json.dumps(report));return source,report

    def test_only_reviewed_pairs_are_published_and_repeat_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,_=self.fixture(root);stage=root/'stage';result=module.build(source,stage)
            self.assertEqual(len(result['records'][0]['images']),2);self.assertEqual(result['records'][1]['images'],[])
            self.assertEqual(len(module.build(source,stage)['records']),2)
            self.assertEqual(json.loads((stage/'data/index.json').read_text())['dates'],['2026-10-26'])

    def test_corrupt_and_cross_store_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,report=self.fixture(root)
            report['records'][0]['files'][0]['sha256']='bad';(source/'reviewed-progress.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'integrity'):module.build(source,root/'stage')
            report['records'][0]['files'][0]['path']='../private.png';(source/'reviewed-progress.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'paths'):module.build(source,root/'stage')

    def test_automatic_checks_are_not_mislabeled_as_visual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,report=self.fixture(root)
            report['records'][0]['status']='ocr_verified';(source/'reviewed-progress.json').write_text(json.dumps(report))
            result=module.build(source,root/'stage')
            self.assertEqual(len(result['records'][0]['images']),2)
            self.assertEqual(result['records'][0]['status'],'ocr_verified')
            self.assertIn('未人工逐图复核',result['records'][0]['review_method'])

    def test_retired_entry_removal_preserves_other_live_content(self):
        html='<main>live budget settings</main>\n  <a href="#customer-inspection">客户端巡检结果</a>\n  <section class="center-section" id="customer-inspection"><div>old</div><iframe></iframe></section>\n<section id="budget">custom budget</section>'
        result=module.remove_entry(html)
        self.assertNotIn('customer-inspection',result)
        self.assertIn('live budget settings',result)
        self.assertIn('<section id="budget">custom budget</section>',result)
        self.assertEqual(module.remove_entry(result),result)
