export function canonicalStoreName(storeName) {
  const text = String(storeName || "").trim();
  return /第13档口|熙悦美食城|熙悦|丽泽/.test(text) ? "丽泽门店" : text;
}

export function dayName(day) {
  return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][day] || "";
}

export function budgetDateContext(dateValue = process.env.PROMO_BUDGET_DATE || process.env.BUDGET_TARGET_DATE || "") {
  const date = parseBudgetDate(dateValue) || new Date();
  const day = date.getDay();
  return {
    date: formatDate(date),
    day,
    day_name: dayName(day),
    day_key: ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][day],
    day_type: day === 0 || day === 6 ? "weekend" : "weekday",
    day_type_name: day === 0 || day === 6 ? "周末" : "工作日",
  };
}

function parseBudgetDate(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const match = text.match(/^(\d{4})-?(\d{2})-?(\d{2})$/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function firstFinite(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return null;
}

function nestedBudget(source, keys, periodKey, chinesePeriodKey) {
  for (const key of keys) {
    const item = source?.[key];
    if (!item || typeof item !== "object") continue;
    const value = firstFinite(
      item[periodKey],
      item[chinesePeriodKey],
      item.budget,
      item.value,
      item.amount,
    );
    if (value !== null) return { value, source: key };
  }
  return null;
}

function directBudget(source, period, keys) {
  const prefix = period === "午餐" ? "lunch" : "dinner";
  const suffix = period === "午餐" ? "Lunch" : "Dinner";
  const chinese = period;
  for (const key of keys) {
    const pascal = key ? key[0].toUpperCase() + key.slice(1) : key;
    const value = firstFinite(
      source?.[`${key}${suffix}Budget`],
      source?.[`${prefix}Budget${pascal}`],
      source?.[`${key}${suffix}`],
      source?.[`${prefix}${pascal}`],
      source?.[`${key}${chinese}预算`],
      source?.[`${chinese}预算${key}`],
    );
    if (value !== null) return { value, source: key };
  }
  return null;
}

function periodKeys(period) {
  return period === "午餐"
    ? { english: "lunchBudget", chinese: "午餐预算" }
    : { english: "dinnerBudget", chinese: "晚餐预算" };
}

function dayKeys(context) {
  const dayIndex = String(context.day);
  const english = context.day_key;
  const pascal = english[0].toUpperCase() + english.slice(1);
  return [english, pascal, dayIndex, context.day_name];
}

function dayTypeKeys(context) {
  return context.day_type === "weekend"
    ? ["weekend", "Weekend", "周末", "holiday", "Holiday"]
    : ["weekday", "Weekday", "workday", "Workday", "工作日"];
}

export function resolveBudget({ overrides, platform, storeName, period, fallback, dateContext = budgetDateContext() }) {
  const canonicalName = canonicalStoreName(storeName);
  const aliasName = Object.keys(overrides?.stores || {}).find((name) => canonicalStoreName(name) === canonicalName);
  const byStore = overrides?.stores?.[canonicalName] || overrides?.stores?.[aliasName] || {};
  const byPlatform = byStore?.[platform] || byStore?.all || {};
  const { english: periodKey, chinese: chinesePeriodKey } = periodKeys(period);
  const exactDayKeys = dayKeys(dateContext);
  const typeKeys = dayTypeKeys(dateContext);

  const candidates = [
    nestedBudget(byPlatform, exactDayKeys, periodKey, chinesePeriodKey),
    nestedBudget(byStore, exactDayKeys, periodKey, chinesePeriodKey),
    directBudget(byPlatform, period, exactDayKeys),
    directBudget(byStore, period, exactDayKeys),
    nestedBudget(byPlatform, typeKeys, periodKey, chinesePeriodKey),
    nestedBudget(byStore, typeKeys, periodKey, chinesePeriodKey),
    directBudget(byPlatform, period, typeKeys),
    directBudget(byStore, period, typeKeys),
  ].filter(Boolean);

  if (candidates.length) {
    return {
      budget: candidates[0].value,
      source: candidates[0].source,
      source_type: exactDayKeys.includes(candidates[0].source) ? "day" : "day_type",
      date_context: dateContext,
    };
  }

  const defaultBudget = firstFinite(byPlatform?.[periodKey], byStore?.[periodKey], fallback) || Number(fallback || 0);
  return {
    budget: defaultBudget,
    source: defaultBudget === Number(fallback || 0) ? "rules" : "default",
    source_type: "default",
    date_context: dateContext,
  };
}

export function buildWeekendPreset(config, dateContext = budgetDateContext()) {
  const preset = config?.weekendPreset || {};
  const activeDays = Array.isArray(preset.activeDays) ? preset.activeDays : [0, 6];
  const configured = Object.keys(preset).length > 0;
  const enabledSetting = Boolean(preset.enabled);
  const isActiveDay = activeDays.includes(dateContext.day);
  const enabled = enabledSetting && isActiveDay;
  const name = preset.name || "周末预设方案";
  const status = enabled ? "active" : configured ? "configured_inactive" : "not_configured";
  const activeDayNames = activeDays.map(dayName).filter(Boolean);
  const message = enabled
    ? `${name}今日生效，预算将按周末规则预览。`
    : configured
      ? enabledSetting
        ? `${name}已启用，但今日不在启用日，当前不会改变任何门店预算。`
        : `${name}已配置但未启用，当前不会改变任何门店预算。`
      : "周末预设待配置，当前不会改变任何门店预算。";
  return {
    enabled,
    configured,
    enabled_setting: enabledSetting,
    status,
    message,
    next_action: enabledSetting
      ? "如需调整周末规则，修改 config/promo_budget_overrides.json 的周末预算、倍率、最低预算或启用日。"
      : "确认周末预算规则后，把 config/promo_budget_overrides.json 的 weekendPreset.enabled 改为 true，或给门店配置周末/周日预算。",
    name,
    today_day: dateContext.day,
    today_date: dateContext.date,
    today_day_name: dateContext.day_name,
    today_day_type: dateContext.day_type_name,
    is_active_day: isActiveDay,
    active_days: activeDays,
    active_day_names: activeDayNames,
    lunch_multiplier: Number(preset.lunchMultiplier || 1),
    dinner_multiplier: Number(preset.dinnerMultiplier || 1),
    min_budget: Number(preset.minBudget || 0),
    round_to: Number(preset.roundTo || 1),
    notes: preset.notes || "",
  };
}

export function applyWeekendPresetIfNeeded(budget, period, resolution, weekendPreset) {
  if (!weekendPreset?.enabled || resolution?.source_type !== "default") return budget;
  const multiplier = period === "午餐" ? weekendPreset.lunch_multiplier : weekendPreset.dinner_multiplier;
  const roundTo = weekendPreset.round_to > 0 ? weekendPreset.round_to : 1;
  const minBudget = Math.max(0, weekendPreset.min_budget || 0);
  const adjusted = Math.max(minBudget, Number(budget || 0) * multiplier);
  return Math.round(adjusted / roundTo) * roundTo;
}
