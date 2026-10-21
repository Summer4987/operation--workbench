import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {MemoryStore,memoryCommand} from './memory.mjs';
import {searchCommand,searchPrivacy} from './search.mjs';
import {Assistant} from './core.mjs';
function temp(t){const p=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-personal-'));t.after(()=>fs.rmSync(p,{recursive:true,force:true}));return p;}
const config={WECOM_MEMORY_ENABLED:'1',WECOM_MEMORY_MODEL_CONSENT:'1',WECOM_SEARCH_ENABLED:'1'};
test('explicit memories persist across instances, deduplicate, update and truly remove old context',t=>{
 const root=temp(t),a=new MemoryStore(root);
 const added=a.handle(memoryCommand('记住：我喜欢简短答复，先给结论'));const id=added.match(/[a-f0-9]{8}/)[0];
 const b=new MemoryStore(root);assert.equal(b.read().length,1);assert.equal(fs.statSync(b.file).mode&0o777,0o600);
 b.handle(memoryCommand('记住：我喜欢简短答复，先给结论'));assert.equal(b.read().length,1);
 fs.mkdirSync(path.join(root,'sessions'));fs.writeFileSync(path.join(root,'sessions','a.json'),'old facts');
 b.handle(memoryCommand(`修改记忆 ${id} 我喜欢详细说明`));assert.equal(b.read()[0].text,'我喜欢详细说明');assert.equal(fs.readdirSync(path.join(root,'sessions')).length,0);
 b.handle(memoryCommand(`删除记忆 ${id}`));assert.deepEqual(new MemoryStore(root).read(),[]);
});
test('memory rejects credentials, fails closed on corruption, and clear requires exact confirmation',t=>{
 const a=new MemoryStore(temp(t));assert.match(a.handle(memoryCommand('记住：API_KEY=secretvalue')),/不存入/);assert.deepEqual(a.read(),[]);
 a.handle(memoryCommand('记住：常用表格为易代仓预约表'));assert.match(a.handle(memoryCommand('清空长期记忆')),/确认/);assert.equal(a.read().length,1);
 a.handle(memoryCommand('确认清空长期记忆'));assert.deepEqual(a.read(),[]);
 fs.writeFileSync(a.file,'broken');assert.throws(()=>a.handle(memoryCommand('记住：新内容')),/损坏/);assert.equal(fs.readFileSync(a.file,'utf8'),'broken');
});
test('only related facts enter model context with consent, ordinary chat never becomes long term memory',async t=>{
 const root=temp(t),calls=[];let a=new Assistant(config,root,{llm:async m=>{calls.push(m);return {content:'好的'};}});
 await a.answer('记住：我的称呼是测试老板','x');assert.equal(calls.length,0);
 await a.answer('你该怎么称呼我？','x');assert.match(JSON.stringify(calls[0]),/测试老板/);
 assert.equal(a.memories.read().length,1);
 a=new Assistant({...config,WECOM_MEMORY_MODEL_CONSENT:'0'},root,{llm:async m=>{assert(!JSON.stringify(m).includes('测试老板'));return {content:'好的'};}});
 await a.answer('你该怎么称呼我？','new');
});
test('public search sends only the explicit query, never memory/history, and returns real source links on model failure',async t=>{
 const root=temp(t),seen=[];
 const a=new Assistant(config,root,{search:async q=>{seen.push(q);return {query:q,results:[{title:'Python官方',url:'https://www.python.org/',snippet:'Programming language'}]};},llm:async()=>{throw Error('model offline');}});
 a.memories.handle(memoryCommand('记住：我住在私人地址甲街12号'));
 const result=await a.answer('联网搜索：Python official documentation','web');assert.deepEqual(seen,['Python official documentation']);assert.match(result.text,/https:\/\/www.python.org\//);assert.doesNotMatch(result.text,/甲街/);
 const blocked=await a.answer('联网搜索：我的客户手机号13812345678','web');assert.match(blocked.text,/尚未发送/);assert.equal(seen.length,1);
 assert.equal(searchCommand('帮我联网查一下 杭州天气'),'杭州天气');assert(!searchPrivacy('我的营业数据'));assert(!searchPrivacy('甲街12号',[{text:'我住在甲街12号'}]));
});
test('unapproved external search remains disabled',async t=>{
 const a=new Assistant({},temp(t),{search:()=>{throw Error('must not search');}});
 assert.match((await a.answer('联网搜索：公开资料','x')).text,/尚未启用/);
});
