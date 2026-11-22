/* Rank platform-reported conversion rates without mixing platform denominators. */
(function () {
  'use strict';
  function rank(rows, stores, date, platform, metric) {
    return stores.map(store => {
      const matches = rows.filter(r => r.date === date && r.platform === platform && r.store === store);
      const raw = matches.length === 1 ? matches[0][metric] : null;
      const rate = typeof raw === 'number' && Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : null;
      return {store, rate};
    }).sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1));
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {rank};
  if (typeof document === 'undefined' || typeof records === 'undefined') return;
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const kinds = ['new', 'old'];
  function render(kind) {
    const platform = document.getElementById(kind + 'ConversionPlatform').value;
    const rows = rank(records, targetStores, dateSelect.value, platform, kind + '_customer_order_conversion');
    const max = Math.max(...rows.map(r => r.rate ?? 0), 0.01);
    document.getElementById(kind + 'ConversionBars').innerHTML = rows.map(r => `
      <div class="metric-row">
        <span>${escape(r.store)}</span>
        <div class="metric-track"><i style="width:${r.rate === null ? 0 : r.rate / max * 100}%"></i></div>
        <b>${r.rate === null ? '未采集' : (r.rate * 100).toFixed(1) + '%'}</b>
      </div>`).join('');
  }
  for (const kind of kinds) {
    document.getElementById(kind + 'ConversionPlatform').addEventListener('change', () => render(kind));
  }
  dateSelect.addEventListener('change', () => kinds.forEach(render));
  kinds.forEach(render);
})();
