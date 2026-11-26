import test from 'node:test';
import assert from 'node:assert/strict';
import {watchCommand,startWatch,Assistant} from './core.mjs';

test('值守口令解析',()=>{
  assert.equal(watchCommand('值守：上午运营失败了'),'上午运营失败了');
  assert.equal(watchCommand('让值守看一下实时采集'),'看一下实时采集');
  assert.equal(watchCommand('今天运营哪里失败了'),null);
});

test('未启用时不启动值守',()=>{
  let spawned=false;
  const r=startWatch('x',{},{spawn:()=>{spawned=true;},exists:()=>true});
  assert.equal(r.ok,false);assert.equal(spawned,false);
});

test('启用后后台启动值守脚本并传入原话',()=>{
  let call;
  const r=startWatch('修一下实时采集',{WECOM_AI_WATCH_ENABLED:'1',WECOM_DATA_ROOTS:'["/prod"]'},
    {exists:()=>true,spawn:(cmd,args,opts)=>{call={cmd,args,opts};return {unref(){}};}});
  assert.equal(r.ok,true);
  assert.equal(call.cmd,'/bin/zsh');assert.deepEqual(call.args,['/prod/scripts/ai_watch_request.zsh']);
  assert.equal(call.opts.detached,true);assert.equal(call.opts.env.AI_WATCH_REQUEST,'修一下实时采集');
});

test('值守口令不经过模型',async()=>{
  const a=new Assistant({WECOM_AI_WATCH_ENABLED:'1',WECOM_DATA_ROOTS:'["/prod"]'},'/tmp/watch-test',{llm:()=>{throw Error('不应调用模型');}});
  a.watchDeps={exists:()=>true,spawn:()=>({unref(){}})};
  const r=await a.answer('值守：上午运营失败了','k');
  assert.match(r.text,/已交给值守/);
});
