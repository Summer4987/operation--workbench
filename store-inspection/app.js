let inspectionItems = [];
let threshold = 200;

const yuan = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

const rowsEl = document.querySelector("#inspectionRows");
const statusFilter = document.querySelector("#statusFilter");
const searchInput = document.querySelector("#searchInput");

function statusText(status) {
  if (status === "unknown") return "未确认";
  return status === "warning" ? "需提醒" : "正常";
}

function isReliableBalance(item) {
  if (item.balance === null || item.balance === undefined || item.balance === "") return false;
  const balance = Number(item.balance);
  if (!Number.isFinite(balance)) return false;
  if (balance !== 0) return true;
  return item.confirmed_zero === true;
}

function balanceValue(item) {
  return isReliableBalance(item) ? Number(item.balance) : null;
}

function rowStatus(item) {
  const value = balanceValue(item);
  if (value === null) return "unknown";
  return value < threshold ? "warning" : "normal";
}

function renderStats(data) {
  const reliableItems = inspectionItems.filter((item) => balanceValue(item) !== null);
  const warningCount = reliableItems.filter((item) => rowStatus(item) === "warning").length;
  const lowest = reliableItems.length ? Math.min(...reliableItems.map((item) => Number(item.balance || 0))) : null;
  document.querySelector("#platformCount").textContent = data.summary.platform_count;
  document.querySelector("#storeCount").textContent = `${reliableItems.length}/${inspectionItems.length}`;
  document.querySelector("#warningCount").textContent = warningCount;
  document.querySelector("#lowestBalance").textContent = lowest === null ? "未确认" : yuan.format(lowest);
  document.querySelector("#generatedAt").textContent =
    data.status === "failed" ? "巡检失败" : `生成 ${data.generated_at}，未确认 ${inspectionItems.length - reliableItems.length} 条`;
}

function renderRows() {
  const status = statusFilter.value;
  const keyword = searchInput.value.trim().toLowerCase();
  const filtered = inspectionItems.filter((item) => {
    const currentStatus = rowStatus(item);
    const matchesStatus = status === "all" || currentStatus === status;
    const haystack = `${item.platform} ${item.store_name} ${item.store_id}`.toLowerCase();
    return matchesStatus && (!keyword || haystack.includes(keyword));
  });

  if (!filtered.length) {
    rowsEl.innerHTML = `<tr><td class="empty" colspan="6">没有符合条件的巡检结果</td></tr>`;
    return;
  }

  rowsEl.innerHTML = filtered
    .map((item) => {
      const currentStatus = rowStatus(item);
      const value = balanceValue(item);
      return `
        <tr>
          <td>${item.platform}</td>
          <td>${item.store_name}</td>
          <td>${item.store_id || "-"}</td>
          <td class="money ${currentStatus}">${value === null ? "未确认" : yuan.format(value)}</td>
          <td><span class="pill ${currentStatus}">${statusText(currentStatus)}</span></td>
          <td>${value === null ? "采集未确认，请重跑巡检" : item.source || "自动巡检"}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadInspection() {
  let data = window.INSPECTION_DATA;
  if (!data) {
    const response = await fetch("./latest.json", { cache: "no-store" });
    data = await response.json();
  }
  inspectionItems = data.items || [];
  threshold = Number(data.threshold || 200);
  renderStats(data);
  if (data.status === "failed") {
    rowsEl.innerHTML = `<tr><td class="empty" colspan="6">巡检失败：${data.message || "请确认饿了么页面已登录"}</td></tr>`;
    return;
  }
  renderRows();
}

statusFilter.addEventListener("change", renderRows);
searchInput.addEventListener("input", renderRows);

loadInspection().catch((error) => {
  rowsEl.innerHTML = `<tr><td class="empty" colspan="6">巡检结果读取失败：${error.message}</td></tr>`;
});
