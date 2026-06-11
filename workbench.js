const data = window.WORKBENCH_DATA || {};

const sections = [...document.querySelectorAll(".module, .topbar")];
const navLinks = [...document.querySelectorAll(".nav a")];

const yuan = (value) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: 0,
  })}`;

const num = (value, digits = 0) =>
  Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
  });

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
    return `较昨日同时段 ${signedNumber(realtimeOrders.delta)} 单`;
  }
  if (!previous || previous.status === "missing") return previous?.message || "昨日同时段 暂无历史数据，明天开始生成";
  const previousIncome = Number(previous.income ?? previous.total_income ?? 0);
  const previousOrders = Number(previous.orders ?? previous.total_orders ?? 0);
  const incomeDelta = currentIncome - previousIncome;
  const orderDelta = currentOrders - previousOrders;
  const moneyText = `${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}`;
  const orderText = `${orderDelta >= 0 ? "+" : "-"}${num(Math.abs(orderDelta))} 单`;
  return `较昨日同时段 ${moneyText} / ${orderText}`;
}

function signedNumber(value) {
  const rounded = Math.round(Number(value || 0));
  return `${rounded > 0 ? "+" : ""}${num(rounded)}`;
}

function text(id, value) {
  const el = document.querySelector(`#${id}`);
  if (el) el.textContent = value;
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
  return String(value || "")
    .replace(/熊小小牛排饭/g, "")
    .replace(/POKEBEAR/g, "")
    .replace(/[（）()]/g, "")
    .replace(/[·]/g, "")
    .slice(0, 18);
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

function realtimeStoreDetail(item) {
  const platforms = item.platforms || {};
  const eleme = platforms["饿了么"] || item.eleme || {};
  const meituan = platforms["美团"] || item.meituan || {};
  const elemeOrders = Number(item.eleme_orders ?? eleme.orders ?? 0);
  const elemeIncome = Number(item.eleme_income ?? eleme.income ?? 0);
  const meituanOrders = Number(item.meituan_orders ?? meituan.orders ?? 0);
  const meituanIncome = Number(item.meituan_income ?? meituan.income ?? 0);
  const parts = [];
  if (elemeOrders || elemeIncome) parts.push(`饿了么 ${num(elemeOrders)} 单 / ${yuan(elemeIncome)}`);
  if (meituanOrders || meituanIncome) parts.push(`美团 ${num(meituanOrders)} 单 / ${yuan(meituanIncome)}`);
  return parts.join(" · ") || "等待平台拆分";
}

function realtimeStoreCompare(item, compareMap) {
  const store = item.store || item.store_name || item.name || "未命名门店";
  const previous = compareMap.get(store);
  if (!previous) return data.realtime_comparison?.message || "昨日同时段 明天开始生成";
  if (previous.orders) {
    const orders = previous.orders || {};
    return `较昨日同时段 ${signedNumber(orders.delta)} 单`;
  }
  const incomeDelta = Number(previous.income_delta ?? realtimeStoreIncome(item) - Number(previous.income || 0));
  const orderDelta = Number(previous.orders_delta ?? realtimeStoreOrders(item) - Number(previous.orders || 0));
  const moneyText = `${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}`;
  const orderText = `${orderDelta >= 0 ? "+" : "-"}${num(Math.abs(orderDelta))} 单`;
  return `较昨日同时段 ${moneyText} / ${orderText}`;
}

function renderRealtimeCard(daily, stores, totalIncome, totalOrders) {
  const realtime = data.realtime || {};
  const summary = realtime.summary || {};
  const sourceStores = realtimeStores(daily);
  const compareMap = yesterdayStoreMap(daily);
  const covered = sourceStores.filter((item) => realtimeStoreOrders(item) || realtimeStoreIncome(item)).length;
  const platformCoverage = Number(summary.platform_store_count || 0);
  const platformTarget = platformCoverage || summary.missing_count !== undefined ? platformCoverage + Number(summary.missing_count || 0) : 0;
  const targetCount = Number(realtime.target_count ?? daily.target_stores?.length ?? sourceStores.length);
  const missing = Number(summary.missing_count ?? Math.max(0, targetCount - covered));
  const generatedAt = realtime.generated_at || realtime.collected_at || data.generated_at || "-";

  text("realtimeIncome", yuan(totalIncome));
  text("realtimeOrders", `${num(totalOrders)} 单`);
  text("realtimeCoverage", platformTarget ? `${platformCoverage}/${platformTarget}` : `${covered}/${targetCount || sourceStores.length || 0}`);
  text("realtimeStatus", realtime.status === "ok" || realtime.status === "ready" || sourceStores.length ? "已同步" : "待采集");
  text("realtimeMeta", `最近采集：${generatedAt}，覆盖 ${covered || 0} 家门店，缺失 ${missing} 个平台门店。`);

  rows(
    "realtimeStoreRows",
    sourceStores
      .slice()
      .sort((a, b) => realtimeStoreIncome(b) - realtimeStoreIncome(a))
      .slice(0, 8),
    (item) => {
      const store = item.store || item.store_name || item.name || "未命名门店";
      return `<div class="realtime-store"><span>${store}</span><strong>${yuan(realtimeStoreIncome(item))}</strong><em>${num(realtimeStoreOrders(item))} 单</em><em class="realtime-compare">${realtimeStoreCompare(item, compareMap)}</em><em>${realtimeStoreDetail(item)}</em></div>`;
    }
  );
}

function renderDaily() {
  const daily = data.daily || {};
  const realtime = data.realtime || {};
  const realtimeSummary = realtime.summary || {};
  const latestDate = latestDailyDate(daily);
  const latestRecords = latestDailyRows(daily);
  const stores = storeTotals(latestRecords);
  const dailyIncome = latestRecords.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const dailyOrders = latestRecords.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const totalIncome = Number(realtime.income ?? realtime.total_income ?? realtimeSummary.total_income ?? dailyIncome);
  const totalOrders = Number(realtime.orders ?? realtime.total_orders ?? realtimeSummary.total_orders ?? dailyOrders);
  text("metricIncomeLabel", "实时数据");
  text("metricIncome", yuan(totalIncome));
  text("metricOrders", `实时单量 ${num(totalOrders)} 单`);
  text("metricYesterdayCompare", comparisonLabel(totalIncome, totalOrders, sameTimeYesterday(daily)));
  renderRealtimeCard(daily, stores, totalIncome, totalOrders);
  text("dailyStoreCount", `${stores.length || 0} 家`);
  text("dailySummary", `只看最新日报日期 ${latestDate || "-"}：总收入 ${yuan(dailyIncome)}，总单量 ${num(dailyOrders)} 单，覆盖 ${stores.length || 0} 家门店。`);
  rows(
    "dailyRows",
    stores
      .slice()
      .sort((a, b) => Number(b.income || 0) - Number(a.income || 0))
      .slice(0, 8),
    (item) => `<div class="good-row"><span>${item.store}</span><strong>${yuan(item.income)}</strong><em>${num(item.orders)} 单</em></div>`
  );
}

function renderAnomalies() {
  const daily = data.daily || {};
  const latestDate = latestDailyDate(daily);
  const anomalies = groupedAnomalies(daily.focus_items || []);
  text("anomalyCount", `${anomalies.length} 家`);
  text("anomalyStatus", anomalies.length ? "需处理" : "正常");
  text("anomalySummary", anomalies.length ? `${latestDate || "最新日报"} 发现 ${anomalies.length} 家异常门店，优先处理高风险项。` : `${latestDate || "最新日报"} 暂无异常门店。`);
  rows(
    "anomalyRows",
    anomalies,
    (group) => {
      const issues = group.issues.map((item) => item.title).join("；");
      const body = group.issues.map((item) => item.body).filter(Boolean)[0] || "请打开日报查看详情。";
      return `<div class="warn-row"><span>${group.store}</span><strong>${group.issues.length} 项异常</strong><em>${issues}。${body}</em></div>`;
    }
  );
}

function renderReviews() {
  const daily = data.daily || {};
  const review = daily.review_summary || {};
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
  const statusText = review.status === "ready" ? "已同步" : review.status === "stale" ? "旧数据" : "待同步";

  text("reviewStatus", statusText);
  text("reviewCount", `${totalReviews} 条`);
  text(
    "reviewSummary",
    review.message || `当前评价预览覆盖 ${stores.length} 家门店，疑似问题评价 ${totalIssues} 条。`
  );
  document.querySelector("#reviews")?.classList.toggle("alert", totalIssues > 0);

  rows(
    "reviewRows",
    stores
      .slice()
      .sort((a, b) => b.negative_count - a.negative_count || b.review_count - a.review_count)
      .slice(0, 8),
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

function renderBalances() {
  const balances = data.balances || {};
  const summary = balances.summary || {};
  const warnings = (balances.items || []).filter((item) => item.status === "warning");
  text("metricWarnings", `${summary.warning_count ?? warnings.length} 个`);
  text("metricLowest", `最低 ${yuan(summary.lowest_balance || 0)} · ${summary.store_count || 0} 条`);
  text("balanceWarningCount", `${summary.warning_count ?? warnings.length} 个`);
  text("balanceSummary", `最新巡检：${balances.generated_at || "-"}，阈值 ${yuan(balances.threshold || 100)}`);
  text("balanceStatus", balances.status === "ok" ? "正常" : "注意");
  cls("balanceMetricCard", "alert", warnings.length > 0);
  document.querySelector("#balances")?.classList.toggle("alert", warnings.length > 0);
  document.querySelector("#metricLowest")?.classList.toggle("danger", warnings.length > 0);
  rows(
    "balanceRows",
    warnings.slice(0, 6),
    (item) => `<div class="warn-row"><span>${item.platform} · ${shortStore(item.store_name)}</span><strong>${yuan(item.balance)}</strong><em>需充值</em></div>`
  );
}

function renderBudget() {
  const budget = data.budget || {};
  const summary = budget.summary || {};
  const eleme = budget.eleme_lunch || [];
  const meituan = budget.meituan_lunch || [];
  text("metricBudget", `${summary.total_initial_budget_items || eleme.length + meituan.length} 项`);
  text("metricBudgetMeta", `饿了么 ${eleme.length} 自动 · 美团 ${meituan.length} 自动`);
  text("budgetCount", `${eleme.length + meituan.length} 项`);
  text("budgetSummary", `预览生成：${budget.generated_at || "-"}。饿了么和美团都已接入上午按钮自动执行。`);
  rows(
    "budgetRows",
    [...eleme.slice(0, 4), ...meituan.slice(0, 4)],
    (item) => `<div><span>${item.platform} · ${shortStore(item.store)}</span><strong>${yuan(item.targetBudget)}</strong><em>${item.status === "auto" ? "自动" : "人工"}</em></div>`
  );
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

function activateNav() {
  const anchorLinks = navLinks.filter((link) => (link.getAttribute("href") || "").startsWith("#"));
  if (!anchorLinks.length) return;
  const hash = window.location.hash.replace("#", "");
  const hashSection = hash ? sections.find((section) => section.id === hash) : null;
  const current = hashSection || sections
    .map((section) => ({
      id: section.id,
      top: Math.abs(section.getBoundingClientRect().top - 90),
    }))
    .sort((a, b) => a.top - b.top)[0];

  if (!current) return;
  anchorLinks.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${current.id}`);
  });
}

text("generatedAt", `数据更新时间：${data.generated_at || "未生成"}`);
renderDaily();
renderAnomalies();
renderReviews();
renderBalances();
renderBudget();
renderInventory();
window.addEventListener("scroll", activateNav, { passive: true });
activateNav();
