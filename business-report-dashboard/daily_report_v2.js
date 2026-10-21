/* Single-day review. Kept separate from the weekly analysis and chart renderer. */
(function () {
  'use strict';
  const LIMIT = 0.10;
  const shift = (date, days) => {
    const d = new Date(date + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  };
  const numeric = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
  const sum = (rows, key) => rows.reduce((n, r) => n + Number(r[key] || 0), 0);
  const pct = (a, b) => a !== null && b > 0 ? (a - b) / b : null;
  const reached = n => n !== null && Math.abs(n) >= LIMIT - 1e-10;
  const metrics = [
    ['income', '营业额', 'money'], ['orders', '订单量', 'int'],
    ['impressions', '曝光量', 'int'], ['visit_conversion', '进店转化率', 'rate'],
    ['order_conversion', '下单转化率', 'rate'], ['ticket', '收入单均价', 'money'],
  ];
  function aggregate(rows) {
    if (!rows.length) return Object.fromEntries(metrics.map(([key]) => [key, null]));
    const result = {};
    for (const key of ['income', 'orders', 'impressions']) {
      result[key] = rows.every(r => numeric(r[key])) ? sum(rows, key) : null;
    }
    result.ticket = result.orders > 0 && result.income !== null ? result.income / result.orders : null;
    // Weight report conversion rates by their funnel denominators, not by order count.
    const visitsKnown = rows.every(r => numeric(r.impressions) && numeric(r.visit_conversion));
    const visits = visitsKnown ? rows.reduce((n, r) => n + Number(r.impressions) * Number(r.visit_conversion), 0) : 0;
    result.visit_conversion = visitsKnown && result.impressions > 0 ? visits / result.impressions : null;
    result.order_conversion = visitsKnown && visits > 0 && rows.every(r => numeric(r.order_conversion))
      ? rows.reduce((n, r) => n + Number(r.impressions) * Number(r.visit_conversion) * Number(r.order_conversion), 0) / visits : null;
    return result;
  }
  function compare(all, date, ref, store) {
    const filter = d => all.filter(r => r.date === d && (!store || r.store === store));
    const current = filter(date), previous = filter(ref);
    const key = r => JSON.stringify([r.store, r.platform]);
    const before = new Map(previous.map(r => [key(r), r]));
    const a = current.filter(r => before.has(key(r))), b = a.map(r => before.get(key(r)));
    const complete = a.length > 0 && a.length === current.length && b.length === previous.length;
    const now = aggregate(a), then = aggregate(b);
    return {date: ref, complete, platforms: [...new Set(a.map(r => r.platform))], count: a.length,
      now, then, changes: Object.fromEntries(metrics.map(([k]) => [k, pct(now[k], then[k])]))};
  }
  function analyze(all, stores, date) {
    const day = shift(date, -1), week = shift(date, -7);
    return stores.map(store => {
      const current = all.filter(r => r.store === store && r.date === date);
      const expected = new Set(all.filter(r => r.store === store && r.date >= shift(date, -28) && r.date <= date).map(r => r.platform));
      const missing = [...expected].filter(p => !current.some(r => r.platform === p));
      const comparisons = [compare(all, date, day, store), compare(all, date, week, store)];
      const signals = comparisons.flatMap((c, i) => ['income', 'impressions', 'visit_conversion', 'order_conversion'].filter(k => reached(c.changes[k])).map(k => ({key: k, change: c.changes[k], point: k.endsWith('conversion') ? c.now[k] - c.then[k] : null, basis: i === 0 ? '较前一日' : '较上周同日', complete: c.complete, date: c.date, platforms: c.platforms})));
      const incomeSignals = signals.filter(s => s.key === 'income' && s.complete);
      const down = incomeSignals.some(s => s.change < 0), up = incomeSignals.some(s => s.change > 0);
      const bothKnown = comparisons.every(c => c.complete && c.changes.income !== null);
      const status = !current.length || missing.length ? 'pending' : down && up ? 'mixed' : down ? 'down' : up ? 'up' : bothKnown ? 'stable' : 'unknown';
      return {store, current: aggregate(current), comparisons, missing, signals, status, platforms: [...new Set(current.map(r => r.platform))]};
    });
  }
  const api = {LIMIT, shift, aggregate, compare, analyze};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || typeof records === 'undefined') return;

  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (v, digits = 0) => v === null ? '—' : Number(v).toLocaleString('zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits});
  const percent = v => v === null ? '无可比基准' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
  const points = v => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}个百分点`;
  const value = (v, type) => v === null ? '—' : type === 'rate' ? `${(v * 100).toFixed(1)}%` : type === 'money' ? `¥${number(v, 2)}` : number(v);
  const labels = {down:'异常下滑', up:'明显上涨', mixed:'涨跌分化', stable:'营业额稳定', pending:'数据待核实', unknown:'比较数据不足'};
  const metricLabel = key => metrics.find(m => m[0] === key)[1];
  const report = document.createElement('div'); report.id = 'dailyReview';
  document.querySelector('header').after(report);
  // Replace accumulated single-day blocks. Preserve weekly analysis and charts.
  for (const selector of ['.focus-panel', '.analysis-panel']) document.querySelector(selector)?.remove();
  for (const selector of ['.kpis', '.table-wrap']) {
    const el = document.querySelector(selector);
    if (el) { el.hidden = true; el.style.display = 'none'; }
  }
  document.getElementById('incomeChangeBars').parentElement.querySelector('h2').textContent = '门店营业额较前一日变化';
  const style = document.createElement('style');
  style.textContent = `
    body{background:#f4f6f8}main{max-width:1560px;margin:auto}#dailyReview{--dr-muted:#68758a;--dr-line:#e5eaf0;color:#182438}
    .dr-summary{background:#fff;border:1px solid var(--dr-line);border-top:3px solid #0f766e;border-radius:14px;padding:22px 24px;margin-bottom:18px}
    .dr-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.dr-heading h2{margin:0;font-size:20px}.dr-heading span,.dr-note{font-size:12px;color:var(--dr-muted);line-height:1.6}
    .dr-lead{font-size:17px;font-weight:600;line-height:1.65;margin:14px 0}.dr-groups{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    .dr-group{border:1px solid var(--dr-line);border-radius:10px;padding:14px;background:#fafbfc}.dr-group h3{font-size:13px;margin:0 0 8px}.dr-group p{font-size:13px;line-height:1.65;margin:0}.dr-group.down h3{color:#b42318}.dr-group.up h3{color:#087f72}.dr-group.stable h3{color:#456078}
    .dr-alerts{margin-top:14px;border-top:1px solid var(--dr-line);padding-top:12px}.dr-alerts h3{font-size:14px;margin:0 0 8px}.dr-alerts ul{margin:0;padding-left:19px;font-size:13px;line-height:1.8}.dr-alerts li+li{margin-top:3px}
    .dr-note{margin:10px 0 0}.dr-rules{font-size:12px;color:var(--dr-muted);margin-top:12px}.dr-rules summary{cursor:pointer}.dr-rules p{line-height:1.7;margin:8px 0 0}
    .dr-section-title{font-size:18px;margin:22px 0 12px}.dr-total{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:14px}.dr-total article{background:#fff;border:1px solid var(--dr-line);border-radius:10px;padding:16px}.dr-total h3{font-size:12px;font-weight:500;color:var(--dr-muted);margin:0}.dr-total strong{font-size:26px;display:block;margin:6px 0 8px}.dr-total small{font-size:12px;line-height:1.8;display:block;color:var(--dr-muted)}
    .dr-store{background:#fff;border:1px solid var(--dr-line);border-radius:12px;margin-bottom:12px;padding:17px 20px}.dr-store-header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.dr-store-header a{color:#182438;font-weight:650;text-decoration:none}.dr-store-header small{font-size:11px;color:var(--dr-muted);margin-left:10px}.dr-badge{border-radius:20px;padding:4px 9px;font-size:11px;background:#eff3f6;color:#456078;white-space:nowrap}.dr-badge.down,.dr-badge.mixed{background:#fff0ed;color:#b42318}.dr-badge.up{background:#e8f7f2;color:#087f72}.dr-badge.pending,.dr-badge.unknown{background:#fff6e5;color:#936014}
    .dr-metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}.dr-metric{border-left:1px solid var(--dr-line);padding-left:12px}.dr-metric:first-child{border-left:0;padding-left:0}.dr-metric h4{font-size:11px;color:var(--dr-muted);font-weight:500;margin:0 0 4px}.dr-value{font-size:20px;font-weight:650;white-space:nowrap}.dr-comparison{font-size:11px;color:var(--dr-muted);line-height:1.8;margin-top:6px}.dr-change{display:block;font-size:12px}.dr-change.alert{font-weight:650;color:#ae4a16}.dr-base{font-size:10px;color:#8290a3;display:block}.dr-store-note{margin:10px 0 0;font-size:11px;color:#936014;line-height:1.6}
    .dr-history{color:#936014;background:#fff6e5;border-radius:6px;padding:7px 10px;font-size:12px;margin-top:10px}
    @media(max-width:1000px){.dr-metrics{grid-template-columns:repeat(3,minmax(0,1fr));row-gap:18px}.dr-metric:nth-child(4){border-left:0;padding-left:0}.dr-groups{grid-template-columns:1fr}.dr-value{font-size:19px}}@media(max-width:600px){.dr-summary{padding:16px}.dr-heading{align-items:flex-start;flex-direction:column;gap:4px}.dr-total{grid-template-columns:1fr}.dr-store{padding:15px}.dr-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.dr-metric:nth-child(4){border-left:1px solid var(--dr-line);padding-left:12px}.dr-metric:nth-child(odd){border-left:0;padding-left:0}.dr-store-header small{display:block;margin:3px 0 0}}
  `;
  document.head.append(style);
  function update() {
    const date = dateSelect.value;
    if (!date) { report.innerHTML = '<p class="dr-note">暂无日报数据。</p>'; return; }
    const rows = analyze(records, targetStores, date);
    const chinaToday = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const isYesterday = shift(chinaToday, -1) === date;
    const groups = [
      ['down', '异常下滑', rows.filter(r => r.status === 'down' || r.status === 'mixed')],
      ['up', '明显上涨', rows.filter(r => r.status === 'up' || r.status === 'mixed')],
      ['stable', '营业额稳定', rows.filter(r => r.status === 'stable')],
    ];
    const pending = rows.filter(r => r.status === 'pending' || r.status === 'unknown');
    const groupHtml = groups.map(([key, label, list]) => `<div class="dr-group ${key}"><h3>${label} · ${list.length} 家</h3><p>${list.length ? list.map(r => `${esc(r.store)}${key === 'stable' ? '' : `（${r.signals.filter(s => s.key === 'income' && s.complete && (key === 'down' ? s.change < 0 : s.change > 0)).map(s => `${s.basis} ${percent(s.change)}`).join('；')}）`}`).join('<br>') : '暂无'}</p></div>`).join('');
    const alerts = rows.map(r => {
      const signals = r.signals.filter(s => s.key !== 'income' || !s.complete || r.status === 'pending');
      if (!signals.length) return '';
      return `<li><b>${esc(r.store)}</b>：${signals.map(s => `${metricLabel(s.key)}${s.basis} ${percent(s.change)}${s.point === null ? '' : `（${points(s.point)}）`}${s.complete ? '' : `〔仅${esc(s.platforms.join('、'))}可比〕`}`).join('；')}。</li>`;
    }).filter(Boolean);
    const totalNow = aggregate(records.filter(r => r.date === date));
    const totalCompare = [compare(records, date, shift(date,-1)), compare(records, date, shift(date,-7))];
    function comparison(c, key, type, i) {
      const change = c.changes[key];
      const delta = type === 'rate' && c.now[key] !== null && c.then[key] !== null ? `${points(c.now[key] - c.then[key])} / ${percent(change)}` : percent(change);
      return `<div class="dr-comparison">${i === 0 ? '较前一日' : '较上周同日'}<span class="dr-change ${reached(change) ? 'alert' : ''}">${delta}</span><span class="dr-base">${c.date.slice(5)}：${value(c.then[key],type)}${!c.complete && c.count ? ` · 仅${esc(c.platforms.join('、'))}；当日 ${value(c.now[key],type)}` : ''}</span></div>`;
    }
    report.innerHTML = `<section class="dr-summary"><div class="dr-heading"><h2>AI 日报概况</h2><span>${date}${isYesterday ? ' · 昨日' : ''} · 对比 ${shift(date,-1)} / ${shift(date,-7)}</span></div><p class="dr-lead">${isYesterday ? '昨日' : '当日'}营业额 ¥${number(totalNow.income,2)}；${groups[0][2].length} 家下滑异常，${groups[1][2].length} 家明显上涨，${groups[2][2].length} 家保持稳定${pending.length ? `，${pending.length} 家比较数据待核实` : ''}。</p><div class="dr-groups">${groupHtml}</div>${pending.length ? `<p class="dr-note">待核实：${pending.map(r=>`${esc(r.store)}（${r.missing.length ? `当日缺少${esc(r.missing.join('、'))}` : '前一日或上周同日比较不完整 / 基数为零'}）`).join('；')}。</p>` : ''}${alerts.length ? `<div class="dr-alerts"><h3>曝光与转化提醒</h3><ul>${alerts.join('')}</ul></div>` : '<p class="dr-note">可比数据中，曝光和转化率未触发 ±10% 提醒。</p>'}${rows.some(r=>r.status==='mixed') ? '<p class="dr-note">涨跌分化门店同时列入上涨和下滑，具体方向以对应比较日期为准。</p>' : ''}${!isYesterday ? '<div class="dr-history">当前查看历史日报，并非昨日经营状态。</div>' : ''}<details class="dr-rules"><summary>判断口径 · 单日变化达到 ±10% 提醒</summary><p>营业额、曝光、进店转化率、下单转化率，只比较所选日期的前一个自然日和上周同日。变化率 =（当日值 − 对比值）÷ 对比值；达到 ±10% 即提醒，转化率同时显示百分点差。例如 10% → 9%，下降 1 个百分点，相对下降 10%。营业额两项比较均完整且未触发才标记稳定；零基数不计算涨跌幅。按同店同平台配对，缺失数据不按零补齐；当日缺报依据近 28 天出现过的平台识别，需要核实是否停业或退出。转化率按漏斗分母加权：进店率按曝光量，下单率按曝光量 × 进店率推算的进店人数；不同平台口径可能有差异。以上为规则自动归纳，不代表已确认原因。</p></details></section><h2 class="dr-section-title">${isYesterday ? '昨日' : '当日'}经营详情 <span class="dr-note">${date} · 每项同时列出前一日、上周同日</span></h2><div class="dr-total">${metrics.slice(0,3).map(([key,label,type])=>`<article><h3>总${label}</h3><strong>${value(totalNow[key],type)}</strong>${totalCompare.map((c,i)=>`<small>${i===0?'较前一日':'较上周同日'} ${percent(c.changes[key])}${!c.complete ? ' · 覆盖不完整' : ''}</small>`).join('')}</article>`).join('')}</div>${rows.map(r=>`<article class="dr-store"><div class="dr-store-header"><div><a href="${esc(storeReportFiles[r.store]||'#')}">${esc(r.store)} ↗</a><small>${esc(r.platforms.join(' + ') || '当日无数据')}</small></div><span class="dr-badge ${r.status}">${labels[r.status]}</span></div><div class="dr-metrics">${metrics.map(([key,label,type])=>`<div class="dr-metric"><h4>${label}</h4><div class="dr-value">${value(r.current[key],type)}</div>${r.comparisons.map((c,i)=>comparison(c,key,type,i)).join('')}</div>`).join('')}</div>${r.missing.length || r.comparisons.some(c=>!c.complete) ? `<p class="dr-store-note">${r.missing.length ? `当日缺少 ${esc(r.missing.join('、'))}；` : ''}${r.comparisons.filter(c=>!c.complete).map(c=>`${c.date}：${c.count ? `仅 ${esc(c.platforms.join('、'))} 可比，涨跌幅按共同样本计算` : '无共同平台数据'}`).join('；')}。</p>` : ''}</article>`).join('')}`;
    // Existing change chart also uses the exact prior calendar day and paired samples.
    const chartRows = rows.map(r=>({store:r.store,income_change:r.comparisons[0].changes.income}));
    renderChangeBars('incomeChangeBars', chartRows, 'income_change');
    const conversionRows = rows.map(r => ({store:r.store,...r.current}));
    renderBars('visitBars', conversionRows.filter(r=>r.visit_conversion !== null), 'visit_conversion', v=>value(v,'rate'));
    renderBars('orderBars', conversionRows.filter(r=>r.order_conversion !== null), 'order_conversion', v=>value(v,'rate'));
    document.getElementById('previousDateLabel').textContent = `对比 ${shift(date,-1)}，按同店同平台；无可比数据不补零`;
  }
  dateSelect.addEventListener('change', update);
  update();
})();
