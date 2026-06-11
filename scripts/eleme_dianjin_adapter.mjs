import fs from "node:fs/promises";
import vm from "node:vm";

const rulesPath = "dianjin-prototype/rules.js";
const logicPath = "dianjin-prototype/logic.js";
const configPath = "dianjin-prototype/automation_config.json";
const outputDir = "outputs/dianjin_automation";

function loadBrowserRules() {
  const context = { window: {} };
  vm.runInNewContext(awaitText(rulesPath), context);
  vm.runInNewContext(awaitText(logicPath), context);
  return {
    rules: context.window.DIANJIN_RULES,
    logic: context.window.DIANJIN_LOGIC,
  };
}

function awaitText(path) {
  return globalThis.__fileCache?.[path] || "";
}

async function loadRuntime() {
  globalThis.__fileCache = {
    [rulesPath]: await fs.readFile(rulesPath, "utf8"),
    [logicPath]: await fs.readFile(logicPath, "utf8"),
  };
  const { rules, logic } = loadBrowserRules();
  const config = JSON.parse(await fs.readFile(configPath, "utf8"));
  return { rules, logic, config };
}

function parseArgs(argv) {
  const args = { command: argv[2] || "dry-run" };
  for (let i = 3; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }
  return args;
}

function filterTasks(tasks, args) {
  return tasks.filter((task) => {
    if (args.period && task.period !== args.period) return false;
    if (args.time && task.time !== args.time) return false;
    if (args.type && task.type !== args.type) return false;
    if (args.store && !task.store.includes(args.store)) return false;
    return true;
  });
}

function taskToAction(task) {
  if (task.type === "budget") {
    return {
      actionType: "set_budget",
      platform: task.platform,
      period: task.period,
      time: task.time,
      store: task.store,
      shopId: task.shopId,
      elemeFullName: task.elemeFullName,
      budget: task.budget,
      bidChange: 0,
      instruction: `切换到「${task.store}」，将预算调整为 ${task.budget} 元，出价保持不变，保存前确认门店名称。`,
    };
  }

  return {
    actionType: "check_spend_and_adjust_bid",
    platform: task.platform,
    period: task.period,
    time: task.time,
    store: task.store,
    shopId: task.shopId,
    elemeFullName: task.elemeFullName,
    lunchBudget: task.budget,
    expectedSpend: task.expectedSpend,
    instruction: `切换到「${task.store}」，读取 ${task.time} 实际使用金额；低于 ${task.expectedSpend} 元则出价 +0.1，达到 ${task.expectedSpend * 1.1} 元且低于 ${task.expectedSpend * 1.2} 元则 -0.1，达到 ${task.expectedSpend * 1.2} 元或以上则 -0.2。`,
  };
}

function summarize(actions) {
  const byType = actions.reduce((memo, action) => {
    memo[action.actionType] = (memo[action.actionType] || 0) + 1;
    return memo;
  }, {});
  return {
    actionCount: actions.length,
    setBudget: byType.set_budget || 0,
    checkSpendAndAdjustBid: byType.check_spend_and_adjust_bid || 0,
  };
}

function parseMoney(text) {
  if (text === null || text === undefined) return null;
  const normalized = String(text).replace(/,/g, "");
  if (normalized.includes("-")) return 0;
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function parseTableRowsFromProbe(probe) {
  const tables = probe.tables || [];
  const headerTable = tables.find((table) => table.headers?.includes("门店名称/ID"));
  const bodyTable = tables.find((table) => table.rows?.some((row) => row.length >= 10 && row.some((cell) => String(cell || "").trim())));
  const dataTable = bodyTable || headerTable;
  if (!dataTable) return [];
  const headers = headerTable?.headers?.length ? headerTable.headers : dataTable.headers?.length ? dataTable.headers : [
    "",
    "门店名称/ID",
    "门店出价",
    "每日预算",
    "自动提预算(元)",
    "今日花费(元)",
    "预算使用率",
    "推广时段",
    "推广渠道",
    "定向设置",
    "投放开关",
    "推广数据",
  ];
  return (dataTable.rows || [])
    .filter((row) => row.some((cell) => String(cell || "").trim()))
    .map((row, index) => {
      const byHeader = Object.fromEntries(headers.map((header, col) => [header || `列${col}`, row[col] || ""]));
      const nameCell = byHeader["门店名称/ID"] || "";
      const bidCell = byHeader["门店出价"] || "";
      const budgetCell = byHeader["每日预算"] || "";
      const spendCell = byHeader["今日花费(元)"] || "";
      return {
        index,
        nameText: nameCell,
        id: nameCell.match(/ID[:：]\s*(\d+)/)?.[1] || "",
        bid: parseMoney(bidCell),
        bidAssistantStatus: String(bidCell).includes("出价助手：开启") ? "开启" : String(bidCell).includes("出价助手：关闭") ? "关闭" : "",
        budget: parseMoney(budgetCell),
        spend: parseMoney(spendCell),
        budgetUsage: byHeader["预算使用率"] || "",
        schedule: byHeader["推广时段"] || "",
        switchStatus: byHeader["投放开关"] || "",
        raw: byHeader,
      };
    });
}

function shopMapFromProbe(probe) {
  const tree = probe.apiSummaries?.find((item) => item.type === "restaurantTree");
  const shops = (tree?.shops || []).filter((shop) => shop.restaurantType === "LEAF");
  return new Map(shops.map((shop) => [Number(shop.id), shop]));
}

function currentRowsFromProbe(probe) {
  const shopsById = shopMapFromProbe(probe);
  return parseTableRowsFromProbe(probe).map((row) => ({
    ...row,
    shopId: Number(row.id),
    fullName: shopsById.get(Number(row.id))?.name || "",
  }));
}

function makeRecommendations(tasks, currentRows, args, logic) {
  const rowsByShopId = new Map(currentRows.map((row) => [Number(row.shopId), row]));
  return filterTasks(tasks, args).map((task) => {
    const current = rowsByShopId.get(Number(task.shopId));
    if (task.type === "budget") {
      return {
        task,
        current,
        found: Boolean(current),
        recommendation: current
          ? current.budget === task.budget
            ? "预算已符合"
            : `预算需从 ${current.budget} 调整为 ${task.budget}`
          : "当前页未找到该门店",
      };
    }
    if (!current) {
      return { task, current, found: false, recommendation: "当前页未找到该门店" };
    }
    const decision = logic.evaluateBid(task.expectedSpend, current.spend);
    return {
      task,
      current,
      found: true,
      decision,
      recommendation: `当前花费 ${current.spend}，预期 ${task.expectedSpend}，${decision.label}`,
    };
  });
}

async function latestProbeFile(prefix) {
  const files = await fs.readdir(outputDir).catch(() => []);
  const matches = [];
  for (const file of files) {
    if (!file.startsWith(prefix) || !file.endsWith(".json")) continue;
    const path = `${outputDir}/${file}`;
    const stat = await fs.stat(path);
    matches.push({ path, mtime: stat.mtimeMs });
  }
  matches.sort((a, b) => b.mtime - a.mtime);
  return matches[0]?.path || null;
}

async function latestProbeFiles(prefix, count = 2) {
  const files = await fs.readdir(outputDir).catch(() => []);
  const matches = [];
  for (const file of files) {
    if (!file.startsWith(prefix) || !file.endsWith(".json")) continue;
    const path = `${outputDir}/${file}`;
    const stat = await fs.stat(path);
    matches.push({ path, mtime: stat.mtimeMs });
  }
  matches.sort((a, b) => b.mtime - a.mtime);
  return matches.slice(0, count).map((item) => item.path);
}

async function combinedCurrentRowsFromLatestProbes() {
  const files = await latestProbeFiles("eleme_store_probe_", 6);
  const rowsByShopId = new Map();
  const usedFiles = [];
  for (const file of files) {
    const probe = JSON.parse(await fs.readFile(file, "utf8"));
    const rows = currentRowsFromProbe(probe);
    if (!rows.length) continue;
    usedFiles.push(file);
    for (const row of rows) {
      if (!row.shopId) continue;
      if (!rowsByShopId.has(row.shopId)) rowsByShopId.set(row.shopId, row);
    }
    if (rowsByShopId.size >= 12) break;
  }
  return { files: usedFiles, rows: Array.from(rowsByShopId.values()) };
}

async function probeChrome(config) {
  const response = await fetch(`${config.chrome.debugUrl}/json/version`);
  if (!response.ok) throw new Error(`Chrome 调试端口不可用：${response.status}`);
  return response.json();
}

async function cdpJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
  }

  async ready() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
      this.ws.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.id && this.pending.has(message.id)) {
          const pending = this.pending.get(message.id);
          this.pending.delete(message.id);
          if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
          else pending.resolve(message.result);
          return;
        }
        if (message.method && this.handlers.has(message.method)) {
          for (const handler of this.handlers.get(message.method)) handler(message.params || {});
        }
      };
    });
  }

  on(method, handler) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(handler);
  }

  async send(method, params = {}) {
    await this.ready();
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  close() {
    this.ws.close();
  }
}

async function findOrOpenPromotionTab(config) {
  const tabs = await cdpJson(`${config.chrome.debugUrl}/json/list`);
  const existing = tabs.find((tab) =>
    tab.type === "page" &&
    tab.url.includes("doujin-isv-manage") &&
    tab.url.includes("__path__=eleCpcChain/oldBranch")
  );
  if (existing) return existing;
  return cdpJson(`${config.chrome.debugUrl}/json/new?${encodeURIComponent(config.eleme.promotionUrl)}`, { method: "PUT" });
}

async function probePromotionPage(config) {
  if (!config.eleme.promotionUrl) {
    throw new Error("automation_config.json 里还没有配置 eleme.promotionUrl");
  }
  await probeChrome(config);
  const tab = await findOrOpenPromotionTab(config);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  const networkUrls = [];
  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    await cdp.send("DOM.enable");
    await cdp.send("Runtime.evaluate", {
      expression: "window.__DIANJIN_PROBE_MARKER__ = Date.now()",
      returnByValue: true,
    }).catch(() => {});
    await cdp.send("Page.navigate", { url: config.eleme.promotionUrl });
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const targets = await cdp.send("Target.getTargets").catch(() => ({ targetInfos: [] }));
    const result = await cdp.send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const text = document.body ? document.body.innerText.slice(0, 6000) : '';
        const allTextControls = Array.from(document.querySelectorAll('button,[role="button"],a,.ant-tabs-tab,.ant-radio-wrapper,label,span'))
          .filter(visible)
          .map((el) => (el.innerText || el.textContent || '').trim())
          .filter(Boolean)
          .slice(0, 160);
        const controls = Array.from(document.querySelectorAll('button,input,textarea,select,[role="button"],a'))
          .filter(visible)
          .slice(0, 160)
          .map((el) => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            role: el.getAttribute('role') || '',
            text: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80),
            className: String(el.className || '').slice(0, 120)
          }));
        const tables = Array.from(document.querySelectorAll('table')).map((table) => ({
          headers: Array.from(table.querySelectorAll('th')).map((th) => (th.innerText || th.textContent || '').trim()),
          rows: Array.from(table.querySelectorAll('tbody tr')).slice(0, 20).map((tr) =>
            Array.from(tr.querySelectorAll('td')).map((td) => (td.innerText || td.textContent || '').trim())
          )
        }));
        const antRows = Array.from(document.querySelectorAll('.ant-table-row, [class*="table"] tr')).slice(0, 30).map((row) => ({
          text: (row.innerText || row.textContent || '').trim().slice(0, 500),
          inputs: Array.from(row.querySelectorAll('input')).map((input) => ({
            type: input.type,
            value: input.value,
            placeholder: input.placeholder,
            className: String(input.className || '').slice(0, 100)
          }))
        }));
        return { url: location.href, title: document.title, text, allTextControls, controls, tables, antRows };
      })()`,
    });
    return {
      ...result.result.value,
      targets: (targets.targetInfos || []).map((target) => ({ type: target.type, title: target.title, url: target.url })).slice(0, 20),
      networkUrls,
    };
  } finally {
    cdp.close();
  }
}

async function fetchBranchSolutions(config, pageNum = 1, pageSize = 10) {
  const probePath = await latestProbeFile("eleme_store_probe_");
  if (!probePath) throw new Error("没有可复用的门店探测文件，无法取得接口请求体");
  const probe = JSON.parse(await fs.readFile(probePath, "utf8"));
  const api = (probe.apiResponses || []).find((item) => item.url.includes("method=queryBranchSolutions") && item.request?.postData);
  if (!api) throw new Error("探测文件里没有 queryBranchSolutions 请求体");
  const body = JSON.parse(api.request.postData);
  body.params.params[1].pageNum = Number(pageNum);
  body.params.params[1].pageSize = Number(pageSize);
  body.params.reqId = `${Date.now()}${Math.random().toString(36).slice(2)}`;

  await probeChrome(config);
  const tab = await findOrOpenPromotionTab(config);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  try {
    await cdp.send("Runtime.enable");
    const result = await cdp.send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const response = await fetch(${JSON.stringify(api.url)}, {
          method: 'POST',
          credentials: 'include',
          headers: { 'content-type': 'application/json' },
          body: ${JSON.stringify(JSON.stringify(body))}
        });
        return await response.json();
      })()`,
    });
    return result.result.value;
  } finally {
    cdp.close();
  }
}

async function probeStore(config, storeName, pageNumber = "") {
  if (!storeName) throw new Error("请提供 --store 门店名");
  if (!config.eleme.promotionUrl) {
    throw new Error("automation_config.json 里还没有配置 eleme.promotionUrl");
  }
  await probeChrome(config);
  const tab = await findOrOpenPromotionTab(config);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  const apiResponses = [];
  const apiSummaries = [];
  const responseIds = [];
  const requestPayloads = new Map();
  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    cdp.on("Network.responseReceived", (params) => {
      const url = params.response?.url || "";
      if (!["XHR", "Fetch"].includes(params.type)) return;
      if (!/doujin|cpc|branch|shop|campaign|plan|budget|bid|query|list/i.test(url)) return;
      responseIds.push({ requestId: params.requestId, url, status: params.response.status });
    });
    cdp.on("Network.requestWillBeSent", (params) => {
      const url = params.request?.url || "";
      if (!/doujin|cpc|branch|shop|campaign|plan|budget|bid|query|list/i.test(url)) return;
      requestPayloads.set(params.requestId, {
        url,
        method: params.request?.method,
        postData: params.request?.postData || "",
      });
    });
    await cdp.send("Page.navigate", { url: config.eleme.promotionUrl });
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const result = await cdp.send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(async (storeName) => {
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const input = Array.from(document.querySelectorAll('input'))
          .filter(visible)
          .find((el) => (el.placeholder || '').includes('门店') || (el.placeholder || '').includes('搜索')) ||
          Array.from(document.querySelectorAll('input')).filter(visible)[0];
        if (!input) return { ok: false, error: '没有找到搜索输入框', title: document.title, text: document.body?.innerText?.slice(0, 2000) || '' };
        input.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
        if (setter) setter.call(input, storeName);
        else input.value = storeName;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await wait(200);
        const searchButton = Array.from(document.querySelectorAll('button,[role="button"]'))
          .filter(visible)
          .find((el) => ((el.innerText || '').includes('搜索') || String(el.className || '').includes('search-button'))) ||
          input.closest('.ant-input-search')?.querySelector('button');
        if (searchButton) {
          searchButton.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
          searchButton.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
          searchButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        } else {
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
        }
        await wait(3500);
        const pageNumber = ${JSON.stringify(pageNumber)};
        if (pageNumber) {
          const pageButton = document.querySelector('.ant-pagination-item-' + pageNumber) || Array.from(document.querySelectorAll('.ant-pagination-item')).find((el) => (el.innerText || '').trim() === pageNumber);
          if (pageButton) {
            const target = pageButton.querySelector('a') || pageButton;
            target.scrollIntoView({ block: 'center', inline: 'center' });
            target.click();
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
            target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            await wait(2500);
          }
        }
        const cellDetails = (cell) => ({
          text: (cell.innerText || cell.textContent || '').trim(),
          title: cell.getAttribute('title') || '',
          ariaLabel: cell.getAttribute('aria-label') || '',
          className: String(cell.className || '').slice(0, 160),
          html: cell.innerHTML.slice(0, 1200),
          inputs: Array.from(cell.querySelectorAll('input')).map((input) => ({
            type: input.type,
            value: input.value,
            placeholder: input.placeholder,
            className: String(input.className || '').slice(0, 120)
          })),
          buttons: Array.from(cell.querySelectorAll('button,[role="button"],a')).map((button) => ({
            text: (button.innerText || button.textContent || '').trim(),
            className: String(button.className || '').slice(0, 120)
          }))
        });
        const tables = Array.from(document.querySelectorAll('table')).map((table) => ({
          headers: Array.from(table.querySelectorAll('th')).map((th) => (th.innerText || th.textContent || '').trim()),
          rows: Array.from(table.querySelectorAll('tbody tr')).slice(0, 20).map((tr) =>
            Array.from(tr.querySelectorAll('td')).map((td) => (td.innerText || td.textContent || '').trim())
          ),
          rowDetails: Array.from(table.querySelectorAll('tbody tr')).slice(0, 20).map((tr, rowIndex) => ({
            rowIndex,
            className: String(tr.className || '').slice(0, 160),
            text: (tr.innerText || tr.textContent || '').trim(),
            cells: Array.from(tr.querySelectorAll('td')).map(cellDetails)
          }))
        }));
        const matchingElements = Array.from(document.querySelectorAll('tr,.ant-table-row,div,span'))
          .filter(visible)
          .map((el) => ({
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.textContent || '').trim(),
            className: String(el.className || '').slice(0, 120),
            inputs: Array.from(el.querySelectorAll('input')).map((input) => ({
              type: input.type,
              value: input.value,
              placeholder: input.placeholder,
              className: String(input.className || '').slice(0, 100)
            }))
          }))
          .filter((item) => item.text.includes(storeName) || item.inputs.length)
          .slice(0, 60);
        return {
          ok: true,
          url: location.href,
          title: document.title,
          storeName,
          pageNumber,
          searchInput: { value: input.value, placeholder: input.placeholder, className: String(input.className || '').slice(0, 100) },
          tables,
          matchingElements,
          pageText: document.body?.innerText?.slice(0, 5000) || ''
        };
      })(${JSON.stringify(storeName)})`,
      awaitPromise: true,
    });
    for (const item of responseIds.slice(-30)) {
      try {
        const body = await cdp.send("Network.getResponseBody", { requestId: item.requestId });
        const text = body.body || "";
        let parsed = null;
        try {
          parsed = JSON.parse(text);
        } catch {}
        const summary = summarizeApiResponse(item.url, parsed);
        if (summary) apiSummaries.push(summary);
        apiResponses.push({
          url: item.url,
          status: item.status,
          request: requestPayloads.get(item.requestId) || null,
          bodyPreview: text.slice(0, 4000),
          parsedPreview: parsed ? JSON.stringify(parsed).slice(0, 4000) : null,
        });
      } catch {}
    }
    return { ...result.result.value, apiResponses, apiSummaries };
  } finally {
    cdp.close();
  }
}

async function probeExecutionControls(config, storeName, shopId = "", pageNumber = "") {
  if (!storeName && !shopId) throw new Error("请提供 --store 门店名或 --shopId");
  if (!config.eleme.promotionUrl) {
    throw new Error("automation_config.json 里还没有配置 eleme.promotionUrl");
  }
  await probeChrome(config);
  const tab = await findOrOpenPromotionTab(config);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    await cdp.send("Page.navigate", { url: config.eleme.promotionUrl });
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const result = await cdp.send("Runtime.evaluate", {
      returnByValue: true,
      awaitPromise: true,
      expression: `(async ({ storeName, shopId, pageNumber }) => {
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const visible = (el) => {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
        const input = Array.from(document.querySelectorAll('input'))
          .filter(visible)
          .find((el) => (el.placeholder || '').includes('门店') || (el.placeholder || '').includes('搜索')) ||
          Array.from(document.querySelectorAll('input')).filter(visible)[0];
        if (!input) return { ok: false, error: '没有找到搜索输入框', title: document.title, text: textOf(document.body).slice(0, 2000) };
        input.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
        if (setter) setter.call(input, storeName || shopId);
        else input.value = storeName || shopId;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await wait(200);
        const searchButton = Array.from(document.querySelectorAll('button,[role="button"]'))
          .filter(visible)
          .find((el) => textOf(el).includes('搜索') || String(el.className || '').includes('search-button')) ||
          input.closest('.ant-input-search')?.querySelector('button');
        if (searchButton) searchButton.click();
        else {
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
        }
        await wait(3500);
        if (pageNumber) {
          const pageButton = document.querySelector('.ant-pagination-item-' + pageNumber) || Array.from(document.querySelectorAll('.ant-pagination-item')).find((el) => textOf(el) === pageNumber);
          if (pageButton) {
            (pageButton.querySelector('a') || pageButton).click();
            await wait(2500);
          }
        }

        const snapshot = (label) => {
          const row = Array.from(document.querySelectorAll('tbody tr,.ant-table-row'))
            .find((tr) => (shopId && textOf(tr).includes(String(shopId))) || (storeName && textOf(tr).includes(storeName)));
          const rowCells = row ? Array.from(row.querySelectorAll('td')).map((td, index) => ({
            index,
            text: textOf(td),
            className: String(td.className || '').slice(0, 180),
            inputs: Array.from(td.querySelectorAll('input')).filter(visible).map((el) => ({
              type: el.type,
              value: el.value,
              placeholder: el.placeholder,
              className: String(el.className || '').slice(0, 140)
            })),
            buttons: Array.from(td.querySelectorAll('button,[role="button"],a')).filter(visible).map((el) => ({
              text: textOf(el),
              role: el.getAttribute('role') || '',
              className: String(el.className || '').slice(0, 160)
            }))
          })) : [];
          const controls = Array.from(document.querySelectorAll('button,[role="button"],a,input,textarea'))
            .filter(visible)
            .slice(0, 220)
            .map((el) => ({
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              role: el.getAttribute('role') || '',
              text: textOf(el) || el.value || el.placeholder || el.getAttribute('aria-label') || '',
              disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
              className: String(el.className || '').slice(0, 160)
            }));
          const overlays = Array.from(document.querySelectorAll('.ant-modal,.ant-popover,.ant-drawer,.ant-dropdown,.ant-message,.ant-notification'))
            .filter(visible)
            .map((el) => ({
              className: String(el.className || '').slice(0, 160),
              text: textOf(el).slice(0, 1500),
              inputs: Array.from(el.querySelectorAll('input,textarea')).filter(visible).map((input) => ({
                type: input.type,
                value: input.value,
                placeholder: input.placeholder,
                className: String(input.className || '').slice(0, 140)
              })),
              buttons: Array.from(el.querySelectorAll('button,[role="button"],a')).filter(visible).map((button) => ({
                text: textOf(button),
                className: String(button.className || '').slice(0, 140)
              }))
            }));
          return {
            label,
            url: location.href,
            title: document.title,
            rowFound: Boolean(row),
            rowText: row ? textOf(row).slice(0, 1000) : '',
            rowCells,
            controls,
            overlays
          };
        };

        const steps = [snapshot('搜索后')];
        const row = Array.from(document.querySelectorAll('tbody tr,.ant-table-row'))
          .find((tr) => (shopId && textOf(tr).includes(String(shopId))) || (storeName && textOf(tr).includes(storeName)));
        if (!row) return { ok: false, error: '没有找到目标门店行', steps };

        const checkbox = row.querySelector('input[type="checkbox"]');
        if (checkbox) {
          checkbox.click();
          checkbox.dispatchEvent(new Event('change', { bubbles: true }));
          await wait(900);
          steps.push(snapshot('勾选门店后'));
        }

        for (const buttonText of ['预算', '出价']) {
          const button = Array.from(document.querySelectorAll('button,[role="button"],a'))
            .filter(visible)
            .find((el) => textOf(el) === buttonText);
          if (!button) continue;
          button.click();
          await wait(1200);
          steps.push(snapshot('打开' + buttonText + '弹窗'));
          const closeButton = Array.from(document.querySelectorAll('.ant-modal button,[class*="modal"] button,.ant-drawer button,[class*="drawer"] button'))
            .filter(visible)
            .find((el) => ['取消', '关闭'].includes(textOf(el)) || String(el.className || '').includes('close'));
          if (closeButton) closeButton.click();
          else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          await wait(500);
        }

        const cells = Array.from(row.querySelectorAll('td'));
        for (const item of [
          { label: '点击出价单元格', index: 2 },
          { label: '点击预算单元格', index: 3 }
        ]) {
          const cell = cells[item.index];
          if (!cell) continue;
          cell.scrollIntoView({ block: 'center', inline: 'center' });
          cell.click();
          await wait(900);
          steps.push(snapshot(item.label));
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          await wait(300);
        }

        return { ok: true, storeName, shopId, pageNumber, steps };
      })(${JSON.stringify({ storeName, shopId, pageNumber })})`,
    });
    return result.result.value;
  } finally {
    cdp.close();
  }
}

async function runExecutionPreview(config, args) {
  const previewPath = args.file || "outputs/dianjin_automation/execution_preview_1040.json";
  const preview = JSON.parse(await fs.readFile(previewPath, "utf8"));
  const limit = args.limit === "all" ? Number.POSITIVE_INFINITY : Number(args.limit || 1);
  const rows = (preview.rows || [])
    .filter((row) => row.canExecute)
    .filter((row) => !args.type || row.type === args.type)
    .filter((row) => !args.store || row.store.includes(args.store))
    .filter((row) => !args.shopId || Number(row.shopId) === Number(args.shopId))
    .filter((row) => row.type !== "bid-check" || row.currentBid !== row.targetBid)
    .filter((row) => row.type !== "budget" || row.currentBudget !== row.targetBudget)
    .slice(0, limit);
  const commit = args.commit === true || args.commit === "true";
  if (commit && config.safety?.dryRun !== false) {
    throw new Error("当前 automation_config.json 的 safety.dryRun 仍为 true，禁止正式保存");
  }
  if (!rows.length) {
    return { ok: true, mode: commit ? "commit" : "rehearse", previewPath, total: 0, results: [] };
  }

  await probeChrome(config);
  const tab = await findOrOpenPromotionTab(config);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  const results = [];
  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    await cdp.send("Page.navigate", { url: config.eleme.promotionUrl });
    await new Promise((resolve) => setTimeout(resolve, 5000));
    for (const row of rows) {
      await cdp.send("Page.navigate", { url: config.eleme.promotionUrl });
      await new Promise((resolve) => setTimeout(resolve, 3500));
      const value = row.type === "budget" ? row.targetBudget : row.targetBid;
      const actionButton = row.type === "budget" ? "预算" : "出价";
      const result = await cdp.send("Runtime.evaluate", {
        returnByValue: true,
        awaitPromise: true,
        expression: `(async ({ row, value, actionButton, commit }) => {
          const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
          const visible = (el) => {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const textOf = (el) => (el?.innerText || el?.textContent || '').trim();
          const setInputValue = (input, nextValue) => {
            input.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(input, String(nextValue));
            else input.value = String(nextValue);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
          };
          const clickButtonByText = async (buttonText) => {
            const button = Array.from(document.querySelectorAll('button,[role="button"],a'))
              .filter(visible)
              .find((el) => textOf(el).replace(/\\s/g, '') === buttonText.replace(/\\s/g, ''));
            if (!button) return false;
            await clickElement(button);
            await wait(900);
            return true;
          };
          const clickElement = async (el) => {
            el.scrollIntoView({ block: 'center', inline: 'center' });
            const rect = el.getBoundingClientRect();
            const eventInit = {
              bubbles: true,
              cancelable: true,
              view: window,
              clientX: rect.left + rect.width / 2,
              clientY: rect.top + rect.height / 2,
              button: 0,
              buttons: 1,
            };
            el.dispatchEvent(new PointerEvent('pointerover', eventInit));
            el.dispatchEvent(new MouseEvent('mouseover', eventInit));
            el.dispatchEvent(new PointerEvent('pointermove', eventInit));
            el.dispatchEvent(new MouseEvent('mousemove', eventInit));
            el.dispatchEvent(new PointerEvent('pointerdown', eventInit));
            el.dispatchEvent(new MouseEvent('mousedown', eventInit));
            el.dispatchEvent(new PointerEvent('pointerup', { ...eventInit, buttons: 0 }));
            el.dispatchEvent(new MouseEvent('mouseup', { ...eventInit, buttons: 0 }));
            el.dispatchEvent(new MouseEvent('click', { ...eventInit, buttons: 0 }));
            if (typeof el.click === 'function') el.click();
            await wait(300);
          };
          const closeActiveModal = async () => {
            const modals = Array.from(document.querySelectorAll('.ant-modal')).filter(visible);
            const modal = modals.at(-1);
            if (!modal) return false;
            const cancel = Array.from(modal.querySelectorAll('button,[role="button"],a'))
              .filter(visible)
              .find((button) => textOf(button).replace(/\\s/g, '') === '取消' || String(button.className || '').includes('ant-modal-close'));
            if (cancel) cancel.click();
            else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            await wait(600);
            return true;
          };
          const snapshotModal = () => {
            const modals = Array.from(document.querySelectorAll('.ant-modal')).filter(visible);
            const modal = modals.at(-1);
            if (!modal) return null;
            return {
              text: textOf(modal).slice(0, 1200),
              inputs: Array.from(modal.querySelectorAll('input')).filter(visible).map((input) => ({
                type: input.type,
                value: input.value,
                checked: Boolean(input.checked),
                placeholder: input.placeholder,
                className: String(input.className || '').slice(0, 140)
              })),
              buttons: Array.from(modal.querySelectorAll('button,[role="button"],a')).filter(visible).map((button) => ({
                text: textOf(button),
                disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true'),
                className: String(button.className || '').slice(0, 140)
              }))
            };
          };
          const chooseRadioByText = async (modal, labelText) => {
            const normalizedLabel = labelText.replace(/\\s/g, '');
            const wrappers = Array.from(modal.querySelectorAll('.ant-radio-wrapper,label,[class*="radio"]'))
              .filter(visible)
              .filter((el) => textOf(el).replace(/\\s/g, '').includes(normalizedLabel));
            const wrapper = wrappers[0];
            if (!wrapper) return false;
            const radio = wrapper.querySelector('input[type="radio"]');
            const clickTargets = [
              wrapper.querySelector('.ant-radio'),
              wrapper.querySelector('.ant-radio-inner'),
              wrapper,
              radio
            ].filter(Boolean);
            for (const target of clickTargets) {
              const rect = target.getBoundingClientRect();
              const eventInit = {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2,
              };
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.dispatchEvent(new PointerEvent('pointerdown', eventInit));
              target.dispatchEvent(new MouseEvent('mousedown', eventInit));
              target.dispatchEvent(new PointerEvent('pointerup', eventInit));
              target.dispatchEvent(new MouseEvent('mouseup', eventInit));
              target.dispatchEvent(new MouseEvent('click', eventInit));
              if (typeof target.click === 'function') target.click();
              await wait(250);
              const nowChecked = Boolean(radio?.checked) ||
                Boolean(wrapper.querySelector('.ant-radio-checked')) ||
                String(wrapper.className || '').includes('ant-radio-wrapper-checked');
              if (nowChecked) return true;
            }
            return false;
          };

          await closeActiveModal();
          const searchTerm = String(row.shopId || row.store);
          const input = Array.from(document.querySelectorAll('input'))
            .filter(visible)
            .find((el) => (el.placeholder || '').includes('门店') || (el.placeholder || '').includes('搜索')) ||
            Array.from(document.querySelectorAll('input')).filter(visible)[0];
          if (!input) return { ok: false, store: row.store, shopId: row.shopId, error: '没有找到搜索输入框' };
          setInputValue(input, searchTerm);
          const searchButton = Array.from(document.querySelectorAll('button,[role="button"]'))
            .filter(visible)
            .find((el) => textOf(el).includes('搜索') || String(el.className || '').includes('search-button')) ||
            input.closest('.ant-input-search')?.querySelector('button');
          if (searchButton) searchButton.click();
          else input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          await wait(2600);

          let targetRow = Array.from(document.querySelectorAll('tbody tr,.ant-table-row'))
            .find((tr) => textOf(tr).includes(String(row.shopId)));
          if (!targetRow) {
            const pageTwo = document.querySelector('.ant-pagination-item-2') ||
              Array.from(document.querySelectorAll('.ant-pagination-item')).find((el) => textOf(el) === '2');
            if (pageTwo) {
              (pageTwo.querySelector('a') || pageTwo).click();
              await wait(2200);
              targetRow = Array.from(document.querySelectorAll('tbody tr,.ant-table-row'))
                .find((tr) => textOf(tr).includes(String(row.shopId)));
            }
          }
          if (!targetRow) return { ok: false, store: row.store, shopId: row.shopId, error: '没有找到目标门店行' };
          const rowText = textOf(targetRow).slice(0, 1000);
          const checkbox = targetRow.querySelector('input[type="checkbox"]');
          if (!checkbox) return { ok: false, store: row.store, shopId: row.shopId, rowText, error: '没有找到行选择框' };
          if (!checkbox.checked) {
            checkbox.click();
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            await wait(800);
          }

          const opened = await clickButtonByText(actionButton);
          if (!opened) return { ok: false, store: row.store, shopId: row.shopId, rowText, error: '没有找到' + actionButton + '按钮' };
          const modals = Array.from(document.querySelectorAll('.ant-modal')).filter(visible);
          const modal = modals.at(-1);
          if (!modal) return { ok: false, store: row.store, shopId: row.shopId, rowText, error: '没有打开设置弹窗' };
          const valueInput = Array.from(modal.querySelectorAll('input[type="text"],input:not([type])'))
            .filter(visible)
            .find((input) => String(input.className || '').includes('ant-input-number-input')) ||
            Array.from(modal.querySelectorAll('input')).filter(visible)[0];
          if (!valueInput) return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: snapshotModal(), error: '弹窗里没有找到数值输入框' };
          setInputValue(valueInput, value);
          if (row.type === 'budget' && textOf(modal).includes('快速获量')) {
            const quickChosen = await chooseRadioByText(modal, '快速获量');
            if (!quickChosen) {
              return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: snapshotModal(), error: '预算弹窗要求获量速度，但没有找到快速获量选项', saved: false };
            }
            await wait(300);
            setInputValue(valueInput, value);
          }
          if (row.type === 'bid-check') {
            if (/出价助手|出价模式/.test(textOf(modal))) {
              const checkedAssistant = Array.from(modal.querySelectorAll('.ant-switch,button[role="switch"]'))
                .filter(visible)
                .some((el) => (el.getAttribute('aria-checked') === 'true') || String(el.className || '').includes('ant-switch-checked'));
              if (checkedAssistant) {
                return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: snapshotModal(), error: '检测到出价助手或出价模式控件处于开启状态，禁止保存；脚本不会调整这些设置', saved: false };
              }
            }
            const assistantSwitch = Array.from(modal.querySelectorAll('.ant-switch,button[role="switch"]'))
              .filter(visible)
              .find((el) => textOf(modal).includes('出价助手')) || null;
            if (assistantSwitch) {
              const isChecked = assistantSwitch.getAttribute('aria-checked') === 'true' || String(assistantSwitch.className || '').includes('ant-switch-checked');
              if (isChecked) {
                return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: snapshotModal(), error: '出价助手已开启，禁止保存；脚本不会关闭或调整出价助手', saved: false };
              }
            }
          }
          await wait(400);
          const modalAfterFill = snapshotModal();
          let saved = false;
          if (commit) {
            const okButton = Array.from(modal.querySelectorAll('button,[role="button"],a'))
              .filter(visible)
              .find((button) => textOf(button).replace(/\\s/g, '') === '确定');
            if (!okButton) return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: modalAfterFill, error: '没有找到确定按钮' };
            await clickElement(okButton);
            saved = true;
            let stillOpen = true;
            const modalTitleText = actionButton === '预算' ? '设置预算' : '设置出价';
            const start = Date.now();
            while (Date.now() - start < 16000) {
              const openModals = Array.from(document.querySelectorAll('.ant-modal')).filter(visible);
              const targetModal = openModals.find((item) => textOf(item).includes(modalTitleText));
              stillOpen = Boolean(targetModal);
              if (!stillOpen) break;
              const loadingButton = Array.from(targetModal.querySelectorAll('button,[role="button"],a'))
                .filter(visible)
                .find((button) => textOf(button).replace(/\s/g, '') === '确定' && String(button.className || '').includes('ant-btn-loading'));
              await wait(500);
            }
            if (stillOpen) {
              return { ok: false, store: row.store, shopId: row.shopId, rowText, modal: snapshotModal(), error: '点确定后弹窗仍未关闭，可能页面校验未通过', saved: false };
            }
          } else {
            await closeActiveModal();
          }
          return {
            ok: true,
            store: row.store,
            shopId: row.shopId,
            type: row.type,
            actionButton,
            value,
            currentBid: row.currentBid,
            targetBid: row.targetBid,
            currentBudget: row.currentBudget,
            targetBudget: row.targetBudget,
            rowText,
            modalAfterFill,
            saved
          };
        })(${JSON.stringify({ row, value, actionButton, commit })})`,
      });
      results.push(result.result.value);
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  } finally {
    cdp.close();
  }
  return {
    ok: results.every((result) => result.ok),
    mode: commit ? "commit" : "rehearse",
    previewPath,
    total: rows.length,
    results,
  };
}

function summarizeApiResponse(url, parsed) {
  if (!parsed || typeof parsed !== "object") return null;
  const data = parsed.result?.data;
  if (url.includes("getRestaurantTree") && data) {
    const shops = [];
    const visit = (node) => {
      if (!node) return;
      shops.push({
        id: node.id,
        name: node.name,
        restaurantType: node.restaurantType,
        validShopId: node.validShopId,
        parentId: node.parentId,
      });
      for (const child of node.childList || []) visit(child);
    };
    visit(data);
    return { type: "restaurantTree", shops };
  }
  if (url.includes("queryBranchSolutions") && Array.isArray(data)) {
    return {
      type: "branchSolutions",
      solutions: data.map((solution) => {
        const adgroup = solution.adgroupList?.[0] || {};
        return {
          campaignId: solution.id,
          shopId: Number(adgroup.shopId || adgroup.entityId || 0),
          entityName: adgroup.entityName || "",
          budget: solution.budget,
          bidPrice: solution.bidPrice ?? adgroup.bidPrice,
          state: solution.state,
          auditState: solution.auditState,
          riskState: solution.riskState,
          launchHours: solution.launchHours,
          launchHoursHalf: solution.launchHoursHalf,
          gmtModified: adgroup.gmtModified || solution.gmtModified || null,
        };
      }),
    };
  }
  if (url.includes("queryBranchSummary") && data) {
    return { type: "branchSummary", data };
  }
  return null;
}

async function main() {
  const args = parseArgs(process.argv);
  const { rules, logic, config } = await loadRuntime();
  const tasks = filterTasks(logic.buildTasks(rules), args);
  const actions = tasks.map(taskToAction);

  if (args.command === "probe") {
    const version = await probeChrome(config);
    console.log(JSON.stringify({ ok: true, browser: version.Browser, webSocketDebuggerUrl: version.webSocketDebuggerUrl }, null, 2));
    return;
  }

  if (args.command === "probe-page") {
    const pageInfo = await probePromotionPage(config);
    await fs.mkdir(outputDir, { recursive: true });
    const outputPath = `${outputDir}/eleme_page_probe_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    await fs.writeFile(outputPath, JSON.stringify(pageInfo, null, 2), "utf8");
    console.log(`页面探测已保存：${outputPath}`);
    console.log(`标题：${pageInfo.title}`);
    console.log(`地址：${pageInfo.url}`);
    console.log(`控件数：${pageInfo.controls.length}`);
    console.log(pageInfo.controls.slice(0, 20).map((item) => `- ${item.tag} ${item.type || item.role} ${item.text}`).join("\n"));
    return;
  }

  if (args.command === "probe-store") {
    const pageInfo = await probeStore(config, args.store, args.page || "");
    await fs.mkdir(outputDir, { recursive: true });
    const safeStore = String(args.store || "store").replace(/[\\/:*?"<>|]/g, "_");
    const outputPath = `${outputDir}/eleme_store_probe_${safeStore}_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    await fs.writeFile(outputPath, JSON.stringify(pageInfo, null, 2), "utf8");
    console.log(`门店探测已保存：${outputPath}`);
    console.log(`标题：${pageInfo.title}`);
    console.log(`地址：${pageInfo.url}`);
    console.log(`匹配元素：${pageInfo.matchingElements?.length || 0}`);
    console.log((pageInfo.matchingElements || []).slice(0, 10).map((item) => `- ${item.tag}: ${item.text.slice(0, 120)}`).join("\n"));
    return;
  }

  if (args.command === "probe-execution-controls") {
    const pageInfo = await probeExecutionControls(config, args.store || "金融街店", args.shopId || "", args.page || "");
    await fs.mkdir(outputDir, { recursive: true });
    const safeStore = String(args.store || args.shopId || "store").replace(/[\\/:*?"<>|]/g, "_");
    const outputPath = `${outputDir}/eleme_execution_controls_${safeStore}_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    await fs.writeFile(outputPath, JSON.stringify(pageInfo, null, 2), "utf8");
    console.log(`执行控件探测已保存：${outputPath}`);
    console.log(`结果：${pageInfo.ok ? "成功" : "未完成"}${pageInfo.error ? `，${pageInfo.error}` : ""}`);
    for (const step of pageInfo.steps || []) {
      const usefulControls = (step.controls || []).filter((item) => /预算|出价|批量|修改|保存|确定|取消|编辑|设置|开启|关闭/.test(item.text));
      console.log(`- ${step.label}：行${step.rowFound ? "已找到" : "未找到"}，弹层 ${step.overlays?.length || 0}，相关控件 ${usefulControls.length}`);
      for (const control of usefulControls.slice(0, 12)) {
        console.log(`  · ${control.tag} ${control.text}${control.disabled ? "（不可用）" : ""}`);
      }
    }
    return;
  }

  if (args.command === "fetch-solutions") {
    const pageNum = Number(args.page || 1);
    const data = await fetchBranchSolutions(config, pageNum, Number(args.pageSize || 10));
    const summary = summarizeApiResponse("method=queryBranchSolutions", data);
    await fs.mkdir(outputDir, { recursive: true });
    const outputPath = `${outputDir}/eleme_branch_solutions_page${pageNum}_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    await fs.writeFile(outputPath, JSON.stringify({ pageNum, raw: data, summary }, null, 2), "utf8");
    console.log(`计划接口数据已保存：${outputPath}`);
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "execute-preview") {
    const output = await runExecutionPreview(config, args);
    await fs.mkdir(outputDir, { recursive: true });
    const outputPath = `${outputDir}/eleme_execution_${output.mode}_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    await fs.writeFile(outputPath, JSON.stringify(output, null, 2), "utf8");
    console.log(`${output.mode === "commit" ? "正式执行" : "执行演练"}结果已保存：${outputPath}`);
    console.log(`任务数：${output.total}，成功：${output.results.filter((item) => item.ok).length}，失败：${output.results.filter((item) => !item.ok).length}`);
    for (const item of output.results) {
      const action = item.type === "budget" ? `预算 ${item.currentBudget} -> ${item.targetBudget}` : `出价 ${item.currentBid} -> ${item.targetBid}`;
      console.log(`- ${item.ok ? "成功" : "失败"} ${item.store}：${item.error || action}${item.saved ? "，已保存" : "，未保存"}`);
    }
    if (!output.ok || output.results.some((item) => !item.ok)) {
      process.exitCode = 1;
    }
    return;
  }

  if (args.command === "analyze-probe") {
    const probePath = args.file || (await latestProbeFile("eleme_store_probe_")) || (await latestProbeFile("eleme_page_probe_"));
    if (!probePath) throw new Error("没有找到可分析的页面探测文件");
    const probe = JSON.parse(await fs.readFile(probePath, "utf8"));
    const rows = parseTableRowsFromProbe(probe);
    const output = {
      probePath,
      title: probe.title,
      url: probe.url,
      rowCount: rows.length,
      rows,
    };
    console.log(JSON.stringify(output, null, 2));
    return;
  }

  if (args.command === "analyze-state") {
    const probePath = args.file || (await latestProbeFile("eleme_store_probe_")) || (await latestProbeFile("eleme_page_probe_"));
    if (!probePath) throw new Error("没有找到可分析的页面探测文件");
    const probe = JSON.parse(await fs.readFile(probePath, "utf8"));
    const currentRows = currentRowsFromProbe(probe);
    const recommendations = makeRecommendations(logic.buildTasks(rules), currentRows, args, logic);
    const output = {
      probePath,
      generatedAt: new Date().toISOString(),
      currentRows,
      recommendations,
      summary: {
        currentRows: currentRows.length,
        recommendations: recommendations.length,
        found: recommendations.filter((item) => item.found).length,
        missing: recommendations.filter((item) => !item.found).length,
      },
    };
    if (args.output) {
      await fs.writeFile(args.output, JSON.stringify(output, null, 2), "utf8");
      console.log(`状态分析已保存：${args.output}`);
    } else {
      console.log(JSON.stringify(output, null, 2));
    }
    return;
  }

  if (args.command === "analyze-state-combined") {
    const combined = await combinedCurrentRowsFromLatestProbes();
    const recommendations = makeRecommendations(logic.buildTasks(rules), combined.rows, args, logic);
    const output = {
      probeFiles: combined.files,
      generatedAt: new Date().toISOString(),
      currentRows: combined.rows,
      recommendations,
      summary: {
        currentRows: combined.rows.length,
        recommendations: recommendations.length,
        found: recommendations.filter((item) => item.found).length,
        missing: recommendations.filter((item) => !item.found).length,
      },
    };
    if (args.output) {
      await fs.writeFile(args.output, JSON.stringify(output, null, 2), "utf8");
      console.log(`合并状态分析已保存：${args.output}`);
    } else {
      console.log(JSON.stringify(output, null, 2));
    }
    return;
  }

  if (args.command === "plan") {
    console.log(JSON.stringify({ summary: summarize(actions), actions }, null, 2));
    return;
  }

  if (args.command !== "dry-run") {
    throw new Error(`未知命令：${args.command}`);
  }

  await fs.mkdir(outputDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const outputPath = `${outputDir}/eleme_dry_run_${stamp}.json`;
  const payload = {
    generatedAt: new Date().toISOString(),
    dryRun: true,
    sourceFile: rules.sourceFile,
    config: {
      promotionUrl: config.eleme.promotionUrl,
      promotionUrlConfigured: Boolean(config.eleme.promotionUrl),
      requireStoreNameCheck: config.safety.requireStoreNameCheck,
      requireBeforeSaveConfirm: config.safety.requireBeforeSaveConfirm,
    },
    summary: summarize(actions),
    actions,
  };
  await fs.writeFile(outputPath, JSON.stringify(payload, null, 2), "utf8");

  console.log(`试运行已生成：${outputPath}`);
  console.log(`饿了么点金页面：${config.eleme.promotionUrl || "未配置"}`);
  console.log(`任务数：${payload.summary.actionCount}，预算任务：${payload.summary.setBudget}，消耗检查：${payload.summary.checkSpendAndAdjustBid}`);
  for (const action of actions.slice(0, Number(args.limit || 8))) {
    console.log(`- ${action.time} ${action.store}: ${action.instruction}`);
  }
  if (actions.length > Number(args.limit || 8)) {
    console.log(`... 还有 ${actions.length - Number(args.limit || 8)} 条`);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
