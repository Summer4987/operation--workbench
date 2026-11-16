from scripts.set_longxia_bid_policy import updated_config


def test_only_bid_range_changes_and_original_is_preserved():
    data={'longxia':{'templates':[{'id':'t','minBid':40,'maxBid':90,'shares':[1,2]}],'stores':[{'profileId':'p','dailyBudget':10000}],'periods':[[630,660]]},'other':'preserved'}
    new=updated_config(data)
    assert new['longxia']['templates'][0]=={'id':'t','minBid':50,'maxBid':100,'shares':[1,2]}
    assert data['longxia']['templates'][0]['maxBid']==90
    assert new['longxia']['stores']==data['longxia']['stores']
    assert new['longxia']['periods']==data['longxia']['periods']
    assert new['other']=='preserved'
