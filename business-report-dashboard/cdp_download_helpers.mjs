async function getJson(url) {
  const response = await fetch(url);
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${response.status} ${url}\n${text.slice(0, 300)}`);
  }
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.handlers = {};
  }

  async ready() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
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
      } else if (message.method && this.handlers[message.method]) {
        for (const handler of this.handlers[message.method]) handler(message.params);
      }
    };
  }

  on(method, handler) {
    if (!this.handlers[method]) this.handlers[method] = [];
    this.handlers[method].push(handler);
  }

  async send(method, params = {}) {
    await this.ready();
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  close() {
    this.ws.close();
  }
}

async function findOrOpenPage(debugUrl, urlPart, openUrl) {
  const tabs = await getJson(`${debugUrl}/json`);
  const existing = tabs.find((tab) => tab.type === "page" && tab.url.includes(urlPart));
  if (existing) return existing;
  return getJson(`${debugUrl}/json/new?${encodeURIComponent(openUrl)}`);
}

async function elemeLatest(debugUrl, openUrl, targetDate = "") {
  const tab = await findOrOpenPage(debugUrl, "melody-stats-next.ele.me/new/#/download-center", openUrl);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  const histories = [];
  const historyRequestIds = [];
  try {
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    cdp.on("Network.responseReceived", (params) => {
      const url = params.response?.url || "";
      if (!url.includes("/api/download/queryHistoryTaskList")) return;
      if (!["XHR", "Fetch"].includes(params.type)) return;
      historyRequestIds.push(params.requestId);
    });
    await cdp.send("Page.navigate", { url: openUrl });
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await cdp.send("Page.reload", { ignoreCache: true });
    await new Promise((resolve) => setTimeout(resolve, 12000));
    for (const requestId of historyRequestIds) {
      try {
        const body = await cdp.send("Network.getResponseBody", { requestId });
        histories.push(JSON.parse(body.body));
      } catch {}
    }
    const history = histories.find((item) => item?.code === 0 && Array.isArray(item?.data)) || histories.at(-1);
    const rows = Array.isArray(history?.data) ? history.data : [];
    const ready = rows.find((row) => {
      if (!(row.downloadStatus === 1 && row.downloadUrl && row.fileName)) return false;
      return !targetDate || row.fileName.includes(targetDate);
    });
    if (!ready) {
      throw new Error(`下载列表里没有可下载的饿了么文件：${JSON.stringify(history || {}).slice(0, 1000)}`);
    }
    return {
      platform: "eleme",
      filename: ready.fileName,
      url: ready.downloadUrl,
      created_at: ready.gmtCreate || null,
      task_id: ready.taskId || null,
    };
  } finally {
    cdp.close();
  }
}

const command = process.argv[2];
const debugUrl = process.argv[3];
const openUrl = process.argv[4];
const targetDate = process.argv[5] || "";

if (command === "eleme-latest") {
  const latest = await elemeLatest(debugUrl, openUrl, targetDate);
  process.stdout.write(JSON.stringify(latest));
} else {
  throw new Error(`未知命令：${command}`);
}
