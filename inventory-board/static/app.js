const INVENTORY_ORDER_KEY = "inventory-card-order-v1";

function readInventoryOrder() {
  try {
    const value = JSON.parse(localStorage.getItem(INVENTORY_ORDER_KEY) || "[]");
    return Array.isArray(value) ? [...new Set(value.filter((sku) => typeof sku === "string"))] : [];
  } catch {
    return [];
  }
}

const state = {
  inventory: [],
  cardOrder: readInventoryOrder(),
  reordering: false,
  draggedSku: null,
  deliveryMonth: "",
  inboundTemplate: null,
};

const els = {
  form: document.querySelector("#uploadForm"),
  file: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  message: document.querySelector("#uploadMessage"),
  grid: document.querySelector("#inventoryGrid"),
  reorder: document.querySelector("#reorderButton"),
  resetOrder: document.querySelector("#resetOrderButton"),
  orderMessage: document.querySelector("#orderMessage"),
  productCount: document.querySelector("#productCount"),
  warningCount: document.querySelector("#warningCount"),
  search: document.querySelector("#searchInput"),
  filter: document.querySelector("#statusFilter"),
  imports: document.querySelector("#importsList"),
  movements: document.querySelector("#movementsList"),
  storeDeliveries: document.querySelector("#storeDeliveryGrid"),
  deliveryMonth: document.querySelector("#deliveryMonthSelect"),
  refresh: document.querySelector("#refreshButton"),
  feishuSync: document.querySelector("#feishuSyncButton"),
  feishuSyncMessage: document.querySelector("#feishuSyncMessage"),
  templateDownloadLink: document.querySelector("#templateDownloadLink"),
  templateStatusText: document.querySelector("#templateStatusText"),
};

els.file.addEventListener("change", () => {
  els.fileName.textContent = els.file.files[0]?.name || "选择 Excel 文件";
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(els.form);
  setMessage("正在导入...");
  try {
    const response = await fetch("/api/import", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "导入失败");
    const text = payload.status === "duplicate" ? payload.message : `导入成功：${payload.line_count} 行`;
    setMessage(text, "ok");
    els.form.reset();
    els.fileName.textContent = "选择 Excel 文件";
    await loadAll();
  } catch (error) {
    setMessage(error.message, "error");
  }
});

els.reorder.addEventListener("click", () => {
  state.reordering = !state.reordering;
  els.reorder.textContent = state.reordering ? "完成排序" : "调整顺序";
  els.reorder.setAttribute("aria-pressed", String(state.reordering));
  els.orderMessage.textContent = state.reordering
    ? "拖动手柄或点击前移、后移；顺序自动保存到当前浏览器"
    : "顺序自动保存在当前浏览器";
  renderInventory();
});

els.resetOrder.addEventListener("click", () => {
  state.cardOrder = [];
  saveInventoryOrder("已恢复默认顺序");
  renderInventory();
});

function orderedInventory() {
  const bySku = new Map(state.inventory.map((item) => [item.sku, item]));
  const saved = state.cardOrder.filter((sku) => bySku.has(sku));
  const seen = new Set(saved);
  return [...saved.map((sku) => bySku.get(sku)), ...state.inventory.filter((item) => !seen.has(item.sku))];
}

function saveInventoryOrder(message = "顺序已保存到当前浏览器") {
  try {
    localStorage.setItem(INVENTORY_ORDER_KEY, JSON.stringify(state.cardOrder));
    els.orderMessage.textContent = message;
  } catch {
    els.orderMessage.textContent = "当前浏览器无法保存顺序，本次调整仅在当前页面生效";
  }
}

function moveInventoryCard(sku, targetSku, after = false) {
  if (!state.reordering || sku === targetSku) return;
  const order = orderedInventory().map((item) => item.sku);
  if (!order.includes(sku) || !order.includes(targetSku)) return;
  order.splice(order.indexOf(sku), 1);
  order.splice(order.indexOf(targetSku) + (after ? 1 : 0), 0, sku);
  state.cardOrder = order;
  saveInventoryOrder();
  renderInventory();
}

els.grid.addEventListener("click", (event) => {
  const button = event.target.closest("[data-order-move]");
  if (!button || !state.reordering) return;
  const cards = [...els.grid.querySelectorAll(".sku-card")];
  const card = button.closest(".sku-card");
  const direction = Number(button.dataset.orderMove);
  const target = cards[cards.indexOf(card) + direction];
  if (target) {
    moveInventoryCard(card.dataset.sku, target.dataset.sku, direction > 0);
    const moved = [...els.grid.querySelectorAll(".sku-card")].find((item) => item.dataset.sku === card.dataset.sku);
    const focus = moved?.querySelector(`[data-order-move="${direction}"]:not(:disabled)`) || moved?.querySelector("[data-order-move]:not(:disabled)");
    focus?.focus();
  }
});

els.grid.addEventListener("dragstart", (event) => {
  const handle = event.target.closest(".order-drag-handle");
  if (!state.reordering || !handle) { event.preventDefault(); return; }
  state.draggedSku = handle.closest(".sku-card").dataset.sku;
  event.dataTransfer.setData("text/plain", state.draggedSku);
  event.dataTransfer.effectAllowed = "move";
});

function clearDropTargets() {
  els.grid.querySelectorAll(".order-drop-target").forEach((card) => card.classList.remove("order-drop-target"));
}
els.grid.addEventListener("dragover", (event) => {
  const card = event.target.closest(".sku-card");
  if (!state.reordering || !state.draggedSku || !card) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  clearDropTargets();
  card.classList.add("order-drop-target");
});
els.grid.addEventListener("drop", (event) => {
  const card = event.target.closest(".sku-card");
  if (!state.reordering || !state.draggedSku || !card) return;
  event.preventDefault();
  const from = state.draggedSku;
  const to = card.dataset.sku;
  const order = orderedInventory().map((item) => item.sku);
  state.draggedSku = null;
  clearDropTargets();
  moveInventoryCard(from, to, order.indexOf(from) < order.indexOf(to));
});
els.grid.addEventListener("dragend", () => { state.draggedSku = null; clearDropTargets(); });

els.search.addEventListener("input", renderInventory);
els.filter.addEventListener("change", renderInventory);
els.deliveryMonth.addEventListener("change", async () => {
  state.deliveryMonth = els.deliveryMonth.value;
  const storeDeliveries = await fetchJson(`/api/store-deliveries?month=${encodeURIComponent(state.deliveryMonth)}`);
  renderStoreDeliveries(storeDeliveries);
});
els.refresh.addEventListener("click", loadAll);
els.feishuSync.addEventListener("click", syncToFeishu);

async function syncToFeishu() {
  els.feishuSync.disabled = true;
  setSyncMessage("正在同步当前库存到飞书…");
  try {
    const response = await fetch("/api/feishu/inventory-sync", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "飞书同步失败");
    const target = [payload.spreadsheet_title, payload.sheet_title].filter(Boolean).join(" / ") || payload.sheet_id || "目标飞书表";
    setSyncMessage(`同步成功：${target} 已写入 ${payload.row_count} 项库存，读回校验 ${payload.verified_row_count} 行（${payload.synced_at}）`, "ok");
  } catch (error) {
    setSyncMessage(error.message, "error");
  } finally {
    els.feishuSync.disabled = false;
  }
}

function setSyncMessage(text, type = "") {
  els.feishuSyncMessage.textContent = text;
  els.feishuSyncMessage.className = `message sync-message ${type}`;
}

async function loadAll() {
  const [summary, imports, movements, storeDeliveries, templateStatus] = await Promise.all([
    fetchJson("/api/summary"),
    fetchJson("/api/imports"),
    fetchJson("/api/movements"),
    fetchJson(state.deliveryMonth ? `/api/store-deliveries?month=${encodeURIComponent(state.deliveryMonth)}` : "/api/store-deliveries"),
    fetchJson("/api/inbound-template/status"),
  ]);
  state.inventory = summary.items;
  state.inboundTemplate = templateStatus;
  els.productCount.textContent = summary.stats.product_count;
  els.warningCount.textContent = summary.stats.warning_count;
  renderInventory();
  renderImports(imports.items);
  renderMovements(movements.items);
  renderStoreDeliveries(storeDeliveries);
  renderTemplateStatus();
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("数据读取失败");
  return response.json();
}

function renderInventory() {
  const term = els.search.value.trim().toLowerCase();
  const filter = els.filter.value;
  const rows = orderedInventory().filter((item) => {
    const matchText = `${item.name} ${item.sku}`.toLowerCase().includes(term);
    const balance = Number(item.balance);
    const threshold = Number(item.warning_threshold);
    if (!matchText) return false;
    if (filter === "warning") return balance <= threshold;
    if (filter === "negative") return balance < 0;
    return true;
  });

  els.grid.innerHTML = rows
    .map((item, index) => {
      const balance = Number(item.balance);
      const threshold = Number(item.warning_threshold);
      const status = balance < 0 ? "danger" : balance <= threshold ? "warn" : "ok";
      const label = balance < 0 ? "负库存" : balance <= threshold ? "需补货" : "正常";
      const ratio = threshold > 0 ? Math.max(0, Math.min(100, (balance / threshold) * 100)) : 100;
      return `
        <article class="sku-card color-${state.inventory.indexOf(item) % 12} ${status}" data-sku="${escapeHtml(item.sku)}">
          ${state.reordering ? `<div class="card-order-controls">
            <span class="order-drag-handle" draggable="true" title="拖动调整顺序">⠿ 拖动</span>
            <button type="button" data-order-move="-1" aria-label="${shortName(item.name)}前移" ${index === 0 ? "disabled" : ""}>前移</button>
            <button type="button" data-order-move="1" aria-label="${shortName(item.name)}后移" ${index === rows.length - 1 ? "disabled" : ""}>后移</button>
          </div>` : ""}
          <div class="sku-top">
            <span class="sku-code">${escapeHtml(item.sku)}</span>
            ${status === "ok" ? "" : `<span class="status-dot">${label}</span>`}
          </div>
          <h3>${shortName(item.name)}</h3>
          <div class="sku-balance">
            <strong>${formatNumber(balance)}</strong>
            <span>${escapeHtml(item.unit || "")}</span>
          </div>
          <div class="meter"><span style="width:${ratio}%"></span></div>
          <div class="sku-meta">
            <span>${escapeHtml(item.spec || "无规格")}</span>
            <label>预警 <input class="warning-input" type="number" min="0" step="1" value="${formatNumber(threshold)}" data-sku="${escapeHtml(item.sku)}" /></label>
          </div>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll(".warning-input").forEach((input) => {
    input.addEventListener("change", async () => {
      await fetch(`/api/products/${encodeURIComponent(input.dataset.sku)}/warning`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ warning_threshold: Number(input.value) }),
      });
      await loadAll();
    });
  });
}

function renderImports(items) {
  els.imports.innerHTML = items.length
    ? items.map((item) => `
      <div class="list-item">
        <div>
          <b>${escapeHtml(item.filename)}</b>
          <small>${typeName(item.movement_type)} · ${sourceName(item.source)} · ${escapeHtml(item.created_at)}</small>
          ${item.message ? `<small class="list-message ${item.status === "failed" ? "error" : ""}">${escapeHtml(item.message)}</small>` : ""}
        </div>
        <span class="tag ${item.status === "success" ? "ok" : "danger"}">${statusName(item.status)} ${item.line_count || 0} 行</span>
      </div>
    `).join("")
    : `<small>还没有导入记录</small>`;
}

function renderMovements(items) {
  els.movements.innerHTML = items.length
    ? items.map((item) => `
      <div class="list-item">
        <div><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.filename)} · ${escapeHtml(item.created_at)}</small></div>
        <span class="tag ${item.movement_type === "inbound" ? "ok" : "warn"}">${typeName(item.movement_type)} ${formatNumber(item.quantity)}</span>
      </div>
    `).join("")
    : `<small>还没有库存流水</small>`;
}

function renderStoreDeliveries(payload) {
  const stores = payload.items || [];
  const months = payload.months || [];
  state.deliveryMonth = payload.selected_month || state.deliveryMonth || "";
  els.deliveryMonth.innerHTML = months.length
    ? months.map((month) => `<option value="${escapeHtml(month)}" ${month === state.deliveryMonth ? "selected" : ""}>${escapeHtml(month)}</option>`).join("")
    : `<option value="">暂无月份</option>`;

  els.storeDeliveries.innerHTML = stores.length
    ? stores.map((store) => `
      <article class="store-card">
        <div class="store-title">
          <strong>${escapeHtml(store.store_name)}</strong>
          <span>${formatNumber(store.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0))} 件</span>
        </div>
        ${renderDeliveryDates(store.dates || [])}
        <div class="delivery-tags">
          ${store.items.map((item) => `
            <span title="${escapeHtml(item.sku)}">
              ${shortName(item.product_name || item.sku)}
              <b>${formatNumber(item.quantity)}</b>
            </span>
          `).join("")}
        </div>
      </article>
    `).join("")
    : `<small>还没有门店配送记录</small>`;
}

function renderDeliveryDates(dates) {
  if (!dates.length) return "";
  return `
    <div class="delivery-dates">
      ${dates.slice(0, 4).map((item) => `
        <span>${formatDateShort(item.date)} <b>${formatNumber(item.quantity)}</b></span>
      `).join("")}
    </div>
  `;
}

function renderTemplateStatus() {
  const info = state.inboundTemplate;
  if (!info) return;
  els.templateStatusText.textContent = info.hint || "";
  if (info.available && info.download_url) {
    els.templateDownloadLink.href = info.download_url;
    els.templateDownloadLink.classList.remove("disabled");
    els.templateDownloadLink.removeAttribute("aria-disabled");
  } else {
    els.templateDownloadLink.href = "#";
    els.templateDownloadLink.classList.add("disabled");
    els.templateDownloadLink.setAttribute("aria-disabled", "true");
  }
}

function setMessage(text, type = "") {
  els.message.textContent = text;
  els.message.className = `message ${type}`;
}

function typeName(type) {
  return type === "inbound" ? "入库" : "出库";
}

function statusName(status) {
  return status === "success" ? "成功" : status === "failed" ? "失败" : "处理中";
}

function sourceName(source) {
  if (source === "cloud_order") return "门店云端下单";
  return "总看板上传";
}

function formatNumber(value) {
  const num = Number(value || 0);
  return Number.isInteger(num) ? String(num) : num.toFixed(2);
}

function money(value) {
  const num = Number(value || 0);
  return `¥${num.toLocaleString("zh-CN", {
    minimumFractionDigits: Number.isInteger(num) ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDateShort(value) {
  const text = String(value || "");
  const match = text.match(/^\\d{4}-(\\d{2})-(\\d{2})/);
  return match ? `${match[1]}-${match[2]}` : escapeHtml(text);
}

function shortName(value) {
  return escapeHtml(String(value ?? "").replace(/^熊小小牛排饭-/, ""));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

loadAll();
