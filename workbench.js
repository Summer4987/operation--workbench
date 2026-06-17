const data = window.WORKBENCH_DATA || {};
const PROMO_BUDGET_OVERRIDES_URL = "http://139.155.148.169/api/promo-budget-overrides?token=xiongxiaoxiao-order";
const FINANCE_UPLOAD_URL = "/api/finance/upload?token=xiongxiaoxiao-order";
const FINANCE_ENTRY_URL = "/api/finance/entry?token=xiongxiaoxiao-order";
const FINANCE_OPENING_URL = "/api/finance/opening?token=xiongxiaoxiao-order";
const SUPPLY_CHAIN_FLOW_URL = "/api/supply-chain/flow?token=xiongxiaoxiao-order";
let budgetOverridesFetchStarted = false;

const mainView = document.querySelector(".main");
const commandBoard = document.querySelector(".command-board");
const overviewAlert = document.querySelector(".overview-alert");
const pageSections = [...document.querySelectorAll(".center-section")];
const navLinks = [...document.querySelectorAll(".nav a")];

const yuan = (value) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: 0,
  })}`;

const num = (value, digits = 0) =>
  Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
  });

const pct = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;

function sameTimeYesterday(daily) {
  return (
    daily.same_time_yesterday ||
    daily.yesterday_same_period ||
    data.same_time_yesterday ||
    data.realtime?.same_time_yesterday ||
    null
  );
}

function yesterdayStoreMap(daily) {
  const realtimeComparison = data.realtime_comparison;
  if (realtimeComparison?.status === "ready") {
    return new Map((realtimeComparison.stores || []).map((item) => [item.store || item.store_name || item.name, item]));
  }
  const previous = sameTimeYesterday(daily);
  return new Map((previous?.stores || []).map((item) => [item.store || item.store_name || item.name, item]));
}

function comparisonLabel(currentIncome, currentOrders, previous) {
  const realtimeComparison = data.realtime_comparison;
  const realtimeOrders = realtimeComparison?.summary?.orders;
  if (realtimeComparison?.status === "ready" && realtimeOrders) {
    const baseTime = realtimeComparison.matched_time ? realtimeComparison.matched_time.slice(11, 16) : "最近时刻";
    return `较昨日基准 ${baseTime} ${signedNumber(realtimeOrders.delta)} 单`;
  }
  if (!previous || previous.status === "missing") return previous?.message || "昨日暂无可用实时历史数据，明天开始生成";
  const previousIncome = Number(previous.income ?? previous.total_income ?? 0);
  const previousOrders = Number(previous.orders ?? previous.total_orders ?? 0);
  const incomeDelta = currentIncome - previousIncome;
  const orderDelta = currentOrders - previousOrders;
  const moneyText = `${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}`;
  const orderText = `${orderDelta >= 0 ? "+" : "-"}${num(Math.abs(orderDelta))} 单`;
  return `较昨日基准 ${moneyText} / ${orderText}`;
}

function signedNumber(value) {
  const rounded = Math.round(Number(value || 0));
  return `${rounded > 0 ? "+" : ""}${num(rounded)}`;
}

function trendClass(delta) {
  const value = Number(delta || 0);
  if (value > 0) return "trend-up";
  if (value < 0) return "trend-down";
  return "trend-flat";
}

function text(id, value) {
  const el = document.querySelector(`#${id}`);
  if (el) el.textContent = value;
}

function html(id, value) {
  const el = document.querySelector(`#${id}`);
  if (el) el.innerHTML = value;
}

function cls(id, className, enabled) {
  const el = document.querySelector(`#${id}`);
  if (el) el.classList.toggle(className, enabled);
}

function latestDailyDate(daily) {
  const sourceDates = daily.source_dates || [];
  if (sourceDates.length) return sourceDates[sourceDates.length - 1];
  const dates = [...new Set((daily.records || []).map((item) => item.date).filter(Boolean))].sort();
  return dates[dates.length - 1] || "";
}

function latestDailyRows(daily) {
  const date = latestDailyDate(daily);
  return (daily.records || []).filter((item) => item.date === date);
}

function dailyRowsByDate(daily, date) {
  return (daily.records || []).filter((item) => item.date === date);
}

function previousDailyDate(daily, currentDate) {
  const dates = [...new Set((daily.records || []).map((item) => item.date).filter(Boolean))]
    .sort()
    .filter((date) => date < currentDate);
  return dates[dates.length - 1] || "";
}

function storeTotals(records) {
  const byStore = new Map();
  records.forEach((item) => {
    const key = item.store || item.store_raw || "未命名门店";
    const current = byStore.get(key) || {
      store: key,
      income: 0,
      orders: 0,
      impressions: 0,
      platforms: new Set(),
    };
    current.income += Number(item.income || 0);
    current.orders += Number(item.orders || 0);
    current.impressions += Number(item.impressions || 0);
    if (item.platform) current.platforms.add(item.platform);
    byStore.set(key, current);
  });
  return [...byStore.values()].map((item) => ({
    ...item,
    platform_count: item.platforms.size,
  }));
}

function groupedAnomalies(items) {
  const grouped = new Map();
  (items || []).forEach((item) => {
    const store = item.store || "未命名门店";
    const entry = grouped.get(store) || { store, high: 0, issues: [] };
    if (item.level === "high") entry.high += 1;
    entry.issues.push(item);
    grouped.set(store, entry);
  });
  return [...grouped.values()].sort((a, b) => b.high - a.high || b.issues.length - a.issues.length);
}

function shortStore(value) {
  return canonicalStoreName(value)
    .replace(/熊小小牛排饭/g, "")
    .replace(/POKEBEAR/g, "")
    .replace(/[（）()]/g, "")
    .replace(/[·]/g, "")
    .slice(0, 18);
}

function canonicalStoreName(value) {
  const text = String(value || "").trim();
  if (/第13档口|熙悦美食城|熙悦|丽泽/.test(text)) return "丽泽门店";
  return text;
}

function compactText(value, maxLength = 110) {
  const textValue = String(value || "").replace(/\s+/g, " ").trim();
  if (textValue.length <= maxLength) return textValue;
  return `${textValue.slice(0, maxLength)}...`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function rows(id, items, render) {
  const el = document.querySelector(`#${id}`);
  if (!el) return;
  el.innerHTML = items.length ? items.map(render).join("") : '<div class="empty-line">暂无数据</div>';
}

const FINANCE_LOCAL_ENTRIES_KEY = "xiong_finance_manual_entries_v1";
const FINANCE_PENDING_UPLOADS_KEY = "xiong_finance_pending_uploads_v1";
const FINANCE_ARAP_ENTRIES_KEY = "xiong_finance_arap_entries_v1";
const FINANCE_OPENING_ENTRIES_KEY = "xiong_finance_opening_entries_v1";
const financeFlowState = {
  payload: null,
};

function readLocalList(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeLocalList(key, value) {
  localStorage.setItem(key, JSON.stringify(value.slice(0, 80)));
}

function financeFileSummary(files) {
  return [...(files || [])].map((file) => `${file.name} ${(file.size / 1024 / 1024).toFixed(1)}MB`).join("、");
}

function financeOpeningTotal(entry) {
  return (
    Number(entry.bank_balance || 0)
    + Number(entry.wechat_balance || 0)
    + Number(entry.alipay_balance || 0)
    + Number(entry.inventory_amount || 0)
    + Number(entry.receivable_amount || 0)
    - Number(entry.payable_amount || 0)
    - Number(entry.third_party_payable_amount || 0)
  );
}

function renderFinanceOpeningEntries(entries = readLocalList(FINANCE_OPENING_ENTRIES_KEY)) {
  rows(
    "financeOpeningRows",
    entries.slice(0, 6),
    (entry) => `
      <div class="good-row">
        <span>${escapeHtml(entry.month || "-")} · 起账 ${escapeHtml(entry.start_date || "-")}</span>
        <strong>${yuan(financeOpeningTotal(entry))}</strong>
        <em>资金 ${yuan(Number(entry.bank_balance || 0) + Number(entry.wechat_balance || 0) + Number(entry.alipay_balance || 0))} · 库存 ${yuan(entry.inventory_amount)} · 应收 ${yuan(entry.receivable_amount)} · 应付 ${yuan(Number(entry.payable_amount || 0) + Number(entry.third_party_payable_amount || 0))}</em>
      </div>
    `
  );
}

async function loadFinanceOpeningEntries() {
  try {
    const response = await fetch(FINANCE_OPENING_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    const items = Array.isArray(result.items) ? result.items : [];
    if (items.length) {
      writeLocalList(FINANCE_OPENING_ENTRIES_KEY, items);
      renderFinanceOpeningEntries(items);
      text("financeOpeningStatus", "已保存");
      text("financeOpeningMessage", "已读取云端最近保存的期初建账记录。");
    } else {
      renderFinanceOpeningEntries();
    }
  } catch {
    renderFinanceOpeningEntries();
  }
}

function initializeFinanceOpeningControls() {
  const form = document.querySelector("#financeOpeningForm");
  if (form && !form.dataset.bound) {
    form.dataset.bound = "true";
    const monthInput = form.querySelector('[name="month"]');
    const startDateInput = form.querySelector('[name="start_date"]');
    if (monthInput && !monthInput.value) monthInput.value = "2026-07";
    if (startDateInput && !startDateInput.value) startDateInput.value = "2026-07-01";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const opening = {
        id: `${Date.now()}`,
        created_at: new Date().toISOString(),
        month: formData.get("month") || "",
        start_date: formData.get("start_date") || "",
        bank_balance: Number(formData.get("bank_balance") || 0),
        wechat_balance: Number(formData.get("wechat_balance") || 0),
        alipay_balance: Number(formData.get("alipay_balance") || 0),
        inventory_amount: Number(formData.get("inventory_amount") || 0),
        receivable_amount: Number(formData.get("receivable_amount") || 0),
        payable_amount: Number(formData.get("payable_amount") || 0),
        third_party_payable_amount: Number(formData.get("third_party_payable_amount") || 0),
        note: formData.get("note") || "",
        sync_status: "local_pending",
      };
      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      const entries = readLocalList(FINANCE_OPENING_ENTRIES_KEY);
      try {
        const response = await fetch(FINANCE_OPENING_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(opening),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        const saved = result.opening || { ...opening, sync_status: "cloud_saved" };
        writeLocalList(FINANCE_OPENING_ENTRIES_KEY, [saved, ...entries]);
        text("financeOpeningStatus", "已保存");
        text("financeOpeningMessage", "期初建账已保存到云端。下一步从起账日期开始导入银行流水。");
        renderFinanceOpeningEntries();
      } catch {
        writeLocalList(FINANCE_OPENING_ENTRIES_KEY, [opening, ...entries]);
        text("financeOpeningStatus", "本页暂存");
        text("financeOpeningMessage", "云端保存暂时失败，已先保存在本页。");
        renderFinanceOpeningEntries();
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }

  const clearButton = document.querySelector("#financeClearOpeningLocal");
  if (clearButton && !clearButton.dataset.bound) {
    clearButton.dataset.bound = "true";
    clearButton.addEventListener("click", () => {
      localStorage.removeItem(FINANCE_OPENING_ENTRIES_KEY);
      text("financeOpeningStatus", "待保存");
      text("financeOpeningMessage", "本页期初记录已清空；云端已保存记录不会被删除。");
      renderFinanceOpeningEntries([]);
    });
  }

  const openingCard = document.querySelector("#finance-opening-card");
  if (openingCard && !openingCard.dataset.loaded) {
    openingCard.dataset.loaded = "true";
    loadFinanceOpeningEntries();
  } else {
    renderFinanceOpeningEntries();
  }
}

function financeFlowMonthValue() {
  const input = document.querySelector("#financeFlowMonth");
  return input?.value || "2026-06";
}

function financeFlowSearchValue() {
  return String(document.querySelector("#financeFlowSearch")?.value || "").trim().toLowerCase();
}

function financeFlowMatches(item, term) {
  if (!term) return true;
  const locations = (item.locations || []).map((entry) => entry.location).join(" ");
  return `${item.lot_id || ""} ${item.product_name || ""} ${item.factory || ""} ${locations}`.toLowerCase().includes(term);
}

const financeFlowSettlementPrices = [
  { sku: "牛五花牛排", spec: "20kg/箱", prices: { 北京直营店: 1316.51, 成都直营店: 1316.51, 北京仓: 1500 } },
  { sku: "嫩肩牛肉", spec: "27.5kg/箱", prices: { 北京直营店: 2255, 成都直营店: 2255, 北京仓: 2420 } },
  { sku: "藤椒牛肉", spec: "28kg/箱", prices: { 北京直营店: 2016, 成都直营店: 2016, 北京仓: 2100 } },
  { sku: "眼肉牛排", spec: "10kg/箱", prices: { 北京直营店: 844.79, 成都直营店: 844.79, 北京仓: 940 } },
  { sku: "板腱牛排", spec: "10kg/箱", prices: { 北京直营店: 923.62, 成都直营店: 923.62, 北京仓: 1040 } },
  { sku: "菲力牛排", spec: "10kg/箱", prices: { 北京直营店: 912.98, 成都直营店: 912.98, 北京仓: 1030 } },
  { sku: "三文鱼块", spec: "10kg/箱", prices: { 北京直营店: 700, 成都直营店: 700, 北京仓: 1060 } },
  { sku: "调理鸡胸肉", spec: "14.4kg/箱", prices: { 北京直营店: 249.12, 成都直营店: 249.12, 北京仓: 288 } },
  { sku: "调理手枪腿", spec: "15kg/箱", prices: { 北京直营店: 253.5, 成都直营店: 253.5, 北京仓: 300 } },
  { sku: "冷冻虾仁", spec: "10kg/箱", prices: { 北京直营店: 515, 成都直营店: 515, 北京仓: 610 } },
  { sku: "拌鱼酱", spec: "10kg/箱", prices: { 北京直营店: 175, 成都直营店: 175, 北京仓: 240 } },
  { sku: "藤椒酱", spec: "10kg/箱", prices: { 北京直营店: 240, 成都直营店: 240, 北京仓: 320 } },
  { sku: "拌饭汁", spec: "10kg/箱", prices: { 北京直营店: 327, 成都直营店: 327, 北京仓: 435 } },
  { sku: "双椒酱", spec: "12kg/箱", prices: { 北京直营店: 276, 成都直营店: 276, 北京仓: 330 } },
  { sku: "寿司调味汁", spec: "10kg/箱", prices: { 北京直营店: 255, 成都直营店: 255, 北京仓: 320 } },
  { sku: "白卡定制餐盒", spec: "300个/箱", prices: { 北京直营店: 108, 成都直营店: 108, 北京仓: 116 } },
  { sku: "玉米淀粉餐盒", spec: "300个/箱", prices: { 北京直营店: 227, 成都直营店: 227, 北京仓: 234 } },
  { sku: "四件套餐具", spec: "800个/袋", prices: { 北京直营店: 158, 成都直营店: 158, 北京仓: 168 } },
  { sku: "无纺布打包袋", spec: "1000个/袋", prices: { 北京直营店: 440, 成都直营店: 440, 北京仓: 460 } },
];

function financeFlowPriceFor(productName, destination) {
  const cleanProduct = String(productName || "").trim();
  const cleanDestination = String(destination || "").trim();
  const row = financeFlowSettlementPrices.find((item) => item.sku === cleanProduct);
  return Number(row?.prices?.[cleanDestination] || 0);
}

function updateFinanceFlowDatalists(payload = financeFlowState.payload || {}) {
  const productList = document.querySelector("#financeFlowProductOptions");
  if (productList) {
    productList.innerHTML = financeFlowSettlementPrices
      .map((item) => `<option value="${escapeHtml(item.sku)}">${escapeHtml(item.spec)}</option>`)
      .join("");
  }
  const lotList = document.querySelector("#financeFlowLotOptions");
  if (lotList) {
    const lots = new Set();
    (payload.items || []).forEach((item) => {
      if (item.lot_id) lots.add(item.lot_id);
      (item.recent_events || []).forEach((event) => {
        if (event.event_type === "生产" && event.date && event.product_name) {
          lots.add(`${String(event.date).replaceAll("-", "")}-${event.product_name}`);
        }
      });
    });
    lotList.innerHTML = [...lots].sort().reverse().map((lot) => `<option value="${escapeHtml(lot)}"></option>`).join("");
  }
}

function generateFinanceFlowLotId(form) {
  const eventType = form?.querySelector('[name="event_type"]')?.value || "";
  const dateValue = form?.querySelector('[name="date"]')?.value || "";
  const productName = form?.querySelector('[name="product_name"]')?.value || "";
  const lotField = form?.querySelector('[name="lot_id"]');
  if (!lotField || eventType !== "生产" || !dateValue || !productName) return;
  lotField.value = `${dateValue.replaceAll("-", "")}-${productName}`;
}

function updateFinanceFlowCalculatedAmounts(form) {
  if (!form) return { amount: 0, unitPrice: 0 };
  const eventType = form.querySelector('[name="event_type"]')?.value || "";
  const productName = form.querySelector('[name="product_name"]')?.value || "";
  const destination = form.querySelector('[name="to_location"]')?.value || "";
  const quantity = Number(form.querySelector('[name="quantity"]')?.value || 0);
  const paymentStatus = form.querySelector('[name="payment_status"]')?.value || "应付";
  const unitPrice = financeFlowPriceFor(productName, destination);
  const amount = unitPrice && quantity > 0 ? Number((quantity * unitPrice).toFixed(2)) : 0;
  const payableField = form.querySelector('[name="payable_amount"]');
  const paidField = form.querySelector('[name="paid_amount"]');
  const receivableField = form.querySelector('[name="receivable_amount"]');
  const settlementField = form.querySelector('[name="settlement_status"]');
  const unitPriceField = form.querySelector('[name="unit_price"]');
  if (payableField) payableField.value = "0";
  if (paidField) paidField.value = "0";
  if (receivableField) receivableField.value = "0";
  if (unitPriceField) unitPriceField.value = String(unitPrice || 0);
  if (settlementField) settlementField.value = paymentStatus === "已付" ? "已结算" : "批次用完结算";
  if (eventType === "销售" && destination === "北京仓") {
    if (receivableField) receivableField.value = String(amount);
  } else if (paymentStatus === "已付") {
    if (paidField) paidField.value = String(amount);
  } else {
    if (payableField) payableField.value = String(amount);
  }
  return { amount, unitPrice };
}

const financeFlowPresets = {
  production: {
    event_type: "生产",
    product_name: "牛五花牛排",
    unit: "件",
    from_location: "",
    to_location: "工厂暂存",
    payment_status: "应付",
    counterparty: "牛五花牛排工厂",
    note: "工厂生产完成，货权暂存工厂，批次用完后结算应付。",
  },
  warehouse_sale: {
    event_type: "销售",
    product_name: "牛五花牛排",
    unit: "件",
    from_location: "工厂暂存",
    to_location: "北京仓",
    payment_status: "应付",
    counterparty: "北京仓",
    note: "发给北京仓，形成供应链应收。",
  },
  direct_store: {
    event_type: "领用",
    product_name: "牛五花牛排",
    unit: "件",
    from_location: "工厂暂存",
    to_location: "北京直营店",
    payment_status: "应付",
    counterparty: "北京直营店",
    note: "发给北京直营店，作为门店领用/成本归集。",
  },
};

function applyFinanceFlowPreset(form, presetKey) {
  const preset = financeFlowPresets[presetKey];
  if (!form || !preset) return;
  Object.entries(preset).forEach(([name, value]) => {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.value = value;
  });
  if (presetKey === "production") generateFinanceFlowLotId(form);
  updateFinanceFlowCalculatedAmounts(form);
}

function renderFinanceFlow() {
  const payload = financeFlowState.payload || {};
  updateFinanceFlowDatalists(payload);
  const term = financeFlowSearchValue();
  const items = (payload.items || []).filter((item) => financeFlowMatches(item, term));
  const totals = payload.totals || {};
  text("financeFlowStatus", payload.items ? `${items.length} 个批次` : "待读取");
  html(
    "financeFlowKpis",
    [
      { label: "采购批次", value: `${Number(totals.lot_count || 0)} 批`, detail: "按采购批次或采购单号追踪" },
      { label: "供应链应付", value: yuan(totals.payable_amount), detail: `未结算 ${yuan(totals.open_payable_amount)}` },
      { label: "供应链应收", value: yuan(totals.receivable_amount), detail: `未收 ${yuan(totals.open_receivable_amount)}` },
      { label: "已结算付款", value: yuan(totals.paid_amount), detail: "批次用完后结算付款" },
    ].map((item) => `
      <article>
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        <em>${escapeHtml(item.detail)}</em>
      </article>
    `).join("")
  );
  rows(
    "financeFlowRows",
    items.slice(0, 40),
    (item) => {
      const locations = (item.locations || []).length
        ? item.locations.map((entry) => `${entry.location} ${num(entry.quantity, 2)}${item.unit || ""}`).join(" / ")
        : "暂无位置余额";
      const purchased = Number(item.purchase_quantity || 0);
      const outbound = Number(item.out_quantity || 0);
      const balance = Number(item.balance_quantity || 0);
      const rowClass = balance < 0 ? "warn-row" : "good-row";
      const money = `应付 ${yuan(item.payable_amount)} / 已结 ${yuan(item.paid_amount)} / 应收 ${yuan(item.receivable_amount)}`;
      return `
        <div class="${rowClass}">
          <span>${escapeHtml(item.lot_id || "-")} · ${escapeHtml(item.product_name || "-")}</span>
          <strong>购 ${num(purchased, 2)} / 出 ${num(outbound, 2)} / 余 ${num(balance, 2)}${escapeHtml(item.unit || "")}</strong>
          <em>${escapeHtml(locations)}${item.factory ? ` · ${escapeHtml(item.factory)}` : ""} · ${escapeHtml(money)}</em>
        </div>
      `;
    }
  );
  rows(
    "financeFlowLocationRows",
    payload.locations || [],
    (entry) => `
      <div class="good-row">
        <span>${escapeHtml(entry.location || "未指定位置")}</span>
        <strong>${num(entry.quantity, 2)}</strong>
        <em>所有采购批次当前位置合计</em>
      </div>
    `
  );
  rows(
    "financeFlowMovementRows",
    (payload.recent_events || []).slice(0, 16),
    (item) => `
      <div class="${["生产", "采购", "调拨"].includes(item.event_type) ? "good-row" : "warn-row"}">
        <span>${escapeHtml(item.date || "-")} · ${escapeHtml(item.event_type || "-")} · ${escapeHtml(item.lot_id || "-")}</span>
        <strong>${escapeHtml(item.product_name || "-")} ${num(item.quantity, 2)}${escapeHtml(item.unit || "")}</strong>
        <em>${escapeHtml([item.from_location, item.to_location].filter(Boolean).join(" -> ") || item.counterparty || item.note || "")}${item.receivable_amount ? ` · 应收 ${yuan(item.receivable_amount)}` : ""}${item.payable_amount ? ` · 应付 ${yuan(item.payable_amount)}` : ""}</em>
      </div>
    `
  );
}

async function loadFinanceFlow() {
  text("financeFlowStatus", "读取中");
  try {
    const flowResponse = await fetch(SUPPLY_CHAIN_FLOW_URL);
    if (!flowResponse.ok) throw new Error(`inventory ${flowResponse.status}`);
    financeFlowState.payload = await flowResponse.json();
    renderFinanceFlow();
  } catch {
    financeFlowState.payload = { items: [], recent_events: [], locations: [], totals: {} };
    text("financeFlowStatus", "读取失败");
    renderFinanceFlow();
  }
}

function initializeFinanceFlowControls() {
  const card = document.querySelector("#finance-flow-card");
  if (!card) return;
  const monthInput = document.querySelector("#financeFlowMonth");
  if (monthInput && !monthInput.value) monthInput.value = "2026-06";
  if (!card.dataset.bound) {
    card.dataset.bound = "true";
    document.querySelector("#financeFlowRefresh")?.addEventListener("click", loadFinanceFlow);
    monthInput?.addEventListener("change", loadFinanceFlow);
    document.querySelector("#financeFlowSearch")?.addEventListener("input", renderFinanceFlow);
    const form = document.querySelector("#financeFlowEntryForm");
    const dateInput = form?.querySelector('[name="date"]');
    if (dateInput && !dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
    updateFinanceFlowDatalists();
    updateFinanceFlowCalculatedAmounts(form);
    form?.querySelectorAll("[data-flow-preset]").forEach((button) => {
      button.addEventListener("click", () => applyFinanceFlowPreset(form, button.dataset.flowPreset));
    });
    form?.querySelectorAll('[name="date"], [name="event_type"], [name="product_name"], [name="quantity"], [name="to_location"], [name="payment_status"]').forEach((field) => {
      field.addEventListener("input", () => {
        generateFinanceFlowLotId(form);
        updateFinanceFlowCalculatedAmounts(form);
      });
      field.addEventListener("change", () => {
        generateFinanceFlowLotId(form);
        updateFinanceFlowCalculatedAmounts(form);
      });
    });
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      generateFinanceFlowLotId(form);
      updateFinanceFlowCalculatedAmounts(form);
      const formData = new FormData(form);
      const entry = {
        id: `${Date.now()}`,
        date: formData.get("date") || "",
        event_type: formData.get("event_type") || "",
        lot_id: formData.get("lot_id") || "",
        product_name: formData.get("product_name") || "",
        factory: "",
        quantity: Number(formData.get("quantity") || 0),
        unit: formData.get("unit") || "",
        from_location: formData.get("from_location") || "",
        to_location: formData.get("to_location") || "",
        payable_amount: Number(formData.get("payable_amount") || 0),
        paid_amount: Number(formData.get("paid_amount") || 0),
        receivable_amount: Number(formData.get("receivable_amount") || 0),
        settlement_status: formData.get("settlement_status") || "",
        unit_cost: Number(formData.get("unit_price") || 0),
        counterparty: formData.get("counterparty") || "",
        note: formData.get("note") || "",
      };
      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      text("financeFlowEntryMessage", "正在保存货权流向...");
      try {
        const response = await fetch(SUPPLY_CHAIN_FLOW_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
        financeFlowState.payload = result.summary || financeFlowState.payload;
        text("financeFlowEntryMessage", "已保存到云端货权流向台账。");
        form.reset();
        if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);
        const unitInput = form.querySelector('[name="unit"]');
        if (unitInput) unitInput.value = "件";
        const paymentInput = form.querySelector('[name="payment_status"]');
        if (paymentInput) paymentInput.value = "应付";
        updateFinanceFlowDatalists(financeFlowState.payload);
        updateFinanceFlowCalculatedAmounts(form);
        renderFinanceFlow();
      } catch (error) {
        text("financeFlowEntryMessage", error.message || "云端保存失败，请稍后重试。");
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }
  if (!card.dataset.loaded) {
    card.dataset.loaded = "true";
    loadFinanceFlow();
  } else {
    renderFinanceFlow();
  }
}

function renderFinanceRecentEntries() {
  const entries = readLocalList(FINANCE_LOCAL_ENTRIES_KEY);
  rows(
    "financeRecentEntries",
    entries.slice(0, 8),
    (entry) => `
      <div class="good-row">
        <span>${escapeHtml(entry.date || "-")} · ${escapeHtml(entry.ledger || "-")}</span>
        <strong>${escapeHtml(entry.direction || "")} ${yuan(entry.amount)}</strong>
        <em>${escapeHtml(entry.channel || "")}${entry.counterparty ? ` · ${escapeHtml(entry.counterparty)}` : ""}${entry.files ? ` · 凭证 ${escapeHtml(entry.files)}` : ""}</em>
      </div>
    `
  );
}

function initializeFinanceIntakeControls() {
  const form = document.querySelector("#financeManualEntryForm");
  if (form && !form.dataset.bound) {
    form.dataset.bound = "true";
    const dateInput = form.querySelector("#financeEntryDate");
    if (dateInput && !dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const entry = {
        id: `${Date.now()}`,
        created_at: new Date().toISOString(),
        date: formData.get("date") || "",
        ledger: formData.get("ledger") || "",
        direction: formData.get("direction") || "",
        amount: Number(formData.get("amount") || 0),
        channel: formData.get("channel") || "",
        counterparty: formData.get("counterparty") || "",
        account: formData.get("account") || "",
        note: formData.get("note") || "",
        files: financeFileSummary(form.querySelector('[name="attachments"]')?.files || []),
        sync_status: "local_pending",
      };
      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      const entries = readLocalList(FINANCE_LOCAL_ENTRIES_KEY);
      try {
        const response = await fetch(FINANCE_ENTRY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        writeLocalList(FINANCE_LOCAL_ENTRIES_KEY, [result.entry || { ...entry, sync_status: "cloud_saved" }, ...entries]);
        text("financeManualEntryMessage", "已保存到云端财务录入记录。");
        form.reset();
        if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);
        renderFinanceRecentEntries();
      } catch {
        writeLocalList(FINANCE_LOCAL_ENTRIES_KEY, [entry, ...entries]);
        text("financeManualEntryMessage", "云端保存暂时失败，已先保存在本页待同步记录。");
        renderFinanceRecentEntries();
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }

  const clearButton = document.querySelector("#financeClearLocalEntries");
  if (clearButton && !clearButton.dataset.bound) {
    clearButton.dataset.bound = "true";
    clearButton.addEventListener("click", () => {
      localStorage.removeItem(FINANCE_LOCAL_ENTRIES_KEY);
      text("financeManualEntryMessage", "本页最近录入已清空。");
      renderFinanceRecentEntries();
    });
  }

  document.querySelectorAll(".finance-source-file").forEach((input) => {
    if (input.dataset.bound) return;
    input.dataset.bound = "true";
    input.addEventListener("change", () => {
      const card = input.closest(".finance-entry-card");
      const status = card?.querySelector(".finance-upload-status");
      if (status) status.textContent = input.files?.length ? `已选择 ${input.files.length} 个文件` : "未选择文件";
    });
  });

  document.querySelectorAll(".finance-upload-button").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", async () => {
      const card = button.closest(".finance-entry-card");
      const input = card?.querySelector(".finance-source-file");
      const status = card?.querySelector(".finance-upload-status");
      const files = [...(input?.files || [])];
      if (!files.length) {
        if (status) status.textContent = "请先选择文件。";
        return;
      }
      button.disabled = true;
      if (status) status.textContent = "正在尝试上传...";
      const sourceId = button.dataset.sourceId || "unknown";
      const sourceName = button.dataset.sourceName || sourceId;
      const payload = new FormData();
      payload.append("source_id", sourceId);
      payload.append("source_name", sourceName);
      files.forEach((file) => payload.append("files", file, file.name));
      try {
        const response = await fetch(FINANCE_UPLOAD_URL, { method: "POST", body: payload });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (status) status.textContent = "上传成功，稍后刷新财务状态。";
      } catch {
        const pending = readLocalList(FINANCE_PENDING_UPLOADS_KEY);
        writeLocalList(FINANCE_PENDING_UPLOADS_KEY, [
          {
            id: `${Date.now()}`,
            source_id: sourceId,
            source_name: sourceName,
            files: files.map((file) => ({ name: file.name, size: file.size })),
            created_at: new Date().toISOString(),
            sync_status: "api_pending",
          },
          ...pending,
        ]);
        if (status) status.textContent = "云端上传接口暂未接通，已先登记文件名。";
      } finally {
        button.disabled = false;
      }
    });
  });

  renderFinanceRecentEntries();
}

const financeArapActions = {
  receivable_add: {
    title: "新增应收",
    ledger: "供应链账",
    direction: "应收",
    channel: "应收账款",
    account: "未收款",
    counterpartyLabel: "客户",
    note: "登记客户欠款，收款时再核销应收。",
  },
  receivable_settle: {
    title: "核销收款",
    ledger: "供应链账",
    direction: "核销收款",
    channel: "应收账款",
    account: "银行卡",
    counterpartyLabel: "客户",
    note: "收到款项后冲减应收，不重复计收入。",
  },
  payable_add: {
    title: "新增应付",
    ledger: "门店总账",
    direction: "应付",
    channel: "应付账款",
    account: "未付款",
    counterpartyLabel: "供应商",
    note: "登记已发生但未支付的采购或费用。",
  },
  payable_settle: {
    title: "核销付款",
    ledger: "门店总账",
    direction: "核销付款",
    channel: "应付账款",
    account: "银行卡",
    counterpartyLabel: "供应商",
    note: "付款后冲减应付，不重复计成本费用。",
  },
};

function ensureFinanceArapModal() {
  let modal = document.querySelector("#financeArapModal");
  if (modal) return modal;
  document.body.insertAdjacentHTML(
    "beforeend",
    `
      <div class="finance-arap-modal" id="financeArapModal" hidden>
        <form class="finance-arap-dialog" id="financeArapForm">
          <div class="finance-arap-dialog-head">
            <div>
              <span id="financeArapFormEyebrow">应收应付</span>
              <strong id="financeArapFormTitle">新增记录</strong>
            </div>
            <button type="button" class="finance-arap-close" id="financeArapClose" aria-label="关闭">×</button>
          </div>
          <div class="finance-arap-form-grid">
            <label>
              <span>日期</span>
              <input name="date" type="date" required />
            </label>
            <label>
              <span>账本</span>
              <select name="ledger" required>
                <option value="门店总账">门店总账</option>
                <option value="供应链账">供应链账</option>
              </select>
            </label>
            <label>
              <span>金额</span>
              <input name="amount" type="number" min="0" step="0.01" placeholder="0.00" required />
            </label>
            <label>
              <span id="financeArapCounterpartyLabel">往来方</span>
              <input name="counterparty" type="text" placeholder="客户或供应商" required />
            </label>
            <label class="finance-arap-wide">
              <span>备注</span>
              <textarea name="note" rows="2" placeholder="例如：对应哪笔采购、哪张发票、哪次收款"></textarea>
            </label>
          </div>
          <input name="direction" type="hidden" />
          <input name="channel" type="hidden" />
          <input name="account" type="hidden" />
          <div class="finance-arap-dialog-foot">
            <em id="financeArapFormHint">保存后进入云端财务记录。</em>
            <button type="submit">保存</button>
          </div>
        </form>
      </div>
    `
  );
  modal = document.querySelector("#financeArapModal");
  modal.querySelector("#financeArapClose")?.addEventListener("click", () => {
    modal.hidden = true;
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) modal.hidden = true;
  });
  return modal;
}

function renderFinanceArapEntries() {
  const entries = readLocalList(FINANCE_ARAP_ENTRIES_KEY);
  const receivables = entries.filter((entry) => ["应收", "核销收款"].includes(entry.direction));
  const payables = entries.filter((entry) => ["应付", "核销付款"].includes(entry.direction));
  rows(
    "financeReceivableRows",
    [
      ...receivables.slice(0, 8).map((entry) => ({
        label: `${entry.date || "-"} · ${entry.direction}`,
        value: `${entry.counterparty || "未填客户"} ${yuan(entry.amount)}`,
        detail: entry.note || (entry.direction === "应收" ? "客户欠款登记" : "收款核销"),
      })),
      ...(!receivables.length ? [
        { label: "新增应收", value: "供应链销售客户欠款", detail: "业务发生时确认收入并形成应收，收款时只核销应收，不重复计收入。" },
        { label: "核销收款", value: "冲减应收", detail: "银行或微信到账后，选择对应应收记录核销。" },
      ] : []),
    ],
    (item) => `<div class="good-row"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
  rows(
    "financePayableRows",
    [
      ...payables.slice(0, 8).map((entry) => ({
        label: `${entry.date || "-"} · ${entry.direction}`,
        value: `${entry.counterparty || "未填供应商"} ${yuan(entry.amount)}`,
        detail: entry.note || (entry.direction === "应付" ? "供应商欠款登记" : "付款核销"),
      })),
      ...(!payables.length ? [
        { label: "新增应付", value: "供应商欠款", detail: "采购或费用发生但未付款时登记应付。" },
        { label: "核销付款", value: "冲减应付", detail: "付款时只冲应付，不重复计成本费用。" },
      ] : []),
    ],
    (item) => `<div class="good-row"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

function initializeFinanceArapControls() {
  document.querySelectorAll("[data-finance-arap-action]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const config = financeArapActions[button.dataset.financeArapAction || ""];
      if (!config) return;
      const modal = ensureFinanceArapModal();
      const form = modal.querySelector("#financeArapForm");
      form.reset();
      form.dataset.action = button.dataset.financeArapAction || "";
      form.elements.date.value = new Date().toISOString().slice(0, 10);
      form.elements.ledger.value = config.ledger;
      form.elements.direction.value = config.direction;
      form.elements.channel.value = config.channel;
      form.elements.account.value = config.account;
      text("financeArapFormTitle", config.title);
      text("financeArapCounterpartyLabel", config.counterpartyLabel);
      text("financeArapFormHint", config.note);
      modal.hidden = false;
    });
  });

  const modal = ensureFinanceArapModal();
  const form = modal.querySelector("#financeArapForm");
  if (form && !form.dataset.bound) {
    form.dataset.bound = "true";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const entry = {
        id: `${Date.now()}`,
        created_at: new Date().toISOString(),
        date: formData.get("date") || "",
        ledger: formData.get("ledger") || "",
        direction: formData.get("direction") || "",
        amount: Number(formData.get("amount") || 0),
        channel: formData.get("channel") || "",
        counterparty: formData.get("counterparty") || "",
        account: formData.get("account") || "",
        note: formData.get("note") || "",
        files: "",
        sync_status: "local_pending",
      };
      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      const arapEntries = readLocalList(FINANCE_ARAP_ENTRIES_KEY);
      try {
        const response = await fetch(FINANCE_ENTRY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        const saved = result.entry || { ...entry, sync_status: "cloud_saved" };
        writeLocalList(FINANCE_ARAP_ENTRIES_KEY, [saved, ...arapEntries]);
        const manualEntries = readLocalList(FINANCE_LOCAL_ENTRIES_KEY);
        writeLocalList(FINANCE_LOCAL_ENTRIES_KEY, [saved, ...manualEntries]);
        renderFinanceArapEntries();
        renderFinanceRecentEntries();
        modal.hidden = true;
      } catch {
        writeLocalList(FINANCE_ARAP_ENTRIES_KEY, [entry, ...arapEntries]);
        renderFinanceArapEntries();
        modal.hidden = true;
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }
  renderFinanceArapEntries();
}

function financeReviewKey(item) {
  return [
    item.source || "",
    item.time || item.transaction_time || item.transaction_date || "",
    item.amount || "",
    item.counterparty || "",
    item.description || "",
  ].join("|");
}

function initializeFinanceReviewControls() {
  document.querySelectorAll(".finance-review-confirm").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", async () => {
      const row = button.closest(".finance-review-card");
      const status = row?.querySelector(".finance-review-confirm-status");
      const ledger = row?.querySelector('[name="review_ledger"]')?.value || "";
      const channel = row?.querySelector('[name="review_channel"]')?.value || "";
      const note = row?.querySelector('[name="review_note"]')?.value || "";
      const amount = Number(button.dataset.amount || 0);
      const direction = button.dataset.direction || (amount >= 0 ? "收入" : "支出");
      const entry = {
        id: `${Date.now()}-${button.dataset.index || "0"}`,
        created_at: new Date().toISOString(),
        date: button.dataset.date || new Date().toISOString().slice(0, 10),
        ledger,
        direction: "确认流水",
        amount: Math.abs(amount),
        channel,
        counterparty: button.dataset.counterparty || "",
        account: button.dataset.source || "银行流水",
        note: `${direction} ${amount >= 0 ? "+" : "-"}${yuan(Math.abs(amount))}；原摘要：${button.dataset.description || ""}${note ? `；确认备注：${note}` : ""}`,
        files: "",
        sync_status: "local_pending",
        review_key: button.dataset.reviewKey || "",
      };
      if (!ledger || !channel) {
        if (status) status.textContent = "请选择账本和渠道。";
        return;
      }
      button.disabled = true;
      if (status) status.textContent = "正在保存...";
      const entries = readLocalList(FINANCE_LOCAL_ENTRIES_KEY);
      try {
        const response = await fetch(FINANCE_ENTRY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        writeLocalList(FINANCE_LOCAL_ENTRIES_KEY, [result.entry || { ...entry, sync_status: "cloud_saved" }, ...entries]);
        row?.classList.add("confirmed");
        if (status) status.textContent = "已保存确认记录。";
        button.textContent = "已确认";
        renderFinanceRecentEntries();
      } catch {
        writeLocalList(FINANCE_LOCAL_ENTRIES_KEY, [entry, ...entries]);
        if (status) status.textContent = "云端暂未保存，已先记在本页。";
      } finally {
        button.disabled = false;
      }
    });
  });
}

function realtimeStores(daily) {
  const realtime = data.realtime || {};
  const directStores = realtime.stores || realtime.store_summary || realtime.items;
  if (Array.isArray(directStores) && directStores.length) return directStores;
  return daily.store_summary || storeTotals(latestDailyRows(daily));
}

function realtimeStoreIncome(item) {
  return Number(item.income ?? item.total_income ?? item.amount ?? 0);
}

function realtimeStoreOrders(item) {
  return Number(item.orders ?? item.total_orders ?? 0);
}

function realtimePlatformMetrics(item) {
  const platforms = item.platforms || {};
  const eleme = platforms["饿了么"] || item.eleme || {};
  const meituan = platforms["美团"] || item.meituan || {};
  return [
    {
      key: "eleme",
      name: "饿了么",
      orders: Number(item.eleme_orders ?? eleme.orders ?? 0),
      income: Number(item.eleme_income ?? eleme.income ?? 0),
    },
    {
      key: "meituan",
      name: "美团",
      orders: Number(item.meituan_orders ?? meituan.orders ?? 0),
      income: Number(item.meituan_income ?? meituan.income ?? 0),
    },
  ];
}

function realtimeStoreDetail(item) {
  const parts = realtimePlatformMetrics(item)
    .filter((platform) => platform.orders || platform.income)
    .map((platform) => `${platform.name} ${num(platform.orders)} 单 / ${yuan(platform.income)}`);
  return parts.join(" · ") || "等待平台拆分";
}

function renderRealtimePlatformRows(item) {
  const activePlatforms = realtimePlatformMetrics(item).filter((platform) => platform.orders || platform.income);
  if (!activePlatforms.length) return '<div class="platform-empty">等待平台拆分</div>';
  return activePlatforms
    .map(
      (platform) => `
        <div class="platform-row platform-${platform.key}">
          <span>${platform.name}</span>
          <div class="platform-figures">
            <strong>${yuan(platform.income)}</strong>
            <em>${num(platform.orders)} 单</em>
          </div>
        </div>`
    )
    .join("");
}

function dailyStoreCards(records) {
  const byStore = new Map();
  records.forEach((item) => {
    const store = item.store || item.store_raw || "未命名门店";
    const row = byStore.get(store) || { store, income: 0, orders: 0, platforms: [] };
    const platform = item.platform || "平台";
    const income = Number(item.income || 0);
    const orders = Number(item.orders || 0);
    row.income += income;
    row.orders += orders;
    row.platforms.push({
      name: platform,
      key: platform.includes("饿") ? "eleme" : platform.includes("美") ? "meituan" : "other",
      income,
      orders,
    });
    byStore.set(store, row);
  });
  return [...byStore.values()]
    .sort((a, b) => Number(b.income || 0) - Number(a.income || 0));
}

function renderOverviewDailyStoreCards(records) {
  const el = document.querySelector("#overviewDailyStoreCards");
  if (!el) return;
  const stores = dailyStoreCards(records);
  if (!stores.length) {
    el.innerHTML = '<div class="empty-line">暂无日报门店数据</div>';
    return;
  }
  el.innerHTML = stores.map((store) => `
    <div class="overview-daily-store">
      <div class="overview-daily-store-head">
        <strong>${escapeHtml(shortStore(store.store))}</strong>
        <em>${yuan(store.income)} / ${num(store.orders)} 单</em>
      </div>
      <div class="overview-daily-platforms">
        ${store.platforms
          .sort((a, b) => Number(b.income || 0) - Number(a.income || 0))
          .map((platform) => `
            <div class="overview-daily-platform platform-${platform.key}">
              <span>${escapeHtml(platform.name)}</span>
              <strong>${yuan(platform.income)} / ${num(platform.orders)} 单</strong>
            </div>
          `).join("")}
      </div>
    </div>
  `).join("");
}

function realtimeStoreCompare(item, compareMap) {
  const store = item.store || item.store_name || item.name || "未命名门店";
  const previous = compareMap.get(store);
  if (!previous) return data.realtime_comparison?.message || "昨日暂无可用历史数据";
  const baseTime = data.realtime_comparison?.matched_time ? data.realtime_comparison.matched_time.slice(11, 16) : "";
  const prefix = baseTime ? `较昨日基准 ${baseTime}` : "较昨日基准";
  if (previous.orders) {
    const orders = previous.orders || {};
    return `${prefix} ${signedNumber(orders.delta)} 单`;
  }
  const incomeDelta = Number(previous.income_delta ?? realtimeStoreIncome(item) - Number(previous.income || 0));
  const orderDelta = Number(previous.orders_delta ?? realtimeStoreOrders(item) - Number(previous.orders || 0));
  const moneyText = `${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}`;
  const orderText = `${orderDelta >= 0 ? "+" : "-"}${num(Math.abs(orderDelta))} 单`;
  return `${prefix} ${moneyText} / ${orderText}`;
}

function realtimeStoreCompareDelta(item, compareMap) {
  const store = item.store || item.store_name || item.name || "未命名门店";
  const previous = compareMap.get(store);
  if (!previous) return 0;
  if (previous.orders) return Number(previous.orders.delta || 0);
  return Number(previous.orders_delta ?? realtimeStoreOrders(item) - Number(previous.orders || 0));
}

function renderRealtimeCard(daily, stores, totalIncome, totalOrders) {
  const realtime = data.realtime || {};
  const realtimeComparison = data.realtime_comparison || {};
  const realtimeCollection = data.realtime_collection || {};
  const summary = realtime.summary || {};
  const sourceStores = realtimeStores(daily);
  const compareMap = yesterdayStoreMap(daily);
  const covered = sourceStores.filter((item) => realtimeStoreOrders(item) || realtimeStoreIncome(item)).length;
  const platformCoverage = Number(summary.platform_store_count || 0);
  const platformTarget = platformCoverage || summary.missing_count !== undefined ? platformCoverage + Number(summary.missing_count || 0) : 0;
  const targetCount = Number(realtime.target_count ?? daily.target_stores?.length ?? sourceStores.length);
  const missing = Number(summary.missing_count ?? Math.max(0, targetCount - covered));
  const generatedAt = realtimeCollection.last_success_at || realtime.generated_at || realtime.collected_at || data.generated_at || "-";
  const collectionStatus = realtimeCollection.status || realtime.status;
  const collectionIssue = realtimeCollection.message || "";
  const realtimeFailures = realtimeCollection.platform_failures || [];
  const failedPlatformStoreCount = Number(realtimeCollection.summary?.failed_platform_store_count || 0);
  const comparisonBaseText = realtimeComparison?.matched_time_label
    ? `对比基准：${realtimeComparison.matched_time_label}。`
    : "";
  const realtimeStatusText = collectionStatus === "stale"
    ? "偏旧"
    : collectionStatus === "failed_after_success"
      ? "最近失败"
      : collectionStatus === "ok" || realtime.status === "ready" || sourceStores.length
        ? "已同步"
        : "待采集";

  text("realtimeIncome", yuan(totalIncome));
  text("realtimeOrders", `${num(totalOrders)} 单`);
  text("realtimeCompare", comparisonLabel(totalIncome, totalOrders, sameTimeYesterday(daily)).replace(/^较/, ""));
  document.querySelector("#realtimeCompare")?.classList.remove("trend-up", "trend-down", "trend-flat");
  document.querySelector("#realtimeCompare")?.classList.add(trendClass(Number(realtimeComparison?.summary?.orders?.delta || 0)));
  text("realtimeCoverage", platformTarget ? `${platformCoverage}/${platformTarget}` : `${covered}/${targetCount || sourceStores.length || 0}`);
  text("realtimeStatus", realtimeStatusText);
  text("realtimeMeta", `最近成功：${generatedAt}，覆盖 ${covered || 0} 家门店，当前缺失 ${missing} 个平台门店，最近失败缺失 ${failedPlatformStoreCount} 个。${comparisonBaseText}${collectionIssue && collectionStatus !== "ok" ? ` ${collectionIssue}` : ""}`);
  document.querySelector("#realtime")?.classList.toggle("alert", ["stale", "failed_after_success", "partial", "missing_latest"].includes(collectionStatus));

  rows(
    "realtimeStoreRows",
    [
      ...realtimeFailures.map((item) => ({ ...item, kind: "platform_failure" })),
      ...sourceStores
        .slice()
        .sort((a, b) => realtimeStoreIncome(b) - realtimeStoreIncome(a))
        .slice(0, 8)
        .map((item) => ({ ...item, kind: "store" })),
    ],
    (item) => {
      if (item.kind === "platform_failure") {
        const stores = (item.stores || []).slice(0, 4).join("、");
        const storeText = stores ? `${stores}${(item.stores || []).length > 4 ? "等" : ""}` : "待确认";
        const storeActions = (item.store_recovery_actions || [])
          .slice(0, 3)
          .map((action) => `${action.store}：${action.human_action}`)
          .join("；");
        const guide = (realtimeCollection.repair_guides || []).find((entry) => entry.platform === item.platform && entry.failure_type === item.failure_type);
        const guideText = guide ? `向导：${guide.title}，${(guide.checklist || [])[0] || guide.verify_command || ""}` : "";
        const detail = [item.message || storeText, guideText, item.recovery_summary || item.human_action || "先处理平台状态后重跑实时采集。", storeActions]
          .filter(Boolean)
          .map((part) => escapeHtml(part))
          .join("<br>");
        return `
        <div class="realtime-store realtime-store-alert">
          <div class="realtime-store-head">
            <span>${escapeHtml(item.platform)}采集失败</span>
            <em class="realtime-compare">${escapeHtml(item.failure_type || "需处理")}</em>
          </div>
          <div class="realtime-primary">
            <div>
              <span>缺失</span>
              <strong>${num(item.missing_count || 0)} 个门店</strong>
            </div>
            <em>${detail}</em>
          </div>
        </div>`;
      }
      const store = item.store || item.store_name || item.name || "未命名门店";
      const compareDelta = realtimeStoreCompareDelta(item, compareMap);
      return `
        <div class="realtime-store">
          <div class="realtime-store-head">
            <span>${escapeHtml(store)}</span>
            <em class="realtime-compare ${trendClass(compareDelta)}">${escapeHtml(realtimeStoreCompare(item, compareMap))}</em>
          </div>
          <div class="realtime-primary">
            <div>
              <span>收入</span>
              <strong>${yuan(realtimeStoreIncome(item))}</strong>
            </div>
            <div>
              <span>单量</span>
              <strong>${num(realtimeStoreOrders(item))} 单</strong>
            </div>
          </div>
          <div class="platform-breakdown">${renderRealtimePlatformRows(item)}</div>
        </div>`;
    }
  );
}

function renderDaily() {
  const daily = data.daily || {};
  const dailyTrends = data.daily_trends || {};
  const realtime = data.realtime || {};
  const realtimeSummary = realtime.summary || {};
  const latestDate = latestDailyDate(daily);
  const latestRecords = latestDailyRows(daily);
  const previousDate = previousDailyDate(daily, latestDate);
  const previousRecords = previousDate ? dailyRowsByDate(daily, previousDate) : [];
  const stores = storeTotals(latestRecords);
  const platforms = daily.platform_summary || [];
  const focusItems = daily.focus_items || [];
  const highFocusCount = focusItems.filter((item) => item.level === "high").length;
  const dailyIncome = latestRecords.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const dailyOrders = latestRecords.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const previousIncome = previousRecords.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const previousOrders = previousRecords.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const orderDelta = dailyOrders - previousOrders;
  const incomeDelta = dailyIncome - previousIncome;
  const dailyImpressions = latestRecords.reduce((sum, item) => sum + Number(item.impressions || 0), 0);
  const orderConversionRows = latestRecords.filter((item) => Number(item.order_conversion || 0));
  const avgOrderConversion = orderConversionRows.length
    ? orderConversionRows.reduce((sum, item) => sum + Number(item.order_conversion || 0), 0) / orderConversionRows.length
    : 0;
  const totalIncome = Number(realtime.income ?? realtime.total_income ?? realtimeSummary.total_income ?? dailyIncome);
  const totalOrders = Number(realtime.orders ?? realtime.total_orders ?? realtimeSummary.total_orders ?? dailyOrders);
  text("metricIncomeLabel", "实时数据");
  text("metricIncome", yuan(totalIncome));
  text("metricOrders", `实时单量 ${num(totalOrders)} 单`);
  text("metricYesterdayCompare", comparisonLabel(totalIncome, totalOrders, sameTimeYesterday(daily)));
  renderRealtimeCard(daily, stores, totalIncome, totalOrders);
  text("briefOrders", `${num(dailyOrders)} 单`);
  text("briefIncome", yuan(dailyIncome));
  const orderCompareEl = document.querySelector("#briefOrdersCompare");
  const incomeCompareEl = document.querySelector("#briefIncomeCompare");
  if (orderCompareEl) {
    orderCompareEl.textContent = previousDate ? `较前日 ${signedNumber(orderDelta)} 单` : "较前日 暂无";
    orderCompareEl.className = trendClass(orderDelta);
  }
  if (incomeCompareEl) {
    incomeCompareEl.textContent = previousDate ? `较前日 ${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}` : "较前日 暂无";
    incomeCompareEl.className = trendClass(incomeDelta);
  }
  text("dailyStoreCount", `${stores.length || 0} 家`);
  text("dailySummary", `只看最新日报日期 ${latestDate || "-"}：总收入 ${yuan(dailyIncome)}，总单量 ${num(dailyOrders)} 单，覆盖 ${stores.length || 0} 家门店。`);
  renderOverviewDailyStoreCards(latestRecords);
  text("dailyPageSummary", `已直接接入完整经营日报。上方 AI 周分析结合近 7 天与前 7 天环比判断门店涨跌。`);
  rows(
    "dailyCommandRows",
    [
      { label: "营业额", value: yuan(dailyIncome), detail: `${num(dailyOrders)} 单 · 客单 ${dailyOrders ? yuan(dailyIncome / dailyOrders) : "¥0"}`, tone: "good" },
      { label: "曝光", value: num(dailyImpressions), detail: `下单转化 ${pct(avgOrderConversion)}`, tone: avgOrderConversion ? "neutral" : "warn" },
      { label: "异常重点", value: `${num(highFocusCount)} 项`, detail: focusItems.length ? `${focusItems.length} 条日报异常需复看` : "暂无高优先级异常", tone: highFocusCount ? "warn" : "good" },
      { label: "覆盖门店", value: `${num(stores.length)} 家`, detail: `${platforms.length || 0} 个平台汇总`, tone: stores.length ? "neutral" : "warn" },
    ],
    (item) => `<div class="${item.tone === "warn" ? "warn-row" : item.tone === "good" ? "good-row" : ""}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
  renderDailyWeekAnalysis(dailyTrends);
}

function formatMetricDelta(delta, unit = "") {
  const value = Number(delta || 0);
  return `${value > 0 ? "+" : ""}${num(value)}${unit}`;
}

function renderDailyWeekAnalysis(dailyTrends) {
  const summary = dailyTrends.summary || {};
  const orderSummary = summary.orders || {};
  const incomeSummary = summary.income || {};
  const stores = dailyTrends.stores || dailyTrends.top_movers || [];
  const period = dailyTrends.periods || {};
  const current = period.current_7d || {};
  const previous = period.previous_7d || {};
  const periodText = current.start_date && previous.start_date
    ? `${current.start_date} 至 ${current.end_date} 对比 ${previous.start_date} 至 ${previous.end_date}`
    : dailyTrends.message || "等待周分析数据";
  if (!stores.length && !Object.keys(summary).length) {
    html("dailyWeekAnalysis", '<div class="empty-line">暂无足够历史数据生成AI周分析</div>');
    return;
  }
  const orderDelta = Number(orderSummary.delta_daily_avg || 0);
  const incomeDelta = Number(incomeSummary.delta_daily_avg || 0);
  const movers = stores.slice(0, 8).map((item) => {
    const orders = item.orders || {};
    const income = item.income || {};
    const delta = Number(orders.delta_daily_avg || 0);
    return `
      <div class="week-store ${trendClass(delta)}">
        <span>${escapeHtml(shortStore(item.store))}</span>
        <strong>${delta >= 0 ? "涨" : "跌"} ${formatMetricDelta(delta, " 单/日")}</strong>
        <em>${escapeHtml(compactText(item.reason || "", 92))}</em>
        <small>${escapeHtml(compactText(item.action || `营业额日均 ${formatMetricDelta(Number(income.delta_daily_avg || 0))}`, 110))}</small>
      </div>`;
  }).join("");
  html(
    "dailyWeekAnalysis",
    `
      <div class="week-analysis-head">
        <div>
          <span>AI周分析</span>
          <strong class="${trendClass(orderDelta)}">单量日均 ${formatMetricDelta(orderDelta, " 单")}</strong>
          <em class="${trendClass(incomeDelta)}">营业额日均 ${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}</em>
        </div>
        <p>${escapeHtml(periodText)}</p>
      </div>
      <div class="week-store-grid">${movers}</div>
    `
  );
}

let dailyOrderPendingSummary = null;

function priorityDetailList(items, formatter, emptyText, limit = 6) {
  if (!items.length) return emptyText;
  const shown = items.slice(0, limit).map(formatter);
  const remaining = items.length - shown.length;
  return `${shown.join("；")}${remaining > 0 ? `；另 ${remaining} 个` : ""}`;
}

function timestampValue(value) {
  if (!value) return 0;
  const normalized = String(value).trim().replace(" ", "T");
  const time = Date.parse(normalized);
  return Number.isFinite(time) ? time : 0;
}

function freshPromoBalanceStatus(balances, promoBalanceStatus) {
  const balanceTime = timestampValue(balances.generated_at);
  const statusTime = timestampValue(promoBalanceStatus.source_generated_at || promoBalanceStatus.generated_at);
  if (!statusTime) return {};
  if (balanceTime && statusTime < balanceTime) return {};
  return promoBalanceStatus;
}

function countPromoBalanceAbnormal(balances, promoBalanceStatus, balanceThreshold) {
  const summary = promoBalanceStatus.summary || {};
  const lowBalanceItems = promoBalanceStatus.low_balance_items || [];
  const platformFailures = (promoBalanceStatus.platforms || []).filter((item) => item.status === "failed");
  const unconfirmedItems = (balances.items || []).filter((item) => balanceValue(item) === null);
  const hasPromoStatus = Boolean(promoBalanceStatus.generated_at || promoBalanceStatus.source_generated_at || lowBalanceItems.length || platformFailures.length);
  const lowBalanceCount = Number(summary.low_balance_count ?? balances.summary?.warning_count ?? 0);
  const platformFailureCount = Number(summary.platform_failure_count || platformFailures.length);
  const unconfirmedCount = unconfirmedItems.length;
  if (hasPromoStatus && (lowBalanceCount || platformFailureCount || unconfirmedCount)) {
    const lowBalanceDetail = priorityDetailList(
      lowBalanceItems,
      (item) => `${item.platform || "-"} ${shortStore(item.store_name)} ${yuan(balanceValue(item))}`,
      "",
    );
    const failureDetail = priorityDetailList(
      platformFailures,
      (item) => `${item.platform || "-"}巡检失败`,
      "",
    );
    const unconfirmedDetail = priorityDetailList(
      unconfirmedItems,
      (item) => `${item.platform || "-"} ${shortStore(item.store_name)}未确认`,
      "",
    );
    return {
      count: lowBalanceCount + platformFailureCount + unconfirmedCount,
      detail: [
        lowBalanceDetail,
        failureDetail,
        unconfirmedDetail,
      ].filter(Boolean).join("；"),
    };
  }
  const balanceWarnings = (balances.items || []).filter((item) => {
    const value = balanceValue(item);
    return value !== null && value < balanceThreshold;
  });
  return {
    count: balanceWarnings.length,
    detail: priorityDetailList(
      balanceWarnings,
      (item) => `${item.platform || "-"} ${shortStore(item.store_name)} ${yuan(balanceValue(item))}`,
      "无余额异常",
    ),
  };
}

function countInventoryAbnormal(inventory) {
  const warnings = (inventory.items || []).filter((item) => Number(item.balance || 0) <= Number(item.warning_threshold || 0));
  const count = Number(inventory.warning_count ?? warnings.length);
  return {
    count,
    detail: priorityDetailList(
      warnings,
      (item) => `${item.sku || "-"} ${item.name || ""} ${num(item.balance, 2)}${item.unit || ""}/${num(item.warning_threshold, 2)}${item.unit || ""}`,
      "无库存异常",
    ),
  };
}

function countPendingDailyOrders() {
  if (!dailyOrderPendingSummary) {
    return { count: null, detail: "" };
  }
  if (dailyOrderPendingSummary.status === "failed") {
    return { count: null, detail: "" };
  }
  const count = Number(dailyOrderPendingSummary.pending_count || 0);
  return {
    count,
    detail: "",
  };
}

function priorityItems() {
  const balances = data.balances || {};
  const promoBalanceStatus = freshPromoBalanceStatus(balances, data.promo_balance_status || {});
  const inventory = data.inventory || {};
  const balanceThreshold = Number((promoBalanceStatus.summary || balances.summary || {}).warning_threshold || balances.threshold || 200);
  const balanceAbnormal = countPromoBalanceAbnormal(balances, promoBalanceStatus, balanceThreshold);
  const inventoryAbnormal = countInventoryAbnormal(inventory);
  const pendingOrders = countPendingDailyOrders();

  return [
    {
      type: "余额异常",
      title: `${num(balanceAbnormal.count)} 个`,
      detail: balanceAbnormal.detail,
      level: balanceAbnormal.count ? "warning" : "ok",
    },
    {
      type: "库存异常",
      title: `${num(inventoryAbnormal.count)} 个`,
      detail: inventoryAbnormal.detail,
      level: inventoryAbnormal.count ? "danger" : "ok",
    },
    {
      type: "未处理订货订单",
      title: pendingOrders.count === null ? "读取中" : `${num(pendingOrders.count)} 单`,
      detail: pendingOrders.detail,
      level: pendingOrders.count === null ? "warning" : pendingOrders.count ? "danger" : "ok",
    },
  ];
}

function renderPriority() {
  const items = priorityItems();
  const hasAlert = items.some((item) => item.level !== "ok");
  text("priorityStatus", hasAlert ? "需关注" : "正常");
  rows(
    "priorityRows",
    items,
    (item) => `<div class="${item.level === "ok" ? "good-row" : "warn-row"}"><span>${escapeHtml(item.type)}</span><strong>${escapeHtml(item.title)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

async function loadDailyOrderPendingSummary() {
  try {
    const response = await fetch("/daily-order/api/admin/summary?status=pending&token=daily-order-admin", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "订货后台读取失败");
    dailyOrderPendingSummary = {
      status: "ready",
      pending_count: Number(payload.stats?.pending_count ?? payload.stats?.order_count ?? (payload.orders || []).length),
      channel_count: (payload.channels || []).length,
    };
  } catch (error) {
    dailyOrderPendingSummary = { status: "failed", message: error.message };
  }
  renderPriority();
}

function renderHealth() {
  const taskHealth = data.task_health || {};
  const taskRuns = data.task_runs || {};
  const macminiSmoke = data.macmini_smoke_status || {};
  const operationCheck = data.operation_automation_check || {};
  const summary = taskHealth.summary || {};
  const environment = taskHealth.environment || {};
  const tasks = taskHealth.tasks || [];
  const morningTasks = taskHealth.morning_tasks || [];
  const smokeStatus = macminiSmoke.status || "waiting_log";
  const operationBlockers = operationCheck.blockers || [];
  const operationWarnings = operationCheck.warnings || [];
  const operationEnvironment = operationCheck.environment || environment;
  const operationRow = {
    name: "系统体检",
    status: operationBlockers.length ? "danger" : operationWarnings.length ? "warn" : "ok",
    status_text: operationBlockers.length ? "阻塞" : operationWarnings.length ? "提醒" : "正常",
    reason: operationBlockers.length
      ? `${operationEnvironment.label || "当前环境"}发现 ${operationBlockers.length} 个阻塞项`
      : operationWarnings.length
        ? `${operationEnvironment.label || "当前环境"}有 ${operationWarnings.length} 个提醒`
        : `${operationEnvironment.label || "当前环境"}体检通过`,
    human_action: (operationBlockers[0] || operationWarnings[0] || {}).message || "",
    last_seen_at: operationCheck.generated_at || "",
    environment_label: operationEnvironment.label || "",
  };
  const smokeRow = {
    name: "Mac mini 只读冒烟",
    status: smokeStatus === "ready" ? "ok" : smokeStatus === "failed" ? "danger" : "warn",
    status_text: smokeStatus === "ready" ? "已完成" : smokeStatus === "failed" ? "失败" : "待回传",
    reason: macminiSmoke.message || "等待 Mac mini 生产冒烟日志。",
    human_action: macminiSmoke.next_action || "",
    last_seen_at: macminiSmoke.summary?.updated_at || "",
    environment_label: "Mac mini 生产环境",
  };
  const abnormalCount = Number(summary.warn || 0) + Number(summary.danger || 0);
  const statusPrefix = environment.role === "production" ? "生产" : "开发";
  text("healthStatus", `${statusPrefix}${abnormalCount ? "注意" : "正常"}`);
  text(
    "healthSummary",
    `共 ${summary.total || tasks.length || 0} 个自动化任务：正常 ${summary.ok || 0}，注意 ${summary.warn || 0}，需处理 ${summary.danger || 0}，规划中 ${summary.planned || 0}。${taskHealth.generated_at ? `任务健康生成：${taskHealth.generated_at}。` : ""}`
  );
  rows(
    "morningTaskRows",
    morningTasks,
    (task) => {
      const runStatus = task.last_run_status || "missing";
      const cls = runStatus === "success" ? "good-row" : runStatus === "missing" || runStatus === "skipped" ? "neutral-row" : "warn-row";
      const statusText = task.last_run_status_text || (runStatus === "success" ? "成功" : runStatus === "failed" ? "失败" : runStatus === "running" ? "运行中" : runStatus === "skipped" ? "跳过" : runStatus === "warning" ? "注意" : "未记录");
      const meta = [
        task.last_run_step ? `步骤：${task.last_run_step}` : "",
        task.last_run_message || task.reason || "",
        task.failure_type ? `原因：${task.failure_type}` : "",
        task.human_action ? `处理：${task.human_action}` : "",
        task.evidence ? `记录：${task.evidence}` : "",
      ].filter(Boolean).join(" · ");
      return `<div class="${cls}"><span>${escapeHtml(task.name || task.id || "未知任务")}</span><strong>${escapeHtml(task.last_run_at || "未记录")}</strong><strong>${escapeHtml(statusText)}</strong><em>${escapeHtml(meta || task.schedule || "-")}</em></div>`;
    }
  );
  const healthRows = operationEnvironment.role === "production" || operationBlockers.length
    ? [operationRow, smokeRow, ...tasks]
    : [smokeRow, ...tasks, operationRow];
  rows(
    "healthRows",
    healthRows,
    (task) => {
      const cls = task.status === "ok" ? "good-row" : "warn-row";
      const meta = [
        task.reason,
        task.last_run_status ? `最近运行：${task.last_run_status}` : "",
        task.last_run_step ? `步骤：${task.last_run_step}` : "",
        task.repair_guide ? `向导：${task.repair_guide}` : "",
        task.human_action ? `处理：${task.human_action}` : "",
        task.last_seen_at ? `最近：${task.last_seen_at}` : "",
        task.evidence ? `记录：${task.evidence}` : "",
        task.environment_label || environment.label || "",
      ].filter(Boolean).join(" · ");
      return `<div class="${cls}"><span>${escapeHtml(task.name)}</span><strong>${escapeHtml(task.status_text || task.status)}</strong><em>${escapeHtml(meta || task.next_step || "-")}</em></div>`;
    }
  );
  const taskNames = new Map(tasks.map((task) => [task.id, task.name]));
  const events = (taskRuns.events || []).slice(-18).reverse();
  rows(
    "healthRunRows",
    events,
    (event) => {
      const ok = event.status === "success";
      const cls = ok ? "good-row" : "warn-row";
      const statusText = event.status === "success" ? "成功" : event.status === "failed" ? "失败" : event.status === "running" ? "运行中" : event.status === "skipped" ? "跳过" : event.status || "-";
      const meta = [
        event.created_at ? `时间：${event.created_at}` : "",
        event.step ? `步骤：${event.step}` : "",
        event.message || "",
        event.failure_type ? `原因：${event.failure_type}` : "",
        event.log_path ? `日志：${event.log_path}` : "",
      ].filter(Boolean).join(" · ");
      return `<div class="${cls}"><span>${escapeHtml(taskNames.get(event.task_id) || event.task_id || "未知任务")}</span><strong>${escapeHtml(statusText)}</strong><em>${escapeHtml(meta || "-")}</em></div>`;
    }
  );
}

function renderAiAdvice() {
  const advice = data.ai_advice || {};
  if (Array.isArray(advice.rows) && advice.rows.length) {
    text("aiTrend", advice.trend || "待积累");
    text("aiAdviceSummary", advice.summary || "AI建议会优先处理自动化异常，再结合经营数据解释波动。");
    rows(
      "aiAdviceRows",
      advice.rows,
      (item) => {
        const cls = item.level === "需人工处理" || item.level === "建议" ? "warn-row" : "good-row";
        const detail = [item.reason, item.action].filter(Boolean).join("；");
        return `<div class="${cls}"><span>${escapeHtml(item.level || item.center || "建议")}</span><strong>${escapeHtml(item.title || "-")}</strong><em>${escapeHtml(compactText(detail || "-", 170))}</em></div>`;
      }
    );
    return;
  }
  const daily = data.daily || {};
  const stores = storeTotals(latestDailyRows(daily));
  const compare = yesterdayStoreMap(daily);
  const insights = stores
    .map((store) => {
      const previous = compare.get(store.store);
      const previousOrders = Number(previous?.orders?.previous ?? previous?.orders ?? previous?.total_orders ?? 0);
      const delta = previousOrders ? Number(store.orders || 0) - previousOrders : 0;
      const rate = previousOrders ? delta / previousOrders : 0;
      return { ...store, previousOrders, delta, rate };
    })
    .filter((item) => item.previousOrders)
    .sort((a, b) => Math.abs(b.rate) - Math.abs(a.rate));

  const totalOrders = stores.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const previousOrders = insights.reduce((sum, item) => sum + item.previousOrders, 0);
  const totalDelta = previousOrders ? totalOrders - previousOrders : 0;
  const trendText = previousOrders ? `${totalDelta >= 0 ? "上涨" : "下跌"} ${signedNumber(totalDelta)} 单` : "待积累";
  text("aiTrend", trendText);
  text(
    "aiAdviceSummary",
    previousOrders
      ? `按昨日同时段对比，整体单量${totalDelta >= 0 ? "上涨" : "下跌"}。优先查看波动最大的门店，再结合曝光、评价、余额和库存排查原因。`
      : "已有AI建议入口，待实时历史数据继续积累后，按天/周分析涨跌原因。"
  );
  rows(
    "aiAdviceRows",
    insights.slice(0, 5),
    (item) => {
      const action = item.delta < 0 ? "检查曝光、差评、库存和预算是否拖累" : "复盘高峰品类和推广设置，沉淀可复制动作";
      return `<div class="${item.delta < 0 ? "warn-row" : "good-row"}"><span>${escapeHtml(item.store)}</span><strong>${signedNumber(item.delta)} 单</strong><em>${action}</em></div>`;
    }
  );
}

function renderAnomalies() {
  const daily = data.daily || {};
  const dailyFocus = data.daily_focus || {};
  const latestDate = latestDailyDate(daily);
  const focusItems = dailyFocus.items || [];
  const anomalies = focusItems.length ? focusItems : groupedAnomalies(daily.focus_items || []);
  text("anomalyCount", `${anomalies.length} 家`);
  text("anomalyStatus", anomalies.length ? "需处理" : "正常");
  text("anomalySummary", dailyFocus.message || (anomalies.length ? `${latestDate || "最新日报"} 发现 ${anomalies.length} 家异常门店，优先处理高风险项。` : `${latestDate || "最新日报"} 暂无异常门店。`));
  rows(
    "anomalyRows",
    anomalies,
    (group) => {
      const issues = (group.issues || []).map((item) => item.title).filter(Boolean).join("；");
      const body = group.action || (group.issues || []).map((item) => item.body).filter(Boolean)[0] || "请打开日报查看详情。";
      const highText = group.high_count !== undefined ? `高 ${group.high_count || 0} / 中 ${group.medium_count || 0}` : `${(group.issues || []).length} 项异常`;
      return `<div class="warn-row"><span>${escapeHtml(group.store)}</span><strong>${escapeHtml(highText)}</strong><em>${escapeHtml(issues)}。${escapeHtml(body)}</em></div>`;
    }
  );
}

function renderReviews() {
  const daily = data.daily || {};
  const review = daily.review_summary || {};
  const reviewActions = data.review_actions || {};
  const actionSummary = reviewActions.summary || {};
  const weeklyRecap = reviewActions.weekly_recap || {};
  const weeklySummary = weeklyRecap.summary || {};
  const stores = Object.entries(review.stores || {}).map(([store, item]) => ({
    store,
    review_count: Number(item.review_count || 0),
    negative_count: Number(item.negative_count || 0),
    review_avg_rating: Number(item.review_avg_rating || item.avg_rating || 0),
    platforms: item.platforms || {},
    top_keywords: item.top_keywords || [],
    bad_review_examples: item.bad_review_examples || item.examples || [],
  }));
  const totalReviews = stores.reduce((sum, item) => sum + item.review_count, 0);
  const totalIssues = stores.reduce((sum, item) => sum + item.negative_count, 0);
  const pendingNegative = Number(actionSummary.negative_count || totalIssues || 0);
  const statusText = pendingNegative
    ? "待回复"
    : review.status === "ready"
      ? "已同步"
      : review.status === "stale"
        ? "旧数据"
        : "待同步";

  text("reviewStatus", statusText);
  text("reviewCount", `${num(totalIssues)} / ${num(totalReviews)} 条`);
  text(
    "reviewSummary",
    `${review.used_date || review.target_date || "昨日"}：差评 ${num(totalIssues)} 条 / 总评价 ${num(totalReviews)} 条，覆盖 ${stores.length} 家门店。`
  );
  document.querySelector("#reviews")?.classList.toggle("alert", pendingNegative > 0);

  rows(
    "reviewCommandRows",
    [
      {
        label: "昨日总评价",
        value: `${num(totalReviews)} 条`,
        detail: `覆盖 ${num(stores.length)} 家门店`,
        tone: "neutral",
      },
      {
        label: "昨日差评",
        value: `${num(totalIssues)} 条`,
        detail: `差评率 ${totalReviews ? ((totalIssues / totalReviews) * 100).toFixed(1) : "0.0"}%`,
        tone: totalIssues ? "warn" : "good",
      },
      {
        label: "待回复",
        value: `${num(pendingNegative)} 条`,
        detail: pendingNegative ? "优先处理有差评门店" : "暂无待回复差评",
        tone: pendingNegative ? "warn" : "good",
      },
      {
        label: "本周问题",
        value: `${num(weeklySummary.negative_count || actionSummary.weekly_negative_count || 0)} 条`,
        detail: `本周评价 ${num(weeklySummary.review_count || actionSummary.weekly_review_count || 0)} 条`,
        tone: Number(weeklySummary.negative_count || 0) ? "warn" : "good",
      },
    ],
    (item) => `<div class="${item.tone === "warn" ? "warn-row" : item.tone === "good" ? "good-row" : ""}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  const weeklyStores = (weeklyRecap.stores || []).slice(0, 3);
  const weeklyIssues = (weeklyRecap.issue_types || []).slice(0, 3);
  rows(
    "reviewWeeklyRows",
    [
      {
        label: "重点门店",
        value: weeklyStores.length ? weeklyStores.map((item) => `${item.store} ${num(item.negative_count)} 条`).join(" / ") : "暂无",
        detail: weeklyStores.length ? weeklyStores.map((item) => `${item.store} 问题率 ${(Number(item.negative_rate || 0) * 100).toFixed(1)}%，均分 ${Number(item.avg_rating || 0).toFixed(2)}`).join("；") : "本周暂无明显差评集中门店。",
        className: weeklyStores.some((item) => Number(item.negative_count || 0)) ? "warn-row" : "good-row",
      },
      {
        label: "高频问题",
        value: weeklyIssues.length ? weeklyIssues.map((item) => `${item.issue_type} ${num(item.count)}`).join(" / ") : "暂无",
        detail: (weeklyRecap.actions || []).slice(0, 2).join("；") || weeklyRecap.next_action || "继续观察差评、评分和同类问题复发。",
        className: weeklyIssues.length ? "warn-row" : "good-row",
      },
    ],
    (item) => `<div class="${item.className}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  rows(
    "reviewRows",
    stores
      .slice()
      .sort((a, b) => Number(b.negative_count || 0) - Number(a.negative_count || 0) || Number(b.review_count || 0) - Number(a.review_count || 0)),
    (item) => {
      const keywords = item.top_keywords.length ? item.top_keywords.join("、") : "无集中关键词";
      const badReviews = item.bad_review_examples
        .filter(Boolean)
        .map((content, index) => `<span class="bad-review">${index + 1}. ${escapeHtml(content)}</span>`)
        .join("");
      const badReviewText = badReviews ? `<br><b class="bad-review-title">差评内容</b>${badReviews}` : "";
      const platformText = ["美团", "饿了么"]
        .map((platform) => {
          const detail = item.platforms[platform] || {};
          const count = Number(detail.review_count || 0);
          const negative = Number(detail.negative_count || 0);
          const rating = Number(detail.review_avg_rating || detail.avg_rating || 0);
          return `${platform} ${count} 条 / 差评 ${negative} / 评价均分 ${rating ? rating.toFixed(2) : "-"}`;
        })
        .join("；");
      const cls = item.negative_count ? "warn-row" : "good-row";
      return `<div class="${cls}"><span>${escapeHtml(item.store)}</span><strong>${item.negative_count}/${item.review_count} 条</strong><em>${escapeHtml(platformText)}<br>合计评价均分 ${item.review_avg_rating.toFixed(2)} · ${escapeHtml(keywords)}${badReviewText}</em></div>`;
    }
  );
}

function isReliableBalance(item) {
  if (item.balance === null || item.balance === undefined || item.balance === "") return false;
  const balance = Number(item.balance);
  if (!Number.isFinite(balance)) return false;
  if (balance !== 0) return true;
  if (item.confirmed_zero === true) return true;
  if (/CDP|接口读取|api/i.test(String(item.source || ""))) return true;
  if (item.api_seen === true || item.account_response_url || item.page_url) return true;
  return false;
}

function balanceValue(item) {
  return isReliableBalance(item) ? Number(item.balance) : null;
}

function balanceDisplay(item) {
  const value = balanceValue(item);
  return value === null ? "未确认" : yuan(value);
}

function renderBalances() {
  const balances = data.balances || {};
  const promoBalanceStatus = freshPromoBalanceStatus(balances, data.promo_balance_status || {});
  const summary = promoBalanceStatus.summary || balances.summary || {};
  const evidenceSync = promoBalanceStatus.evidence_sync || {};
  const threshold = Number(summary.warning_threshold || balances.threshold || 200);
  const allBalanceItems = balances.items || [];
  const reliableItems = allBalanceItems.filter((item) => balanceValue(item) !== null);
  const unconfirmedItems = allBalanceItems.filter((item) => balanceValue(item) === null);
  const warnings = reliableItems.filter((item) => Number(item.balance || 0) < threshold);
  const platformFailures = (promoBalanceStatus.platforms || []).filter((item) => item.status === "failed");
  const platformFailureCount = Number(summary.platform_failure_count || platformFailures.length || 0);
  const lowBalanceCount = warnings.length;
  const lowestReliable = reliableItems.length ? Math.min(...reliableItems.map((item) => Number(item.balance || 0))) : null;
  const needsAttention = platformFailureCount > 0 || lowBalanceCount > 0;
  const statusText = platformFailureCount ? "巡检失败" : lowBalanceCount ? "需充值" : "正常";
  text("metricWarnings", `${lowBalanceCount} 个`);
  text("metricLowest", `最低 ${lowestReliable === null ? "未确认" : yuan(lowestReliable)} · ${reliableItems.length}/${allBalanceItems.length} 条可靠`);
  text("balanceWarningCount", `${lowBalanceCount} 个`);
  text(
    "balanceSummary",
    `最新巡检：${promoBalanceStatus.source_generated_at || balances.generated_at || "-"}，平台失败 ${platformFailureCount} 个，低余额 ${lowBalanceCount} 个，余额未确认 ${unconfirmedItems.length} 个，阈值 ${yuan(threshold)}，证据清单 ${evidenceSync.file_count || 0} 个。CDP/API 读到的 0 元按已确认余额处理。`
  );
  text("balanceStatus", statusText);
  cls("balanceMetricCard", "alert", needsAttention);
  document.querySelector("#balances")?.classList.toggle("alert", needsAttention);
  document.querySelector("#metricLowest")?.classList.toggle("danger", needsAttention);
  rows(
    "balanceRows",
    [
      ...platformFailures.map((item) => ({ ...item, kind: "platform_failure" })),
      ...warnings.slice(0, 6).map((item) => ({ ...item, kind: "low_balance" })),
      ...unconfirmedItems.slice(0, 6).map((item) => ({ ...item, kind: "unconfirmed_balance" })),
    ],
    (item) => {
      if (item.kind !== "platform_failure") {
        const value = balanceValue(item);
        const gap = value === null ? 0 : Math.max(0, threshold - value);
        const detail = value === null ? `采集未确认 · 来源 ${item.source || "-"} · 请重跑余额巡检` : `阈值 ${yuan(threshold)} · 差额 ${yuan(gap)}`;
        return `<div class="${value === null || value < threshold ? "warn-row" : "good-row"}"><span>${escapeHtml(item.platform)} · ${escapeHtml(shortStore(item.store_name))}</span><strong>${escapeHtml(balanceDisplay(item))}</strong><em>${escapeHtml(detail)}</em></div>`;
      }
      const recovery = item.recovery || {};
      const steps = (recovery.steps || []).slice(0, 2).join("；");
      const evidence = item.evidence || [];
      const evidenceText = evidence.length ? `证据：${evidence.slice(0, 2).map((entry) => `${entry.kind || "file"} ${entry.path}`).join("；")}` : "";
      const detail = [recovery.summary || item.human_action || item.message || "先处理平台状态", steps, recovery.verify_command ? `复查：${recovery.verify_command}` : "", evidenceText].filter(Boolean).join(" · ");
      return `<div class="warn-row"><span>${escapeHtml(item.platform)} · 巡检失败</span><strong>${escapeHtml(recovery.title || item.failure_type || "需处理")}</strong><em>${escapeHtml(detail)}</em></div>`;
    }
  );
}

function budgetStoreNames(budget, saved) {
  const names = new Set();
  ["eleme_lunch", "eleme_dinner", "meituan_lunch", "meituan_dinner"].forEach((key) => {
    (budget[key] || []).forEach((item) => names.add(canonicalStoreName(item.sourceStore || item.store)));
  });
  Object.keys(saved.stores || {}).forEach((name) => names.add(canonicalStoreName(name)));
  return [...names].filter(Boolean).sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function platformBudget(saved, store, platform, field) {
  const direct = saved.stores?.[store]?.[platform] || {};
  if (direct[field]) return Number(direct[field] || 0);
  const aliasKey = Object.keys(saved.stores || {}).find((name) => canonicalStoreName(name) === store);
  return Number((saved.stores?.[aliasKey]?.[platform] || {})[field] || 0);
}

function platformBudgetStores(budget, saved, platform) {
  const names = new Set();
  const keys = platform === "饿了么" ? ["eleme_lunch", "eleme_dinner"] : ["meituan_lunch", "meituan_dinner"];
  keys.forEach((key) => {
    (budget[key] || []).forEach((item) => names.add(canonicalStoreName(item.sourceStore || item.store)));
  });
  Object.entries(saved.stores || {}).forEach(([name, cfg]) => {
    if (cfg?.[platform]) names.add(canonicalStoreName(name));
  });
  return [...names].filter(Boolean).sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function applyBudgetOverrides(payload, refreshedAt = "") {
  const overrides = payload?.data || payload;
  if (!overrides || typeof overrides !== "object") return false;
  data.budget = data.budget || {};
  data.budget.overrides = overrides;
  if (refreshedAt) data.budget.overrides_refreshed_at = refreshedAt;
  return true;
}

async function hydrateBudgetOverrides() {
  if (budgetOverridesFetchStarted) return;
  budgetOverridesFetchStarted = true;
  try {
    const response = await fetch(PROMO_BUDGET_OVERRIDES_URL, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "预算配置读取失败");
    if (applyBudgetOverrides(payload, new Date().toLocaleString("zh-CN", { hour12: false }))) {
      renderBudget();
    }
  } catch (error) {
    data.budget = data.budget || {};
    data.budget.overrides_load_error = error.message || "预算配置读取失败";
    renderBudget();
  }
}

function renderBudgetEditor(budget, saved) {
  const container = document.querySelector("#budgetEditorRows");
  if (!container) return;
  const fields = [
    ["工作日午餐", "lunchBudget"],
    ["工作日晚餐", "dinnerBudget"],
    ["周末午餐", "weekendLunchBudget"],
    ["周末晚餐", "weekendDinnerBudget"],
  ];
  container.innerHTML = ["饿了么", "美团"].map((platform) => {
    const names = platformBudgetStores(budget, saved, platform);
    return `
      <section class="budget-platform-section">
        <h3>${escapeHtml(platform)}</h3>
        <div class="budget-platform-rows">
          ${names.map((store) => `
            <div class="budget-edit-row" data-store="${escapeHtml(store)}" data-platform="${escapeHtml(platform)}">
              <strong>${escapeHtml(shortStore(store))}</strong>
              ${fields.map(([label, field]) => `
                <label>${label}<input data-platform="${platform}" data-field="${field}" type="number" min="1" step="1" value="${platformBudget(saved, store, platform, field) || ""}"></label>
              `).join("")}
            </div>
          `).join("") || '<div class="empty-line">暂无该平台预算门店</div>'}
        </div>
      </section>
    `;
  }).join("");
}

function collectBudgetEditorPayload() {
  const stores = {};
  document.querySelectorAll(".budget-edit-row").forEach((row) => {
    const store = canonicalStoreName(row.dataset.store);
    stores[store] = stores[store] || {};
    row.querySelectorAll("input").forEach((input) => {
      const value = Number(input.value || 0);
      if (value <= 0) return;
      const platform = input.dataset.platform;
      stores[store][platform] = stores[store][platform] || {};
      stores[store][platform][input.dataset.field] = value;
    });
    if (!Object.keys(stores[store]).length) delete stores[store];
  });
  return { stores };
}

async function saveBudgetEditor() {
  const button = document.querySelector("#budgetSaveButton");
  const status = document.querySelector("#budgetSaveStatus");
  if (!button || !status) return;
  button.disabled = true;
  button.textContent = "保存中...";
  status.className = "save-status pending";
  status.textContent = "正在同步云端预算配置。";
  try {
    const response = await fetch(PROMO_BUDGET_OVERRIDES_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectBudgetEditorPayload()),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "保存失败");
    applyBudgetOverrides(payload, new Date().toLocaleString("zh-CN", { hour12: false }));
    renderBudget();
    status.className = "save-status success";
    status.textContent = `已保存到云端：${new Date().toLocaleString("zh-CN", { hour12: false })}`;
    button.textContent = "已保存";
  } catch (error) {
    status.className = "save-status error";
    status.textContent = `保存失败：${error.message || "请稍后重试"}`;
    button.textContent = "重新保存";
  } finally {
    button.disabled = false;
  }
}

function renderBudget() {
  const budget = data.budget || {};
  const retry = data.promo_budget_retry || {};
  const summary = budget.summary || {};
  const retrySummary = retry.summary || {};
  const saved = budget.overrides || {};
  const eleme = budget.eleme_lunch || [];
  const meituan = budget.meituan_lunch || [];
  text("metricBudget", `${summary.total_initial_budget_items || eleme.length + meituan.length} 项`);
  text("metricBudgetMeta", `饿了么 ${eleme.length} 自动 · 美团 ${meituan.length} 自动`);
  text("budgetCount", `${eleme.length + meituan.length} 项`);
  const affectedByLatestRun = retrySummary.affected_by_latest_run_count || 0;
  const retryGuide = (retry.repair_guides || [])[0] || {};
  const retryGuideStep = (retryGuide.checklist || [])[0] || "";
  const retryText = retry.status === "ready" ? `门店级重试：${retrySummary.safe_retry_count || 0} 项可重试，${retrySummary.manual_count || 0} 项需人工${affectedByLatestRun ? `，最近执行影响 ${affectedByLatestRun} 项` : ""}${retryGuide.title ? `，修复向导 ${retrySummary.repair_guide_count || (retry.repair_guides || []).length} 个` : ""}。` : "门店级重试策略待生成。";
  const configReadAt = budget.overrides_refreshed_at || budget.generated_at || "-";
  const loadErrorText = budget.overrides_load_error ? `云端预算实时读取失败：${budget.overrides_load_error}。` : "";
  text("budgetSummary", `云端预算配置读取时间：${configReadAt}。${loadErrorText}只展示已保存的预算配置；如果执行失败，不显示为已设置成功。${retryText}`);
  renderBudgetEditor(budget, saved);
  const budgetSaveButton = document.querySelector("#budgetSaveButton");
  if (budgetSaveButton) budgetSaveButton.onclick = saveBudgetEditor;
  hydrateBudgetOverrides();
  rows(
    "budgetRows",
    budgetStoreNames(budget, saved),
    (store) => {
      const cfg = saved.stores?.[store] || {};
      const detail = ["饿了么", "美团"].map((platform) => {
        const item = cfg[platform] || {};
        const parts = [
          item.lunchBudget ? `工作日午 ${yuan(item.lunchBudget)}` : "",
          item.dinnerBudget ? `工作日晚 ${yuan(item.dinnerBudget)}` : "",
          item.weekendLunchBudget ? `周末午 ${yuan(item.weekendLunchBudget)}` : "",
          item.weekendDinnerBudget ? `周末晚 ${yuan(item.weekendDinnerBudget)}` : "",
        ].filter(Boolean).join(" / ");
        return parts ? `${platform}：${parts}` : "";
      }).filter(Boolean).join("；");
      return `<div class="${detail ? "good-row" : "warn-row"}"><span>${escapeHtml(shortStore(store))}</span><strong>${detail ? "已保存" : "未配置"}</strong><em>${escapeHtml(detail || "云端暂无该门店预算配置")}</em></div>`;
    }
  );
  const retryRows = retry.status === "ready"
    ? [
        ...(affectedByLatestRun || retry.latest_run?.status ? [{ label: "最近执行影响", value: `${affectedByLatestRun || 0} 项`, detail: retry.latest_run?.failure_type || retry.latest_run?.status || "无" }] : []),
        ...(retryGuide.title ? [{ label: "修复向导", value: `${retrySummary.repair_guide_count || (retry.repair_guides || []).length} 个`, detail: `${retryGuide.title}：${retryGuideStep}` }] : []),
        { label: "可安全重试", value: `${retrySummary.safe_retry_count || 0} 项`, detail: "仅超时/普通执行失败" },
        { label: "需人工处理", value: `${retrySummary.manual_count || 0} 项`, detail: "登录/权限/页面/映射/预算安全" },
      ]
    : [{ label: "重试策略", value: "待生成", detail: "先生成预算预览" }];
  rows(
    "budgetRetryRows",
    retryRows,
    (item) => `<div class="${(item.label === "需人工处理" || item.label === "最近执行影响") && Number.parseInt(item.value, 10) ? "warn-row" : "good-row"}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

function renderBidding() {
  text("biddingStatus", "建设中");
  text("biddingCount", "框架保留");
  text("biddingSummary", "建设中：旧的推广出价调整逻辑已删除。此页只保留页面框架，等待接入新的调整规则。");
  document.querySelector("#bidding")?.classList.remove("alert");
  rows(
    "biddingRows",
    [
      { label: "规则状态", value: "待接入", detail: "等待新的出价调整逻辑。" },
      { label: "旧逻辑", value: "已移除", detail: "旧审批队列、旧出价建议和旧执行计划不再展示。" },
    ],
    (item) => `<div class="good-row"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

function orderSuggestionGroups(orderSuggestions) {
  const groups = Array.isArray(orderSuggestions.groups) ? orderSuggestions.groups : [];
  if (groups.length) return groups;
  const grouped = new Map();
  (orderSuggestions.items || []).forEach((item) => {
    const channel = item.warehouse || "未配置供应渠道";
    const group = grouped.get(channel) || {
      channel,
      status: "待人工确认",
      item_count: 0,
      estimated_cost: 0,
      items: [],
    };
    group.items.push(item);
    group.item_count += 1;
    group.estimated_cost += Number(item.estimated_cost || 0);
    grouped.set(channel, group);
  });
  return [...grouped.values()].sort((a, b) => b.item_count - a.item_count);
}

function orderItemsPreview(group) {
  const items = group.items || [];
  if (!items.length) return "暂无品项";
  return items
    .slice(0, 4)
    .map((item) => `${item.name || item.sku || "未命名商品"} ${num(item.suggested_quantity, 2)}${item.unit || ""}`)
    .join("；");
}

function checklistText(orderSuggestions, groups) {
  const summary = orderSuggestions.summary || {};
  const confirmation = orderSuggestions.confirmation || {};
  const lines = [
    "熊小小订货建议人工确认清单",
    `生成时间：${orderSuggestions.generated_at || data.generated_at || "-"}`,
    `建议品项：${summary.suggestion_count || 0} 项`,
    `供应渠道：${summary.channel_count || groups.length || 0} 个`,
    `预估金额：${yuan(summary.estimated_cost || 0)}`,
    `确认状态：${confirmation.status === "pending" ? "待人工确认" : "当前无需订货"}`,
    "",
    "确认前禁止动作：",
    ...(confirmation.required_before || ["生成渠道下单清单", "远控安卓下单", "付款"]).map((item) => `- ${item}`),
    "",
    "渠道明细：",
  ];

  groups.forEach((group) => {
    lines.push("");
    lines.push(`[${group.channel || "未配置供应渠道"}] ${group.item_count || 0} 项，预估 ${yuan(group.estimated_cost || 0)}`);
    (group.items || []).forEach((item) => {
      lines.push(
        `- ${item.name || item.sku || "未命名商品"}｜规格 ${item.spec || "-"}｜库存 ${num(item.balance, 2)}${item.unit || ""}｜预警 ${num(item.warning_threshold, 2)}｜建议 ${num(item.suggested_quantity, 2)}${item.unit || ""}｜预估 ${yuan(item.estimated_cost || 0)}`
      );
    });
  });
  lines.push("");
  lines.push("人工确认：品项、数量、供应渠道、替代品、付款金额均确认无误后，再生成渠道下单清单。");
  return lines.join("\n");
}

function openOrderingChecklist(orderSuggestions, groups) {
  const text = checklistText(orderSuggestions, groups);
  const win = window.open("", "_blank", "noopener,noreferrer");
  if (!win) return;
  win.document.write(`<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <title>订货建议人工确认清单</title>
    <style>
      body { margin: 32px; color: #111827; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", Arial, sans-serif; }
      pre { white-space: pre-wrap; font-size: 14px; line-height: 1.75; }
      button { margin-bottom: 18px; padding: 9px 13px; border: 1px solid #d1d5db; border-radius: 8px; background: #0f766e; color: #fff; font-weight: 800; }
      @media print { button { display: none; } body { margin: 18mm; } }
    </style>
  </head>
  <body>
    <button onclick="window.print()">打印 / 保存 PDF</button>
    <pre>${escapeHtml(text)}</pre>
  </body>
</html>`);
  win.document.close();
}

function orderListStatusText(status) {
  if (status === "ready") return "已生成";
  if (status === "waiting_confirmation") return "等待确认";
  if (status === "not_required") return "无需订货";
  if (status === "failed") return "生成失败";
  return "未生成";
}

function executionPreviewStatusText(status) {
  if (status === "payment_confirmed") return "付款已确认";
  if (status === "waiting_payment_confirmation") return "等待付款确认";
  if (status === "waiting_order_lists") return "等待清单";
  if (status === "not_required") return "无需订货";
  if (status === "failed") return "生成失败";
  return "未生成";
}

function androidPlanStatusText(status) {
  if (status === "ready") return "只读计划";
  if (status === "waiting_payment_confirmation") return "等待付款确认";
  if (status === "not_required") return "无需订货";
  if (status === "failed") return "生成失败";
  return "未生成";
}

function androidConfigStatusText(status) {
  if (status === "ready") return "配置可用";
  if (status === "missing_config") return "待补配置";
  return "未检查";
}

function orderListPreview(orderList) {
  const lines = orderList.lines || [];
  if (!lines.length) return orderList.next_action || "暂无品项";
  return lines
    .slice(0, 4)
    .map((item) => `${item.name || item.sku || "未命名商品"} ${num(item.quantity, 2)}${item.unit || ""}`)
    .join("；");
}

function executionPreviewText(preview) {
  const blocked = preview.blocked_actions || [];
  if (blocked.length) return `禁止：${blocked.slice(0, 3).join("、")}`;
  const steps = preview.execution_steps || [];
  return steps.slice(0, 3).join("；") || "暂无执行步骤";
}

function androidPlanText(job) {
  const stops = job.stop_before || [];
  if (stops.length) return `停止于：${stops.slice(0, 3).join("、")}`;
  const checks = job.preflight_checks || [];
  return checks.slice(0, 3).join("；") || "等待人工接管";
}

function androidConfigRows(config) {
  const missing = config.missing || [];
  const warnings = config.warnings || [];
  const setupChecklist = config.setup_checklist || [];
  return [
    ...missing.slice(0, 5).map((item) => ({ type: "缺少", detail: item })),
    ...warnings.slice(0, 3).map((item) => ({ type: "提示", detail: item })),
    ...setupChecklist.slice(0, 4).map((item) => ({ type: item.label || "配置步骤", detail: item.command || item.detail || "", note: item.detail || "Mac mini 生产环境执行" })),
  ];
}

function renderOrdering() {
  const orderSuggestions = data.order_suggestions || {};
  const orderLists = data.order_lists || {};
  const executionPreview = data.order_execution_preview || {};
  const androidPlan = data.android_execution_plan || {};
  const androidConfig = data.android_config || {};
  const summary = orderSuggestions.summary || {};
  const confirmation = orderSuggestions.confirmation || {};
  const groups = orderSuggestionGroups(orderSuggestions);
  const listSummary = orderLists.summary || {};
  const listRows = orderLists.order_lists || [];
  const executionSummary = executionPreview.summary || {};
  const executionRows = executionPreview.channel_previews || [];
  const androidSummary = androidPlan.summary || {};
  const androidRows = androidPlan.android_jobs || [];
  const androidConfigSummary = androidConfig.summary || {};
  const deviceRows = androidConfigRows(androidConfig);
  const suggestionCount = Number(summary.suggestion_count || groups.reduce((sum, group) => sum + Number(group.item_count || 0), 0));
  const channelCount = Number(summary.channel_count || groups.length);
  const estimatedCost = Number(summary.estimated_cost || groups.reduce((sum, group) => sum + Number(group.estimated_cost || 0), 0));
  const pending = confirmation.status === "pending" && suggestionCount > 0;
  const hasOrderLists = orderLists.status === "ready" && listRows.length > 0;
  const statusText = orderSuggestions.status === "failed" ? "生成失败" : hasOrderLists ? "待下单" : pending ? "待确认" : "无需订货";
  const statusEl = document.querySelector("#orderingStatus");

  text("orderingStatus", statusText);
  if (statusEl) {
    statusEl.className = `tag ${orderSuggestions.status === "failed" ? "danger" : pending ? "planning" : "ready"}`;
  }
  text("orderingSuggestionCount", `${suggestionCount} 项`);
  text(
    "orderingSummary",
    orderSuggestions.status === "failed"
      ? orderSuggestions.message || "订货建议生成失败，请查看任务健康报告。"
      : `按库存预警生成订货建议，当前 ${channelCount} 个供应渠道，预估 ${yuan(estimatedCost)}。`
  );
  text("orderingConfirmStatus", pending ? "需人工确认" : "当前无需处理");
  text("orderingConfirmMessage", confirmation.message || "订货建议只用于人工确认；确认前不会自动下单或付款。");
  text("orderingListStatus", orderListStatusText(orderLists.status));
  text("orderingListMessage", orderLists.message || orderLists.confirmation?.message || "人工确认后生成渠道下单清单。");
  text("orderingListCount", `${Number(listSummary.order_list_count || listRows.length)} 个渠道`);
  text("orderingExecutionStatus", executionPreviewStatusText(executionPreview.status));
  text("orderingExecutionMessage", executionPreview.message || executionPreview.payment_confirmation?.message || "远控安卓下单前生成执行预览。");
  text("orderingExecutionCount", `${Number(executionSummary.channel_count || executionRows.length)} 个渠道`);
  text("orderingAndroidStatus", androidPlanStatusText(androidPlan.status));
  text("orderingAndroidMessage", androidPlan.message || androidPlan.operator?.message || "只读计划，真实执行前人工接管。");
  text("orderingAndroidCount", `${Number(androidSummary.channel_count || androidRows.length)} 个渠道`);
  text("orderingDeviceStatus", androidConfigStatusText(androidConfig.status));
  text("orderingDeviceMessage", androidConfig.message || "按配置模板补齐远控安卓真实设备信息。");
  text("orderingDeviceCount", `${Number(androidConfigSummary.missing_count || 0)} 项缺失`);
  document.querySelector("#ordering")?.classList.toggle(
    "alert",
    pending || hasOrderLists || executionPreview.status === "waiting_payment_confirmation" || androidPlan.status === "ready" || androidConfig.status === "missing_config" || orderSuggestions.status === "failed" || orderLists.status === "failed" || executionPreview.status === "failed" || androidPlan.status === "failed"
  );

  rows(
    "orderingRows",
    groups.slice(0, 8),
    (group) => `<div class="${pending ? "warn-row" : "good-row"}"><span>${escapeHtml(group.channel || "未配置供应渠道")}</span><strong>${num(group.item_count)} 项 / ${yuan(group.estimated_cost)}</strong><em>${escapeHtml(orderItemsPreview(group))}</em></div>`
  );

  rows(
    "orderingListRows",
    listRows.slice(0, 8),
    (item) => `<div class="warn-row"><span>${escapeHtml(item.channel || "未配置供应渠道")}</span><strong>${num(item.item_count)} 项 / ${yuan(item.estimated_cost)}</strong><em>${escapeHtml(orderListPreview(item))}</em></div>`
  );

  rows(
    "orderingExecutionRows",
    executionRows.slice(0, 8),
    (item) => `<div class="warn-row"><span>${escapeHtml(item.channel || "未配置供应渠道")}</span><strong>${num(item.item_count)} 项 / ${yuan(item.estimated_cost)}</strong><em>${escapeHtml(executionPreviewText(item))}</em></div>`
  );

  rows(
    "orderingAndroidRows",
    androidRows.slice(0, 8),
    (item) => `<div class="warn-row"><span>${escapeHtml(item.channel || "未配置供应渠道")}</span><strong>${escapeHtml(item.target_app || "供应渠道 App")}</strong><em>${escapeHtml(androidPlanText(item))}</em></div>`
  );

  rows(
    "orderingDeviceRows",
    deviceRows,
    (item) => `<div class="warn-row"><span>${escapeHtml(item.type)}</span><strong>${escapeHtml(item.detail)}</strong><em>${escapeHtml(item.note || "真实执行前处理")}</em></div>`
  );

  const button = document.querySelector("#orderingChecklistButton");
  if (button) {
    button.disabled = !suggestionCount;
    button.textContent = suggestionCount ? "生成确认清单" : "暂无订货建议";
    button.onclick = () => openOrderingChecklist(orderSuggestions, groups);
  }
}

function renderInventory() {
  const inventory = data.inventory || {};
  const warnings = (inventory.items || []).filter((item) => Number(item.balance || 0) <= Number(item.warning_threshold || 0));
  text("metricInventory", `${inventory.warning_count ?? warnings.length} 个`);
  text("metricInventoryValue", `货值 ${yuan(inventory.inventory_value || 0)} · ${inventory.source === "cloud" ? "云端" : "本地"}`);
  text("inventoryProductCount", `${inventory.product_count || 0} 项`);
  text("inventorySummary", `当前库存货值 ${yuan(inventory.inventory_value || 0)}，预警 ${inventory.warning_count || 0} 项，来源：${inventory.source === "cloud" ? "腾讯云库存" : "本地备用数据"}。`);
  cls("inventoryMetricCard", "alert", warnings.length > 0);
  document.querySelector("#inventory")?.classList.toggle("alert", warnings.length > 0);
  document.querySelector("#metricInventoryValue")?.classList.toggle("danger", warnings.length > 0);
  rows(
    "inventoryRows",
    warnings.slice(0, 6),
    (item) => `<div class="warn-row"><span>${item.name}</span><strong>${num(item.balance, 2)} ${item.unit || ""}</strong><em>预警 ${num(item.warning_threshold, 2)}</em></div>`
  );
}

function renderTools() {
  const warehouse = data.tool_warehouse || {};
  const sales = warehouse.sales_receipt || {};
  const contract = warehouse.franchise_contract || {};
  const salesChecks = sales.checks || [];
  const printCheck = sales.print_check || {};
  const salesReadyCount = salesChecks.filter((item) => item.exists).length;
  text("salesReceiptStatus", sales.status_text || (sales.status === "ready" ? "已接入" : "待检查"));
  text("salesReceiptCount", sales.status === "ready" ? "可用" : sales.status === "needs_print_check" ? "待校验" : `${salesReadyCount}/${salesChecks.length || 4}`);
  text("salesReceiptSummary", sales.message || "销售单生成器等待状态检查。");
  document.querySelector(".module-receipt")?.classList.toggle("alert", sales.status && sales.status !== "ready");
  rows(
    "salesReceiptRows",
    [
      ...(salesChecks.length ? salesChecks : [
        { label: "页面", exists: false, path: "sales-receipt-generator/index.html" },
        { label: "脚本", exists: false, path: "sales-receipt-generator/app.js" },
      ]),
      ...(printCheck.status ? [{
        label: "打印校验",
        exists: printCheck.status === "ok",
        path: printCheck.screenshot || "",
        detail: printCheck.message || "",
      }] : []),
    ],
    (item) => `<div class="${item.exists ? "good-row" : "warn-row"}"><span>${escapeHtml(item.label)}</span><strong>${item.exists ? "通过" : "缺失"}</strong><em>${escapeHtml(item.detail || item.path || "")}</em></div>`
  );

  const requiredFields = contract.required_fields || [];
  const intakeChecklist = contract.intake_checklist || [];
  const missing = contract.missing || [];
  const contractSetup = contract.setup || {};
  text("franchiseContractStatus", contract.status_text || "待模板");
  text("franchiseContractCount", `${requiredFields.length || 0} 项字段`);
  text("franchiseContractSummary", contract.message || "加盟合同生成器等待合同模板和字段确认。");
  document.querySelector(".module-contract")?.classList.toggle("alert", contract.status === "waiting_template");
  rows(
    "franchiseContractRows",
    [
      ...(missing.length ? [{ label: "当前缺口", value: `${missing.length} 项`, detail: missing.join("、") }] : []),
      { label: "初始化", value: contractSetup.directory_ready && contractSetup.field_template_ready ? "已准备" : "可执行", detail: contractSetup.init_command || "python3 scripts/init_franchise_contract_inbox.py" },
      { label: "字段模板", value: contractSetup.field_template_ready ? "已就绪" : "待生成", detail: contractSetup.field_template_path || "franchise-contract-generator/templates/field_template.csv" },
      ...intakeChecklist.slice(0, 1).map((item) => ({
        label: "接收要求",
        value: item.path || "合同模板",
        detail: item.message || "",
      })),
      ...requiredFields.slice(0, 6).map((field) => ({ label: "字段", value: field, detail: "生成前确认" })),
    ],
    (item) => `<div class="${item.label === "当前缺口" ? "warn-row" : "good-row"}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

function renderFinance() {
  const finance = data.finance_center || {};
  const summary = finance.summary || {};
  const sources = finance.sources || [];
  const intakeChecklist = finance.intake_checklist || [];
  const accounts = finance.accounts || [];
  const missing = finance.missing || [];
  const setup = finance.setup || {};
  const reportGeneration = finance.report_generation || {};
  const ledgerDesign = finance.ledger_design || {};
  const orderFeed = finance.order_automation_feed || {};
  const dailyCollection = finance.daily_collection || {};
  const reconciliationPreview = finance.reconciliation_preview || {};
  const reconciliationSummary = reconciliationPreview.summary || {};
  const reportingPeriod = reconciliationPreview.reporting_period || {};
  const monthlyLedgerPreview = reconciliationPreview.monthly_ledger_preview || {};
  const ledgerPreviewSummary = monthlyLedgerPreview.summary || {};
  const formalLedgerRows = monthlyLedgerPreview.formal_ledgers || [];
  const workPoolRows = monthlyLedgerPreview.work_pools || [];
  const ledgerReviewRows = reconciliationPreview.ledger_review_samples || [];
  const reviewRuleGroups = reconciliationPreview.review_rule_groups || [];
  const reconciliationOutputs = reconciliationPreview.outputs || {};
  const monthlyLedgers = finance.monthly_ledgers || [];
  const assignmentPolicy = finance.ledger_assignment_policy || {};
  const financeChannels = finance.finance_channels || {};
  const channelRows = reconciliationPreview.channel_summary || [];
  const channelReviewRows = reconciliationPreview.channel_review_samples || [];
  const ledgerTables = ledgerDesign.tables || [];
  const orderSources = finance.order_sources || [];
  const paymentRows = dailyCollection.sources || [];
  const waiting = finance.status === "waiting_samples";
  const bankSources = sources.filter((source) => source.id === "bank");
  const bankUploadSources = bankSources.length ? bankSources : sources.slice(0, 1);
  const bankReady = bankUploadSources.some((source) => Number(source.file_count || 0) > 0);
  initializeFinanceFlowControls();
  initializeFinanceOpeningControls();
  const intakeRows = bankUploadSources.map((source) => {
    const fileCount = Number(source.file_count || 0);
    const fields = (source.required_fields || []).slice(0, 4).join("、");
    return {
      label: fileCount > 0 ? "已接收" : "必填",
      value: "银行流水",
      detail: `${fileCount} 个文件 · ${source.path || ""}${fields ? ` · 字段：${fields}` : ""}`,
      path: source.path || "",
      templatePath: source.template_path || "",
      fields,
      fileCount,
      sourceId: source.id || "",
      required: true,
      warn: fileCount === 0,
    };
  });
  const manualInputRows = [
    {
      label: "收入来源",
      value: "Mac mini 自动下载",
      detail: "美团、饿了么、京东、小程序等收入不在录入页手工上传，后续由生产主机定时下载后入账。",
      warn: false,
    },
    {
      label: "人工拆分",
      value: "供应链采购 / 共同费用",
      detail: "用于门店和供应链销售混用的采购，先录支出，再月末拆分。",
      warn: true,
    },
    {
      label: "人工调整",
      value: "应收 / 应付 / 库存",
      detail: "第一版先作为月末调整入口，后续接库存系统和供应商对账；收入不从这里录。",
      warn: true,
    },
    {
      label: "代付结算",
      value: "他人代付",
      detail: "统一进入往来清算，确认后再分配到门店或供应链销售。",
      warn: true,
    },
  ];
  text("financeInputStatus", bankReady ? "可核对" : "待导入");
  text("financeInputCount", bankReady ? "银行流水已到" : "等待银行流水");
  text("financeInputSummary", "录入页只保留银行流水导入；收入由 Mac mini 自动下载平台收入表，其余不明确流水在下方确认。");
  text("financeInputNext", bankReady ? "下一步确认不明确流水，并用手工补录登记流水外的应付、代付和调整。" : "下一步先上传本月银行流水。");
  document.querySelector("#finance-intake")?.classList.toggle("alert", !bankReady || waiting);
  html(
    "financeInputRows",
    intakeRows
      .map(
        (item) => `
          <article class="finance-entry-card ${item.warn ? "needs-input" : "ready-input"}">
            <div class="finance-entry-top">
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(item.value)}</strong>
            </div>
            <div class="finance-entry-status">${item.fileCount} 个文件</div>
            <dl>
              <div>
                <dt>录入位置</dt>
                <dd>${escapeHtml(item.path)}</dd>
              </div>
              <div>
                <dt>模板</dt>
                <dd>${escapeHtml(item.templatePath || "直接上传银行流水 PDF / Excel")}</dd>
              </div>
              <div>
                <dt>关键字段</dt>
                <dd>${escapeHtml(item.fields || "按模板填写")}</dd>
              </div>
            </dl>
            <div class="finance-upload-controls">
              <label>
                <input class="finance-source-file" type="file" multiple data-source-id="${escapeHtml(item.sourceId)}" />
                <span>选择文件</span>
              </label>
              <button class="finance-upload-button" type="button" data-source-id="${escapeHtml(item.sourceId)}" data-source-name="${escapeHtml(item.value)}">上传文件</button>
              <em class="finance-upload-status">未选择文件</em>
            </div>
          </article>
        `
      )
      .join("")
  );
  rows(
    "financeManualRows",
    manualInputRows,
    (item) => `<div class="${item.warn ? "warn-row" : "good-row"}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
  const reviewRows = [
    ...ledgerReviewRows.slice(0, 120).map((item, index) => ({
      ...item,
      index,
      label: item.direction || "待确认",
      value: `${item.source || ""} ${yuan(item.amount)}`,
      detail: `${item.counterparty || ""} · ${item.channel_name || "未知渠道"} · ${item.ledger_name || "待确认账本"}`,
      warn: true,
    })),
    ...(!ledgerReviewRows.length ? channelReviewRows.slice(0, 120).map((item, index) => ({
      ...item,
      index,
      label: item.direction || "待确认",
      value: `${item.source || ""} ${yuan(item.amount)}`,
      detail: `${item.counterparty || ""} · ${item.description || ""}`,
      warn: true,
    })) : []),
  ];
  text("financeReviewStatus", ledgerReviewRows.length ? `${ledgerReviewRows.length} 条待确认` : reviewRows.length ? `${reviewRows.length} 条待确认` : "暂无");
  html(
    "financeReviewRows",
    reviewRows.length
      ? reviewRows.map((item) => {
        const amount = Number(item.amount || 0);
        const date = item.date || item.time || item.transaction_date || "";
        const reviewKey = financeReviewKey(item);
        return `
          <article class="finance-review-card">
            <div class="finance-review-card-main">
              <span>${escapeHtml(date || item.source || "待确认")}</span>
              <strong>${escapeHtml(item.direction || (amount >= 0 ? "收入" : "支出"))} ${yuan(Math.abs(amount))}</strong>
              <em>${escapeHtml(item.counterparty || "未识别往来方")} · ${escapeHtml(item.description || item.channel_name || "无摘要")}</em>
            </div>
            <div class="finance-review-controls">
              <label>
                <span>归属账本</span>
                <select name="review_ledger">
                  <option value="门店总账">门店总账</option>
                  <option value="供应链账">供应链账</option>
                  <option value="待拆分">待拆分</option>
                </select>
              </label>
              <label>
                <span>渠道/科目</span>
                <select name="review_channel">
                  <option value="快驴订货">快驴订货</option>
                  <option value="淘宝采购">淘宝采购</option>
                  <option value="拼多多采购">拼多多采购</option>
                  <option value="京东采购">京东采购</option>
                  <option value="线下扫码/转账">线下扫码/转账</option>
                  <option value="平台收入">平台收入</option>
                  <option value="供应链销售收入">供应链销售收入</option>
                  <option value="供应链采购">供应链采购</option>
                  <option value="他人代付">他人代付</option>
                  <option value="物流/货拉拉">物流/货拉拉</option>
                  <option value="水电燃气">水电燃气</option>
                  <option value="房租/物业">房租/物业</option>
                  <option value="应收账款">应收账款</option>
                  <option value="应付账款">应付账款</option>
                  <option value="人工调整">人工调整</option>
                </select>
              </label>
              <label class="finance-review-note">
                <span>备注</span>
                <input name="review_note" type="text" placeholder="用途、门店、供应商或核销说明" />
              </label>
              <button
                class="finance-review-confirm"
                type="button"
                data-index="${Number(item.index || 0)}"
                data-review-key="${escapeHtml(reviewKey)}"
                data-source="${escapeHtml(item.source || "")}"
                data-date="${escapeHtml(date)}"
                data-direction="${escapeHtml(item.direction || "")}"
                data-amount="${escapeHtml(amount)}"
                data-counterparty="${escapeHtml(item.counterparty || "")}"
                data-description="${escapeHtml(item.description || item.channel_name || "")}"
              >确认归属</button>
              <em class="finance-review-confirm-status">待确认</em>
            </div>
          </article>
        `;
      }).join("")
      : '<div class="empty-line">暂无待确认流水。上传新账单后，系统无法自动判断的流水会出现在这里。</div>'
  );
  initializeFinanceIntakeControls();
  initializeFinanceReviewControls();

  const profitPreview = reconciliationPreview.profit_preview || {};
  const preliminaryTotals = profitPreview.preliminary_totals || {};
  const neededForPnl = profitPreview.needed_for_store_pnl || [];
  const assignedIncome = Number(ledgerPreviewSummary.assigned_income || 0);
  const assignedExpense = Number(ledgerPreviewSummary.assigned_expense || 0);
  const pendingIncome = Number(ledgerPreviewSummary.pending_income || 0);
  const pendingExpense = Number(ledgerPreviewSummary.pending_expense || 0);
  const reportRows = [...formalLedgerRows, ...workPoolRows].filter((row) => row.ledger_type !== "work_pool" || Number(row.count || 0) > 0);
  const canCalculateProfit = profitPreview.status === "ready" && !neededForPnl.length;
  const reportMonth = reportingPeriod.month || "本月";
  const activeLedgerRows = reportRows.length ? reportRows : formalLedgerRows;
  const missingReportItems = neededForPnl.length ? neededForPnl : missing;
  const reportStatusText = canCalculateProfit ? "已出表" : "待生成";
  text("financeReportStatus", reportStatusText);
  text("financeReportCount", canCalculateProfit ? `${Number(ledgerPreviewSummary.formal_ledger_count || formalLedgerRows.length || 2)} 本账` : `${reportMonth} 待生成`);
  text(
    "financeReportSummary",
    canCalculateProfit
      ? (profitPreview.message || "已按门店总账和供应链账生成本月损益表。")
      : "收入账单尚未接入，当前不能计算利润；页面只展示已识别支出和正式报表框架。"
  );
  html(
    "financeReportRows",
    `
      <div class="finance-report-dashboard">
        <section class="finance-report-kpis" aria-label="财务报表摘要">
          <article><span>报表状态</span><strong>${escapeHtml(reportStatusText)}</strong><em>${canCalculateProfit ? "收入、支出已满足出表条件" : "未把缺失收入当作 0 计算"}</em></article>
          <article><span>已识别支出</span><strong>${yuan(assignedExpense + pendingExpense)}</strong><em>当前已进入流水核对的成本费用</em></article>
          <article><span>已接入收入</span><strong>${canCalculateProfit ? yuan(assignedIncome + pendingIncome) : "待平台收入"}</strong><em>美团、饿了么、京东等收入由 Mac mini 自动下载后入账</em></article>
          <article><span>本月利润</span><strong>${canCalculateProfit ? yuan(assignedIncome - assignedExpense) : "暂不计算"}</strong><em>${canCalculateProfit ? "已按当前账本计算" : "收入未接入前不展示亏损数"}</em></article>
        </section>
        <section class="finance-profit-table-wrap">
          <div class="finance-report-title">
            <div>
              <span>${escapeHtml(reportMonth)}</span>
              <strong>门店总账 / 供应链账月度损益表</strong>
            </div>
            <em>${canCalculateProfit ? "第一阶段不拆 5 家门店，先把总账跑通。" : "收入账单接入前，这是待生成报表，不是最终盈亏。"}</em>
          </div>
          <table class="finance-profit-table">
            <thead>
              <tr>
                <th>账本</th>
                <th>收入</th>
                <th>成本费用</th>
                <th>利润</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              ${activeLedgerRows.map((row) => `
                <tr class="${row.ledger_type === "work_pool" ? "pending-row" : ""}">
                  <td>${escapeHtml(row.ledger_name || row.ledger_id)}</td>
                  <td>${canCalculateProfit ? yuan(row.income) : "<span class=\"pending-value\">待平台收入</span>"}</td>
                  <td>${yuan(row.expense)}</td>
                  <td>${canCalculateProfit ? yuan(row.net) : "<span class=\"pending-value\">待收入后计算</span>"}</td>
                  <td>${escapeHtml(canCalculateProfit ? (row.ledger_type === "work_pool" ? `待分配 ${Number(row.count || 0)} 笔` : row.status === "assigned" ? "已归属" : "待规则") : "待收入账单")}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </section>
        <section class="finance-report-notes">
          <article>
            <span>流水预览</span>
            <strong>${Number(reconciliationSummary.transaction_count || 0)} 笔本期流水</strong>
            <em>已识别支出 ${yuan(preliminaryTotals.payment_statement_expense)}；收入未接入时不计入利润</em>
          </article>
          <article>
            <span>出表缺口</span>
            <strong>${missingReportItems.length || 0} 项</strong>
            <em>${escapeHtml(missingReportItems.slice(0, 3).join("；") || "暂无明显缺口")}</em>
          </article>
        </section>
      </div>
    `
  );
  initializeFinanceArapControls();
  rows(
    "financeStockRows",
    [
      { label: "计算公式", value: "月初 + 采购 - 月末", detail: "等于本月实际耗用成本，进入利润表成本。" },
      { label: "第一版", value: "月度盘点", detail: "先只记录月初和月末库存金额，不做每日明细。" },
    ],
    (item) => `<div class="good-row"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );
}

function sectionForHash(hash) {
  if (!hash || hash === "overview") return null;
  const target = document.getElementById(hash);
  if (!target) return null;
  return target.classList.contains("center-section") ? target : target.closest(".center-section");
}

function activatePage() {
  const anchorLinks = navLinks.filter((link) => (link.getAttribute("href") || "").startsWith("#"));
  const requestedHash = window.location.hash.replace("#", "");
  const activeSection = sectionForHash(requestedHash);
  const activeHash = activeSection ? requestedHash : "overview";
  const showOverview = !activeSection;

  if (commandBoard) commandBoard.hidden = !showOverview;
  if (overviewAlert) overviewAlert.hidden = !showOverview;
  pageSections.forEach((section) => {
    section.hidden = section !== activeSection;
  });
  mainView?.classList.toggle("is-overview", showOverview);
  mainView?.classList.toggle("is-detail", !showOverview);

  document.querySelectorAll(".module.is-focused").forEach((module) => {
    module.classList.remove("is-focused");
  });
  if (activeSection && requestedHash && requestedHash !== activeSection.id) {
    document.getElementById(requestedHash)?.classList.add("is-focused");
  }

  anchorLinks.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${activeHash}`);
  });
}

async function loadDailyOrderAdminFrame() {
  const frame = document.querySelector(".ordering-admin-frame");
  if (!frame) return;
  const orderingAdminSrc = frame.dataset.orderingAdminSrc || "/daily-order/admin?token=daily-order-admin";
  frame.src = resolveEmbeddedUrl(orderingAdminSrc);
}

async function loadDailyReportFrame() {
  const frame = document.querySelector(".daily-report-frame");
  if (!frame) return;
  const reportSrc = frame.dataset.reportSrc || "/business-report-dashboard/";
  await loadEmbeddedFrame(frame, reportSrc, "正在加载经营日报...", "经营日报加载失败", "打开经营日报");
}

async function loadInventoryBoardFrame() {
  const frame = document.querySelector(".inventory-board-frame");
  if (!frame) return;
  const inventorySrc = frame.dataset.inventorySrc || "/";
  await loadEmbeddedFrame(frame, inventorySrc, "正在加载成都仓库存管理...", "成都仓库存管理加载失败", "打开成都仓库存管理");
}

async function loadEmbeddedFrame(frame, source, loadingText, failureTitle, linkText) {
  const reportUrl = resolveEmbeddedUrl(source);
  frame.srcdoc = `<!doctype html><html lang="zh-CN"><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,sans-serif;color:#667085;">${escapeHtml(loadingText)}</body></html>`;
  try {
    const response = await fetch(reportUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let html = await response.text();
    const baseTag = `<base href="${escapeHtml(reportUrl)}">`;
    if (/<head[^>]*>/i.test(html)) {
      html = html.replace(/<head([^>]*)>/i, `<head$1>${baseTag}`);
    } else {
      html = `<!doctype html><html lang="zh-CN"><head>${baseTag}</head><body>${html}</body></html>`;
    }
    frame.srcdoc = html;
  } catch (error) {
    frame.srcdoc = `<!doctype html><html lang="zh-CN"><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,sans-serif;color:#667085;">
      <strong style="display:block;color:#172033;margin-bottom:8px;">${escapeHtml(failureTitle)}</strong>
      <span>请刷新页面，或临时打开独立页面。</span>
      <a style="display:inline-block;margin-left:8px;color:#2563eb;" href="${escapeHtml(reportUrl)}" target="_blank" rel="noreferrer">${escapeHtml(linkText)}</a>
    </body></html>`;
    console.warn("Failed to load embedded frame", error);
  }
}

function resolveEmbeddedUrl(source) {
  try {
    return new URL(source, document.baseURI || window.location.href).href;
  } catch (error) {
    return source;
  }
}

const gitLabel = data.system?.git?.commit ? ` · 版本 ${data.system.git.commit}` : "";
text("generatedAt", `数据更新时间：${data.generated_at || "未生成"}${gitLabel}`);
renderDaily();
renderPriority();
renderHealth();
renderReviews();
renderBalances();
renderBudget();
renderBidding();
renderOrdering();
renderInventory();
renderTools();
renderFinance();
window.addEventListener("hashchange", activatePage);
activatePage();
loadDailyOrderPendingSummary();
loadDailyOrderAdminFrame();
loadDailyReportFrame();
loadInventoryBoardFrame();
