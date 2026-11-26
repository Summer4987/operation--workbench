const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('eleme-bidding.js','utf8');
const now=Date.parse('2026-11-26T03:00:00Z');
async function run(overrides={},failed=false){
 const elements=Object.fromEntries(['elemeBiddingRows','elemeBiddingStatus','elemeBiddingSummary','elemeBiddingPeriod'].map(k=>[k,{textContent:'',innerHTML:'',querySelectorAll:()=>[]}]));
 const data={generatedAt:now,day:'2026-11-26',historyDay:'2026-11-26',historyStatus:'ok',stores:[{shopId:'1',name:'<img src=x>',bid:30,spend:1010,expected:1000,state:'reconcile',reason:'等回读'}],events:[{at:now,type:'decision',name:'<img src=x>',action:'hold',reason:'保持原因'},{at:now,type:'adjusted',name:'<img src=x>',before:30,after:40,reason:'慢于计划'}],...overrides};
 const timers=[];class Clock extends Date{static now(){return now;}}
 vm.runInNewContext(source,{window:{WORKBENCH_DATA:{eleme_bid_dashboard:data}},document:{getElementById:k=>elements[k],hidden:false},Date:Clock,Intl,AbortController,setInterval:f=>timers.push(f),setTimeout:()=>1,clearTimeout:()=>{},fetch:async()=>{if(failed)throw Error();return {ok:true,json:async()=>data}}});
 await new Promise(resolve=>setImmediate(resolve));return {elements,timers};
}
(async()=>{
 let {elements:e}=await run();assert.match(e.elemeBiddingRows.innerHTML,/¥0.30/);assert.match(e.elemeBiddingRows.innerHTML,/快 ¥0.10/);assert.match(e.elemeBiddingRows.innerHTML,/保持原因/);assert.match(e.elemeBiddingRows.innerHTML,/待核对/);assert.match(e.elemeBiddingRows.innerHTML,/¥0.30 至 ¥0.40/);assert.ok(!e.elemeBiddingRows.innerHTML.includes('<img'));assert.match(e.elemeBiddingPeriod.textContent,/^推广时段/);
 ({elements:e}=await run({generatedAt:now-900001}));assert.equal(e.elemeBiddingStatus.textContent,'数据过期');assert.match(e.elemeBiddingRows.innerHTML,/快照出价 \/ 快照花费/);assert.ok(!e.elemeBiddingRows.innerHTML.includes('今日花费'));
 ({elements:e}=await run({day:'2026-11-25',historyDay:'2026-11-25'}));assert.equal(e.elemeBiddingStatus.textContent,'数据过期');assert.ok(!e.elemeBiddingRows.innerHTML.includes('保持原因'));
 ({elements:e}=await run({simulation:true}));assert.equal(e.elemeBiddingStatus.textContent,'模拟数据');assert.match(e.elemeBiddingSummary.textContent,/不代表已执行/);
 ({elements:e}=await run({},true));assert.equal(e.elemeBiddingStatus.textContent,'读取失败');assert.match(e.elemeBiddingRows.innerHTML,/历史快照/);
 console.log('Eleme UI: money, gaps, history, escaping, stale/day rollover, simulation and fetch failure passed');
})();
