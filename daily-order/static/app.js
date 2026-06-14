const state = {
  catalog: [],
  stores: [],
  section: "食材",
  foodCategory: "蔬菜",
  quantities: new Map(),
  recentOrders: [],
};

const sectionOrder = ["食材", "包材", "调料", "耗材"];
const foodCategoryOrder = ["蔬菜", "禽蛋", "粮油", "冻品"];
const sectionLabels = {
  "食材": "🥬 食材",
  "包材": "📦 包材",
  "调料": "🧂 调料",
  "耗材": "🧽 耗材",
};

const sourceLabels = {
  "快驴配送": "快驴配送（次日）",
  "快递到店": "快递到店（3日内）",
  "同城物流配送": "同城物流配送（次日）",
  "厂家配送（2日内）": "厂家配送（2日内）",
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
  confirmList: document.querySelector("#confirmList"),
  remark: document.querySelector("#remark"),
  message: document.querySelector("#message"),
  confirmSubmit: document.querySelector("#confirmSubmitButton"),
  successScreen: document.querySelector("#successScreen"),
  successOrderId: document.querySelector("#successOrderId"),
  newOrder: document.querySelector("#newOrderButton"),
  storeOrdersList: document.querySelector("#storeOrdersList"),
  refreshOrders: document.querySelector("#refreshOrdersButton"),
};

els.search.addEventListener("input", renderCatalog);
els.storeName.addEventListener("change", loadStoreOrders);
els.submitButton.addEventListener("click", openConfirm);
els.confirmSubmit.addEventListener("click", submitOrder);
els.newOrder.addEventListener("click", resetOrder);
els.refreshOrders.addEventListener("click", loadStoreOrders);

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
    input.addEventListener("input", () => setQuantity(input.dataset.sku, input.value));
  });
  els.catalogGrid.querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = Number(state.quantities.get(button.dataset.sku) || 0);
      setQuantity(button.dataset.sku, Math.max(0, current + Number(button.dataset.step)));
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
  const quantity = state.quantities.get(item.sku) || "";
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
        <input data-qty data-sku="${escapeHtml(item.sku)}" type="number" inputmode="decimal" min="0" step="1" value="${escapeHtml(quantity)}" aria-label="${escapeHtml(item.name)} 数量" />
        <button type="button" data-step="1" data-sku="${escapeHtml(item.sku)}" aria-label="增加 ${escapeHtml(item.name)}">+</button>
      </div>
      <span class="qty-unit">${escapeHtml(item.unit || "")}</span>
    </article>
  `;
}

function setQuantity(sku, rawValue) {
  const quantity = Number(rawValue || 0);
  if (quantity > 0) {
    state.quantities.set(sku, quantity);
  } else {
    state.quantities.delete(sku);
  }
  updateSummary();
}

function selectedItems() {
  return state.catalog
    .map((item) => ({ ...item, quantity: Number(state.quantities.get(item.sku) || 0) }))
    .filter((item) => item.quantity > 0);
}

function updateSummary() {
  const items = selectedItems();
  const total = items.reduce((sum, item) => sum + item.quantity, 0);
  els.cartCount.textContent = `${items.length} 项`;
  els.summaryText.textContent = items.length ? `已选 ${items.length} 个 SKU` : "还没有选择 SKU";
  els.summaryDetail.textContent = items.length ? `合计数量 ${formatNumber(total)}` : "填写数量后提交";
  els.submitButton.disabled = !items.length;
}

function openConfirm() {
  const items = selectedItems();
  if (!items.length) return;
  els.confirmList.innerHTML = items
    .map((item) => `
      <div class="confirm-row">
        <div>
          <strong>${escapeHtml(item.name)}</strong>
          <small>${escapeHtml([sourceLabel(item.source), item.spec, item.note].filter(Boolean).join(" · "))}</small>
        </div>
        <b>${formatNumber(item.quantity)} ${escapeHtml(item.unit || "")}</b>
      </div>
    `)
    .join("");
  els.message.textContent = "";
  els.message.className = "message";
  els.confirmDialog.showModal();
}

async function submitOrder() {
  const storeName = els.storeName.value.trim();
  if (!storeName) {
    els.message.textContent = "请先选择门店";
    els.message.className = "message error";
    return;
  }
  const items = selectedItems().map((item) => ({ sku: item.sku, quantity: item.quantity }));
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
    await loadStoreOrders();
  } catch (error) {
    els.message.textContent = error.message;
    els.message.className = "message error";
  } finally {
    els.confirmSubmit.disabled = false;
  }
}

function resetOrder() {
  state.quantities.clear();
  els.remark.value = "";
  els.successScreen.style.display = "none";
  renderCatalog();
  updateSummary();
}

async function loadStoreOrders() {
  const storeName = els.storeName.value.trim();
  if (!storeName) {
    state.recentOrders = [];
    renderStoreOrders();
    return;
  }
  els.storeOrdersList.innerHTML = `<p>正在读取订单...</p>`;
  try {
    const response = await fetch(`/daily-order/api/orders?store_name=${encodeURIComponent(storeName)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "订单读取失败");
    state.recentOrders = payload.items || [];
    renderStoreOrders();
  } catch (error) {
    els.storeOrdersList.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
  }
}

function renderStoreOrders() {
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
            ${items.map((item) => `<li><span>${escapeHtml(item.name)} ${escapeHtml(item.spec || "")}</span><b>${formatNumber(item.quantity)}${escapeHtml(item.unit || "")}</b></li>`).join("")}
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

loadCatalog().catch((error) => {
  els.catalogGrid.innerHTML = `<div class="sku-card"><div class="sku-meta"><strong>${escapeHtml(error.message)}</strong></div></div>`;
});
