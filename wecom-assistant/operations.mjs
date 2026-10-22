import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';

const NAMES={'ops.morning_collection':'上午运营','ops.realtime_order_income':'实时单量收入','growth.promo_budget':'推广预算','ops.inventory_warning_daily':'库存预警'};
const MAIN=Object.keys(NAMES);
const LABELS={success:'正常',failed:'失败',warning:'注意',missing:'未记录',running:'运行中',skipped:'跳过'};
const day=now=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
function read(file){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return null;}}
function safe(value){return String(value||'').replace(/https?:\/\/\S+/g,'[链接略]').replace(/\/(?:Users|private|tmp|var)\/[^\s，；。]+/g,'[本机日志]').replace(/(?:token|secret|password|api_key|authorization)\s*[=:]\s*\S+/gi,'[凭据略]').slice(0,1400);}
function bounded(text,maxBytes=3800){let out='';for(const c of text){if(Buffer.byteLength(out+c)>maxBytes-3)return out+'…';out+=c;}return out;}
export function isOperationsRequest(text){return /运营|自动化|采集|推广预算|任务/.test(text)&&/失败|异常|故障|状态|健康|恢复|正常|完成|检查|运行|成功/.test(text);}
export function requestDate(text,now=new Date()){
 const explicit=text.match(/\d{4}-\d{2}-\d{2}/)?.[0];
 if(explicit)return explicit;
 return day(new Date(now.getTime()-(/前天/.test(text)?2:/昨天|昨日/.test(text)?1:0)*86400000));
}
export function loadOperations(config={},target=day(new Date())){
 let roots;
 try{roots=JSON.parse(config.WECOM_DATA_ROOTS||'[]');}catch{roots=[];}
 // The assistant reads production artifacts only; never fall back to Documents copies.
 if(!roots.length)roots=[path.join(os.homedir(),'Library/Application Support/xiong-operation/production')];
 const sources=roots.map(root=>({root,data:read(path.join(root,'outputs/task_runs/latest.json'))})).filter(x=>x.data);
 sources.sort((a,b)=>String(b.data.generated_at||b.data.updated_at||'').localeCompare(String(a.data.generated_at||a.data.updated_at||'')));
 if(!sources.length)return {date:target,error:'未能读取正式运营任务记录，不能判断是否正常。',tasks:[],missing:MAIN};
 const {root,data}=sources[0];const tasks=new Map();
 for(const e of data.events||[]){
  const time=e.created_at||e.updated_at||'';
  if(time.startsWith(target)&&e.task_id)tasks.set(e.task_id,{...e,updated_at:time});
 }
 for(const [id,t] of Object.entries(data.tasks||{})){
  if(String(t.updated_at||'').startsWith(target))tasks.set(id,{...t,task_id:id});
 }
 const morning=read(path.join(root,'outputs/morning_collection_status/latest.json'));
 const rows=[...tasks.values()].map(t=>{
  const id=t.task_id;let details=[];const time=t.updated_at||'';
  if(id==='ops.morning_collection'&&morning&&String(morning.updated_at||morning.generated_at||'').startsWith(target)&&String(morning.updated_at||morning.generated_at)>=time){
   if(morning.status) t={...t,status:morning.status,message:morning.task_message||t.message};
   details=(morning.failed_steps||[]).filter(s=>!['汇总','launchd 包装器'].includes(s.name)).map(s=>`${s.name}：${s.message||s.failure_type||''}`);
  }
  if(t.status==='failed'&&t.extra?.failure_details){
   try{for(const f of JSON.parse(t.extra.failure_details))details.push(`${f.name||f.step}：${f.output_tail||f.message||''}`);}catch{}
  }
  return {id,name:NAMES[id]||safe(id),status:t.status,updated_at:time,step:safe(t.step),message:safe(t.message),details:[...new Set(details.map(safe))]};
 });
 return {date:target,tasks:rows,missing:MAIN.filter(id=>!tasks.has(id)),generated_at:safe(data.generated_at||data.updated_at||'')};
}
export function operationsReply(report,text=''){
 if(report.error)return report.error;
 const issues=report.tasks.filter(t=>['failed','warning','missing'].includes(t.status));
 const rows=/失败|异常|故障/.test(text)?issues:report.tasks;
 const lines=[`运营任务状态（${report.date}，北京时间；读取已有运行记录）`];
 if(!issues.length)lines.push('当日已记录任务中，当前没有失败或异常项。');
 for(const t of rows){lines.push(`• ${t.name}：${LABELS[t.status]||t.status}（${t.updated_at}）`,t.message,...t.details);}
 if(report.missing.length)lines.push('当日尚无记录：'+report.missing.map(id=>NAMES[id]).join('、')+'；不代表任务成功，也可能尚未到运行时间。');
 lines.push('这是最近记录；门店/平台以失败详情为准。预算、出价等不会自动重跑。');
 return lines.join('\n').slice(0,7000);
}
function fingerprint(t){return crypto.createHash('sha256').update(JSON.stringify([t.status,t.step,t.message,t.details])).digest('hex');}
export class OperationsNotifier{
 constructor({stateFile,readReport,send,save,now=()=>new Date()}){Object.assign(this,{stateFile,readReport,send,save,now});this.busy=false;this.state=read(stateFile)||{tasks:{}};this.state.tasks||={};this.lastError='';}
 async tick(){
  if(this.busy)return {busy:true};this.busy=true;
  try{
   const report=this.readReport(day(this.now()));if(report.error)throw Error('运营状态读取失败');
   let sent=0;
   for(const t of report.tasks){
    const previous=this.state.tasks[t.id];const failed=['failed','warning','missing'].includes(t.status);
    const recovered=t.status==='success'&&previous?.active;
    if(!failed&&!recovered)continue;
    const key=fingerprint(t);
    if(failed&&previous?.active&&previous.key===key)continue;
    const title=recovered?'【运营恢复】':'【运营异常】';
    await this.send(bounded([title,`${t.name} · ${t.updated_at}`,t.message,...t.details,'可回复“今天运营哪里失败了”查看当前状态。'].join('\n')));
    this.state.tasks[t.id]={key,active:failed,sent_at:this.now().toISOString()};
    this.save(this.stateFile,this.state);sent++;
   }
   this.lastError='';return {sent};
  }catch{this.lastError='运营提醒读取或发送失败，将在下次检查重试';return {error:this.lastError};}
  finally{this.busy=false;}
 }
}
