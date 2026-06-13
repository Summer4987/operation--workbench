const data = window.WORKBENCH_DATA || {};

const mainView = document.querySelector(".main");
const commandBoard = document.querySelector(".command-board");
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
      return `
        <div class="realtime-store">
          <div class="realtime-store-head">
            <span>${escapeHtml(store)}</span>
            <em class="realtime-compare">${escapeHtml(realtimeStoreCompare(item, compareMap))}</em>
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
  const realtime = data.realtime || {};
  const realtimeSummary = realtime.summary || {};
  const latestDate = latestDailyDate(daily);
  const latestRecords = latestDailyRows(daily);
  const stores = storeTotals(latestRecords);
  const platforms = daily.platform_summary || [];
  const focusItems = daily.focus_items || [];
  const highFocusCount = focusItems.filter((item) => item.level === "high").length;
  const dailyIncome = latestRecords.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const dailyOrders = latestRecords.reduce((sum, item) => sum + Number(item.orders || 0), 0);
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
  text("dailyStoreCount", `${stores.length || 0} 家`);
  text("dailySummary", `只看最新日报日期 ${latestDate || "-"}：总收入 ${yuan(dailyIncome)}，总单量 ${num(dailyOrders)} 单，覆盖 ${stores.length || 0} 家门店。`);
  text("dailyPageSummary", `最新日报日期 ${latestDate || "-"}：按门店、平台和异常项拆开看，优先处理高优先级日报异常。`);
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
  rows(
    "dailyPlatformRows",
    platforms,
    (item) => {
      const detail = [
        `曝光 ${num(item.impressions)}`,
        `访问转化 ${pct(item.visit_conversion)}`,
        `下单转化 ${pct(item.order_conversion)}`,
        `新客 ${num(item.new_customer_orders)} 单`,
        `老客 ${num(item.old_customer_orders)} 单`,
      ].join(" · ");
      return `<div class="good-row"><span>${escapeHtml(item.platform || "平台")}</span><strong>${yuan(item.income)} / ${num(item.orders)} 单</strong><em>${escapeHtml(detail)}</em></div>`;
    }
  );
  rows(
    "dailyFocusRows",
    focusItems.slice(0, 5),
    (item) => `<div class="${item.level === "high" ? "warn-row" : "good-row"}"><span>${escapeHtml(item.store || "门店")}</span><strong>${escapeHtml(item.title || "日报异常")}</strong><em>${escapeHtml(item.body || "打开完整日报复核详情。")}</em></div>`
  );
  rows(
    "dailyRows",
    stores
      .slice()
      .sort((a, b) => Number(b.income || 0) - Number(a.income || 0))
      .slice(0, 8),
    (item) => `<div class="good-row"><span>${escapeHtml(item.store)}</span><strong>${yuan(item.income)}</strong><em>${num(item.orders)} 单 · 曝光 ${num(item.impressions)} · 覆盖 ${num(item.platform_count)} 平台</em></div>`
  );
}

function priorityItems() {
  const balances = data.balances || {};
  const promoBalanceStatus = data.promo_balance_status || {};
  const promoBalanceSummary = promoBalanceStatus.summary || {};
  const realtimeCollection = data.realtime_collection || {};
  const realtimeFailures = realtimeCollection.platform_failures || [];
  const realtimeSummary = realtimeCollection.summary || {};
  const inventory = data.inventory || {};
  const daily = data.daily || {};
  const taskHealth = data.task_health || {};
  const userActionQueue = data.user_action_queue || {};
  const balanceWarnings = promoBalanceStatus.low_balance_items || (balances.items || []).filter((item) => item.status === "warning");
  const platformFailures = (promoBalanceStatus.platforms || []).filter((item) => item.status === "failed");
  const inventoryWarnings = (inventory.items || []).filter((item) => Number(item.balance || 0) <= Number(item.warning_threshold || 0));
  const automationWarnings = groupedAnomalies(daily.focus_items || []).slice(0, 3);
  const taskWarnings = (taskHealth.tasks || []).filter((item) => item.status === "danger").slice(0, 3);
  const items = [];

  (userActionQueue.items || []).slice(0, 3).forEach((item) => {
    items.push({
      type: "用户待办",
      title: item.title || "待处理事项",
      detail: compactText(item.brief_action || item.reason || item.action || "请查看 AI 运营建议。"),
      level: item.priority === "high" ? "danger" : "warning",
    });
  });
  if (inventoryWarnings.length) {
    items.push({
      type: "库存不足",
      title: `${inventoryWarnings.length} 个库存预警`,
      detail: inventoryWarnings.slice(0, 3).map((item) => item.name).join("、"),
      level: "danger",
    });
  }
  if (platformFailures.length) {
    const evidenceCount = Number(promoBalanceSummary.evidence_count || 0);
    items.push({
      type: "推广巡检失败",
      title: `${promoBalanceSummary.platform_failure_count || platformFailures.length} 个平台失败`,
      detail: [
        platformFailures.map((item) => item.recovery?.summary || `${item.platform}：${item.failure_type || "需处理"}`).join("；"),
        evidenceCount ? `证据 ${evidenceCount} 个` : "",
      ].filter(Boolean).join("；"),
      level: "danger",
    });
  }
  if (realtimeFailures.length) {
    items.push({
      type: "实时采集失败",
      title: `${realtimeSummary.platform_failure_count || realtimeFailures.length} 个平台失败`,
      detail: realtimeFailures.map((item) => item.recovery_summary || `${item.platform}：缺 ${item.missing_count || 0} 个门店`).join("；"),
      level: realtimeCollection.status === "missing_latest" ? "danger" : "warning",
    });
  }
  if (balanceWarnings.length) {
    const lowest = balanceWarnings.slice().sort((a, b) => Number(a.balance || 0) - Number(b.balance || 0))[0];
    items.push({
      type: "推广余额不足",
      title: `${balanceWarnings.length} 个余额预警`,
      detail: lowest ? `${lowest.platform} · ${shortStore(lowest.store_name)} ${yuan(lowest.balance)}` : "请打开余额巡检",
      level: "warning",
    });
  }
  automationWarnings.forEach((group) => {
    items.push({
      type: "自动化异常",
      title: `${group.store} ${group.issues.length} 项异常`,
      detail: group.issues.map((item) => item.title).join("；"),
      level: "danger",
    });
  });
  taskWarnings.forEach((task) => {
    items.push({
      type: "任务健康",
      title: `${task.name} ${task.status_text || "需处理"}`,
      detail: task.human_action || task.reason || "请查看自动化任务健康报告。",
      level: "danger",
    });
  });
  if (!items.length) {
    items.push({
      type: "今日状态",
      title: "暂无重点预警",
      detail: "库存、余额和日报异常未发现需要优先处理的事项。",
      level: "ok",
    });
  }
  return items;
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

function renderHealth() {
  const taskHealth = data.task_health || {};
  const macminiSmoke = data.macmini_smoke_status || {};
  const operationCheck = data.operation_automation_check || {};
  const summary = taskHealth.summary || {};
  const environment = taskHealth.environment || {};
  const tasks = (taskHealth.tasks || []).filter((task) => task.status !== "planned").slice(0, 8);
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
  const healthRows = operationEnvironment.role === "production" || operationBlockers.length
    ? [operationRow, smokeRow, ...tasks]
    : [smokeRow, ...tasks, operationRow];
  rows(
    "healthRows",
    healthRows.slice(0, 8),
    (task) => {
      const cls = task.status === "ok" ? "good-row" : "warn-row";
      const meta = [
        task.reason,
        task.repair_guide ? `向导：${task.repair_guide}` : "",
        task.human_action ? `处理：${task.human_action}` : "",
        task.last_seen_at ? `最近：${task.last_seen_at}` : "",
        task.environment_label || environment.label || "",
      ].filter(Boolean).join(" · ");
      return `<div class="${cls}"><span>${escapeHtml(task.name)}</span><strong>${escapeHtml(task.status_text || task.status)}</strong><em>${escapeHtml(meta || task.next_step || "-")}</em></div>`;
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
  const actionItems = reviewActions.items || [];
  const completedItems = reviewActions.completed_items || [];
  const actionSummary = reviewActions.summary || {};
  const weeklyRecap = reviewActions.weekly_recap || {};
  const weeklySummary = weeklyRecap.summary || {};
  const weeklyPeriod = weeklyRecap.period || {};
  const recapPlan = reviewActions.recap_plan || {};
  const followupPlan = reviewActions.followup_plan || {};
  const sopPlan = reviewActions.sop_plan || {};
  const sopClosurePlan = reviewActions.sop_closure_plan || {};
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
  const completedNegative = Number(actionSummary.completed_negative_count || 0);
  const missingEvidence = Number(actionSummary.missing_evidence_count || 0);
  const completedWithEvidence = Number(actionSummary.completed_with_evidence_count || 0);
  const statusText = pendingNegative
    ? "待回复"
    : missingEvidence
      ? "待补证据"
      : completedWithEvidence
        ? "已闭环"
        : review.status === "ready"
          ? "已同步"
          : review.status === "stale"
            ? "旧数据"
            : "待同步";

  text("reviewStatus", statusText);
  text("reviewCount", `${totalReviews} 条`);
  text(
    "reviewSummary",
    `${reviewActions.message || review.message || `当前评价预览覆盖 ${stores.length} 家门店，疑似问题评价 ${totalIssues} 条。`}${completedNegative ? ` 已记录回复 ${completedNegative} 条。` : ""}${missingEvidence ? ` 待补证据 ${missingEvidence} 条。` : ""}`
  );
  document.querySelector("#reviews")?.classList.toggle("alert", pendingNegative > 0);

  rows(
    "reviewCommandRows",
    [
      {
        label: "本周评价",
        value: `${num(weeklySummary.review_count || actionSummary.weekly_review_count || 0)} 条`,
        detail: weeklyPeriod.start_date && weeklyPeriod.end_date ? `${weeklyPeriod.start_date} 至 ${weeklyPeriod.end_date}` : "等待评价历史",
        tone: "neutral",
      },
      {
        label: "本周问题率",
        value: `${((Number(weeklySummary.negative_rate || 0)) * 100).toFixed(1)}%`,
        detail: `疑似问题 ${num(weeklySummary.negative_count || actionSummary.weekly_negative_count || 0)} 条`,
        tone: Number(weeklySummary.negative_count || 0) ? "warn" : "good",
      },
      {
        label: "今日待回复",
        value: `${num(pendingNegative)} 条`,
        detail: actionItems.length ? `${actionItems.length} 家门店需要处理` : "暂无待回复差评",
        tone: pendingNegative ? "warn" : "good",
      },
      {
        label: "闭环进度",
        value: `${num(completedNegative)} 条`,
        detail: missingEvidence ? `待补证据 ${num(missingEvidence)} 条` : "回复证据无缺口",
        tone: missingEvidence ? "warn" : "good",
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
        label: "周复盘结论",
        value: weeklyRecap.status === "needs_review" ? "需复盘" : weeklyRecap.status === "stable" ? "稳定" : "待生成",
        detail: weeklyRecap.message || "暂无评价历史可生成周复盘。",
        className: weeklyRecap.status === "needs_review" ? "warn-row" : "good-row",
      },
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
    "reviewWorkflowRows",
    [
      {
        label: "复盘记录",
        value: `${num(recapPlan.pending_count || 0)} 待记录 / ${num(recapPlan.recorded_count || 0)} 已记录`,
        detail: recapPlan.next_action || recapPlan.message || "评价复盘均已记录。",
        className: Number(recapPlan.pending_count || 0) ? "warn-row" : "good-row",
      },
      {
        label: "7天跟踪",
        value: `${num(followupPlan.recurred_count || 0)} 复发 / ${num(followupPlan.watching_count || 0)} 观察`,
        detail: followupPlan.next_action || followupPlan.message || "暂无需要跟踪的评价复盘。",
        className: Number(followupPlan.recurred_count || 0) ? "warn-row" : "good-row",
      },
      {
        label: "SOP整改",
        value: `${num(sopPlan.waiting_count || 0)} 待开 / ${num(sopPlan.open_count || 0)} 进行中`,
        detail: sopPlan.next_action || sopPlan.message || "暂无复发项需要 SOP 整改。",
        className: Number(sopPlan.waiting_count || sopPlan.open_count || 0) ? "warn-row" : "good-row",
      },
      {
        label: "关闭复查",
        value: `${num(sopClosurePlan.reopen_count || 0)} 复发 / ${num(sopClosurePlan.stable_count || 0)} 稳定`,
        detail: sopClosurePlan.next_action || sopClosurePlan.message || "暂无已关闭 SOP 整改需要复查。",
        className: Number(sopClosurePlan.reopen_count || 0) ? "warn-row" : "good-row",
      },
    ],
    (item) => `<div class="${item.className}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  rows(
    "reviewRows",
    (actionItems.length
      ? [
          ...actionItems.map((item) => ({ ...item, kind: "action" })),
          ...completedItems.slice(0, 3).map((item) => ({ ...item, kind: "completed" })),
        ]
      : completedItems.length
        ? completedItems.slice(0, 8).map((item) => ({ ...item, kind: "completed" }))
        : stores)
      .slice()
      .sort((a, b) => Number(b.negative_count || 0) - Number(a.negative_count || 0) || Number(b.review_count || 0) - Number(a.review_count || 0))
      .slice(0, 8),
    (item) => {
      if (item.kind === "action") {
        const keywords = (item.keywords || []).length ? item.keywords.join("、") : "无集中关键词";
        const platforms = (item.platforms || []).map((platform) => `${platform.platform} ${platform.negative_count} 条`).join("；") || "平台待确认";
        const firstPlatform = (item.platforms || [])[0]?.platform || "";
        const recordCommand = `python3 scripts/record_review_reply.py --store ${item.store} --date ${item.date || ""}${firstPlatform ? ` --platform ${firstPlatform}` : ""} --note '<回复摘要>' --evidence-url '<平台截图或评价链接>'`;
        const examples = (item.examples || []).map((content, index) => `<span class="bad-review">${index + 1}. ${escapeHtml(content)}</span>`).join("");
        const exampleText = examples ? `<br><b class="bad-review-title">差评内容</b>${examples}` : "";
        return `<div class="warn-row"><span>${escapeHtml(item.store)}</span><strong>待回复 ${num(item.negative_count)} 条</strong><em>${escapeHtml(platforms)} · 关键词：${escapeHtml(keywords)}<br>${escapeHtml(item.reply_suggestion || item.human_action || "先查看平台评价详情后回复。")}<br>记录：${escapeHtml(recordCommand)}${exampleText}</em></div>`;
      }
      if (item.kind === "completed") {
        const platform = item.platform ? `${item.platform} · ` : "";
        const evidence = item.evidence || {};
        const evidenceTarget = evidence.url || evidence.web_path || evidence.path || "";
        const evidenceLink = evidence.status === "ready" && evidenceTarget ? `<a class="evidence-link" href="${escapeHtml(evidenceTarget)}" target="_blank" rel="noreferrer">查看证据</a>` : "";
        const evidencePreview = evidence.status === "ready" && evidence.type === "image" && evidence.web_path ? `<img class="evidence-preview" src="${escapeHtml(evidence.web_path)}" alt="评价回复证据截图" />` : "";
        const uploadCommand = evidence.attach_command || `python3 scripts/attach_review_reply_evidence.py --store ${item.store} --date ${item.date || ""}${item.platform ? ` --platform ${item.platform}` : ""} --file '<平台截图路径>'`;
        const evidenceText = evidence.status === "ready" ? `证据：${evidenceTarget}` : `待补平台截图或链接证据；上传：${uploadCommand}`;
        const note = item.note || item.operator || item.recorded_at || "已人工回复";
        const cls = evidence.status === "ready" ? "good-row" : "warn-row";
        return `<div class="${cls}"><span>${escapeHtml(item.store)}</span><strong>${escapeHtml(platform)}已回复</strong><em>${escapeHtml(`${item.date || ""} ${note} · ${evidenceText}`.trim())}${evidenceLink ? `<br>${evidenceLink}` : ""}${evidencePreview}</em></div>`;
      }
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
  const promoBalanceStatus = data.promo_balance_status || {};
  const summary = promoBalanceStatus.summary || balances.summary || {};
  const evidenceSync = promoBalanceStatus.evidence_sync || {};
  const warnings = promoBalanceStatus.low_balance_items || (balances.items || []).filter((item) => item.status === "warning");
  const platformFailures = (promoBalanceStatus.platforms || []).filter((item) => item.status === "failed");
  const platformFailureCount = Number(summary.platform_failure_count || platformFailures.length || 0);
  const lowBalanceCount = Number(summary.low_balance_count ?? summary.warning_count ?? warnings.length);
  const needsAttention = platformFailureCount > 0 || lowBalanceCount > 0;
  const statusText = platformFailureCount ? "巡检失败" : lowBalanceCount ? "需充值" : "正常";
  text("metricWarnings", `${lowBalanceCount} 个`);
  text("metricLowest", `最低 ${yuan(summary.lowest_balance || 0)} · ${summary.store_count || 0} 条`);
  text("balanceWarningCount", `${lowBalanceCount} 个`);
  text(
    "balanceSummary",
    `最新巡检：${promoBalanceStatus.source_generated_at || balances.generated_at || "-"}，平台失败 ${platformFailureCount} 个，低余额 ${lowBalanceCount} 个，阈值 ${yuan(summary.warning_threshold || balances.threshold || 100)}，证据清单 ${evidenceSync.file_count || 0} 个，云端保留 ${evidenceSync.cloud_retention_days || 0} 天`
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
    ],
    (item) => {
      if (item.kind !== "platform_failure") {
        const gap = Math.max(0, Number(item.threshold || 0) - Number(item.balance || 0));
        return `<div class="warn-row"><span>${escapeHtml(item.platform)} · ${escapeHtml(shortStore(item.store_name))}</span><strong>${yuan(item.balance)}</strong><em>阈值 ${yuan(item.threshold || 0)} · 差额 ${yuan(gap)}</em></div>`;
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

function renderBudget() {
  const budget = data.budget || {};
  const retry = data.promo_budget_retry || {};
  const summary = budget.summary || {};
  const retrySummary = retry.summary || {};
  const eleme = budget.eleme_lunch || [];
  const meituan = budget.meituan_lunch || [];
  text("metricBudget", `${summary.total_initial_budget_items || eleme.length + meituan.length} 项`);
  text("metricBudgetMeta", `饿了么 ${eleme.length} 自动 · 美团 ${meituan.length} 自动`);
  text("budgetCount", `${eleme.length + meituan.length} 项`);
  const weekend = budget.weekend_preset || {};
  const affectedByLatestRun = retrySummary.affected_by_latest_run_count || 0;
  const retryGuide = (retry.repair_guides || [])[0] || {};
  const retryGuideStep = (retryGuide.checklist || [])[0] || "";
  const retryText = retry.status === "ready" ? `门店级重试：${retrySummary.safe_retry_count || 0} 项可重试，${retrySummary.manual_count || 0} 项需人工${affectedByLatestRun ? `，最近执行影响 ${affectedByLatestRun} 项` : ""}${retryGuide.title ? `，修复向导 ${retrySummary.repair_guide_count || (retry.repair_guides || []).length} 个` : ""}。` : "门店级重试策略待生成。";
  const weekendStatusText = weekend.status === "active" ? "今日生效" : weekend.status === "configured_inactive" ? "待启用" : "待配置";
  const weekendMessage = weekend.message || (weekend.enabled ? `${weekend.name || "周末预设"}今日生效。` : "周末预设待配置，当前不会改变任何门店预算。");
  text("budgetSummary", `预览生成：${budget.generated_at || "-"}。饿了么和美团都已接入上午按钮自动执行；周末预设：${weekendStatusText}，${weekendMessage}${retryText}`);
  rows(
    "budgetRows",
    [
      ...(weekend.status ? [{ platform: "周末预设", store: weekend.name || "周末方案", targetBudget: weekend.total_budget || 0, status: weekend.status, action: weekend.next_action || weekendMessage }] : []),
      ...eleme.slice(0, 4),
      ...meituan.slice(0, 4),
    ],
    (item) => {
      const statusLabel = item.status === "auto" ? "自动" : item.status === "active" ? "今日生效" : item.status === "configured_inactive" ? "待启用" : item.status === "not_configured" ? "待配置" : "人工";
      const detail = item.platform === "周末预设" && item.action ? `<small>${escapeHtml(item.action)}</small>` : "";
      return `<div><span>${escapeHtml(item.platform)} · ${escapeHtml(shortStore(item.store))}</span><strong>${yuan(item.targetBudget)}</strong><em>${escapeHtml(statusLabel)}</em>${detail}</div>`;
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
  const advice = data.promo_bid_advice || {};
  const queue = data.promo_bid_approval_queue || {};
  const executionPlan = data.promo_bid_execution_plan || {};
  const signalStatus = data.promo_bid_signal_status || {};
  const summary = advice.summary || {};
  const queueSummary = queue.summary || {};
  const planSummary = executionPlan.summary || {};
  const signalSummary = signalStatus.summary || {};
  const signalSetup = signalStatus.setup || {};
  const realExecutionGate = executionPlan.real_execution_gate || {};
  const items = queue.items || advice.items || [];
  const approvalCount = Number(queueSummary.queue_count || queueSummary.approval_required_count || summary.approval_required_count || 0);
  const staleCount = Number(queueSummary.stale_preview_count || summary.stale_preview_count || 0);
  const statusText = queue.status === "waiting_approval" ? "待审批" : queue.status === "no_action" ? "无需处理" : advice.status === "ready" ? "已生成" : advice.status === "partial" ? "部分旧数据" : advice.status === "stale" ? "输入偏旧" : "待生成";
  text("biddingStatus", statusText);
  text("biddingCount", `${approvalCount} 项`);
  text(
    "biddingSummary",
    queue.message || advice.message || `只读出价建议：加价 ${summary.bid_up_count || 0} 项，降价 ${summary.bid_down_count || 0} 项，风险 ${summary.risk_count || 0} 项。`
  );
  document.querySelector("#bidding")?.classList.toggle("alert", approvalCount > 0 || staleCount > 0);
  const gate = queue.approval_gate || advice.approval || {};
  const bidUpCount = queueSummary.bid_up_count ?? summary.bid_up_count ?? 0;
  const bidDownCount = queueSummary.bid_down_count ?? summary.bid_down_count ?? 0;
  const riskCount = queueSummary.risk_count ?? summary.risk_count ?? 0;
  const approvedCount = Number(queueSummary.approved_count || 0);
  const skippedCount = Number(queueSummary.skipped_count || 0);
  const manualRecordedCount = Number(queueSummary.manual_review_recorded_count || 0);
  const firstPendingItem = items.find((item) => item.status === "waiting_approval" || item.status === "manual_review") || {};
  const previewTime = queueSummary.latest_preview_at || summary.latest_preview_at || "";
  const bidItemDetail = (item) => [
    [item.current_bid, item.target_bid].some((value) => value !== undefined && value !== null && value !== "") ? `出价 ${item.current_bid ?? "-"}->${item.target_bid ?? "-"}` : "",
    [item.current_spend, item.expected_spend].some((value) => value !== undefined && value !== null && value !== "") ? `消耗 ${item.current_spend ?? "-"}/${item.expected_spend ?? "-"}` : "",
    item.budget_usage ? `预算 ${item.budget_usage}` : "",
    item.risk || item.reason || item.human_action || `${item.time || ""} ${item.period || ""}`,
  ].filter(Boolean).join(" · ");
  rows(
    "biddingRows",
    [
      { label: "审批队列", value: `${approvalCount} 项`, detail: gate.message || "确认前不自动提交" },
      { label: "审批进度", value: `${approvedCount}/${skippedCount}/${manualRecordedCount}`, detail: `已批准/已跳过/已转人工复核 · 记录文件 ${queue.decision_source || "data/promo_bid_decisions.json"}` },
      { label: "执行计划", value: realExecutionGate.status === "blocked" ? "真实阻断" : `${planSummary.plan_count || 0} 项`, detail: realExecutionGate.message || executionPlan.message || "只生成 dry-run 执行计划，不提交平台" },
      { label: "信号输入", value: `${signalSummary.ready_count || 0}/${signalSummary.missing_count || 0}`, detail: `${signalStatus.message || "等待曝光、进店、转化输入状态"}${signalSetup.template_path ? ` · 模板 ${signalSetup.template_path}` : ""}` },
      { label: "加价/降价", value: `${bidUpCount}/${bidDownCount}`, detail: riskCount ? `风险或不可执行 ${riskCount} 项` : "基于预算消耗与预期消耗" },
      { label: "输入状态", value: staleCount ? `${staleCount} 个旧预览` : "可用", detail: previewTime ? `最新 ${previewTime}` : "等待状态读取" },
      ...(firstPendingItem.decision_command ? [{ label: "记录命令", value: "本地记录", detail: firstPendingItem.decision_command }] : []),
      ...items.filter((item) => Number(item.bid_delta || 0)).slice(0, 5).map((item) => ({
        label: `${item.platform || "平台"} · ${shortStore(item.store || "未命名门店")}`,
        value: item.status === "approved" ? "已批准" : item.status === "skipped" ? "已跳过" : item.status === "manual_review_recorded" ? "已转人工" : item.action || "出价建议",
        detail: bidItemDetail(item),
      })),
    ],
    (item) => {
      const needsAttention = (item.label === "输入状态" && staleCount) || (item.label === "审批队列" && approvalCount) || Boolean(Number.parseInt(item.value, 10));
      return `<div class="${needsAttention ? "warn-row" : "good-row"}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`;
    }
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
  document.querySelector("#franchise-contract")?.classList.toggle("alert", contract.status === "waiting_template");
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
  const waiting = finance.status === "waiting_samples";
  text("financeBillStatus", waiting ? "待样例" : finance.status === "ready_for_mapping" ? "待映射" : "待检查");
  text("financeBillCount", `${Number(summary.sample_file_count || 0)} 个样例`);
  text("financeBillSummary", finance.message || "财务中心等待账单样例和字段字典。");
  document.querySelector("#finance-bills")?.classList.toggle("alert", waiting);
  rows(
    "financeBillRows",
    [
      ...sources.map((source) => ({
        label: source.name,
        value: `${source.file_count || 0} 个文件`,
        detail: [
          source.path || "",
          source.template_path ? `模板：${source.template_path}` : "",
          (source.required_fields || []).length ? `字段：${(source.required_fields || []).slice(0, 4).join("、")}${(source.required_fields || []).length > 4 ? "等" : ""}` : "",
        ].filter(Boolean).join(" · "),
        warn: !source.file_count,
      })),
      ...intakeChecklist.slice(0, 2).map((item) => ({
        label: "接收要求",
        value: item.source || "账单样例",
        detail: item.message || "",
        warn: waiting,
      })),
      ...(missing.length ? [{ label: "当前缺口", value: `${missing.length} 项`, detail: missing.join("、"), warn: true }] : []),
    ],
    (item) => `<div class="${item.warn ? "warn-row" : "good-row"}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  text("financeReportStatus", reportGeneration.status_text || (waiting ? "待样例" : "待映射"));
  text("financeReportCount", `${Number(reportGeneration.account_count || summary.account_count || accounts.length)} 个科目`);
  text("financeReportSummary", reportGeneration.message || "首版科目字典覆盖营业收入、佣金、配送费、推广费、退款和补贴；样例到位后进入字段映射。");
  rows(
    "financeReportRows",
    [
      { label: "初始化", value: setup.directories_ready && setup.templates_ready ? "已准备" : "可执行", detail: setup.init_command || "python3 scripts/init_finance_inbox.py" },
      { label: "模板目录", value: setup.templates_ready ? "已就绪" : "待生成", detail: setup.template_dir || "data/finance-inbox/templates" },
      ...(reportGeneration.report_outputs || []).slice(0, 4).map((item) => ({
        label: "报表",
        value: item,
        detail: "字段映射后生成",
      })),
      ...(reportGeneration.required_before || []).slice(0, 3).map((item) => ({
        label: "前置条件",
        value: item,
        detail: "未满足前不自动出报表",
      })),
      ...accounts.slice(0, 6).map((account) => ({
        label: account.direction === "income" ? "收入" : "支出",
        value: account.name,
        detail: (account.keywords || []).slice(0, 3).join("、"),
      })),
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

const gitLabel = data.system?.git?.commit ? ` · 版本 ${data.system.git.commit}` : "";
text("generatedAt", `数据更新时间：${data.generated_at || "未生成"}${gitLabel}`);
renderDaily();
renderPriority();
renderHealth();
renderAiAdvice();
renderAnomalies();
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
