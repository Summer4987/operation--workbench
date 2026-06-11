(function (global) {
  const checkTimes = ["10:40", "10:50", "11:00"];

  function timeValue(time) {
    const [hour, minute] = time.split(":").map(Number);
    return hour * 60 + minute;
  }

  function formatMoney(value) {
    return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2);
  }

  function evaluateBid(expected, actual) {
    if (!Number.isFinite(actual) || actual < 0) {
      return { label: "请输入有效金额", className: "neutral", delta: 0, reason: "实际消耗需要是非负数字。" };
    }

    const overRate = expected === 0 ? 0 : (actual - expected) / expected;
    if (actual < expected) {
      return {
        label: "出价 +0.1",
        className: "up",
        delta: 0.1,
        reason: `实际 ${formatMoney(actual)} 元低于预期 ${formatMoney(expected)} 元。`,
      };
    }
    if (overRate >= 0.2) {
      return {
        label: "出价 -0.2",
        className: "down-strong",
        delta: -0.2,
        reason: `实际超出预期 ${(overRate * 100).toFixed(1)}%，达到20%或以上。`,
      };
    }
    if (overRate >= 0.1) {
      return {
        label: "出价 -0.1",
        className: "down",
        delta: -0.1,
        reason: `实际超出预期 ${(overRate * 100).toFixed(1)}%，达到10%且低于20%。`,
      };
    }
    return {
      label: "出价不变",
      className: "neutral",
      delta: 0,
      reason: actual === expected ? "实际消耗刚好等于预期。" : "实际消耗未超出预期10%。",
    };
  }

  function buildTasks(rules) {
    const all = [];
    for (const store of rules.stores) {
      all.push({
        id: `lunch-budget-${store.name}`,
        platform: rules.platform,
        period: "午餐",
        time: "10:30",
        type: "budget",
        typeLabel: "预算初始化",
        store: store.name,
        shopId: store.shopId || null,
        elemeFullName: store.elemeFullName || "",
        minBid: store.minBid ?? rules.defaultMinBid ?? 0.5,
        budget: store.lunchBudget,
        bidAction: "出价不变",
        summary: `预算调整为 ${store.lunchBudget} 元`,
      });

      for (const time of checkTimes) {
        all.push({
          id: `lunch-check-${store.name}-${time}`,
          platform: rules.platform,
          period: "午餐",
          time,
          type: "bid-check",
          typeLabel: "消耗检查",
          store: store.name,
          shopId: store.shopId || null,
          elemeFullName: store.elemeFullName || "",
          minBid: store.minBid ?? rules.defaultMinBid ?? 0.5,
          budget: store.lunchBudget,
          expectedSpend: rules.expectedSpendByBudget[store.lunchBudget][time],
          summary: `预期消耗 ${rules.expectedSpendByBudget[store.lunchBudget][time]} 元`,
        });
      }

      all.push({
        id: `dinner-budget-${store.name}`,
        platform: rules.platform,
        period: "晚餐",
        time: "17:30",
        type: "budget",
        typeLabel: "预算初始化",
        store: store.name,
        shopId: store.shopId || null,
        elemeFullName: store.elemeFullName || "",
        minBid: store.minBid ?? rules.defaultMinBid ?? 0.5,
        budget: store.dinnerBudget,
        bidAction: "出价不变",
        summary: `预算调整为 ${store.dinnerBudget} 元`,
      });
    }
    return all.sort((a, b) => timeValue(a.time) - timeValue(b.time) || a.store.localeCompare(b.store, "zh-CN"));
  }

  global.DIANJIN_LOGIC = {
    buildTasks,
    evaluateBid,
    formatMoney,
    timeValue,
  };
})(typeof window === "undefined" ? globalThis : window);
