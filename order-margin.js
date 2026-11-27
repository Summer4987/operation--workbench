(() => {
  const panels = [...document.querySelectorAll("[data-order-margin]")];
  const currency = new Intl.NumberFormat("zh-CN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const count = new Intl.NumberFormat("zh-CN");
  const clock = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const platforms = ["美团", "淘宝闪购"];
  let days = [];
  let request;

  const money = value => value == null ? "—" : currency.format(Number(value));
  const percent = value => value == null ? "—" : `${(value * 100).toFixed(2)}%`;
  const time = value => value ? clock.format(new Date(value)) : "—";
  const combined = rows => {
    if (rows.length !== 2 || rows.some(row => row.status !== "ok")) return null;
    const profit = rows.reduce((sum, row) => sum + Math.round(Number(row.profit) * 100), 0);
    const income = rows.reduce((sum, row) => sum + Math.round(Number(row.income) * 100), 0);
    return {profit: profit / 100, income: income / 100, margin: income === 0 ? null : profit / income};
  };

  function cell(row, value, detail) {
    const element = document.createElement("td");
    element.textContent = value;
    if (detail) {
      const caption = document.createElement("small");
      caption.textContent = detail;
      element.append(caption);
    }
    row.append(element);
  }

  function metricText(row) {
    if (row?.status === "missing_cost") return "待补成本";
    if (!row || (row.status && row.status !== "ok")) return "待采集";
    return `${money(row.profit)} ／ ${percent(row.margin)}`;
  }

  function show(panel, day) {
    const body = panel.querySelector("tbody");
    const status = panel.querySelector(".margin-status");
    body.replaceChildren();
    const rows = (day?.rows || []).filter(row =>
      panel.dataset.orderMargin === "direct" ? row.group === "direct" : row.group !== "direct");
    const valid = rows.filter(row => row.status === "ok");
    const complete = rows.length && valid.length === rows.length;
    const ticks = rows.flatMap(row => row.captured_at ? [row.captured_at] : []).sort();
    const total = key => valid.reduce((sum, row) => sum + Math.round(Number(row[key]) * 100), 0) / 100;
    const values = {
      orders: complete ? count.format(valid.reduce((sum, row) => sum + row.order_count, 0)) : "—",
      income: complete ? money(total("income")) : "—",
      profit: complete ? money(total("profit")) : "—",
      rate: complete && total("income") ? percent(total("profit") / total("income")) : "—",
    };
    for (const [key, value] of Object.entries(values)) panel.querySelector(`[data-margin-total="${key}"]`).textContent = value;
    if (!day) {
      status.textContent = "等待首次毛利分析。每天 21:30 起，在 ROI 复盘结束后采集。";
      return;
    }
    const captured = ticks.length ? ` · 快照 ${time(ticks[0])}–${time(ticks.at(-1))}` : "";
    const waste = complete ? ` · 已知出餐退款餐损 ${money(total("known_waste"))} 元` : "";
    status.textContent = `${day.date} · 已核算 ${valid.length}/${rows.length} 个门店平台${captured}${waste} · ${day.cost_template}`;
    for (const store of new Set(rows.map(row => row.store))) {
      const parts = platforms.map(platform => rows.find(row => row.store === store && row.platform === platform));
      const all = combined(parts.filter(Boolean));
      const tr = document.createElement("tr");
      cell(tr, store);
      for (const row of parts) {
        const details = row?.captured_at ? `${row.order_count ?? "—"} 单 · ${time(row.captured_at)}` : "";
        cell(tr, metricText(row), details);
      }
      cell(tr, all ? metricText(all) : "—", all ? `预计收入 ${money(all.income)} 元` : "");
      body.append(tr);
    }
  }

  function update(panel, selected = panel.querySelector("select").value) {
    const select = panel.querySelector("select");
    select.replaceChildren(...days.map(day => new Option(day.date, day.date)));
    if (days.some(day => day.date === selected)) select.value = selected;
    select.disabled = !days.length;
    show(panel, days.find(day => day.date === select.value));
  }

  function load(panel) {
    const button = panel.querySelector("button");
    button.disabled = true;
    if (!request) {
      request = fetch(new URL("./outputs/order_margin/history.json", document.baseURI), {cache: "no-store"})
        .then(async response => {
          if (response.status === 404) return [];
          if (!response.ok) throw new Error("读取失败");
          const payload = await response.json();
          if (!Array.isArray(payload.days)) throw new Error("数据格式异常");
          return payload.days.sort((a, b) => b.date.localeCompare(a.date));
        })
        .finally(() => { request = null; });
    }
    const selected = panel.querySelector("select").value;
    const wasLatest = selected === days[0]?.date;
    request.then(payload => {
      days = payload;
      update(panel, wasLatest ? "" : selected);
    }).catch(() => {
      panel.querySelector(".margin-status").textContent = "毛利数据读取失败，请刷新重试。";
    }).finally(() => { button.disabled = false; });
  }

  for (const panel of panels) {
    panel.innerHTML = `
      <div class="module-body">
        <div class="roi-controls"><label>数据日期 <select disabled></select></label><button type="button" class="confirm-button">刷新数据</button></div>
        <p class="margin-status" role="status">正在读取毛利数据。</p>
        <div class="roi-summary">
          <div><span>计入订单</span><strong data-margin-total="orders">—</strong></div>
          <div><span>预计收入（元）</span><strong data-margin-total="income">—</strong></div>
          <div><span>订单毛利（元）</span><strong data-margin-total="profit">—</strong></div>
          <div><span>订单毛利率</span><strong data-margin-total="rate">—</strong></div>
        </div>
        <div class="roi-table-wrap">
          <table class="roi-table" aria-label="门店双平台毛利">
            <thead><tr><th scope="col">门店</th><th scope="col">美团</th><th scope="col">淘宝闪购</th><th scope="col">双平台合计</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
        <p class="roi-note">表内为毛利额（元）／毛利率。毛利按平台预计收入减商品成本，套餐按实际选品拆算。无赔付取消退款单剔除，已知餐损单列。数据按采集时点累计。</p>
      </div>`;
    panel.querySelector("select").addEventListener("change", () => update(panel));
    panel.querySelector("button").addEventListener("click", () => load(panel));
  }

  function refreshVisible() {
    const panel = panels.find(item => `#${item.closest("section").id}` === location.hash);
    if (panel) load(panel);
  }
  window.addEventListener("hashchange", refreshVisible);
  refreshVisible();
  setInterval(refreshVisible, 60000);
})();
