import test from 'node:test';
import assert from 'node:assert/strict';
import {noticeCard,sendNotice} from './notify_card.mjs';

test('短通知只发卡片，标题取第一行',async()=>{
  const sent=[];const client={sendMessage:async(_o,b)=>sent.push(b)};
  const mode=await sendNotice(client,'u','【上午运营｜失败】\n结论：日报采集未完成\n时间：08:40');
  assert.equal(mode,'card');assert.equal(sent.length,1);
  assert.equal(sent[0].template_card.main_title.title,'上午运营｜失败');
  assert.equal(sent[0].template_card.main_title.desc,'结论：日报采集未完成');
  assert.equal(sent[0].template_card.card_action.type,1);
});

test('长通知卡片后补发全文',async()=>{
  const sent=[];const client={sendMessage:async(_o,b)=>sent.push(b)};
  const text='【上午运营分类报告】\n结论：存在异常\n'+'• 某项：失败；原因很长很长\n'.repeat(20);
  assert.equal(await sendNotice(client,'u',text),'card+markdown');
  assert.equal(sent[0].msgtype,'template_card');assert.equal(sent[1].markdown.content,text);
  assert.ok(sent[0].template_card.sub_title_text.length<=112);
});

test('卡片发送失败时退回Markdown',async()=>{
  const sent=[];const client={sendMessage:async(_o,b)=>{if(b.msgtype==='template_card')throw Error('x');sent.push(b);}};
  assert.equal(await sendNotice(client,'u','【测试】\n内容'),'markdown-fallback');
  assert.equal(sent[0].msgtype,'markdown');
});

test('超长标题被截断',()=>{
  const {card,needsFullText}=noticeCard('【'+'很'.repeat(40)+'】');
  assert.equal(card.main_title.title.length,26);assert.equal(needsFullText,true);
});
