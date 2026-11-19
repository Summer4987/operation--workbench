"""Run as root on the web host, triggered by Mac mini after main deployment.
Uses only loopback HTTP and test-owned records; never prints secrets or data values.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT='http://127.0.0.1'
HOST='139.155.148.169'
pid=subprocess.check_output(['systemctl','show','inventory-board','-p','MainPID','--value'],text=True).strip()
environ=dict(item.split(b'=',1) for item in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in item)
username=environ.get(b'OPERATION_AUTH_USERNAME',b'summer').decode()
password=environ[b'INVENTORY_PASSWORD'].decode()

def session():return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(client,path,payload=None):
 req=Request(ROOT+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Host':HOST,'Content-Type':'application/json'},method='GET' if payload is None else 'POST')
 try:
  with client.open(req,timeout=15) as response:return response.status,response.read()
 except HTTPError as error:return error.code,error.read()
def json_call(client,path,payload=None):
 status,data=call(client,path,payload)
 assert status==200,(path,status)
 return json.loads(data)
owner=session();member=session();account_id=None
try:
 json_call(owner,'/api/auth/login',{'username':username,'password':password})
 catalog=json_call(owner,'/api/access/accounts')['stores']
 target=next(s for s in catalog if s['id']=='franchise-1')
 payload={'username':'qa.scope.'+secrets.token_hex(5),'name':'临时权限验收','role':'manager','enabled':True,'stores':[target['id']],'permissions':{'overview':['view','export'],'daily':['view','export'],'ordering':['view'],'inventory':['view']},'note':'生产权限验收脚本创建，结束后清理'}
 created=json_call(owner,'/api/access/accounts',payload);account_id=created['account']['id']
 json_call(member,'/api/auth/login',{'username':payload['username'],'password':created['initial_password']})
 mine=json_call(member,'/api/access/me');assert [s['id'] for s in mine['stores']]==[target['id']]
 for module in ['overview','daily','ordering','inventory']:
  data=json_call(member,'/api/access/data/'+module)
  assert all(row['store_id']==target['id'] for row in data['rows'])
  expected=sum(float(r.get('total_orders',r.get('orders',0)) or 0) for r in data['rows'])
  assert data['summary']['orders']==expected
  if module in ['overview','daily']:
   status,export=call(member,'/api/access/data/'+module+'?export=true');assert status==200
   for store in catalog:
    if store['id']!=target['id']:assert store['name'].encode() not in export
 for path in ['/operation-workbench/workbench-data.js','/operation-workbench/data/realtime-history.json','/business-report-dashboard/data/latest.json','/daily-order/api/admin/summary?token=daily-order-admin','/api/promo-budget-overrides','/operation-workbench/account-permissions/']:
  assert call(member,path)[0]==403,path
 assert call(member,'/api/access/accounts')[0]==403
 assert call(member,'/api/access/data/budget')[0]==403
 assert call(member,'/api/access/data/overview',None)[0]==200
 assert call(member,'/operation-workbench/account-permissions/member.html')[0]==200
 json_call(owner,'/api/access/accounts',{**created['account'],'enabled':False})
 assert call(member,'/api/access/me')[0]==401
 # Existing owner sessions and legacy business routes are still usable.
 assert call(owner,'/operation-workbench/')[0]==200
 assert call(owner,'/api/summary')[0]==200
 print('PASS: owner compatibility, account persistence, one-store data/totals/export, raw-link denial, member portal, disabled-session revocation')
finally:
 if account_id:
  con=sqlite3.connect('/var/lib/xiong-access/accounts.sqlite3')
  con.execute('PRAGMA foreign_keys=ON')
  row=con.execute('SELECT name,username FROM accounts WHERE id=?',(account_id,)).fetchone()
  if row and row[0]=='临时权限验收' and row[1].startswith('qa.scope.'):
   con.execute('DELETE FROM accounts WHERE id=?',(account_id,));con.commit()
  con.close()
