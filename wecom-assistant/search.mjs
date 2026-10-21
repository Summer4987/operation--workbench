import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export function searchCommand(text){
 const match=text.trim().match(/^(?:联网搜索|联网查|上网搜索|上网查一下|帮我联网查一下)[：:\s]*([\s\S]+)$/);
 return match?match[1].trim():null;
}
export function searchPrivacy(query,memories=[]){
 if(/密码|密钥|secret|token|api[_ -]?key|身份证|银行卡|客户|客户名单|供应商报价|内部|经营数据|我的|我们|我家|我店|完整聊天|聊天记录|手机号|联系方式/i.test(query)||/\b1[3-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(query))return false;
 // Prevent silently taking stored personal content as an internet query.
 return !memories.some(m=>m.text.length>=6&&(query.includes(m.text)||m.text.includes(query)));
}
export async function searchWeb(query,config,signal){
 signal?.throwIfAborted();
 return new Promise((resolve,reject)=>{
  const child=spawn(config.WECOM_PYTHON||'/usr/bin/python3',[path.join(path.dirname(fileURLToPath(import.meta.url)),'search_bridge.py')],{stdio:['pipe','pipe','ignore']});
  const abort=()=>{child.kill('SIGKILL');reject(signal.reason);};signal?.addEventListener('abort',abort,{once:true});
  const timeout=setTimeout(()=>{child.kill('SIGKILL');reject(Error('联网搜索超时，请稍后重试'));},16000);
  let out='';child.stdout.on('data',d=>{out+=d;if(out.length>100000)child.kill('SIGKILL');});
  child.stdin.on('error',()=>{});child.on('error',()=>{clearTimeout(timeout);signal?.removeEventListener('abort',abort);reject(Error('联网搜索进程不可用'));});
  child.on('close',code=>{clearTimeout(timeout);signal?.removeEventListener('abort',abort);try{const data=JSON.parse(out);if(code||data.error)reject(Error(data.error||'联网搜索失败'));else resolve(data);}catch{reject(Error('联网搜索失败，请稍后重试'));}});
  child.stdin.end(JSON.stringify({query}));
 });
}
export function searchLinks(data){return data.results.map((r,i)=>`${i+1}. ${r.title}\n${r.url}`).join('\n');}
