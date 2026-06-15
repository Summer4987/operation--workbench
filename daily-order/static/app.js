const state = {
  catalog: [],
  stores: [],
  section: "食材",
  foodCategory: "蔬菜",
  quantities: new Map(),
  customNotes: new Map(),
  recentOrders: [],
  recentOrdersStore: "",
  ordersExpanded: false,
};

lockPageZoom();

const sectionOrder = ["食材", "包材", "调料", "耗材"];
const foodCategoryOrder = ["蔬菜", "禽蛋", "粮油", "冻品", "工作餐"];
const customMealSku = "MEAL-001";
const minOrderTotalQuantity = 5;
const sectionLabels = {
  "食材": "🥬 食材",
  "包材": "📦 包材",
  "调料": "🧂 调料",
  "耗材": "🧽 耗材",
};

const sourceLabels = {
  "快驴配送": "快驴配送（次日）",
  "快递到店": "快递到店（3-5天）",
  "同城物流配送": "同城物流配送（次日）",
  "厂家配送（2日内）": "厂家配送（2日内）",
  "自主填写": "自主填写",
};

const vendorGroups = {
  "玉米淀粉盒": "A",
  "小塑料碗": "A",
  "餐具": "A",
  "酱料盒": "B",
  "打包袋": "B",
  "餐盒": "B",
};

const imageVersion = "20260614-vendor-badge";

const els = {
  cartCount: document.querySelector("#cartCount"),
  storeName: document.querySelector("#storeName"),
  search: document.querySelector("#searchInput"),
  sourceTabs: document.querySelector("#sourceTabs"),
  catalogGrid: document.querySelector("#catalogGrid"),
  summaryText: document.querySelector("#summaryText"),
  summaryDetail: document.querySelector("#summaryDetail"),
  submitButton: document.querySelector("#submitButton"),
  confirmDialog: document.querySelector("#confirmDialog"),
  confirmStore: document.querySelector("#confirmStore"),
  confirmList: document.querySelector("#confirmList"),
  remark: document.querySelector("#remark"),
  message: document.querySelector("#message"),
  confirmSubmit: document.querySelector("#confirmSubmitButton"),
  successScreen: document.querySelector("#successScreen"),
  successOrderId: document.querySelector("#successOrderId"),
  newOrder: document.querySelector("#newOrderButton"),
  storeOrdersPanel: document.querySelector("#storeOrdersPanel"),
  storeOrdersList: document.querySelector("#storeOrdersList"),
  toggleOrders: document.querySelector("#toggleOrdersButton"),
  refreshOrders: document.querySelector("#refreshOrdersButton"),
};

els.search.addEventListener("input", renderCatalog);
els.storeName.addEventListener("change", handleStoreChange);
els.submitButton.addEventListener("click", openConfirm);
els.confirmSubmit.addEventListener("click", submitOrder);
els.newOrder.addEventListener("click", resetOrder);
els.toggleOrders.addEventListener("click", toggleStoreOrders);
els.refreshOrders.addEventListener("click", refreshStoreOrders);
renderOrdersPanelState();

async function loadCatalog() {
  const response = await fetch("/daily-order/api/catalog");
  if (!response.ok) throw new Error("SKU 读取失败");
  const payload = await response.json();
  state.catalog = payload.items || [];
  state.stores = payload.stores || [];
  state.foodCategory = foodCategoryOrder.find((category) => state.catalog.some((item) => item.category === category)) || state.foodCategory;
  renderStoreOptions();
  renderTabs();
  renderCatalog();
  updateSummary();
}

function renderStoreOptions() {
  els.storeName.innerHTML = `<option value="">请选择门店</option>${state.stores
    .map((store) => {
      const name = typeof store === "string" ? store : store.name;
      return `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`;
    })
    .join("")}`;
}

function renderTabs() {
  const sections = sectionOrder.filter((section) => state.catalog.some((item) => sectionMatchesItem(section, item)));
  const foodCategories = foodCategoryOrder.filter((category) => state.catalog.some((item) => item.category === category));
  const secondaryTabs = state.section === "食材"
    ? `<div class="tab-row secondary-tabs">${foodCategories
      .map((category) => `<button type="button" class="${category === state.foodCategory ? "active" : ""}" data-food-category="${escapeHtml(category)}">${escapeHtml(category)}</button>`)
      .join("")}</div>`
    : "";
  els.sourceTabs.innerHTML = `
    <div class="tab-row primary-tabs">
      ${sections.map((section) => `<button type="button" class="${section === state.section ? "active" : ""}" data-section="${escapeHtml(section)}">${escapeHtml(sectionLabels[section] || section)}</button>`).join("")}
    </div>
    ${secondaryTabs}
  `;
  els.sourceTabs.querySelectorAll("[data-section]").forEach((button) => {
    button.addEventListener("click", () => {
      state.section = button.dataset.section;
      renderTabs();
      renderCatalog();
    });
  });
  els.sourceTabs.querySelectorAll("[data-food-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.foodCategory = button.dataset.foodCategory;
      renderTabs();
      renderCatalog();
    });
  });
}

function renderCatalog() {
  const term = els.search.value.trim().toLowerCase();
  const items = state.catalog.filter((item) => {
    const categoryMatch = activeCategoryMatchesItem(item);
    const text = `${item.sku} ${item.name} ${item.category} ${item.spec} ${item.unit} ${item.note}`.toLowerCase();
    return categoryMatch && (!term || text.includes(term));
  });

  els.catalogGrid.innerHTML = items.length
    ? items.map(renderItem).join("")
    : `<div class="sku-card"><div class="sku-meta"><strong>没有匹配的 SKU</strong><span>换个关键词试试</span></div></div>`;

  els.catalogGrid.querySelectorAll("[data-qty]").forEach((input) => {
    input.addEventListener("input", () => {
      setQuantity(input.dataset.sku, input.value);
      input.value = state.quantities.get(input.dataset.sku) || "";
    });
  });
  els.catalogGrid.querySelectorAll("[data-custom-note]").forEach((input) => {
    input.addEventListener("input", () => setCustomNote(input.dataset.sku, input.value));
  });
  els.catalogGrid.querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = Number(state.quantities.get(button.dataset.sku) || 0);
      const item = state.catalog.find((candidate) => candidate.sku === button.dataset.sku);
      const minQuantity = minOrderQuantity(item);
      const step = Number(button.dataset.step);
      const next = step < 0 && current <= minQuantity ? 0 : Math.max(0, current + step);
      setQuantity(button.dataset.sku, next);
      renderCatalog();
    });
  });
}

function activeCategoryMatchesItem(item) {
  if (state.section === "食材") return item.category === state.foodCategory;
  return item.category === state.section;
}

function sectionMatchesItem(section, item) {
  if (section === "食材") return foodCategoryOrder.includes(item.category);
  return item.category === section;
}

function renderItem(item) {
  if (isCustomMealItem(item)) return renderCustomMealItem(item);
  const quantity = state.quantities.get(item.sku) || "";
  const minQuantity = minOrderQuantity(item);
  const detail = [sourceLabel(item.source), item.category, item.note].filter(Boolean).join(" · ");
  const nameLine = item.spec ? `${item.name} ${item.spec}` : item.name;
  const vendorGroup = vendorGroups[item.name] || "";
  return `
    <article class="sku-card">
      <div class="sku-image">
        <img src="${escapeHtml(imageSrc(item.image || ""))}" alt="${escapeHtml(item.name)}" loading="lazy" />
      </div>
      <div class="sku-meta">
        <small>${escapeHtml(item.sku)}</small>
        <strong>${escapeHtml(nameLine)}</strong>
        <span>${escapeHtml(detail)}</span>
        ${vendorGroup ? `<em class="vendor-badge vendor-${escapeHtml(vendorGroup)}">同厂商 ${escapeHtml(vendorGroup)}</em>` : ""}
      </div>
      <div class="qty-control">
        <button type="button" data-step="-1" data-sku="${escapeHtml(item.sku)}" aria-label="减少 ${escapeHtml(item.name)}">-</button>
        <input data-qty data-sku="${escapeHtml(item.sku)}" type="number" inputmode="decimal" min="${minQuantity}" step="1" value="${escapeHtml(quantity)}" aria-label="${escapeHtml(item.name)} 数量" />
        <button type="button" data-step="1" data-sku="${escapeHtml(item.sku)}" aria-label="增加 ${escapeHtml(item.name)}">+</button>
      </div>
      <span class="qty-unit">${escapeHtml(item.unit || "")}</span>
    </article>
  `;
}

function renderCustomMealItem(item) {
  const note = state.customNotes.get(item.sku) || "";
  return `
    <article class="sku-card custom-meal-card">
      <div class="sku-image custom-meal-icon" aria-hidden="true">🍱</div>
      <div class="sku-meta custom-meal-meta">
        <small>${escapeHtml(item.sku)} · 自定义</small>
        <strong>${escapeHtml(item.name)}</strong>
        <span>在食材下填写当天需要补充的工作餐原料</span>
        <textarea
          data-custom-note
          data-sku="${escapeHtml(item.sku)}"
          placeholder="例如：猪肉2斤/芹菜3斤/泡椒1袋"
          aria-label="工作餐内容"
        >${escapeHtml(note)}</textarea>
      </div>
      <span class="custom-meal-status">${note.trim() ? "已填写" : "待填写"}</span>
    </article>
  `;
}

function setQuantity(sku, rawValue) {
  const quantity = Number(rawValue || 0);
  const item = state.catalog.find((candidate) => candidate.sku === sku);
  const minQuantity = minOrderQuantity(item);
  if (quantity > 0) {
    state.quantities.set(sku, Math.max(minQuantity, quantity));
  } else {
    state.quantities.delete(sku);
  }
  updateSummary();
}

function minOrderQuantity(item) {
  return Math.max(0, Number(item?.min_quantity || 0));
}

function setCustomNote(sku, rawValue) {
  const note = String(rawValue || "").trim();
  if (note) {
    state.customNotes.set(sku, note);
    if (sku === customMealSku) state.quantities.set(sku, 1);
  } else {
    state.customNotes.delete(sku);
    if (sku === customMealSku) state.quantities.delete(sku);
  }
  updateSummary();
}

function selectedItems() {
  return state.catalog
    .map((item) => ({ ...item, quantity: Number(state.quantities.get(item.sku) || 0), custom_note: state.customNotes.get(item.sku) || "" }))
    .filter((item) => item.quantity > 0);
}

function updateSummary() {
  const items = selectedItems();
  const total = orderTotalQuantity(items);
  if (els.cartCount) els.cartCount.textContent = `${items.length} 项`;
  els.summaryText.textContent = items.length ? `已选 ${items.length} 个 SKU` : "还没有选择 SKU";
  els.summaryDetail.textContent = items.length ? summaryDetailText(total) : `满 ${minOrderTotalQuantity} 件才可提交`;
  els.submitButton.disabled = total < minOrderTotalQuantity;
}

function openConfirm() {
  const items = selectedItems();
  if (!items.length) return;
  const total = orderTotalQuantity(items);
  if (total < minOrderTotalQuantity) return;
  const storeName = els.storeName.value.trim();
  els.confirmStore.textContent = storeName ? `门店：${storeName}` : "门店：未选择";
  els.confirmList.innerHTML = items
    .map((item) => `
      <div class="confirm-row">
        <div>
          <strong>${escapeHtml(item.name)}</strong>
          <small>${escapeHtml([sourceLabel(item.source), item.spec, item.note].filter(Boolean).join(" · "))}</small>
          ${item.custom_note ? `<small>内容：${escapeHtml(item.custom_note)}</small>` : ""}
        </div>
        <b>${isCustomMealItem(item) ? "已填写" : `${formatNumber(item.quantity)} ${escapeHtml(item.unit || "")}`}</b>
      </div>
    `)
    .join("");
  els.message.textContent = "";
  els.message.className = "message";
  els.confirmDialog.showModal();
  requestAnimationFrame(() => els.confirmDialog.focus({ preventScroll: true }));
}

async function submitOrder() {
  const storeName = els.storeName.value.trim();
  if (!storeName) {
    els.message.textContent = "请先选择门店";
    els.message.className = "message error";
    return;
  }
  const items = selectedItems().map((item) => ({ sku: item.sku, quantity: item.quantity, note: item.custom_note || "" }));
  const total = orderTotalQuantity(items);
  if (total < minOrderTotalQuantity) {
    els.message.textContent = `单次订货满 ${minOrderTotalQuantity} 件才可以提交，当前合计 ${formatNumber(total)} 件`;
    els.message.className = "message error";
    return;
  }
  els.confirmSubmit.disabled = true;
  els.message.textContent = "正在提交...";
  try {
    const response = await fetch("/daily-order/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        store_name: storeName,
        remark: els.remark.value.trim(),
        items,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "提交失败");
    els.confirmDialog.close();
    els.successOrderId.textContent = payload.order_id;
    els.successScreen.style.display = "grid";
    if (state.ordersExpanded) await loadStoreOrders();
  } catch (error) {
    els.message.textContent = error.message;
    els.message.className = "message error";
  } finally {
    els.confirmSubmit.disabled = false;
  }
}

function resetOrder() {
  state.quantities.clear();
  state.customNotes.clear();
  els.remark.value = "";
  els.successScreen.style.display = "none";
  renderCatalog();
  updateSummary();
}

function handleStoreChange() {
  state.recentOrders = [];
  state.recentOrdersStore = "";
  if (state.ordersExpanded) {
    loadStoreOrders();
  } else {
    renderStoreOrders();
  }
}

function toggleStoreOrders() {
  state.ordersExpanded = !state.ordersExpanded;
  renderOrdersPanelState();
  if (state.ordersExpanded && els.storeName.value.trim() && state.recentOrdersStore !== els.storeName.value.trim()) {
    loadStoreOrders();
  } else {
    renderStoreOrders();
  }
}

function refreshStoreOrders() {
  if (!state.ordersExpanded) {
    state.ordersExpanded = true;
    renderOrdersPanelState();
  }
  loadStoreOrders();
}

function renderOrdersPanelState() {
  els.storeOrdersPanel.classList.toggle("is-collapsed", !state.ordersExpanded);
  els.storeOrdersPanel.hidden = !state.ordersExpanded;
  els.storeOrdersList.hidden = !state.ordersExpanded;
  els.toggleOrders.textContent = state.ordersExpanded ? "收起已下单订单" : "查看已下单订单";
  els.toggleOrders.setAttribute("aria-expanded", String(state.ordersExpanded));
  els.refreshOrders.hidden = !state.ordersExpanded;
}

async function loadStoreOrders() {
  const storeName = els.storeName.value.trim();
  if (!storeName) {
    state.recentOrders = [];
    state.recentOrdersStore = "";
    renderStoreOrders();
    return;
  }
  els.storeOrdersList.innerHTML = `<p>正在读取订单...</p>`;
  try {
    const response = await fetch(`/daily-order/api/orders?store_name=${encodeURIComponent(storeName)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "订单读取失败");
    state.recentOrders = payload.items || [];
    state.recentOrdersStore = storeName;
    renderStoreOrders();
  } catch (error) {
    els.storeOrdersList.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
  }
}

function renderStoreOrders() {
  renderOrdersPanelState();
  if (!state.ordersExpanded) {
    els.storeOrdersList.innerHTML = "";
    return;
  }
  if (!els.storeName.value.trim()) {
    els.storeOrdersList.innerHTML = `<p>选择门店后可查看最近提交的订单。</p>`;
    return;
  }
  if (!state.recentOrders.length) {
    els.storeOrdersList.innerHTML = `<p>这个门店暂时没有已提交订单。</p>`;
    return;
  }
  els.storeOrdersList.innerHTML = state.recentOrders
    .map((order) => {
      const items = order.items || [];
      const total = items.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
      const statusText = order.status === "processed" ? "已处理" : "未处理";
      return `
        <details class="store-order-card">
          <summary>
            <span>
              <strong>${escapeHtml(order.order_id)}</strong>
              <small>${escapeHtml(formatDate(order.submitted_at))} · ${statusText} · ${items.length} 个 SKU · 合计 ${formatNumber(total)}</small>
            </span>
            <b>明细</b>
          </summary>
          <ul>
            ${items.map((item) => `<li><span>${escapeHtml(item.name)} ${escapeHtml(item.spec || "")}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</span><b>${formatNumber(item.quantity)}${escapeHtml(item.unit || "")}</b></li>`).join("")}
          </ul>
          ${order.remark ? `<small>备注：${escapeHtml(order.remark)}</small>` : ""}
        </details>
      `;
    })
    .join("");
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function orderTotalQuantity(items) {
  return items.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
}

function summaryDetailText(total) {
  if (total < minOrderTotalQuantity) {
    return `合计 ${formatNumber(total)} 件，还差 ${formatNumber(minOrderTotalQuantity - total)} 件可提交`;
  }
  return `合计数量 ${formatNumber(total)}`;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function sourceLabel(source) {
  return sourceLabels[source] || source;
}

function imageSrc(src) {
  return src ? `${src}?v=${imageVersion}` : "";
}

function isCustomMealItem(item) {
  return item.sku === customMealSku;
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

loadCatalog().catch((error) => {
  els.catalogGrid.innerHTML = `<div class="sku-card"><div class="sku-meta"><strong>${escapeHtml(error.message)}</strong></div></div>`;
});
