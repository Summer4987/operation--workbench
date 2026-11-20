import importlib.util
import io
import json
from pathlib import Path
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def env(monkeypatch):
    spec = importlib.util.spec_from_file_location('beijing_security_app', ROOT/'daily-order/app/main.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setenv('STORE_ORDER_ACCOUNTS_JSON', json.dumps({'accounts': {'bj': {'password':'test-password','store_name':'朝阳门店'}, 'cd': {'password':'other-password','store_name':'银泰城店'}}}))
    return m, TestClient(m.app)

def login(c, username='bj', password='test-password'):
    assert c.post('/daily-order/api/auth/login', json={'username':username,'password':password}).status_code == 200

def test_anonymous_denied_even_without_account_configuration(env, monkeypatch):
    m,c=env
    for path in ['/beijing-order/api/catalog','/beijing-order/api/orders?store_name=朝阳门店']:
        assert c.get(path).status_code == 401
    assert c.post('/beijing-order/api/orders',json={}).status_code == 401
    monkeypatch.setattr(m, '_store_order_session', lambda r:None)
    monkeypatch.setattr(m, '_store_order_auth_enabled', lambda:False)
    assert c.get('/beijing-order/api/catalog').status_code == 401
    page=c.get('/beijing-order/');assert page.status_code==200
    assert '请输入门店账号密码' in page.text and 'catalogGrid' not in page.text

def test_store_login_and_forged_store_parameter(env,monkeypatch):
    m,c=env;login(c)
    data=c.get('/beijing-order/api/catalog').json();assert [s['name'] for s in data['stores']]==['朝阳门店']
    monkeypatch.setattr(m,'_public_store_orders',lambda name,*a:[{'verified_store':name}])
    result=c.get('/beijing-order/api/orders?store_name=银泰城店&order_ids=example').json()
    assert result['items']==[{'verified_store':'朝阳门店'}]
    async def submit(*a):return {'bound':a[-1]}
    monkeypatch.setattr(m,'_submit_order',submit)
    assert c.post('/beijing-order/api/orders',json={'store_name':'银泰城店'}).json()['bound']=='朝阳门店'

def test_other_store_cannot_read_catalog_orders_or_submit(env):
    m,c=env;login(c,'cd','other-password')
    for path in ['/beijing-order/api/catalog','/beijing-order/api/orders?store_name=朝阳门店']:
        assert c.get(path).status_code==403
    assert c.post('/beijing-order/api/orders',json={}).status_code==403

def test_dashboard_scope_and_view_edit_separation(env,monkeypatch):
    m,c=env;c.cookies.set('xiong_access','mock-session')
    actor={'owner':False,'stores':[{'name':'朝阳门店'}],'permissions':{'ordering':['view']}}
    monkeypatch.setattr(m.url_request,'urlopen',lambda req,timeout:io.BytesIO(json.dumps(actor).encode()))
    assert c.get('/beijing-order/api/catalog').status_code==200
    assert c.post('/beijing-order/api/orders',json={}).status_code==403
    actor['stores']=[{'name':'银泰城店'}]
    assert c.get('/beijing-order/api/catalog').status_code==403
    actor.update(owner=True)
    assert c.get('/beijing-order/api/catalog').status_code==200

def test_permission_service_failure_is_closed(env,monkeypatch):
    m,c=env;c.cookies.set('xiong_access','mock-session')
    def fail(*a,**k):raise URLError('unavailable')
    monkeypatch.setattr(m.url_request,'urlopen',fail)
    assert c.get('/beijing-order/api/catalog').status_code==503
