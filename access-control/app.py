"""Account store and authorization gateway. No platform execution occurs here."""
from __future__ import annotations
import csv
import html
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request as URLRequest, urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

BASE = Path(__file__).resolve().parent
UI = BASE.parent / 'account-permissions'
COOKIE = 'xiong_access'
ROLES = {'admin', 'regional', 'manager', 'finance', 'franchisee', 'custom'}
STORE_NAMES = ['朝阳门店', '银泰城店', '万象城店', '金融城店', '保利中心店', '安贞', '中关村', '清河', '金融街', '丽泽', '双井', '光谷', '五一广场', '望京', '滨江店']
STORES = [{'id': f'direct-{i+1}', 'name': n, 'group': '直营门店'} for i, n in enumerate(STORE_NAMES[:5])] + [{'id': f'franchise-{i+1}', 'name': n, 'group': '加盟门店'} for i, n in enumerate(STORE_NAMES[5:])]
def catalog():
 result=[dict(s) for s in STORES]
 for group,filename,prefix in [('直营门店','direct-latest.json','direct'),('加盟门店','latest.json','franchise')]:
  source=read_json('business-report-dashboard/data/'+filename)
  for name in source.get('target_stores',[]):
   if not isinstance(name,str) or not name.strip() or any(s['name']==name for s in result):continue
   result.append({'id':prefix+'-'+hashlib.sha256(name.encode()).hexdigest()[:12],'name':name,'group':group})
 return result

MODULES = {
 'direct-messages': ['view'],
 'direct-daily': ['view', 'export'], 'direct-reviews': ['view', 'edit', 'export'],
 'overview': ['view', 'export'], 'daily': ['view', 'export'], 'reviews': ['view', 'edit', 'export'],
 'budget': ['view', 'edit', 'approve', 'export'], 'bidding': ['view', 'edit', 'approve'],
 'balances': ['view', 'export'], 'ordering': ['view', 'edit', 'approve', 'export'],
 'inventory': ['view', 'edit', 'export'], 'floor-plan': ['view', 'edit', 'export'],
 'sales-receipts': ['view', 'edit', 'export'], 'franchise-contract': ['view', 'edit', 'export'],
 'accounts': ['view', 'edit'],
}
app = FastAPI(title='熊小小账号与权限', docs_url=None, redoc_url=None, openapi_url=None)


def db_path():
 return Path(os.environ.get('ACCESS_DB', '/var/lib/xiong-access/accounts.sqlite3'))


@contextmanager
def db():
 p = db_path(); p.parent.mkdir(parents=True, exist_ok=True)
 con = sqlite3.connect(str(p), timeout=15); con.row_factory = sqlite3.Row
 os.chmod(p, 0o600)
 con.executescript('''
 PRAGMA foreign_keys=ON;
 CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,role TEXT NOT NULL,enabled INTEGER NOT NULL,stores TEXT NOT NULL,permissions TEXT NOT NULL,note TEXT NOT NULL,password_hash TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,expires INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at INTEGER NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,detail TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL,at INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key,at);
 CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,module TEXT NOT NULL,store_id TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,created_at INTEGER NOT NULL,reviewer TEXT,reviewed_at INTEGER);
 ''')
 try:
  yield con
  con.commit()
 except Exception:
  con.rollback(); raise
 finally:
  con.close()


def audit(con, actor, action, target, detail=None):
 con.execute('INSERT INTO audit(at,actor,action,target,detail) VALUES(?,?,?,?,?)', (int(time.time()),actor,action,target,json.dumps(detail or {},ensure_ascii=False)))


def password_hash(password):
 salt = secrets.token_hex(16)
 return salt + ':' + hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()


def password_valid(password, saved):
 try:
  salt, expected = saved.split(':')
  actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
  return hmac.compare_digest(actual, expected)
 except (ValueError, TypeError):
  return False


def clean_account(row):
 return {k: (json.loads(row[k]) if k in ('stores','permissions') else bool(row[k]) if k == 'enabled' else row[k]) for k in ('id','username','name','role','enabled','stores','permissions','note','revision','updated_at')}


def owner_cookie(request):
 # Validate existing owner sessions with the existing service; no credential copying.
 cookie = request.cookies.get('operation_session')
 if not cookie: return False
 try:
  req = URLRequest(os.environ.get('ACCESS_LEGACY_URL','http://127.0.0.1:8000')+'/api/auth/check',headers={'Cookie': 'operation_session='+cookie})
  with urlopen(req,timeout=3) as response: return response.status == 204
 except (HTTPError,URLError,TimeoutError): return False


def identity(request):
 token = request.cookies.get(COOKIE)
 if token:
  with db() as con:
   row = con.execute('SELECT a.* FROM accounts a JOIN sessions s ON s.account_id=a.id WHERE s.token_hash=? AND s.expires>? AND a.enabled=1',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
  if not row: raise HTTPException(401,'登录已失效，请重新登录')
  return {**clean_account(row),'owner':False}
 if owner_cookie(request):
  return {'id':'owner','username':os.environ.get('OPERATION_AUTH_USERNAME','summer'),'name':'总管理员','role':'admin','enabled':True,'stores':[s['id'] for s in catalog()],'permissions':MODULES,'owner':True}
 raise HTTPException(401,'需要登录')


def manage(actor, action='view'):
 # Account administrators are global and must be explicitly granted every store.
 if actor['owner'] or (actor['role']=='admin' and set(actor['stores'])=={s['id'] for s in catalog()} and action in actor['permissions'].get('accounts',[])): return
 raise HTTPException(403,'仅总管理员可管理账号与权限')


def require(actor,module,action='view',store=None):
 if module not in MODULES or action not in actor['permissions'].get(module,[]): raise HTTPException(403,'没有此功能或操作权限')
 if store is not None and store not in actor['stores']: raise HTTPException(403,'没有此门店权限')


@app.middleware('http')
async def security(request, call_next):
 if request.method not in ('GET','HEAD','OPTIONS'):
  origin = request.headers.get('origin')
  host = request.headers.get('host','')
  if origin and urlsplit(origin).netloc != host:
   return JSONResponse({'detail':'拒绝跨站操作'},status_code=403)
  if request.headers.get('sec-fetch-site') == 'cross-site': return JSONResponse({'detail':'拒绝跨站操作'},status_code=403)
  if request.headers.get('content-type','').split(';')[0] != 'application/json': return JSONResponse({'detail':'需要 JSON 请求'},status_code=415)
  if int(request.headers.get('content-length','0') or 0)>65536: return JSONResponse({'detail':'请求过大'},status_code=413)
 response = await call_next(request)
 response.headers['Cache-Control']='no-store'
 response.headers['X-Content-Type-Options']='nosniff'
 response.headers['Referrer-Policy']='same-origin'
 return response


@app.get('/health')
def health():
 with db() as con: con.execute('SELECT 1')
 return {'status':'ok'}


@app.get('/login')
def login_page(): return FileResponse(UI/'login.html')


@app.post('/api/auth/login')
async def login(request:Request,payload:dict):
 username = str(payload.get('username','')).strip().lower(); password = str(payload.get('password',''))
 if len(username)>64 or len(password)>256: raise HTTPException(401,'用户名或密码不正确')
 # The proxy overwrites X-Real-IP; do not trust client-supplied forwarding chains.
 ip = request.headers.get('x-real-ip',request.client.host if request.client else '')
 keys = ['ip:'+ip,'user:'+username]
 now=int(time.time())
 with db() as con:
  con.execute('DELETE FROM attempts WHERE at<?',(now-900,))
  for key in keys:
   if con.execute('SELECT count(*) FROM attempts WHERE key=?',(key,)).fetchone()[0]>=(100 if key.startswith('ip:') else 10): raise HTTPException(429,'尝试过于频繁，请 15 分钟后重试')
  row=con.execute('SELECT * FROM accounts WHERE username=? COLLATE NOCASE',(username,)).fetchone()
 if row and row['enabled'] and password_valid(password,row['password_hash']):
  token=secrets.token_urlsafe(40)
  with db() as con:
   con.execute('DELETE FROM sessions WHERE expires<?',(now,))
   con.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],now+7*86400))
   audit(con,username,'login',row['id'])
   con.executemany('DELETE FROM attempts WHERE key=?',[(k,) for k in keys])
  response=JSONResponse({'status':'success','next':'/operation-workbench/account-permissions/member.html'})
  response.set_cookie(COOKIE,token,max_age=7*86400,httponly=True,samesite='lax',secure=request.headers.get('x-forwarded-proto')=='https',path='/')
  response.delete_cookie('operation_session',path='/')
  return response
 if username == os.environ.get('OPERATION_AUTH_USERNAME','summer').lower():
  try:
   req=URLRequest(os.environ.get('ACCESS_LEGACY_URL','http://127.0.0.1:8000')+'/api/auth/login',data=json.dumps({'username':username,'password':password}).encode(),headers={'Content-Type':'application/json','X-Forwarded-Proto':request.headers.get('x-forwarded-proto','http')})
   with urlopen(req,timeout=5) as legacy:
    response=JSONResponse({'status':'success','next':'/operation-workbench/'})
    for cookie in legacy.headers.get_all('Set-Cookie') or []: response.headers.append('Set-Cookie',cookie)
    response.delete_cookie(COOKIE,path='/')
    return response
  except (HTTPError,URLError,TimeoutError): pass
 # Equalize unknown-user password work.
 if not row: hashlib.pbkdf2_hmac('sha256',password.encode(),b'unknown-user-salt',600000)
 with db() as con:
  con.executemany('INSERT INTO attempts VALUES(?,?)',[(k,now) for k in keys])
 raise HTTPException(401,'用户名或密码不正确')


@app.post('/api/access/logout')
def logout(request:Request):
 token=request.cookies.get(COOKIE,'')
 with db() as con: con.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
 response=JSONResponse({'status':'success'})
 response.delete_cookie(COOKIE,path='/');response.delete_cookie('operation_session',path='/')
 return response


@app.get('/api/access/check')
def check(request:Request):
 actor=identity(request)
 if actor['owner']: return Response(status_code=204)
 uri=unquote(urlsplit(request.headers.get('x-original-uri','')).path)
 public_assets={'/operation-workbench/account-session.js','/operation-workbench/account-permissions/member.html','/operation-workbench/account-permissions/member.js','/operation-workbench/account-permissions/styles.css'}
 if uri in public_assets or uri.startswith('/api/access/'): return Response(status_code=204)
 if uri.startswith('/operation-workbench/account-permissions/'):
  manage(actor)
  allowed={'index.html','app.js','model.js','styles.css',''}
  if uri.removeprefix('/operation-workbench/account-permissions/') in allowed: return Response(status_code=204)
 # Deny raw full data, legacy APIs, agent/AI entry points and embedded reports.
 raise HTTPException(403,'该入口不在授权范围，请从个人工作台访问')


@app.get('/api/access/me')
def me(request:Request):
 actor=identity(request)
 return {**actor,'stores':[s for s in catalog() if s['id'] in actor['stores']]}


@app.get('/api/access/accounts')
def accounts(request:Request):
 actor=identity(request);manage(actor)
 with db() as con: rows=con.execute('SELECT * FROM accounts ORDER BY updated_at DESC').fetchall()
 return {'accounts':[clean_account(r) for r in rows],'can_edit':actor['owner'] or 'edit' in actor['permissions'].get('accounts',[]),'stores':catalog(),'owner':{'username':os.environ.get('OPERATION_AUTH_USERNAME','summer'),'name':'原管理账号（保留）'}}


def validate(payload):
 username=str(payload.get('username','')).strip().lower(); name=str(payload.get('name','')).strip()
 if not re.fullmatch(r'[a-z0-9][a-z0-9._@+\-]{2,63}',username) or username==os.environ.get('OPERATION_AUTH_USERNAME','summer').lower(): raise HTTPException(400,'账号格式无效或为保留管理账号')
 if not name or len(name)>40: raise HTTPException(400,'请填写姓名，最多 40 个字')
 role=payload.get('role'); enabled=payload.get('enabled')
 if role not in ROLES or type(enabled) is not bool: raise HTTPException(400,'角色或状态无效')
 stores=payload.get('stores',[]);permissions=payload.get('permissions',{})
 if not isinstance(stores,list) or any(s not in {x['id'] for x in catalog()} for s in stores): raise HTTPException(400,'门店无效')
 if not isinstance(permissions,dict) or any(k not in MODULES for k in permissions): raise HTTPException(400,'权限无效')
 clean={}
 for module,allowed in MODULES.items():
  actions=permissions.get(module,[])
  if not isinstance(actions,list) or any(a not in allowed for a in actions): raise HTTPException(400,'操作权限无效')
  if actions and 'view' not in actions: raise HTTPException(400,'需先授予查看权限')
  clean[module]=list(dict.fromkeys(actions))
 stores=list(dict.fromkeys(stores))
 if enabled and (not stores or not any(clean.values())): raise HTTPException(400,'启用账号需要可见门店和功能')
 if clean['accounts'] and (role!='admin' or set(stores)!={s['id'] for s in catalog()}): raise HTTPException(400,'账号管理属于全局权限，仅可授予拥有全部门店的总管理员')
 return {'username':username,'name':name,'role':role,'enabled':enabled,'stores':stores,'permissions':clean,'note':str(payload.get('note',''))[:300]}


@app.post('/api/access/accounts')
def save_account(request:Request,payload:dict):
 actor=identity(request);manage(actor,'edit');clean=validate(payload)
 account_id=str(payload.get('id') or secrets.token_hex(12)); initial_password=None
 with db() as con:
  existing=con.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
  if payload.get('id') and not existing: raise HTTPException(404,'账号不存在')
  if existing and payload.get('revision')!=existing['revision']: raise HTTPException(409,'账号已被其他人修改，请刷新后重试')
  if account_id==actor['id'] and (not clean['enabled'] or clean['permissions'].get('accounts')!=actor['permissions'].get('accounts') or clean['stores']!=actor['stores']): raise HTTPException(400,'不能在此撤销自己的管理权限，请由另一管理员操作')
  if not existing: initial_password=secrets.token_urlsafe(16)
  values=(clean['username'],clean['name'],clean['role'],int(clean['enabled']),json.dumps(clean['stores']),json.dumps(clean['permissions']),clean['note'])
  try:
   if existing: con.execute('UPDATE accounts SET username=?,name=?,role=?,enabled=?,stores=?,permissions=?,note=?,revision=revision+1,updated_at=? WHERE id=?',(*values,int(time.time()),account_id))
   else: con.execute('INSERT INTO accounts(id,username,name,role,enabled,stores,permissions,note,password_hash,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(account_id,*values,password_hash(initial_password),int(time.time())))
  except sqlite3.IntegrityError: raise HTTPException(409,'账号已存在')
  # Revoke sessions on all account changes, including access reductions.
  con.execute('DELETE FROM sessions WHERE account_id=?',(account_id,))
  audit(con,actor['username'],'update_account' if existing else 'create_account',account_id,clean)
  saved=clean_account(con.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone())
 return {'account':saved,'initial_password':initial_password}


@app.post('/api/access/accounts/{account_id}/reset-password')
def reset_password(account_id:str,request:Request,payload:dict):
 actor=identity(request);manage(actor,'edit'); password=secrets.token_urlsafe(16)
 with db() as con:
  if not con.execute('UPDATE accounts SET password_hash=?,revision=revision+1,updated_at=? WHERE id=?',(password_hash(password),int(time.time()),account_id)).rowcount: raise HTTPException(404,'账号不存在')
  con.execute('DELETE FROM sessions WHERE account_id=?',(account_id,)); audit(con,actor['username'],'reset_password',account_id)
 return {'initial_password':password}


@app.get('/api/access/audit')
def audit_list(request:Request):
 actor=identity(request);manage(actor)
 with db() as con: return {'items':[dict(r) for r in con.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]}


def source_root(): return Path(os.environ.get('ACCESS_DATA_ROOT','/var/www/html/operation-workbench'))


def read_json(relative):
 try:
  data=json.loads((source_root()/relative).read_text())
  return data if isinstance(data,dict) else {}
 except (OSError,ValueError): return {}


def workbook():
 try:
  text=(source_root()/'workbench-data.js').read_text()
  return json.loads(text[text.index('{'):].strip().removesuffix(';'))
 except (OSError,ValueError): return {}


def store_id(name):
 # Exact canonical names/explicit suffix aliases only. Never use substring matching.
 name=str(name or '').strip()
 for s in catalog():
  aliases={s['name'],s['name'].removesuffix('门店').removesuffix('店')}
  if not s['name'].endswith('店'): aliases|={s['name']+'店',s['name']+'门店'}
  if name in aliases:return s['id']
 return None


# Only these scalar business fields may cross the account boundary. No raw text,
# source URLs, platform account IDs, file names, tokens or cross-store narratives.
FIELDS={'date','platform','orders','income','total_orders','total_income','total_impressions','impressions','visit_conversion','order_conversion','customer_paid','total_customer_paid','balance','status','targetBudget','period','time','suggested_bid','current_bid','rating','avg_rating','review_count','negative_count','total_reviews','total_negative','sku','name','quantity','stock','unit','available_qty','warning_threshold','product_name','stock_quantity','current_stock','order_id','created_at','submitted_at','total_quantity','amount','product','outbound_quantity'}


def scoped_rows(items,actor):
 output=[]
 for item in items if isinstance(items,list) else []:
  if not isinstance(item,dict):continue
  sid=store_id(item.get('store') or item.get('store_name'))
  if sid not in actor['stores']:continue
  result={k:v for k,v in item.items() if k in FIELDS and isinstance(v,(str,int,float,bool,type(None)))}
  result['store_id']=sid;result['store']=next(s['name'] for s in catalog() if s['id']==sid)
  output.append(result)
 return output


def data_for(actor,module):
 require(actor,module)
 data=workbook(); generated_at=''; rows=[]
 if module in {'daily','direct-daily','reviews','direct-reviews'}:
  source=read_json('business-report-dashboard/data/'+('direct-latest.json' if module.startswith('direct-') else 'latest.json'))
  generated_at=source.get('generated_at','')
  if module.endswith('reviews'):
   stores=(source.get('review_summary') or {}).get('stores',{})
   items=[{'store':k,**v} for k,v in stores.items() if isinstance(v,dict)] if isinstance(stores,dict) else stores
   rows=scoped_rows(items,actor)
  else: rows=scoped_rows(source.get('store_summary',[]),actor)
 elif module=='overview':
  source=read_json('outputs/realtime_order_income/latest.json') or data.get('realtime',{})
  generated_at=source.get('generated_at','');rows=scoped_rows(source.get('stores',[]),actor)
 elif module=='balances':
  source=read_json('store-inspection/latest.json') or data.get('balances',{})
  generated_at=source.get('generated_at','');rows=scoped_rows(source.get('items',[]),actor)
 elif module=='budget':
  source=read_json('outputs/promo_budget_preview/latest.json') or data.get('budget',{})
  generated_at=source.get('generated_at','');rows=scoped_rows(sum([source.get(k,[]) for k in ['eleme_lunch','eleme_dinner','meituan_lunch','meituan_dinner']],[]),actor)
 elif module=='bidding':
  source=data.get('promo_bid_advice',{});generated_at=source.get('generated_at','');rows=scoped_rows(source.get('items',[]),actor)
 elif module=='inventory':
  try:
   secret=os.environ.get('INVENTORY_PASSWORD','')
   auth=base64.b64encode((os.environ.get('OPERATION_AUTH_USERNAME','summer')+':'+secret).encode()).decode()
   req=URLRequest(os.environ.get('ACCESS_LEGACY_URL','http://127.0.0.1:8000')+'/api/store-deliveries',headers={'Authorization':'Basic '+auth})
   with urlopen(req,timeout=5) as response: inventory=json.load(response)
   items=[]
   for store in inventory.get('items',[]):
    for line in store.get('items',[]):
     items.append({**line,'store':store.get('store_name'),'date':inventory.get('selected_month','')})
   rows=scoped_rows(items,actor)
  except (HTTPError,URLError,TimeoutError,ValueError): raise HTTPException(503,'门店货流数据暂时不可用，请稍后重试')
 elif module=='ordering':
  token=os.environ.get('DAILY_ORDER_ADMIN_TOKEN','daily-order-admin')
  req=URLRequest(os.environ.get('ACCESS_ORDER_URL','http://127.0.0.1:8010')+'/daily-order/api/admin/summary?status=all&token='+quote(token,safe=''))
  try:
   with urlopen(req,timeout=5) as response: orders=json.load(response)
   rows=scoped_rows(orders.get('orders',[]),actor)
  except (HTTPError,URLError,TimeoutError,ValueError): raise HTTPException(503,'订货数据暂时不可用，请稍后重试')
 generated_at=str(generated_at or data.get('generated_at',''))
 # Recompute every aggregate from scoped rows; source-wide totals never leave.
 total_orders=sum(float(r.get('total_orders',r.get('orders',0)) or 0) for r in rows)
 total_income=sum(float(r.get('total_income',r.get('income',0)) or 0) for r in rows)
 return {'module':module,'generated_at':generated_at,'rows':rows,'summary':{'row_count':len(rows),'orders':total_orders,'income':round(total_income,2)},'stores':[s for s in catalog() if s['id'] in actor['stores']]}


@app.get('/api/access/data/{module}')
def data_route(module:str,request:Request,export:bool=False):
 actor=identity(request);require(actor,module,'export' if export else 'view');data=data_for(actor,module)
 if not export:return data
 output=io.StringIO();keys=sorted(set().union(*(r.keys() for r in data['rows']))) if data['rows'] else ['store']
 writer=csv.DictWriter(output,fieldnames=keys);writer.writeheader()
 for row in data['rows']:
  writer.writerow({k: "'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for k,v in row.items()})
 with db() as con:audit(con,actor['username'],'export',module,{'stores':actor['stores'],'rows':len(data['rows'])})
 return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{module}.csv"'})


@app.get('/api/access/requests')
def request_list(request:Request):
 actor=identity(request)
 with db() as con:rows=con.execute('SELECT * FROM requests ORDER BY created_at DESC LIMIT 1000').fetchall()
 return {'items':[dict(r) for r in rows if r['store_id'] in actor['stores'] and 'view' in actor['permissions'].get(r['module'],[]) and (r['account_id']==actor['id'] or 'approve' in actor['permissions'].get(r['module'],[]))]}


@app.post('/api/access/requests')
def create_request(request:Request,payload:dict):
 actor=identity(request);module=str(payload.get('module',''));sid=str(payload.get('store_id',''))
 require(actor,module,'edit',sid)
 body=str(payload.get('body','')).strip()
 if not body or len(body)>2000:raise HTTPException(400,'请填写变更内容，最多 2000 字')
 request_id=secrets.token_hex(12)
 with db() as con:
  con.execute('INSERT INTO requests(id,account_id,module,store_id,body,status,created_at) VALUES(?,?,?,?,?,?,?)',(request_id,actor['id'],module,sid,body,'pending',int(time.time())))
  audit(con,actor['username'],'create_request',request_id,{'module':module,'store_id':sid})
 return {'id':request_id,'status':'pending','execution':'not_executed'}


@app.post('/api/access/requests/{request_id}/review')
def review_request(request_id:str,request:Request,payload:dict):
 actor=identity(request);decision=payload.get('decision')
 if decision not in ('approved','rejected'):raise HTTPException(400,'审批结果无效')
 with db() as con:
  row=con.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
  if not row:raise HTTPException(404,'申请不存在')
  require(actor,row['module'],'approve',row['store_id'])
  if row['account_id']==actor['id']:raise HTTPException(403,'不能审批自己的申请')
  if row['status']!='pending':raise HTTPException(409,'此申请已处理')
  con.execute('UPDATE requests SET status=?,reviewer=?,reviewed_at=? WHERE id=?',(decision,actor['username'],int(time.time()),request_id));audit(con,actor['username'],'review_request',request_id,{'decision':decision})
 return {'status':decision,'execution':'not_executed'}


@app.post('/api/access/ask')
def ask(request:Request,payload:dict):
 actor=identity(request);module=str(payload.get('module','overview'));data=data_for(actor,module)
 # Deliberately no calls to the unscoped production agent. Answers depend only
 # on already filtered data, preventing prompt-based expansion of access.
 return {'answer':f"你有权查看的本模块共有 {len(data['rows'])} 条记录，总单量 {data['summary']['orders']:g}，总营业额 {data['summary']['income']:.2f} 元。数据时间：{data['generated_at'] or '暂无'}。未授权门店未参与汇总。",'summary':data['summary']}


@app.get('/api/access/tools/{module}/{asset:path}')
def tool_asset(module:str,asset:str,request:Request):
 actor=identity(request)
 for action in ('view','edit','export'): require(actor,module,action)
 folders={'floor-plan':'floor-plan-designer','sales-receipts':'sales-receipt-generator','franchise-contract':'franchise-contract-generator'}
 if module not in folders:raise HTTPException(404,'工具不存在')
 root=(source_root()/folders[module]).resolve(); path=(root/asset).resolve()
 if not path.is_relative_to(root) or not path.is_file() or path.suffix not in {'.html','.js','.css','.png','.svg','.txt','.csv'}:raise HTTPException(404,'文件不存在')
 return FileResponse(path)


# Read only generated archive sections. Never return the full document, global
# counts, store selectors or arbitrary files to a scoped account.
def message_sections(actor, date=''):
 require(actor,'direct-messages')
 if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): raise HTTPException(400,'日期格式无效')
 root=source_root()/'business-report-dashboard/direct-dashboard/customer-messages'
 path=root/(date+'.html' if date else 'index.html')
 try: text=path.read_text(encoding='utf-8')
 except OSError: raise HTTPException(404,'暂无消息复盘归档')
 sections=[]
 for match in re.finditer(r'<section class="scope" data-store="([^"]*)"[^>]*>.*?</section>',text,re.S):
  if store_id(html.unescape(match.group(1))) in actor['stores']: sections.append(match.group(0))
 return root, ''.join(sections)


def message_files(sections):
 return {html.unescape(x) for x in re.findall(r'(?:src|href)="(attachments/[^"<>]+)"',sections)}


@app.get('/api/access/messages/page')
def messages_page(request:Request,date:str=''):
 actor=identity(request);root,sections=message_sections(actor,date)
 for file in message_files(sections):
  url='/api/access/messages/media?file='+quote(file,safe='')+'&date='+quote(date)
  sections=sections.replace('"'+html.escape(file,quote=True)+'"','"'+html.escape(url,quote=True)+'"')
 dates=sorted((p.stem for p in root.glob('????-??-??.html') if re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.stem)),reverse=True)
 links=' '.join('<a href="?date='+d+'">'+d+'</a>' for d in dates)
 content='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:15px/1.7 sans-serif;padding:16px;color:#1e293b}section,article{padding:16px;border:1px solid #ddd;margin:12px 0}img,video{max-width:100%;max-height:360px}small,.basis{color:#64748b}.msg{background:#f1f5f9;margin:8px 0;padding:12px}pre{white-space:pre-wrap}a{margin-right:12px}</style><h1>直营门店消息复盘</h1><p>仅展示已授权门店 · '+html.escape(date or '最新归档')+'</p><nav><a href="?">最新</a>'+links+'</nav>'+(sections or '<p>当前授权范围暂无消息记录；不代表当天没有消息。</p>')+'</html>'
 return Response(content,media_type='text/html',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"})


@app.get('/api/access/messages/media')
def messages_media(request:Request,file:str,date:str=''):
 root,sections=message_sections(identity(request),date)
 if file not in message_files(sections): raise HTTPException(403,'附件不在授权范围')
 path=(root/file).resolve()
 if not path.is_relative_to((root/'attachments').resolve()) or not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif','.mp4','.mp3','.m4a','.ogg','.wav'}: raise HTTPException(404,'附件不存在')
 return FileResponse(path,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
