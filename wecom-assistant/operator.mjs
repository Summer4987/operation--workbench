import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRIVATE,loadJson,saveJson,today,Assistant} from './core.mjs';
import {isRealtimeRequest} from './realtime.mjs';

export function operatorToken(root=PRIVATE){
  const file=path.join(root,'operator-token');
  if(!fs.existsSync(file))fs.writeFileSync(file,crypto.randomBytes(32).toString('hex'),{mode:0o600});
  return fs.readFileSync(file,'utf8').trim();
}
export function checkOperator(header,token){
  const actual=Buffer.from(header||''),expected=Buffer.from('Bearer '+token);
  return actual.length===expected.length&&crypto.timingSafeEqual(actual,expected);
}
export async function operatorInbound(payload,{assistant,client,owner,root=PRIVATE}){
  if(!owner)throw Error('尚未绑定账号');
  const text=String(payload.text||'');
  if(text.length>8000||!/入库/.test(text))throw Error('只接受明确的入库请求原文');
  const key=crypto.createHash('sha256').update(owner+'\n'+today()+'\n'+text).digest('hex');
  const receiptFile=path.join(root,'recovery',key+'.json');
  if(payload.send&&loadJson(receiptFile,{}).file_sent)return {ok:true,already_delivered:true};
  const start=Date.now();
  const result=await assistant.answer(text,'operator-'+key);
  if(result.artifacts.length!==1)throw Error('没有生成唯一预约表：'+result.text.slice(0,200));
  const file=result.artifacts[0];
  if(!file.startsWith(path.join(root,'outbox')+'/'))throw Error('产物路径不在工作目录');
  if(!payload.send)return {ok:true,generated:true,process_id:process.pid,elapsed_ms:Date.now()-start,filename:path.basename(file)};
  const media=await client.uploadMedia(fs.readFileSync(file),{type:'file',filename:path.basename(file)});
  await client.sendMessage(owner,{msgtype:'file',file:{media_id:media.media_id}});
  const receipt={created_at:new Date().toISOString(),filename:path.basename(file),file_sent:true,notice_sent:false};
  saveJson(receiptFile,receipt);
  try{await client.sendMessage(owner,{msgtype:'markdown',markdown:{content:'刚才失败的预约表已补发。\n'+result.text}});receipt.notice_sent=true;saveJson(receiptFile,receipt);}catch{}
  return {ok:true,file_delivered:true,notice_delivered:receipt.notice_sent,process_id:process.pid,elapsed_ms:Date.now()-start};
}

export async function operatorRealtime(payload,{assistant}){
  const text=String(payload.text||'');
  if(text.length>8000||!isRealtimeRequest(text))throw Error('只接受实时经营查询原文');
  const start=Date.now();
  const result=await assistant.answer(text,'operator-realtime');
  return {ok:true,process_id:process.pid,elapsed_ms:Date.now()-start,text:result.text,filenames:result.artifacts.map(f=>path.basename(f))};
}

export async function operatorAsk(payload,{assistant,owner}){
  if(!owner)throw Error('尚未绑定账号');
  const text=String(payload.text||'');
  if(!text.trim()||text.length>8000)throw Error('请求长度须为1至8000字');
  const target=payload.verification===true?new Assistant(assistant.config,path.join(assistant.root,'verification','personal')):assistant;
  const start=Date.now();const result=await target.answer(text,'operator-personal');
  return {ok:true,process_id:process.pid,elapsed_ms:Date.now()-start,text:result.text,filenames:result.artifacts.map(f=>path.basename(f))};
}
