const data = window.WORKBENCH_DATA || {};

const yuan = (value) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: 0,
  })}`;

const num = (value, digits = 0) =>
  Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
  });

const pct = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setText(id, value) {
  const el = document.querySelector(`#${id}`);
  if (el) el.textContent = value;
}

function setRows(id, items, renderer, emptyText = "暂无数据") {
  const el = document.querySelector(`#${id}`);
  if (!el) return;
  el.innerHTML = items.length ? items.map(renderer).join("") : `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
}

function latestDailyDate(daily) {
  const sourceDates = daily.source_dates || [];
  if (sourceDates.length) return sourceDates[sourceDates.length - 1];
  const dates = [...new Set((daily.records || []).map((item) => item.date).filter(Boolean))].sort();
  return dates[dates.length - 1] || "";
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

function signedNumber(value) {
  const rounded = Math.round(Number(value || 0));
  return `${rounded > 0 ? "+" : ""}${num(rounded)}`;
}

function trendClass(delta) {
  const value = Number(delta || 0);
  if (value > 0) return "trend-up";
  if (value < 0) return "trend-down";
  return "";
}

function storeIncome(item) {
  return Number(item.income ?? item.total_income ?? 0);
}

function storeOrders(item) {
  return Number(item.orders ?? item.total_orders ?? 0);
}

function platformMetrics(item) {
  const platforms = item.platforms || {};
  const eleme = platforms["饿了么"] || {};
  const meituan = platforms["美团"] || {};
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
  ].filter((platform) => platform.orders || platform.income);
}

function renderPlatformRows(item) {
  const platforms = platformMetrics(item);
  if (!platforms.length) return '<div class="platform-row"><span>平台拆分</span><strong>等待同步</strong></div>';
  return platforms
    .map(
      (platform) => `
        <div class="platform-row platform-${platform.key}">
          <span>${escapeHtml(platform.name)}</span>
          <div>
            <strong>${yuan(platform.income)}</strong>
            <em>${num(platform.orders)} 单</em>
          </div>
        </div>`
    )
    .join("");
}

function renderRealtime() {
  const realtime = data.realtime || {};
  const summary = realtime.summary || {};
  const collection = data.realtime_collection || {};
  const stores = (realtime.stores || []).slice().sort((a, b) => storeIncome(b) - storeIncome(a));
  const totalOrders = Number(realtime.orders ?? realtime.total_orders ?? summary.total_orders ?? 0);
  const totalIncome = Number(realtime.income ?? realtime.total_income ?? summary.total_income ?? 0);
  const platformCoverage = Number(summary.platform_store_count || 0);
  const targetPlatformCount = platformCoverage + Number(summary.missing_count || 0);
  const missing = Number(summary.missing_count || 0);
  const incomeMissing = Number(summary.income_missing_count || 0);
  const generatedAt = collection.last_success_at || realtime.generated_at || realtime.collected_at || data.generated_at || "-";
  const stale = ["stale", "failed_after_success", "partial", "missing_latest"].includes(collection.status || realtime.status);
  const statusEl = document.querySelector("#realtimeStatus");

  setText("generatedAt", `数据生成：${data.generated_at || generatedAt}`);
  setText("sidebarGeneratedAt", data.generated_at || generatedAt);
  setText("realtimeOrders", `${num(totalOrders)} 单`);
  setText("realtimeIncome", yuan(totalIncome));
  setText("realtimeCoverage", targetPlatformCount ? `${platformCoverage}/${targetPlatformCount}` : `${stores.length} 家`);
  setText("storeCount", `${stores.length} 家门店`);
  setText("realtimeStatus", stale ? "需复查" : stores.length ? "已同步" : "待采集");
  statusEl?.classList.toggle("warn", stale);
  statusEl?.classList.toggle("danger", realtime.status === "needs_review");
  setText(
    "realtimeMeta",
    realtime.anomaly_reason ||
      `最近成功：${generatedAt}，覆盖 ${stores.length} 家门店，当前缺失 ${missing} 个平台门店，收入缺失 ${incomeMissing} 个。`
  );

  setRows(
    "realtimeStoreRows",
    stores,
    (item) => `
      <article class="store-card">
        <div class="store-card-head">
          <strong>${escapeHtml(item.store || item.store_name || "未命名门店")}</strong>
          <em>${escapeHtml(item.updated_at || item.collected_at || "")}</em>
        </div>
        <div class="store-figures">
          <div>
            <span>营业额</span>
            <strong>${yuan(storeIncome(item))}</strong>
          </div>
          <div>
            <span>单量</span>
            <strong>${num(storeOrders(item))} 单</strong>
          </div>
        </div>
        <div class="platform-breakdown">${renderPlatformRows(item)}</div>
      </article>`,
    "暂无实时门店数据"
  );
}

function renderDailyBrief() {
  const daily = data.daily || {};
  const latestDate = latestDailyDate(daily);
  const latestRows = dailyRowsByDate(daily, latestDate);
  const previousDate = previousDailyDate(daily, latestDate);
  const previousRows = previousDate ? dailyRowsByDate(daily, previousDate) : [];
  const dailyIncome = latestRows.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const dailyOrders = latestRows.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const previousIncome = previousRows.reduce((sum, item) => sum + Number(item.income || 0), 0);
  const previousOrders = previousRows.reduce((sum, item) => sum + Number(item.orders || 0), 0);
  const incomeDelta = dailyIncome - previousIncome;
  const orderDelta = dailyOrders - previousOrders;
  const orderCompare = document.querySelector("#dailyOrdersCompare");
  const incomeCompare = document.querySelector("#dailyIncomeCompare");

  setText("dailyOrders", `${num(dailyOrders)} 单`);
  setText("dailyIncome", yuan(dailyIncome));
  setText("dailySummary", latestRows.length ? `最新日报日期 ${latestDate}：覆盖 ${new Set(latestRows.map((item) => item.store || item.store_raw)).size} 家门店。` : "等待日报数据。");

  if (orderCompare) {
    orderCompare.textContent = previousDate ? `较前日 ${signedNumber(orderDelta)} 单` : "较前日 暂无";
    orderCompare.className = trendClass(orderDelta);
  }
  if (incomeCompare) {
    incomeCompare.textContent = previousDate ? `较前日 ${incomeDelta >= 0 ? "+" : "-"}${yuan(Math.abs(incomeDelta))}` : "较前日 暂无";
    incomeCompare.className = trendClass(incomeDelta);
  }
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
  const statusEl = document.querySelector("#reviewStatus");

  setText("reviewStatus", pendingNegative ? "待回复" : review.status === "ready" ? "已同步" : "待同步");
  statusEl?.classList.toggle("warn", pendingNegative > 0);
  setText("reviewCount", `${num(totalIssues)} / ${num(totalReviews)} 条`);
  setText(
    "reviewSummary",
    stores.length
      ? `${review.used_date || review.target_date || "昨日"}：差评 ${num(totalIssues)} 条 / 总评价 ${num(totalReviews)} 条，覆盖 ${stores.length} 家门店。`
      : "等待评价数据。"
  );

  setRows(
    "reviewCommandRows",
    [
      { label: "昨日总评价", value: `${num(totalReviews)} 条`, detail: `覆盖 ${num(stores.length)} 家门店`, tone: "" },
      { label: "昨日差评", value: `${num(totalIssues)} 条`, detail: `差评率 ${totalReviews ? ((totalIssues / totalReviews) * 100).toFixed(1) : "0.0"}%`, tone: totalIssues ? "warn-row" : "good-row" },
      { label: "待回复", value: `${num(pendingNegative)} 条`, detail: pendingNegative ? "优先处理有差评门店" : "暂无待回复差评", tone: pendingNegative ? "warn-row" : "good-row" },
      { label: "本周问题", value: `${num(weeklySummary.negative_count || actionSummary.weekly_negative_count || 0)} 条`, detail: `本周评价 ${num(weeklySummary.review_count || actionSummary.weekly_review_count || 0)} 条`, tone: Number(weeklySummary.negative_count || 0) ? "warn-row" : "good-row" },
    ],
    (item) => `<div class="${item.tone}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  setRows(
    "reviewWeeklyRows",
    [
      {
        label: "重点门店",
        value: (weeklyRecap.stores || []).slice(0, 3).map((item) => `${item.store} ${num(item.negative_count)} 条`).join(" / ") || "暂无",
        detail: (weeklyRecap.stores || []).slice(0, 3).map((item) => `${item.store} 问题率 ${(Number(item.negative_rate || 0) * 100).toFixed(1)}%，均分 ${Number(item.avg_rating || 0).toFixed(2)}`).join("；") || "本周暂无明显差评集中门店。",
        tone: (weeklyRecap.stores || []).some((item) => Number(item.negative_count || 0)) ? "warn-row" : "good-row",
      },
      {
        label: "高频问题",
        value: (weeklyRecap.issue_types || []).slice(0, 3).map((item) => `${item.issue_type} ${num(item.count)}`).join(" / ") || "暂无",
        detail: (weeklyRecap.actions || []).slice(0, 2).join("；") || weeklyRecap.next_action || "继续观察差评、评分和同类问题复发。",
        tone: (weeklyRecap.issue_types || []).length ? "warn-row" : "good-row",
      },
    ],
    (item) => `<div class="${item.tone}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong><em>${escapeHtml(item.detail)}</em></div>`
  );

  setRows(
    "reviewRows",
    stores.slice().sort((a, b) => b.negative_count - a.negative_count || b.review_count - a.review_count),
    (item) => {
      const keywords = item.top_keywords.length ? item.top_keywords.join("、") : "无集中关键词";
      const platformText = ["美团", "饿了么"]
        .map((platform) => {
          const detail = item.platforms[platform] || {};
          const count = Number(detail.review_count || 0);
          const negative = Number(detail.negative_count || 0);
          const rating = Number(detail.review_avg_rating || detail.avg_rating || 0);
          return `${platform} ${num(count)} 条 / 差评 ${num(negative)} / 评价均分 ${rating ? rating.toFixed(2) : "-"}`;
        })
        .join("；");
      const badReviewText = item.bad_review_examples
        .filter(Boolean)
        .slice(0, 3)
        .map((content, index) => `<span class="bad-review">${index + 1}. ${escapeHtml(content)}</span>`)
        .join("");
      return `<div class="${item.negative_count ? "warn-row" : "good-row"}"><span>${escapeHtml(item.store)}</span><strong>${num(item.negative_count)}/${num(item.review_count)} 条</strong><em>${escapeHtml(platformText)}<br>合计评价均分 ${item.review_avg_rating.toFixed(2)} · ${escapeHtml(keywords)}${badReviewText ? `<b class="bad-review-title">差评内容</b>${badReviewText}` : ""}</em></div>`;
    },
    "暂无评价数据"
  );
}

function bindNavigation() {
  const links = [...document.querySelectorAll(".nav a")];
  const sections = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  const activate = () => {
    const current = sections
      .slice()
      .reverse()
      .find((section) => section.getBoundingClientRect().top <= 120);
    if (!current) return;
    links.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${current.id}`));
  };
  document.addEventListener("scroll", activate, { passive: true });
  activate();
}

async function loadReportFrame() {
  const frame = document.querySelector(".report-frame");
  if (!frame) return;
  const sources = [frame.dataset.reportSrc, frame.dataset.localReportSrc].filter(Boolean);
  frame.srcdoc = '<!doctype html><html lang="zh-CN"><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,sans-serif;color:#66736e;">正在加载加盟店日报看板...</body></html>';

  for (const source of sources) {
    const url = new URL(source, document.baseURI || window.location.href).href;
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) continue;
      let html = await response.text();
      if (/Directory listing for/i.test(html) || !/<html|<!doctype/i.test(html)) continue;
      const baseTag = `<base href="${escapeHtml(url)}">`;
      html = /<head[^>]*>/i.test(html)
        ? html.replace(/<head([^>]*)>/i, `<head$1>${baseTag}`)
        : `<!doctype html><html lang="zh-CN"><head>${baseTag}</head><body>${html}</body></html>`;
      frame.srcdoc = html;
      return;
    } catch (error) {
      continue;
    }
  }

  frame.srcdoc = '<!doctype html><html lang="zh-CN"><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,sans-serif;color:#66736e;"><strong style="display:block;color:#14201b;margin-bottom:8px;">加盟店日报看板加载失败</strong><span>请刷新页面后重试。</span></body></html>';
}

renderRealtime();
renderDailyBrief();
renderReviews();
bindNavigation();
loadReportFrame();
