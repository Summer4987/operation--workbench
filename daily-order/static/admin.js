const params = new URLSearchParams(location.search);
const token = params.get("token") || "";
const state = {
  status: "pending",
  payload: { orders: [], channels: [], stats: {} },
  seenPendingIds: new Set(),
  loadedOnce: false,
};

lockPageZoom();

const els = {
  tabs: document.querySelectorAll(".admin-tabs button"),
  pendingCount: document.querySelector("#pendingCount"),
  orderCount: document.querySelector("#orderCount"),
  lineCount: document.querySelector("#lineCount"),
  message: document.querySelector("#adminMessage"),
  channelBoard: document.querySelector("#channelBoard"),
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
}

function renderChannels() {
  const channels = state.payload.channels || [];
  els.channelBoard.innerHTML = channels.length
    ? channels.map(renderChannel).join("")
    : `<div class="empty-panel">当前没有订单。</div>`;
  els.channelBoard.querySelectorAll("[data-channel-status]").forEach((button) => {
    button.addEventListener("click", () => updateChannelStatus(button.dataset.channel, button.dataset.channelStatus));
  });
  els.channelBoard.querySelectorAll("[data-order-channel-status]").forEach((button) => {
    button.addEventListener("click", () => updateOrderChannelStatus(button.dataset.orderId, button.dataset.channel, button.dataset.orderChannelStatus));
  });
}

function renderChannel(channel) {
  const nextStatus = state.status === "processed" ? "pending" : "processed";
  const buttonText = nextStatus === "processed" ? "标记本渠道已处理" : "改回本渠道未处理";
  const orders = channel.orders || [];
  return `
    <article class="channel-card ${channelTone(channel.channel)}">
      <header>
        <div>
          <h2>${escapeHtml(channel.channel)}</h2>
          <span>${orders.length} 个订单 · ${(channel.stores || []).length} 个门店</span>
        </div>
        <button type="button" data-channel="${escapeHtml(channel.channel)}" data-channel-status="${nextStatus}">${buttonText}</button>
      </header>
      <div class="channel-totals">
        ${(channel.totals || []).map((item) => `<span>${renderLine(item)}</span>`).join("")}
      </div>
      <div class="channel-order-list">
        ${orders.length ? orders.map((order) => renderChannelOrder(order, channel.channel)).join("") : `<div class="empty-panel">当前渠道没有订单。</div>`}
      </div>
    </article>
  `;
}

function channelTone(channel) {
  if (channel.includes("快驴")) return "tone-kuailv";
  if (channel.includes("淘宝")) return "tone-taobao";
  if (channel.includes("京东")) return "tone-jingdong";
  if (channel.includes("拼多多")) return "tone-pdd";
  if (channel.includes("微信")) return "tone-wechat";
  return "tone-default";
}

function renderChannelOrder(order, channelName) {
  const nextStatus = order.status === "processed" ? "pending" : "processed";
  const buttonText = nextStatus === "processed" ? "标记已处理" : "改回未处理";
  return `
    <section class="channel-order-card ${order.status === "processed" ? "is-processed" : ""}">
      <header>
        <div>
          <strong>${escapeHtml(order.store_name)}</strong>
          <span>${escapeHtml(order.order_id)} · ${escapeHtml(formatDate(order.submitted_at))}</span>
        </div>
        <button
          type="button"
          data-order-id="${escapeHtml(order.order_id)}"
          data-channel="${escapeHtml(channelName)}"
          data-order-channel-status="${nextStatus}"
        >${buttonText}</button>
      </header>
      <p>${escapeHtml(order.store_address || "未填写地址")}</p>
      <div class="admin-order-items">
        ${(order.items || []).map((item) => `<span>${renderLine(item)}</span>`).join("")}
      </div>
      ${order.remark ? `<p class="admin-remark">备注：${escapeHtml(order.remark)}</p>` : ""}
    </section>
  `;
}

async function updateChannelStatus(channel, status) {
  showMessage(`正在更新 ${channel} 渠道状态...`, false);
  try {
    const response = await fetch(`/daily-order/api/admin/channels/${encodeURIComponent(channel)}/status?token=${encodeURIComponent(token)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "渠道状态更新失败");
    showMessage(`${channel} 已更新 ${payload.order_count || 0} 个订单`, false);
    await loadSummary();
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function updateOrderChannelStatus(orderId, channel, status) {
  showMessage("正在更新订单状态...", false);
  try {
    const response = await fetch(`/daily-order/api/admin/orders/${encodeURIComponent(orderId)}/channels/${encodeURIComponent(channel)}/status?token=${encodeURIComponent(token)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "订单状态更新失败");
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

function lockPageZoom() {
  const preventZoom = (event) => event.preventDefault();
  ["gesturestart", "gesturechange", "gestureend"].forEach((eventName) => {
    document.addEventListener(eventName, preventZoom, { passive: false });
  });
  document.addEventListener(
    "touchmove",
    (event) => {
      if (event.scale && event.scale !== 1) event.preventDefault();
    },
    { passive: false }
  );
}

loadSummary();
setInterval(loadSummary, 15000);
