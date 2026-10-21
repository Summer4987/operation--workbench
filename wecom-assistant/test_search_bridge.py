import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('search_bridge',Path(__file__).with_name('search_bridge.py'))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class SearchTests(unittest.TestCase):
 def test_results_are_bounded_deduplicated_and_unsafe_urls_rejected(self):
  xml=b'<rss><channel><item><title>Safe</title><link>https://example.com/</link><description>&lt;b&gt;Snippet&lt;/b&gt;</description></item><item><title>duplicate</title><link>https://example.com/</link></item><item><title>unsafe</title><link>file:///private/file</link></item></channel></rss>'
  r=mod.parse_feed(xml);self.assertEqual(len(r),1);self.assertEqual(r[0]['snippet'],'Snippet')
 def test_xml_entities_are_rejected(self):
  with self.assertRaises(ValueError):mod.parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>')
