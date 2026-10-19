(() => {
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const shift = (date, days) => { const d = new Date(date + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0,10); };
  const sum = (rows, key) => rows.reduce((n,r) => n + Number(r[key] || 0), 0);
  const pct = (a,b) => b > 0 ? (a-b)/b : null;
  const percent = n => n === null ? '无可比基准' : `${n >= 0 ? '+' : ''}${(n*100).toFixed(1)}%`;
  const money = n => n.toLocaleString('zh-CN', {maximumFractionDigits:0});
  const panel = document.createElement('section'); panel.className = 'panel insights-panel';
  document.querySelector('header').after(panel);
  const style = document.createElement('style');
  style.textContent = `.insights-panel{border-top:4px solid #0f766e;margin-bottom:16px}.insight-summary{font-size:22px;font-weight:650;line-height:1.6;margin:12px 0}.insight-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.insight-list{display:grid;gap:8px}.insight-row{display:block;border:1px solid #e2e8f0;border-left:4px solid #94a3b8;border-radius:8px;padding:12px;color:inherit;text-decoration:none}.insight-row.warning{border-left-color:#d97706;background:#fffbeb}.insight-row.danger{border-left-color:#dc2626;background:#fff7f7}.insight-row small{display:block;color:#667085;margin-top:6px;line-height:1.6}.insight-row b{display:flex;justify-content:space-between;gap:10px}.insight-note{color:#667085;font-size:12px;line-height:1.7}.trend-svg{width:100%;height:155px}.trend-svg text{font-size:11px;fill:#667085}@media(max-width:700px){.insight-grid{grid-template-columns:1fr}.insight-summary{font-size:18px}}`;
  document.head.append(style);
  // Pair the exact store/platform keys; never compare a missing platform to zero.
  function pairs(date, reference, store) {
    const a=records.filter(r=>r.date===date && (!store || r.store===store));
    const b=records.filter(r=>r.date===reference && (!store || r.store===store));
    const key=r=>JSON.stringify([r.store,r.platform]);
    const am=new Map(a.map(r=>[key(r),r])), bm=new Map(b.map(r=>[key(r),r]));
    const keys=[...am.keys()].filter(k=>bm.has(k));
    return {a:keys.map(k=>am.get(k)), b:keys.map(k=>bm.get(k)), complete:keys.length===a.length && keys.length===b.length && keys.length>0};
  }
  function update() {
    const date=dateSelect.value;if(!date)return;
    const week=shift(date,-7), yesterday=shift(date,-1), current=records.filter(r=>r.date===date);
    const expected= new Set(records.filter(r=>r.date>=shift(date,-28)&&r.date<=date).map(r=>JSON.stringify([r.store,r.platform])));
    const present=new Set(current.map(r=>JSON.stringify([r.store,r.platform])));
    const missing=[...expected].filter(k=>!present.has(k)).map(k=>JSON.parse(k));
    const rows=targetStores.map(store=>{
      const p=pairs(date,week,store), day=pairs(date,yesterday,store);
      const income=sum(p.a,'income'), previous=sum(p.b,'income'), change=pct(income,previous);
      const orderChange=pct(sum(p.a,'orders'),sum(p.b,'orders'));
      const ticket=pct(sum(p.a,'orders')?income/sum(p.a,'orders'):0,sum(p.b,'orders')?previous/sum(p.b,'orders'):0);
      const history=[1,2,3,4].map(w=>pairs(date,shift(date,-7*w),store)).filter(x=>x.complete && p.complete && JSON.stringify(x.a.map(r=>r.platform).sort())===JSON.stringify(p.a.map(r=>r.platform).sort()));
      const normal=history.length>=3 ? history.reduce((n,x)=>n+sum(x.b,'income'),0)/history.length : null;
      const baseline=normal===null?null:pct(income,normal);
      const issue=change!==null && (Math.abs(change)>=.2 || (baseline!==null && Math.abs(baseline)>=.2));
      return {store,p,change,orderChange,ticket,baseline,history:history.length,impact:income-previous,issue,missing:missing.filter(x=>x[0]===store)};
    }).sort((a,b)=>Number(b.missing.length>0)-Number(a.missing.length>0)||Number(b.issue)-Number(a.issue)||Math.abs(b.impact)-Math.abs(a.impact));
    const total=pairs(date,week), change=pct(sum(total.a,'income'),sum(total.b,'income'));
    const declines=rows.filter(r=>r.issue && r.change<0);
    const historyDates=Array.from({length:14},(_,i)=>shift(date,i-13));
    // Keep the current population fixed; show missing days as gaps, never zero.
    const trendKeys=[...present];
    const trend=historyDates.map(d=>{
      const items=records.filter(r=>r.date===d&&trendKeys.includes(JSON.stringify([r.store,r.platform])));
      return items.length===trendKeys.length && trendKeys.length ? sum(items,'income') : null;
    });
    let chart='<p class="insight-note">近 14 天同店同平台完整数据不足两天，暂不绘制趋势。</p>';
    if(trend.filter(v=>v!==null).length>=2){
      const max=Math.max(...trend.filter(v=>v!==null),1), y=v=>125-v/max*100;
      const segments=[];let segment=[];
      trend.forEach((v,i)=>{if(v===null){if(segment.length)segments.push(segment);segment=[];}else segment.push(`${25+i*40},${y(v)}`);});if(segment.length)segments.push(segment);
      chart=`<svg class="trend-svg" viewBox="0 0 570 155" role="img" aria-label="近14天可比收入趋势"><text x="0" y="15">¥${money(max)}</text><line x1="25" y1="125" x2="545" y2="125" stroke="#cbd5e1"/>${segments.map(p=>`<polyline points="${p.join(' ')}" fill="none" stroke="#0f766e" stroke-width="3"/>`).join('')}${trend.map((v,i)=>v===null?`<text x="${25+i*40}" y="120">×<title>${historyDates[i]}：数据不完整</title></text>`:`<circle cx="${25+i*40}" cy="${y(v)}" r="3" fill="#0f766e"><title>${historyDates[i]}：¥${money(v)}</title></circle>`).join('')}<text x="25" y="148">${historyDates[0]}</text><text x="465" y="148">${date}</text></svg><p class="insight-note">固定当日 ${trendKeys.length} 个门店平台组合；× 为缺失或不完整日期，折线断开。悬停查看金额。</p>`;
    }
    panel.innerHTML=`<div class="section-title"><h2>经营变化与异常</h2><span>${esc(date)} · 对比 ${week}</span></div><p class="insight-summary">可比收入较上周同日 ${percent(change)}${change===null?'':`（¥${money(sum(total.a,'income')-sum(total.b,'income'))}）`}；${total.a.length?`${declines.length} 家门店明显下滑`:'历史不足，暂不判断下滑'}，${missing.length} 项待核实缺报。</p><p class="insight-note">比较覆盖 ${total.a.length}/${current.length} 个当日门店平台组合${total.complete?'':'，覆盖不完整，仅反映共同样本'}。波动提示阈值为 ±20%，用于筛查；不代表已确认的经营原因。零基数不计算涨跌幅。</p><div class="insight-grid"><div><h3>优先核查门店</h3><div class="insight-list">${rows.map(r=>`<a class="insight-row ${r.missing.length?'warning':r.issue&&r.change<0?'danger':r.issue?'warning':''}" href="${esc(storeReportFiles[r.store]||'#')}"><b><span>${esc(r.store)} · ${r.missing.length?'数据待核实':r.issue?'波动提示':r.change===null?'历史不足':'正常波动'}</span><span>${percent(r.change)}</span></b><small>${r.change===null?'上周同日没有可比收入基准':`同平台收入差额 ¥${money(r.impact)} · 单量 ${percent(r.orderChange)} · 收入单均价 ${percent(r.ticket)}`}${!r.p.complete?' · 平台覆盖不完整':''}<br>${r.missing.length?`缺少 ${r.missing.map(x=>esc(x[1])).join('、')}，请核实报表或营业状态；暂不认定经营下滑。`:r.issue?'建议核查订单、流量及活动变化，再判断原因。':'点击查看单店明细。'}<br>${r.baseline===null?'近四周同星期有效样本不足 3 天':`较近四周同星期均值 ${percent(r.baseline)}（${r.history} 天样本）`}</small></a>`).join('')}</div></div><div><h3>近 14 天可比收入趋势</h3>${chart}<p class="insight-note">数据日期为 ${date}。${shift(date,2)<new Date().toISOString().slice(0,10)?'当前为历史数据，请勿作为今日经营状态。':''}缺报依据近 28 天出现过的门店平台组合识别；停业、平台退出需要人工核实。</p><h3>异常筛查口径</h3><p class="insight-note">按缺报、明显波动、收入差额绝对值排序；上涨同样提示。上周同日及四周基准均按共同门店平台比较。未提供订货、毛利、退款、损耗字段，暂不推断这些异常。</p></div></div>`;
    // Keep the main detail table in the same operational priority order.
    const rank=new Map(rows.map((r,i)=>[r.store,i]));
    const body=document.getElementById('storeRows');
    [...body.children].sort((a,b)=>(rank.get(a.querySelector('a')?.textContent)??999)-(rank.get(b.querySelector('a')?.textContent)??999)).forEach(tr=>body.append(tr));
    document.querySelector('.focus-panel').hidden=true;
    document.querySelector('.analysis-panel').hidden=true;
  }
  dateSelect.addEventListener('change',update);update();
})();
