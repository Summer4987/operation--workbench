const sellerName = "成都熊小小餐饮管理有限公司";
const storageKey = "xiongxiaoxiao-sales-receipt";
const sequenceKey = "xiongxiaoxiao-sales-receipt-sequences";
const defaultSealSrc = "./assets/company-seal.png";

const form = document.querySelector("#receiptForm");
const rowsEl = document.querySelector("#itemRows");
const template = document.querySelector("#itemRowTemplate");
const receiptBody = document.querySelector("#receiptBody");
const totalEl = document.querySelector("#receiptTotal");

const fields = {
  saleDate: document.querySelector("#saleDate"),
  receiptNo: document.querySelector("#receiptNo"),
  buyerName: document.querySelector("#buyerName"),
  notes: document.querySelector("#notes"),
  sealImage: document.querySelector("#sealImage")
};

let sealDataUrl = defaultSealSrc;

function resetPrintScale() {
  document.documentElement.style.setProperty("--print-zoom", "1");
}

function prepareOnePagePrint() {
  renderReceipt();
  resetPrintScale();

  const receipt = document.querySelector("#receipt");
  const pageHeightPx = 1010;
  const contentHeight = receipt.scrollHeight;
  const scale = Math.max(0.62, Math.min(1, pageHeightPx / Math.max(contentHeight, 1)));
  document.documentElement.style.setProperty("--print-zoom", scale.toFixed(3));
}

function formatDate(dateText) {
  if (!dateText) return "";
  const [year, month, day] = dateText.split("-");
  return `${year}年${Number(month)}月${Number(day)}日`;
}

function todayText() {
  const today = new Date();
  const offsetDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 10);
}

function receiptNoFor(dateText) {
  const compactDate = (dateText || todayText()).replaceAll("-", "");
  return `XXXS-${compactDate}-001`;
}

function readSequences() {
  try {
    return JSON.parse(localStorage.getItem(sequenceKey) || "{}");
  } catch {
    return {};
  }
}

function saveSequences(sequences) {
  localStorage.setItem(sequenceKey, JSON.stringify(sequences));
}

function receiptNoPattern(dateText) {
  const compactDate = (dateText || todayText()).replaceAll("-", "");
  return {
    compactDate,
    pattern: new RegExp(`^XXXS-${compactDate}-(\\d{3,})$`)
  };
}

function rememberReceiptNo(receiptNo, dateText) {
  const value = String(receiptNo || "").trim();
  const { compactDate, pattern } = receiptNoPattern(dateText);
  const match = value.match(pattern);
  if (!match) return;

  const sequences = readSequences();
  sequences[compactDate] = Math.max(Number(sequences[compactDate] || 0), Number(match[1] || 0));
  saveSequences(sequences);
}

function nextReceiptNo(dateText) {
  const { compactDate } = receiptNoPattern(dateText);
  const sequences = readSequences();
  const next = Number(sequences[compactDate] || 0) + 1;
  sequences[compactDate] = next;
  saveSequences(sequences);
  return `XXXS-${compactDate}-${String(next).padStart(3, "0")}`;
}

function moneyText(value) {
  if (value === "" || value === null || Number.isNaN(Number(value))) return "未填写";
  return `¥${Number(value).toFixed(2)}`;
}

function collectItems() {
  return [...rowsEl.querySelectorAll(".item-row")].map((row) => ({
    name: row.querySelector(".item-name").value.trim(),
    qty: row.querySelector(".item-qty").value,
    unit: row.querySelector(".item-unit").value.trim(),
    amount: row.querySelector(".item-amount").value
  }));
}

function saveDraft() {
  rememberReceiptNo(fields.receiptNo.value, fields.saleDate.value);
  const draft = {
    saleDate: fields.saleDate.value,
    receiptNo: fields.receiptNo.value,
    buyerName: fields.buyerName.value,
    notes: fields.notes.value,
    sealDataUrl,
    items: collectItems()
  };
  localStorage.setItem(storageKey, JSON.stringify(draft));
}

function renderSeal() {
  const sealPreview = document.querySelector("#salesSealPreview");
  if (!sealDataUrl) {
    sealPreview.removeAttribute("src");
    sealPreview.hidden = true;
    return;
  }

  sealPreview.src = sealDataUrl;
  sealPreview.hidden = false;
}

function renderReceipt() {
  const data = {
    saleDate: fields.saleDate.value,
    receiptNo: fields.receiptNo.value || receiptNoFor(fields.saleDate.value),
    buyerName: fields.buyerName.value.trim() || "待填写",
    notes: fields.notes.value.trim() || "无",
    items: collectItems().filter((item) => item.name || item.qty || item.unit || item.amount)
  };

  document.querySelector('[data-out="receiptNo"]').textContent = data.receiptNo;
  document.querySelector('[data-out="buyerName"]').textContent = data.buyerName;
  document.querySelector('[data-out="saleDate"]').textContent = formatDate(data.saleDate);
  document.querySelector('[data-out="notes"]').textContent = data.notes;
  renderSeal();

  receiptBody.innerHTML = "";
  const items = data.items.length ? data.items : [{ name: "待填写", qty: "", unit: "", amount: "" }];
  let total = 0;
  const hasAmount = items.some((item) => item.amount !== "");
  document.querySelector(".receipt-table").classList.toggle("no-amounts", !hasAmount);

  items.forEach((item, index) => {
    const tr = document.createElement("tr");
    const amount = item.amount === "" ? "" : moneyText(item.amount);
    if (item.amount !== "") {
      total += Number(item.amount);
    }

    tr.innerHTML = `
      <td>${index + 1}</td>
      <td>${item.name || "待填写"}</td>
      <td>${item.qty || "未填写"}</td>
      <td>${item.unit || "未填写"}</td>
      <td>${amount}</td>
    `;
    receiptBody.appendChild(tr);
  });

  totalEl.textContent = moneyText(total);
  saveDraft();
}

function addItem(item = {}) {
  const fragment = template.content.cloneNode(true);
  const row = fragment.querySelector(".item-row");
  row.querySelector(".item-name").value = item.name || "";
  row.querySelector(".item-qty").value = item.qty || "";
  row.querySelector(".item-unit").value = item.unit || "";
  row.querySelector(".item-amount").value = item.amount || "";
  rowsEl.appendChild(fragment);
  renderReceipt();
}

function loadDraft() {
  const rawDraft = localStorage.getItem(storageKey);
  const defaultDate = todayText();
  const defaultData = {
    saleDate: defaultDate,
    receiptNo: rawDraft ? receiptNoFor(defaultDate) : nextReceiptNo(defaultDate),
    buyerName: "",
    notes: "",
    items: [{ name: "", qty: "", unit: "", amount: "" }]
  };

  let data = defaultData;
  try {
    data = { ...defaultData, ...JSON.parse(rawDraft || "{}") };
  } catch {
    data = defaultData;
  }

  fields.saleDate.value = data.saleDate || todayText();
  fields.receiptNo.value = data.receiptNo || receiptNoFor(fields.saleDate.value);
  fields.buyerName.value = data.buyerName || "";
  fields.notes.value = data.notes || "";
  sealDataUrl = Object.prototype.hasOwnProperty.call(data, "sealDataUrl") ? data.sealDataUrl : defaultSealSrc;
  rowsEl.innerHTML = "";
  (data.items && data.items.length ? data.items : defaultData.items).forEach(addItem);
  renderReceipt();
}

form.addEventListener("input", (event) => {
  if (event.target === fields.saleDate && !fields.receiptNo.value.trim()) {
    fields.receiptNo.value = receiptNoFor(fields.saleDate.value);
  }
  renderReceipt();
});

document.querySelector("#addItem").addEventListener("click", () => addItem());

rowsEl.addEventListener("click", (event) => {
  if (!event.target.classList.contains("remove-item")) return;
  event.target.closest(".item-row").remove();
  if (!rowsEl.children.length) addItem();
  renderReceipt();
});

document.querySelector("#clearForm").addEventListener("click", () => {
  localStorage.removeItem(storageKey);
  fields.saleDate.value = todayText();
  fields.receiptNo.value = nextReceiptNo(fields.saleDate.value);
  fields.buyerName.value = "";
  fields.notes.value = "";
  sealDataUrl = "";
  fields.sealImage.value = "";
  rowsEl.innerHTML = "";
  addItem();
  renderReceipt();
});

document.querySelector("#printReceipt").addEventListener("click", () => {
  prepareOnePagePrint();
  window.print();
});

fields.sealImage.addEventListener("change", () => {
  const file = fields.sealImage.files && fields.sealImage.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.addEventListener("load", () => {
    sealDataUrl = reader.result || "";
    renderReceipt();
  });
  reader.readAsDataURL(file);
});

document.querySelector("#clearSeal").addEventListener("click", () => {
  sealDataUrl = "";
  fields.sealImage.value = "";
  renderReceipt();
});

window.addEventListener("beforeprint", prepareOnePagePrint);
window.addEventListener("afterprint", resetPrintScale);

loadDraft();

window.xiongSalesReceipt = { sellerName, renderReceipt, prepareOnePagePrint };
