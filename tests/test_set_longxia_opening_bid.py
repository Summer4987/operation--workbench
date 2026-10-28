import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from set_longxia_opening_bid import updated_config

class OpeningConfigTests(unittest.TestCase):
 def test_only_bid_floor_changes_and_source_is_preserved(self):
  data={'longxia':{'templates':[{'minBid':30,'maxBid':90,'shares':[2000,4000,1000,1500,1500,0]}],'stores':[{'dailyBudget':15000,'dayTypes':{'weekday':{'dailyBudget':15000}}}]},'budgetSettings':{'unrelated':'preserved'}}
  original=copy.deepcopy(data);updated=updated_config(data)
  self.assertEqual(data,original);self.assertEqual(updated['longxia']['templates'][0]['minBid'],40)
  updated['longxia']['templates'][0]['minBid']=30;self.assertEqual(updated,original)
 def test_conflicting_ceiling_is_rejected(self):
  with self.assertRaises(ValueError):updated_config({'longxia':{'templates':[{'minBid':10,'maxBid':30}]}})
if __name__=='__main__':unittest.main()
