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
owner=session();user=session();account_id=None
try:
 json_call(owner,'/api/auth/login',{'username':username,'password':password})
 assert b'accountLogout' in call(owner,'/operation-workbench/')[1]
 assert b'accountLogout' in call(owner,'/operation-workbench/account-permissions/')[1]
 assert call(owner,'/operation-workbench/account-session.js')[0]==200
 payload={'username':'qa.messages.'+secrets.token_hex(5),'name':'临时消息验收','role':'custom','enabled':True,'stores':['direct-1'],'permissions':{'direct-messages':['view']},'note':'验收结束清理'}
 created=json_call(owner,'/api/access/accounts',payload);account_id=created['account']['id']
 json_call(user,'/api/auth/login',{'username':payload['username'],'password':created['initial_password']})
 status,raw=call(user,'/api/access/messages/page');assert status==200
 page=raw.decode();assert 'data-store="朝阳门店"' in page
 for store in ['银泰城店','万象城店','金融城店','保利中心店']:assert 'data-store="'+store+'"' not in page
 assert call(user,'/operation-workbench/business-report-dashboard/direct-dashboard/customer-messages/')[0]==403
 import re,html
 media=re.findall(r'(?:src|href)="(/api/access/messages/media[^"]+)"',page)
 if media: assert call(user,html.unescape(media[0]))[0]==200
 assert call(user,'/api/access/messages/media?file=attachments/../../secret')[0]==403
 payload={**created['account'],'permissions':{'direct-daily':['view']}}
 updated=json_call(owner,'/api/access/accounts',payload)
 json_call(user,'/api/auth/login',{'username':payload['username'],'password':created['initial_password']})
 assert call(user,'/api/access/messages/page')[0]==403
 json_call(user,'/api/access/logout',{})
 assert call(user,'/api/access/me')[0]==401
 json_call(owner,'/api/access/logout',{})
 assert call(owner,'/api/access/me')[0]==401
 print('PASS: live logout, owner UI, message permission, scoped archive/attachments and revocation')
finally:
 if account_id:
  with sqlite3.connect('/var/lib/xiong-access/accounts.sqlite3') as con:
   con.execute('DELETE FROM sessions WHERE account_id=?',(account_id,))
   con.execute('DELETE FROM accounts WHERE id=? AND username LIKE ?',(account_id,'qa.messages.%'))
