import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';

export const INSPECTION_URL='http://139.155.148.169/operation-workbench/customer-inspection/';
export async function operatorInspection(payload,{client,owner,reports=path.join(os.homedir(),'Documents/customer-inspection/published'),receipts=path.join(os.homedir(),'.local/share/xiong-wecom-assistant/inspection-notifications')}){
  if(!owner)throw Error('尚未绑定私聊账号');
  const date=String(payload.date||'');
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw Error('采集日期无效');
  const report=JSON.parse(fs.readFileSync(path.join(reports,date+'.json'),'utf8'));
  if(report.date!==date||report.publication_verified!==true||report.url!==INSPECTION_URL||!Array.isArray(report.records)||!report.records.length)throw Error('巡检结果尚未验证发布');
  const rows=report.records,done=rows.filter(r=>r.status==='visually_accepted'&&r.images?.length===2);
  const failed=rows.filter(r=>!done.includes(r));
  const cities=[...new Set(rows.map(r=>r.city))].join('、');
  const key=crypto.createHash('sha256').update(JSON.stringify({date,rows:rows.map(r=>[r.platform,r.store,r.status,(r.images||[]).map(i=>i.sha256)])})).digest('hex');
  fs.mkdirSync(receipts,{recursive:true,mode:0o700});const file=path.join(receipts,key+'.json');
  if(fs.existsSync(file))return {ok:true,already_delivered:true};
  const missing=failed.slice(0,10).map(r=>`${r.store}·${r.platform==='meituan'?'美团':'淘宝闪购'}`).join('、');
  const text=`【客户端巡检${failed.length?'部分完成':'已更新'}】\n${date} · ${cities}\n已复核 ${done.length}/${rows.length} 个店铺平台组合，共 ${done.length*2} 张原图。${failed.length?'\n缺失/待处理：'+missing+(failed.length>10?'等':''):''}\n[查看两图和门店状态](${INSPECTION_URL}?date=${date})\n仅代表该日期已纳入门店，历史结果不代表今天已采。`;
  await client.sendMessage(owner,{msgtype:'markdown',markdown:{content:text}});
  const temp=file+'.tmp';fs.writeFileSync(temp,JSON.stringify({sent_at:new Date().toISOString(),date,key}),{mode:0o600});fs.renameSync(temp,file);
  return {ok:true,delivered:true};
}
