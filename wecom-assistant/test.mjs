import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import ExcelJS from 'exceljs';
import {Access,Assistant,workbook,readEnv,sessionKey,saveJson,loadJson} from './core.mjs';
function temp(t){const p=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-test-'));t.after(()=>fs.rmSync(p,{recursive:true,force:true}));return p;}
test('business data requires exact one-time pairing in a private chat',t=>{
 const access=new Access(temp(t));const body={chattype:'single',from:{userid:'owner'}};
 assert.equal(access.authorize(body),false);assert.equal(access.pair({...body,chattype:'group'},`绑定 ${access.data.token}`),false);
 assert.equal(access.pair(body,'绑定 wrong'),false);assert.equal(access.pair(body,`绑定 ${access.data.token}`),true);
 assert.equal(access.authorize(body),true);assert.equal(access.authorize({...body,from:{userid:'other'}}),false);
 assert.equal(access.authorize({...body,chattype:'group'}),false);assert.equal(access.pair({chattype:'single',from:{userid:'other'}},'绑定 anything'),false);
});
test('expired pairing never grants access',t=>{const access=new Access(temp(t));access.data.expires=0;assert.equal(access.pair({chattype:'single',from:{userid:'x'}},`绑定 ${access.data.token}`),false);});
test('env reader never executes shell or changes values containing equals',t=>{const p=path.join(temp(t),'.env');fs.writeFileSync(p,"WECOM_BOT_SECRET='a=b'\nEVIL=$(touch /tmp/should-not-exist)\n#comment\n");assert.equal(readEnv(p).WECOM_BOT_SECRET,'a=b');assert.equal(readEnv(p).EVIL,'$(touch /tmp/should-not-exist)');});
test('spreadsheet preserves numbers, missing values, and treats formula-like strings as text',async t=>{
 const file=await workbook('../测试',['数量','说明'],[[2,'=HYPERLINK("bad")'],[null,null]],temp(t));
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(file);const s=book.worksheets[0];
 assert.equal(s.getCell('A2').value,2);assert.equal(s.getCell('B2').type,ExcelJS.ValueType.String);assert.equal(s.getCell('B2').value,'=HYPERLINK("bad")');
 assert.equal(s.getCell('A3').value,'');assert.equal(book.worksheets.length,2);assert.equal(fs.statSync(file).mode&0o777,0o600);
});
test('business export uses all source rows, while model results are bounded',async t=>{
 const root=temp(t);let calls=0;
 const assistant=new Assistant({},root,{bridge:async args=>{assert.equal(args.kind,'business');return {rows:Array.from({length:410},(_,i)=>({'门店':String(i),'收入':i})),note:'source'};},llm:async messages=>{
 if(calls++===0)return {role:'assistant',content:null,tool_calls:[{id:'q1',type:'function',function:{name:'query_business',arguments:JSON.stringify({start:'2026-10-20',end:'2026-10-20',export_excel:true})}}]};
 const result=JSON.parse(messages.at(-1).content);assert.equal(result.rows.length,400);assert.equal(result.rows_truncated,true);return {role:'assistant',content:'附件已生成'};
 }});
 const result=await assistant.answer('生成经营表','session');assert.equal(result.artifacts.length,1);
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(result.artifacts[0]);assert.equal(book.worksheets[0].rowCount,411);
 assert.equal(loadJson(path.join(root,'sessions/session.json'),[]).length,2);
});
test('unsupported tools cannot execute a command',async t=>{const a=new Assistant({},temp(t));await assert.rejects(a.tool('shell',{command:'anything'},[]),/不支持/);});
test('history is isolated by sender and room',()=>{assert.notEqual(sessionKey({chattype:'single',from:{userid:'a'}}),sessionKey({chattype:'single',from:{userid:'b'}}));});
