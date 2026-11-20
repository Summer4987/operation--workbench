const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const titles={'direct-messages':'直营门店消息复盘','direct-daily':'直营店日报','direct-reviews':'直营店评价',overview:'加盟店实时数据',daily:'加盟店日报',reviews:'加盟店评价',budget:'推广预算',bidding:'推广出价',balances:'推广余额',ordering:'订货管理',inventory:'门店货流','floor-plan':'平面图设计','sales-receipts':'销售单生成器','franchise-contract':'加盟合同生成器',accounts:'账号与权限'};
const labels={store:'门店',store_id:'门店编号',date:'日期',platform:'平台',orders:'单量',income:'营业额',total_orders:'总单量',total_income:'总营业额',total_impressions:'曝光',balance:'余额',status:'状态',targetBudget:'目标预算',period:'时段',time:'时间',sku:'商品编码',name:'品名',quantity:'数量',unit:'单位',outbound_quantity:'出库数量',order_id:'订单编号',submitted_at:'提交时间',avg_rating:'平均评分'};
let actor,module;
async function api(path,payload){const r=await fetch('/api/access/'+path,payload===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await r.json();if(r.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname));throw new Error('需要重新登录')}if(!r.ok)throw new Error(data.detail||'请求失败');return data}
function fail(e){$('error').textContent=e.message;$('error').hidden=false}
async function load(){
 $('error').hidden=true;
 const requestedModule=module;
 try{
  const messages=requestedModule==='direct-messages';
  $('messagesFrame').hidden=!messages; $('dataPanel').hidden=messages;
  if(messages){$('moduleTitle').textContent=titles[requestedModule];$('messagesFrame').src='/api/access/messages/page';return;}
  $('messagesFrame').removeAttribute('src');
  const data=await api('data/'+encodeURIComponent(requestedModule));
  if(requestedModule!==module)return;
  $('moduleTitle').textContent=titles[module];
  $('updated').textContent='数据更新时间：'+(data.generated_at||'暂无');
  $('summary').textContent=`记录 ${data.summary.row_count} 条 · 单量 ${data.summary.orders} · 营业额 ¥${data.summary.income}`;
  const keys=[...new Set(data.rows.flatMap(r=>Object.keys(r)))].filter(k=>k!=='store_id');
  $('head').innerHTML='<tr>'+keys.map(k=>`<th>${esc(labels[k]||k)}</th>`).join('')+'</tr>';
  $('rows').innerHTML=data.rows.map(r=>'<tr>'+keys.map(k=>`<td>${esc(r[k])}</td>`).join('')+'</tr>').join('');
  $('empty').hidden=data.rows.length>0;
  const actions=actor.permissions[module]||[];
  $('export').hidden=!actions.includes('export');$('export').href='/api/access/data/'+encodeURIComponent(module)+'?export=true';
  $('requestForm').hidden=!actions.includes('edit');
  $('requestStore').innerHTML=actor.stores.map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  const isTool=['floor-plan','sales-receipts','franchise-contract'].includes(module);
  $('toolLink').hidden=!isTool||!['view','edit','export'].every(a=>actions.includes(a));
  $('toolLink').href='/api/access/tools/'+module+'/index.html';
  $('answer').textContent='';await requests();
 }catch(e){fail(e)}
}
async function requests(){const data=await api('requests');const items=data.items.filter(r=>r.module===module);$('requests').innerHTML=items.map(r=>`<article class="request-row"><strong>${esc(actor.stores.find(s=>s.id===r.store_id)?.name||'')} · ${esc({pending:'待审批',approved:'已批准，待正式执行',rejected:'已拒绝'}[r.status])}</strong><p>${esc(r.body)}</p>${r.status==='pending'&&r.account_id!==actor.id&&actor.permissions[module]?.includes('approve')?`<div class="buttons"><button data-review="${esc(r.id)}" data-decision="approved">批准申请</button><button data-review="${esc(r.id)}" data-decision="rejected">拒绝申请</button></div>`:''}</article>`).join('')||'<p class="muted">当前没有你有权查看的申请。</p>'}
$('refresh').addEventListener('click',load);
$('logout').addEventListener('click',async()=>{try{await api('logout',{});location.assign('/login')}catch(e){fail(e)}});
$('requestForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{await api('requests',{module,store_id:$('requestStore').value,body:$('requestBody').value});$('requestBody').value='';await requests()}catch(e){fail(e)}finally{button.disabled=false}});
$('requests').addEventListener('click',async e=>{const b=e.target.closest('[data-review]');if(!b)return;b.disabled=true;try{await api('requests/'+b.dataset.review+'/review',{decision:b.dataset.decision});await requests()}catch(e){fail(e);b.disabled=false}});
$('ask').addEventListener('click',async()=>{try{$('answer').textContent=(await api('ask',{module,question:$('question').value})).answer}catch(e){fail(e)}});
try{
 actor=await api('me');$('me').textContent=actor.name+' · '+actor.username;
 $('scope').textContent='可见门店：'+actor.stores.map(s=>s.name).join('、');
 const allowed=Object.keys(titles).filter(m=>m!=='accounts'&&actor.permissions[m]?.includes('view'));
 $('moduleNav').innerHTML=allowed.map(m=>`<a class="module-link" href="#${m}" data-module="${m}">${titles[m]}</a>`).join('');
 $('adminLink').hidden=!(actor.owner||(actor.role==='admin'&&actor.permissions.accounts?.includes('view')));
 function route(){module=allowed.includes(location.hash.slice(1))?location.hash.slice(1):allowed[0];document.querySelectorAll('[data-module]').forEach(a=>a.classList.toggle('active',a.dataset.module===module));if(module)load();else{$('moduleTitle').textContent='暂无已授权业务功能';$('empty').hidden=false}}
 window.addEventListener('hashchange',route);route();
}catch(e){fail(e)}
