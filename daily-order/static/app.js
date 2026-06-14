const state = {
  catalog: [],
  stores: [],
  source: "全部",
  quantities: new Map(),
};

const els = {
  cartCount: document.querySelector("#cartCount"),
  storeName: document.querySelector("#storeName"),
  contact: document.querySelector("#contact"),
  storeOptions: document.querySelector("#storeOptions"),
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
};

els.search.addEventListener("input", renderCatalog);
els.submitButton.addEventListener("click", openConfirm);
els.confirmSubmit.addEventListener("click", submitOrder);
els.newOrder.addEventListener("click", resetOrder);

async function loadCatalog() {
  const response = await fetch("/daily-order/api/catalog");
  if (!response.ok) throw new Error("SKU 读取失败");
  const payload = await response.json();
  state.catalog = payload.items || [];
  state.stores = payload.stores || [];
  renderStoreOptions();
  renderTabs();
  renderCatalog();
  updateSummary();
}

function renderStoreOptions() {
  els.storeOptions.innerHTML = state.stores.map((store) => `<option value="${escapeHtml(store)}"></option>`).join("");
}

function renderTabs() {
  const sources = ["全部", ...new Set(state.catalog.map((item) => item.source))];
  els.sourceTabs.innerHTML = sources
    .map((source) => `<button type="button" class="${source === state.source ? "active" : ""}" data-source="${escapeHtml(source)}">${escapeHtml(source)}</button>`)
    .join("");
  els.sourceTabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.source = button.dataset.source;
      renderTabs();
      renderCatalog();
    });
  });
}

function renderCatalog() {
  const term = els.search.value.trim().toLowerCase();
  const items = state.catalog.filter((item) => {
    const sourceMatch = state.source === "全部" || item.source === state.source;
    const text = `${item.sku} ${item.name} ${item.category} ${item.spec} ${item.unit} ${item.note}`.toLowerCase();
    return sourceMatch && (!term || text.includes(term));
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

function renderItem(item) {
  const quantity = state.quantities.get(item.sku) || "";
  const detail = [item.source, item.category, item.spec, item.unit ? `单位：${item.unit}` : "", item.note].filter(Boolean).join(" · ");
  return `
    <article class="sku-card">
      <div class="sku-meta">
        <small>${escapeHtml(item.sku)}</small>
        <strong>${escapeHtml(item.name)}</strong>
        <span>${escapeHtml(detail)}</span>
      </div>
      <div class="qty-control">
        <button type="button" data-step="-1" data-sku="${escapeHtml(item.sku)}" aria-label="减少 ${escapeHtml(item.name)}">-</button>
        <input data-qty data-sku="${escapeHtml(item.sku)}" type="number" inputmode="decimal" min="0" step="1" value="${escapeHtml(quantity)}" aria-label="${escapeHtml(item.name)} 数量" />
        <button type="button" data-step="1" data-sku="${escapeHtml(item.sku)}" aria-label="增加 ${escapeHtml(item.name)}">+</button>
      </div>
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
          <small>${escapeHtml([item.source, item.spec, item.note].filter(Boolean).join(" · "))}</small>
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
    els.message.textContent = "请先填写门店名称";
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
        contact: els.contact.value.trim(),
        remark: els.remark.value.trim(),
        items,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "提交失败");
    els.confirmDialog.close();
    els.successOrderId.textContent = payload.order_id;
    els.successScreen.style.display = "grid";
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

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
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
