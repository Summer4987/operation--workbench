const params = new URLSearchParams(location.search);
const token = params.get("token") || "";
const state = {
  status: "pending",
  payload: { orders: [], channels: [], stats: {} },
  seenPendingIds: new Set(),
  loadedOnce: false,
};

const els = {
  tabs: document.querySelectorAll(".admin-tabs button"),
  pendingCount: document.querySelector("#pendingCount"),
  orderCount: document.querySelector("#orderCount"),
  lineCount: document.querySelector("#lineCount"),
  message: document.querySelector("#adminMessage"),
  channelBoard: document.querySelector("#channelBoard"),
  orderBoard: document.querySelector("#orderBoard"),
  notifyButton: document.querySelector("#notifyButton"),
};

els.tabs.forEach((button) => {
  button.addEventListener("click", () => {
    state.status = button.dataset.status;
    els.tabs.forEach((tab) => tab.classList.toggle("active", tab === button));
    loadSummary();
  });
});

els.notifyButton.addEventListener("click", requestNotificationPermission);

async function loadSummary() {
  if (!token) {
    showMessage("后台链接缺少 token，请使用完整后台链接。", true);
    return;
  }
  try {
    const response = await fetch(`/daily-order/api/admin/summary?status=${encodeURIComponent(state.status)}&token=${encodeURIComponent(token)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "后台数据读取失败");
    const freshPending = (payload.orders || []).filter((order) => order.status === "pending" && !state.seenPendingIds.has(order.order_id));
    state.payload = payload;
    renderAll();
    if (state.loadedOnce && freshPending.length) notifyNewOrders(freshPending);
    (payload.orders || []).filter((order) => order.status === "pending").forEach((order) => state.seenPendingIds.add(order.order_id));
    state.loadedOnce = true;
    showMessage(`已更新：${formatDate(new Date().toISOString())}`, false);
  } catch (error) {
    showMessage(error.message, true);
  }
}

function renderAll() {
  const stats = state.payload.stats || {};
  els.pendingCount.textContent = stats.pending_count || 0;
  els.orderCount.textContent = stats.order_count || 0;
  els.lineCount.textContent = stats.line_count || 0;
  renderChannels();
  renderOrders();
}

function renderChannels() {
  const channels = state.payload.channels || [];
  els.channelBoard.innerHTML = channels.length
    ? channels.map(renderChannel).join("")
    : `<div class="empty-panel">当前没有订单。</div>`;
}

function renderChannel(channel) {
  return `
    <article class="channel-card">
      <header>
        <h2>${escapeHtml(channel.channel)}</h2>
        <span>${(channel.stores || []).length} 个门店</span>
      </header>
      <div class="channel-totals">
        ${(channel.totals || []).map((item) => `<span>${renderLine(item)}</span>`).join("")}
      </div>
      <div class="store-breakdown">
        ${(channel.stores || []).map(renderStore).join("")}
      </div>
    </article>
  `;
}

function renderStore(store) {
  return `
    <section class="admin-store-card">
      <div>
        <strong>${escapeHtml(store.store_name)}</strong>
        <span>${escapeHtml(store.store_address || "未填写地址")}</span>
      </div>
      <ul>
        ${(store.items || []).map((item) => `<li>${renderLine(item)}</li>`).join("")}
      </ul>
      <small>订单：${(store.orders || []).map(escapeHtml).join("、")}</small>
    </section>
  `;
}

function renderOrders() {
  const orders = state.payload.orders || [];
  els.orderBoard.innerHTML = orders.length
    ? orders.map(renderOrder).join("")
    : "";
  els.orderBoard.querySelectorAll("[data-next-status]").forEach((button) => {
    button.addEventListener("click", () => updateStatus(button.dataset.orderId, button.dataset.nextStatus));
  });
}

function renderOrder(order) {
  const nextStatus = order.status === "processed" ? "pending" : "processed";
  const buttonText = nextStatus === "processed" ? "标记已处理" : "改回未处理";
  return `
    <article class="admin-order-card">
      <header>
        <div>
          <strong>${escapeHtml(order.store_name)}</strong>
          <span>${escapeHtml(order.order_id)} · ${escapeHtml(formatDate(order.submitted_at))}</span>
        </div>
        <button type="button" data-order-id="${escapeHtml(order.order_id)}" data-next-status="${nextStatus}">${buttonText}</button>
      </header>
      <p>${escapeHtml(order.store_address || "未填写地址")}</p>
      <div class="admin-order-items">
        ${(order.items || []).map((item) => `<span>${escapeHtml(item.purchase_channel || "未分类")} · ${renderLine(item)}</span>`).join("")}
      </div>
      ${order.remark ? `<p class="admin-remark">备注：${escapeHtml(order.remark)}</p>` : ""}
    </article>
  `;
}

async function updateStatus(orderId, status) {
  showMessage("正在更新状态...", false);
  try {
    const response = await fetch(`/daily-order/api/admin/orders/${encodeURIComponent(orderId)}/status?token=${encodeURIComponent(token)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "状态更新失败");
    await loadSummary();
  } catch (error) {
    showMessage(error.message, true);
  }
}

function requestNotificationPermission() {
  if (!("Notification" in window)) {
    showMessage("当前浏览器不支持桌面提醒。", true);
    return;
  }
  Notification.requestPermission().then((permission) => {
    showMessage(permission === "granted" ? "页面提醒已开启。" : "页面提醒没有开启。", permission !== "granted");
  });
}

function notifyNewOrders(orders) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const title = orders.length === 1 ? "有一笔新订货订单" : `有 ${orders.length} 笔新订货订单`;
  const body = orders.map((order) => `${order.store_name} ${order.order_id}`).join("\n");
  new Notification(title, { body });
}

function renderLine(item) {
  const spec = item.spec ? ` ${item.spec}` : "";
  return `${escapeHtml(item.name)}${escapeHtml(spec)} <b>${formatNumber(item.quantity)}${escapeHtml(item.unit || "")}</b>`;
}

function showMessage(text, isError) {
  els.message.textContent = text || "";
  els.message.className = isError ? "admin-message error" : "admin-message";
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
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

loadSummary();
setInterval(loadSummary, 15000);
