// Operator recovery for a failed, explicitly requested reservation; destination is the paired owner only.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {Assistant,PRIVATE,settings,loadJson,saveJson,today} from './core.mjs';
const args=process.argv.slice(2),send=args.includes('--send');
const text=args.filter(a=>a!=='--send').join(' ').trim();
if(!text)throw Error('需要明确的入库请求原文');
const owner=loadJson(path.join(PRIVATE,'access.json'),{}).owner;
if(!owner)throw Error('机器人尚未绑定老板账号');
const key=crypto.createHash('sha256').update(owner+'\n'+today()+'\n'+text).digest('hex');
const receiptFile=path.join(PRIVATE,'recovery',key+'.json');
const previous=loadJson(receiptFile,{});
if(previous.file_sent){console.log(JSON.stringify({already_delivered:true}));process.exit(0);}
const running=await fetch('http://127.0.0.1:18769/health',{signal:AbortSignal.timeout(1000)}).then(r=>r.json()).catch(()=>null);
if(send&&running?.authenticated){
  const token=fs.readFileSync(path.join(PRIVATE,'operator-token'),'utf8').trim();
  const r=await fetch('http://127.0.0.1:18769/operator/inbound',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({text,send:true}),signal:AbortSignal.timeout(65000)});
  const result=await r.json();if(!r.ok||!result.ok)throw Error(result.error||'正式进程补发失败');
  console.log(JSON.stringify(result));process.exit(0);
}
const config=settings();
const result=await new Assistant(config).answer(text,'recovery-'+key);
if(result.artifacts.length!==1)throw Error('没有生成唯一入库附件，请核对原文');
const file=result.artifacts[0];
if(!send){console.log(JSON.stringify({generated:true,file}));process.exit(0);}
if(running?.authenticated)throw Error('请先停止常驻连接，避免重复连接互相挤掉');
const require=createRequire(import.meta.url),{WSClient}=require('@wecom/aibot-node-sdk');
const client=new WSClient({botId:config.WECOM_BOT_ID,secret:config.WECOM_BOT_SECRET,maxReconnectAttempts:0,
  logger:{debug(){},info(){},warn(){},error(){}}});
const timeout=setTimeout(()=>{client.disconnect();console.error('补发连接或发送超时');process.exit(1);},25000);
client.on('error',()=>{clearTimeout(timeout);client.disconnect();console.error('补发企微连接失败');process.exit(1);});
client.once('authenticated',async()=>{
  try{
    const media=await client.uploadMedia(fs.readFileSync(file),{type:'file',filename:path.basename(file)});
    await client.sendMessage(owner,{msgtype:'file',file:{media_id:media.media_id}});
    const receipt={created_at:new Date().toISOString(),filename:path.basename(file),file_sent:true,notice_sent:false};
    saveJson(receiptFile,receipt);
    try{
      await client.sendMessage(owner,{msgtype:'markdown',markdown:{content:'刚才超时的入库预约已补发，文件见上一条附件。\n'+result.text.replace('见附件。','')}});
      receipt.notice_sent=true;saveJson(receiptFile,receipt);
    }catch{/* File delivery is authoritative; a failed notice must not duplicate the file. */}
    console.log(JSON.stringify({file_delivered:true,notice_delivered:receipt.notice_sent}));
    clearTimeout(timeout);client.disconnect();process.exit(0);
  }catch{clearTimeout(timeout);client.disconnect();console.error('入库附件补发失败');process.exit(1);}
});client.connect();
