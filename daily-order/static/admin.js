const params = new URLSearchParams(location.search);
const token = params.get("token") || "";
const state = {
  status: "pending",
  payload: { orders: [], channels: [], stats: {} },
  seenPendingIds: new Set(),
  loadedOnce: false,
  copyTexts: new Map(),
};

lockPageZoom();

const channelShortcuts = [
  { channel: "快驴", label: "快驴订货" },
  { channel: "微信群", label: "微信群" },
  { channel: "淘宝", label: "淘宝" },
  { channel: "拼多多", label: "拼多多" },
  { channel: "京东", label: "京东" },
];

const els = {
  tabs: document.querySelectorAll(".admin-tabs button"),
  pendingCount: document.querySelector("#pendingCount"),
  orderCount: document.querySelector("#orderCount"),
  lineCount: document.querySelector("#lineCount"),
  message: document.querySelector("#adminMessage"),
  channelNav: document.querySelector("#channelNav"),
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
  renderChannelNav();
  renderChannels();
}

function renderChannelNav() {
  if (!els.channelNav) return;
  const available = new Set((state.payload.channels || []).map((channel) => channel.channel));
  els.channelNav.innerHTML = channelShortcuts.map((item) => `
    <button
      class="${available.has(item.channel) ? "" : "is-empty"}"
      type="button"
      data-channel-jump="${escapeHtml(item.channel)}"
    >${escapeHtml(item.label)}</button>
  `).join("");
  els.channelNav.querySelectorAll("[data-channel-jump]").forEach((button) => {
    button.addEventListener("click", () => jumpToChannel(button.dataset.channelJump));
  });
}

function renderChannels() {
  const channels = state.payload.channels || [];
  state.copyTexts.clear();
  els.channelBoard.innerHTML = channels.length
    ? channels.map(renderChannel).join("")
    : `<div class="empty-panel">当前没有订单。</div>`;
  els.channelBoard.querySelectorAll("[data-channel-status]").forEach((button) => {
    button.addEventListener("click", () => updateChannelStatus(button.dataset.channel, button.dataset.channelStatus));
  });
  els.channelBoard.querySelectorAll("[data-order-channel-status]").forEach((button) => {
    button.addEventListener("click", () => updateOrderChannelStatus(button.dataset.orderId, button.dataset.channel, button.dataset.orderChannelStatus));
  });
  els.channelBoard.querySelectorAll("[data-copy-wechat]").forEach((button) => {
    button.addEventListener("click", () => copyWechatText(button.dataset.copyWechat, button));
  });
}

function renderChannel(channel) {
  const nextStatus = state.status === "processed" ? "pending" : "processed";
  const buttonText = nextStatus === "processed" ? "标记本渠道已处理" : "改回本渠道未处理";
  const orders = channel.orders || [];
  return `
    <article class="channel-card ${channelTone(channel.channel)}" id="${escapeHtml(channelAnchor(channel.channel))}" data-channel-card="${escapeHtml(channel.channel)}">
      <header>
        <div>
          <h2>${escapeHtml(channel.channel)}</h2>
          <span>${orders.length} 个订单 · ${(channel.stores || []).length} 个门店</span>
        </div>
        <button type="button" data-channel="${escapeHtml(channel.channel)}" data-channel-status="${nextStatus}">${buttonText}</button>
      </header>
      <div class="channel-totals">
        ${(channel.totals || []).map((item) => `<span>${renderChannelLine(item, channel.channel)}</span>`).join("")}
      </div>
      <div class="channel-order-list">
        ${renderChannelOrderList(channel)}
      </div>
    </article>
  `;
}

function jumpToChannel(channel) {
  const card = document.querySelector(`[data-channel-card="${cssEscape(channel)}"]`);
  if (!card) {
    showMessage(`${channel} 当前没有订单。`, false);
    return;
  }
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function channelAnchor(channel) {
  const index = channelShortcuts.findIndex((item) => item.channel === channel);
  if (index >= 0) return `channel-${index}`;
  return `channel-${channel.replace(/[^0-9A-Za-z\u4e00-\u9fff_-]+/g, "-")}`;
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

function renderChannelOrderList(channel) {
  const orders = channel.orders || [];
  if (channel.channel === "微信群") return renderWechatGroupCards(channel);
  return orders.length ? orders.map((order) => renderChannelOrder(order, channel.channel)).join("") : `<div class="empty-panel">当前渠道没有订单。</div>`;
}

function renderWechatGroupCards(channel) {
  const groups = wechatMessageGroups(channel);
  if (!groups.length) return `<div class="empty-panel">当前渠道没有订单。</div>`;
  return groups.map((group) => {
    const key = `wechat-${state.copyTexts.size}`;
    state.copyTexts.set(key, group.text);
    return `
      <article class="wechat-group-card">
        <header>
          <div>
            <strong>${escapeHtml(group.name)}</strong>
            <span>${group.orderEntries.length} 个订单 · ${group.stores.length} 个门店</span>
          </div>
          <div class="wechat-group-actions">
            <button type="button" data-copy-wechat="${escapeHtml(key)}">复制群消息</button>
            <button type="button" data-channel="${escapeHtml(group.name)}" data-channel-status="${group.nextStatus}">${group.buttonText}</button>
          </div>
        </header>
        <pre>${escapeHtml(group.text)}</pre>
        <div class="wechat-order-actions">
          ${group.orderEntries.map(renderWechatOrderAction).join("")}
        </div>
      </article>
    `;
  }).join("");
}

function wechatMessageGroups(channel) {
  const byGroup = new Map();
  (channel.orders || []).forEach((order) => {
    (order.items || []).forEach((item) => {
      const groupName = item.purchase_channel || "微信群";
      const group = byGroup.get(groupName) || { stores: new Map(), orders: new Map() };
      const storeKey = `${order.store_name}||${order.store_address || ""}`;
      const store = group.stores.get(storeKey) || {
        storeName: order.store_name || "未命名门店",
        address: order.store_address || "未填写地址",
        items: new Map(),
      };
      const orderEntry = group.orders.get(order.order_id) || {
        orderId: order.order_id,
        storeName: order.store_name || "未命名门店",
        submittedAt: order.submitted_at || "",
        status: "processed",
        items: new Map(),
      };
      if (item.status !== "processed") orderEntry.status = "pending";
      const itemKey = `${item.name}||${item.spec || ""}||${item.unit || ""}`;
      const line = store.items.get(itemKey) || {
        name: item.name || "",
        spec: item.spec || "",
        unit: item.unit || "",
        quantity: 0,
      };
      line.quantity += Number(item.quantity || 0);
      store.items.set(itemKey, line);
      const orderLine = orderEntry.items.get(itemKey) || { ...line, quantity: 0 };
      orderLine.quantity += Number(item.quantity || 0);
      orderEntry.items.set(itemKey, orderLine);
      group.stores.set(storeKey, store);
      group.orders.set(order.order_id, orderEntry);
      byGroup.set(groupName, group);
    });
  });
  return [...byGroup.entries()].map(([name, group]) => ({
    name,
    stores: [...group.stores.values()],
    orderEntries: [...group.orders.values()],
    text: wechatMessageText(name, [...group.stores.values()]),
  })).map((group) => {
    const processed = group.orderEntries.length > 0 && group.orderEntries.every((entry) => entry.status === "processed");
    return {
      ...group,
      nextStatus: processed ? "pending" : "processed",
      buttonText: processed ? "改回未处理" : "标记本群已处理",
    };
  });
}

function wechatMessageText(groupName, stores) {
  return [
    `【${groupName}】`,
    ...stores.map((store) => [
      store.storeName,
      `地址：${store.address}`,
      "货品：",
      ...[...store.items.values()].map((item) => `- ${plainLine(item)}`),
    ].join("\n")),
  ].join("\n\n");
}

function renderWechatOrderAction(entry) {
  return `
    <section class="wechat-order-row ${entry.status === "processed" ? "is-processed" : ""}">
      <div>
        <strong>${escapeHtml(entry.storeName)}</strong>
        <span>${escapeHtml(entry.orderId)} · ${escapeHtml(formatDate(entry.submittedAt))}</span>
        <em>${[...entry.items.values()].map((item) => escapeHtml(plainLine(item))).join("、")}</em>
      </div>
    </section>
  `;
}

function channelTone(channel) {
  if (channel.includes("快驴")) return "tone-kuailv";
  if (channel.includes("淘宝")) return "tone-taobao";
  if (channel.includes("京东")) return "tone-jingdong";
  if (channel.includes("拼多多")) return "tone-pdd";
  if (channel.includes("微信") || channel.includes("群")) return "tone-wechat";
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
        ${(order.items || []).map((item) => `<span>${renderChannelLine(item, channelName)}</span>`).join("")}
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

async function copyWechatText(key, button) {
  const text = state.copyTexts.get(key);
  if (!text) return;
  try {
    await copyText(text);
    if (button) {
      button.classList.add("copied");
      button.textContent = "已复制";
      window.setTimeout(() => {
        button.classList.remove("copied");
        button.textContent = "复制群消息";
      }, 1800);
    }
    showMessage("群消息已复制。", false);
  } catch (error) {
    showMessage("复制失败，请手动复制预览内容。", true);
  }
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (error) {
      // HTTP pages and embedded browsers can expose clipboard but reject writes.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("copy failed");
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

function plainLine(item) {
  const spec = item.spec ? ` ${item.spec}` : "";
  return `${item.name}${spec} ${formatNumber(item.quantity)}${item.unit || ""}`;
}

function renderChannelLine(item, displayChannel) {
  const line = renderLine(item);
  const itemChannel = item.purchase_channel || "";
  if (displayChannel === "微信群" && itemChannel && itemChannel !== "微信群") {
    return `${escapeHtml(itemChannel)} · ${line}`;
  }
  return line;
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
