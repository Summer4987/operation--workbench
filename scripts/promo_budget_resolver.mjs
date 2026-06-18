export function canonicalStoreName(storeName) {
  const text = String(storeName || "").trim();
  return /第13档口|熙悦美食城|熙悦|丽泽/.test(text) ? "丽泽门店" : text;
}

export function dayName(day) {
  return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][day] || "";
}

const DEFAULT_CHINA_HOLIDAYS = {
  "2026-01-01": "元旦",
  "2026-01-02": "元旦",
  "2026-01-03": "元旦",
  "2026-02-15": "春节",
  "2026-02-16": "春节",
  "2026-02-17": "春节",
  "2026-02-18": "春节",
  "2026-02-19": "春节",
  "2026-02-20": "春节",
  "2026-02-21": "春节",
  "2026-02-22": "春节",
  "2026-02-23": "春节",
  "2026-04-04": "清明节",
  "2026-04-05": "清明节",
  "2026-04-06": "清明节",
  "2026-05-01": "劳动节",
  "2026-05-02": "劳动节",
  "2026-05-03": "劳动节",
  "2026-05-04": "劳动节",
  "2026-05-05": "劳动节",
  "2026-06-19": "端午节",
  "2026-06-20": "端午节",
  "2026-06-21": "端午节",
  "2026-09-25": "中秋节",
  "2026-09-26": "中秋节",
  "2026-09-27": "中秋节",
  "2026-10-01": "国庆节",
  "2026-10-02": "国庆节",
  "2026-10-03": "国庆节",
  "2026-10-04": "国庆节",
  "2026-10-05": "国庆节",
  "2026-10-06": "国庆节",
  "2026-10-07": "国庆节",
};

const DEFAULT_CHINA_ADJUSTED_WORKDAYS = {
  "2026-01-04": "元旦调休上班",
  "2026-02-14": "春节调休上班",
  "2026-02-28": "春节调休上班",
  "2026-05-09": "劳动节调休上班",
  "2026-09-20": "国庆节调休上班",
  "2026-10-10": "国庆节调休上班",
};

export function budgetDateContext(
  dateValue = process.env.PROMO_BUDGET_DATE || process.env.BUDGET_TARGET_DATE || "",
  calendarConfig = {},
) {
  const date = parseBudgetDate(dateValue) || new Date();
  const dateText = formatDate(date);
  const day = date.getDay();
  const holidayName = calendarLabel(dateText, calendarConfig, "chinaHolidays", DEFAULT_CHINA_HOLIDAYS);
  const adjustedWorkdayName = calendarLabel(
    dateText,
    calendarConfig,
    "chinaAdjustedWorkdays",
    DEFAULT_CHINA_ADJUSTED_WORKDAYS,
  );
  const isNaturalWeekend = day === 0 || day === 6;
  const isHoliday = Boolean(holidayName);
  const isAdjustedWorkday = Boolean(adjustedWorkdayName);
  const isWeekendBudgetDay = !isAdjustedWorkday && (isNaturalWeekend || isHoliday);
  return {
    date: dateText,
    day,
    day_name: dayName(day),
    day_key: ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][day],
    day_type: isWeekendBudgetDay ? "weekend" : "weekday",
    day_type_name: isWeekendBudgetDay ? "周末/节假日" : "工作日",
    is_natural_weekend: isNaturalWeekend,
    is_china_holiday: isHoliday,
    china_holiday_name: holidayName || "",
    is_adjusted_workday: isAdjustedWorkday,
    adjusted_workday_name: adjustedWorkdayName || "",
    budget_rule_reason: isAdjustedWorkday
      ? adjustedWorkdayName
      : isHoliday
        ? `${holidayName}，按周末预算执行`
        : isNaturalWeekend
          ? "自然周末，按周末预算执行"
          : "普通工作日，按工作日预算执行",
  };
}

function calendarLabel(dateText, config, key, defaults) {
  const merged = {
    ...defaults,
    ...normalizeCalendarConfig(config?.[key]),
  };
  return merged[dateText] || "";
}

function normalizeCalendarConfig(value) {
  if (Array.isArray(value)) {
    return Object.fromEntries(value.map((date) => [String(date), "中国法定节假日"]));
  }
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).map(([date, label]) => [
      String(date),
      typeof label === "object" && label ? String(label.name || label.label || "") : String(label || ""),
    ]),
  );
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
    ? ["weekend", "Weekend", "周末", "holiday", "Holiday", "节假日", "法定节假日"]
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
  const isActiveDay = dateContext.day_type === "weekend" || activeDays.includes(dateContext.day);
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
