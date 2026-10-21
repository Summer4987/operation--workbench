import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export function memoryCommand(text){
 const s=text.trim();
 if(/^(查看|列出|我的|长期)记忆$|^查看长期记忆$|^记忆列表$/.test(s))return {action:'list'};
 if(/^(长期记忆帮助|记忆帮助)$/.test(s))return {action:'help'};
 if(s==='确认清空长期记忆')return {action:'clear'};
 if(s==='清空长期记忆')return {action:'confirm_clear'};
 let m=s.match(/^(?:请)?记住[：:\s]*([\s\S]+)$/);if(m)return {action:'add',text:m[1].trim()};
 m=s.match(/^修改记忆\s+([a-f0-9]{8})[：:\s]+([\s\S]+)$/i);if(m)return {action:'edit',id:m[1].toLowerCase(),text:m[2].trim()};
 m=s.match(/^删除记忆\s+([a-f0-9]{8})$/i);if(m)return {action:'delete',id:m[1].toLowerCase()};
 m=s.match(/^搜索记忆[：:\s]+([\s\S]+)$/);if(m)return {action:'find',text:m[1].trim()};
 return null;
}
const HELP='长期记忆用法：\n记住：我希望回复简短，先给结论\n查看记忆\n搜索记忆 关键词\n修改记忆 ID 新内容\n删除记忆 ID\n清空长期记忆\n只保存你明确要求记住的内容，不自动永久保存全部聊天。';
const sensitive=s=>/密码|密钥|secret|api[_ -]?key|access[_ -]?token|私钥|身份证|银行卡|BEGIN.*PRIVATE KEY/i.test(s);
function tokens(s){const v=s.normalize('NFKC').toLowerCase();return new Set([...(v.match(/[a-z0-9_]{2,}/g)||[]),...[...(v.match(/[\p{Script=Han}]+/gu)||[])].flatMap(w=>w.length<2?[w]:Array.from({length:w.length-1},(_,i)=>w.slice(i,i+2)))]);}
export class MemoryStore{
 constructor(root){this.root=root;this.file=path.join(root,'memory','facts.json');}
 read(){
  if(!fs.existsSync(this.file))return [];
  let data;try{data=JSON.parse(fs.readFileSync(this.file,'utf8'));}catch{throw Error('长期记忆文件损坏，请先检查，未覆盖原文件');}
  if(!Array.isArray(data)||data.some(x=>!x||!/^[a-f0-9]{8}$/.test(x.id)||typeof x.text!=='string'||typeof x.updated_at!=='string'))throw Error('长期记忆文件损坏，请先检查，未覆盖原文件');
  return data;
 }
 write(data){fs.mkdirSync(path.dirname(this.file),{recursive:true,mode:0o700});const tmp=this.file+'.'+crypto.randomUUID()+'.tmp';fs.writeFileSync(tmp,JSON.stringify(data),{mode:0o600});fs.renameSync(tmp,this.file);}
 clearContext(){
  const dir=path.join(this.root,'sessions');
  if(fs.existsSync(dir))for(const f of fs.readdirSync(dir))if(/\.json$/.test(f))fs.rmSync(path.join(dir,f));
 }
 handle(cmd){
  if(cmd.action==='help')return HELP;
  if(cmd.action==='confirm_clear')return '如需删除所有长期记忆，请发送“确认清空长期记忆”。';
  const data=this.read();
  if(cmd.action==='clear'){this.write([]);this.clearContext();return '长期记忆已清空，同时清除近期对话上下文。上传原文件和已生成表格仍保留。';}
  if(cmd.action==='list'||cmd.action==='find'){
   const rows=cmd.action==='find'?data.filter(x=>x.text.includes(cmd.text)):data;
   return rows.length?'长期记忆（'+rows.length+'条）：\n'+rows.slice(0,30).map(x=>`${x.id}｜${x.text}`).join('\n')+(rows.length>30?'\n仅显示前30条，请用“搜索记忆 关键词”缩小范围。':''):'暂无匹配的长期记忆。';
  }
  if(cmd.action==='add'||cmd.action==='edit'){
   if(!cmd.text||cmd.text.length>1000)return '每条记忆请写1至1000字，可分条保存。';
   if(sensitive(cmd.text))return '密码、密钥、证件号和银行卡信息不存入助手记忆。请使用密码管理器保存。';
  }
  if(cmd.action==='add'){
   const old=data.find(x=>x.text===cmd.text);if(old)return `这条已经记住了：${old.id}｜${old.text}`;
   if(data.length>=500)return '长期记忆已达500条，请先整理或删除不再需要的内容。';
   const entry={id:crypto.randomBytes(4).toString('hex'),text:cmd.text,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),source:'explicit_owner_command'};
   this.write([...data,entry]);return `已长期记住：${entry.id}｜${entry.text}\n以后相关问题会参考这条；可用“修改记忆 ${entry.id} 新内容”或“删除记忆 ${entry.id}”管理。`;
  }
  const index=data.findIndex(x=>x.id===cmd.id);if(index<0)return '找不到这个记忆ID，请先发“查看记忆”。';
  if(cmd.action==='delete')data.splice(index,1);
  else if(cmd.action==='edit')data[index]={...data[index],text:cmd.text,updated_at:new Date().toISOString()};
  this.write(data);this.clearContext();return cmd.action==='delete'?'该条长期记忆已删除，同时清除近期对话上下文，避免继续引用旧内容。':`记忆已修改：${cmd.id}｜${cmd.text}\n近期对话上下文已清除，避免继续引用旧内容。`;
 }
 relevant(query){
  const words=tokens(query);
  return this.read().map(x=>({...x,score:[...tokens(x.text)].filter(w=>words.has(w)).length+(/称呼|我叫|我的名字|回复|偏好|习惯|语言/.test(x.text)?2:0)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||b.updated_at.localeCompare(a.updated_at)).slice(0,6).map(({id,text})=>({id,text}));
 }
}
