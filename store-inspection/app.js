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
  return status === "warning" ? "需提醒" : "正常";
}

function renderStats(data) {
  document.querySelector("#platformCount").textContent = data.summary.platform_count;
  document.querySelector("#storeCount").textContent = data.summary.store_count;
  document.querySelector("#warningCount").textContent = data.summary.warning_count;
  document.querySelector("#lowestBalance").textContent = yuan.format(data.summary.lowest_balance);
  document.querySelector("#generatedAt").textContent =
    data.status === "failed" ? "巡检失败" : `生成 ${data.generated_at}`;
}

function renderRows() {
  const status = statusFilter.value;
  const keyword = searchInput.value.trim().toLowerCase();
  const filtered = inspectionItems.filter((item) => {
    const matchesStatus = status === "all" || item.status === status;
    const haystack = `${item.platform} ${item.store_name} ${item.store_id}`.toLowerCase();
    return matchesStatus && (!keyword || haystack.includes(keyword));
  });

  if (!filtered.length) {
    rowsEl.innerHTML = `<tr><td class="empty" colspan="6">没有符合条件的巡检结果</td></tr>`;
    return;
  }

  rowsEl.innerHTML = filtered
    .map((item) => {
      const rowStatus = Number(item.balance) < threshold ? "warning" : item.status;
      return `
        <tr>
          <td>${item.platform}</td>
          <td>${item.store_name}</td>
          <td>${item.store_id || "-"}</td>
          <td class="money ${rowStatus}">${yuan.format(item.balance)}</td>
          <td><span class="pill ${rowStatus}">${statusText(rowStatus)}</span></td>
          <td>${item.source || "自动巡检"}</td>
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
