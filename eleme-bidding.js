/* Read-only feed: shares the existing workbench owner authentication boundary. */
(() => {
  const root = document.getElementById('elemeBiddingRows');
  if (!root) return;
  let snapshot = window.WORKBENCH_DATA?.eleme_bid_dashboard || {}, fetchError = '', busy = false;
  const esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  const money = n => Number.isSafeInteger(n) ? `¥${(n / 100).toFixed(2)}` : '—';
  const time = n => Number.isFinite(n) ? new Date(n).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : '未提供';
  const day = n => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n));
  const labels = {ok:'正常', blocked:'阻止', reconcile:'待核对', pending:'待核对', error:'读取失败'};
  const actions = {hold:'保持',raise:'上调',lower:'下调',increase:'上调',decrease:'下调',stop:'停止',block:'阻止'};
  const types = {decision:'判断',adjusted:'已调价',error:'异常',skip:'跳过',recalibrate:'重新校准'};
  function render() {
    const s = snapshot, now = Date.now(), today = day(now), stores = Array.isArray(s.stores) ? s.stores : [];
    const fresh = Number.isFinite(s.generatedAt) && now - s.generatedAt <= 900000 && now >= s.generatedAt && s.day === today;
    const valid = fresh && !fetchError && !s.error;
    const status = document.getElementById('elemeBiddingStatus');
    status.textContent = fetchError || s.error ? '读取失败' : !s.generatedAt ? '等待数据' : !fresh ? '数据过期' : s.simulation ? '模拟数据' : '数据正常';
    status.className = `tag ${valid && !s.simulation ? 'good' : 'planning'}`;
    document.getElementById('elemeBiddingSummary').textContent = `数据生成时间：${time(s.generatedAt)} · ${stores.length} 家门店。${s.simulation ? '当前为模拟结果，不代表已执行调价。' : ''}${valid ? '每分钟检查看板更新。' : '以下仅为最后一次快照，不作为当前值或今日实时花费。'}${s.error ? ' 本轮读取失败。' : ''}${fetchError}`;
    const parts = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(now)).split(':').map(Number);
    const minute = parts[0] * 60 + parts[1], inPeriod = minute >= 630 && minute < 750 || minute >= 1020 && minute < 1200;
    document.getElementById('elemeBiddingPeriod').textContent = `${inPeriod ? '推广时段' : '非推广时段'}（10:30–12:30、17:00–20:00） · 北京时间`;
    const opened = new Set([...root.querySelectorAll('details[open]')].map(el=>el.dataset.store));
    const events = s.historyDay === today && Array.isArray(s.events) ? s.events : [];
    const historyWarning = s.historyStatus === 'missing' ? '调价记录尚未生成，无法确认当天历史。' : s.historyStatus !== 'ok' ? '调价记录读取不完整，以下仅展示成功读取的记录。' : s.historyDay !== today ? '等待当天记录更新。' : '';
    root.innerHTML = `${!valid ? '<p class="warning">历史快照 · 下列金额均为生成时间的读数</p>' : ''}${historyWarning ? `<p>${historyWarning}</p>` : ''}${stores.length ? `<div class="remote-fleet-table-wrap"><table class="remote-fleet-table"><thead><tr><th>门店</th><th>${valid ? '当前出价 / 今日花费' : '快照出价 / 快照花费'}</th><th>${valid ? '此刻计划花费 / 差距' : '快照计划 / 差距'}</th><th>当天最近一次调价</th><th>下次检查 / 状态</th></tr></thead><tbody>${stores.map((x,i)=>{
      const key = String(x.shopId || x.name || i);
      const logs = events.filter(e=>e.shopId ? String(e.shopId) === String(x.shopId) : e.name && e.name === x.name);
      const last = logs.filter(e=>e.type==='adjusted' && !e.simulation).at(-1);
      const gap = Number.isSafeInteger(x.gap) ? x.gap : Number.isSafeInteger(x.spend) && Number.isSafeInteger(x.expected) ? x.spend - x.expected : null;
      const state = s.error ? '读取失败' : labels[x.state] || '待核对';
      return `<tr><td data-label="门店"><strong>${esc(x.name || '未命名门店')}</strong><details data-store="${esc(key)}" ${opened.has(key)?'open':''}><summary>当天全部记录（${logs.length}）</summary><div class="remote-fleet-log">${logs.slice().reverse().map(e=>`<article><small>${esc(time(e.at))} · ${esc(types[e.type] || '记录')}${e.simulation?' · 模拟':''}</small><p>${esc(actions[e.action] || e.action || '')} ${money(e.before)} 至 ${money(e.after)}</p><p>${esc(e.reason || e.message || '未提供原因')}</p><small>计划 ${money(e.expected)} · 实际 ${money(e.actual)}</small></article>`).join('') || `<p>${historyWarning || '当天暂无该门店记录。'}</p>`}</div></details></td>
      <td data-label="出价 / 花费"><strong>${money(x.bid)}</strong><small>${valid ? '今日花费' : '快照花费'} ${money(x.spend)}</small>${x.simulation?'<small>模拟结果</small>':''}</td>
      <td data-label="计划 / 差距"><strong>${money(x.expected)}</strong><small>${gap===null?'暂无可比读数':gap===0?'与计划持平':`${gap>0?'快':'慢'} ${money(Math.abs(gap))}`}</small></td>
      <td data-label="最近调价">${last ? `<strong>${money(last.before)} 至 ${money(last.after)}</strong><small>${esc(time(last.at))}</small><p>${esc(last.reason || last.message || '未提供原因')}</p>` : '<p>当天暂无已确认调价记录</p>'}</td>
      <td data-label="检查 / 状态"><span class="remote-fleet-pill ${state==='正常'?'':'warning'}">${esc(state)}</span><p>${esc(x.reason || x.message || '等待检查')}</p><small>${valid ? '下次检查' : '快照计划检查'} ${esc(time(s.nextCheckAt))}</small></td></tr>`;
    }).join('')}</tbody></table></div>` : '<div class="fleet-empty">等待 Mac mini 回传调价数据</div>'}`;
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),10000);
    try {
      const response = await fetch('./outputs/eleme_bid_dashboard/latest.json', {cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error('unavailable');
      const next = await response.json();
      if (!next || !Array.isArray(next.stores)) throw new Error('invalid');
      snapshot = next; fetchError = '';
    } catch { fetchError = ' 看板更新失败，请刷新或检查登录状态。'; }
    finally { clearTimeout(timer); busy = false; render(); }
  }
  render();
  setInterval(render, 15000);
  setInterval(refresh, 60000);
  refresh();
})();
