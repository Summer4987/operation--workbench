const storageKey = "xiongxiaoxiao-franchise-contract-draft-v1";
const fieldIds = [
  "partyType", "partyName", "partyId", "legalRepresentative", "partyAddress", "partyPhone", "partyEmail",
  "storeShortName", "licenseCity", "storeAddress", "noticeContact", "noticePhone", "noticeAddress",
  "receiverName", "receiverPhone", "receiverAddress", "signDate", "termYears"
];
const fields = Object.fromEntries(fieldIds.map((id) => [id, document.getElementById(id)]));
const form = document.getElementById("contractForm");
const sameNotice = document.getElementById("sameNotice");
const sameDelivery = document.getElementById("sameDelivery");
let templates = { brand: "", service: "" };

function localToday() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function chineseDate(value) {
  if (!value) return "";
  const [year, month, day] = value.split("-").map(Number);
  return `${year}年${month}月${day}日`;
}

function endDate(value, years) {
  if (!value) return "";
  const [year, month, day] = value.split("-").map(Number);
  const result = new Date(year + Number(years), month - 1, day);
  if (month === 2 && day === 29 && result.getMonth() !== 1) result.setDate(0);
  return `${result.getFullYear()}年${result.getMonth() + 1}月${result.getDate()}日`;
}

function normalizeStoreName(value) {
  const name = value.trim();
  if (!name) return "";
  return name.endsWith("店") ? name : `${name}店`;
}

function normalizeCity(value) {
  const city = value.trim();
  if (!city) return "";
  return /[市州盟区县]$/.test(city) ? city : `${city}市`;
}

function syncLinkedFields() {
  if (sameNotice.checked) {
    fields.noticeContact.value = fields.partyName.value;
    fields.noticePhone.value = fields.partyPhone.value;
    fields.noticeAddress.value = fields.partyAddress.value;
  }
  if (sameDelivery.checked) {
    fields.receiverName.value = fields.partyName.value;
    fields.receiverPhone.value = fields.partyPhone.value;
    fields.receiverAddress.value = fields.storeAddress.value;
  }
  ["noticeContact", "noticePhone", "noticeAddress"].forEach((id) => fields[id].disabled = sameNotice.checked);
  ["receiverName", "receiverPhone", "receiverAddress"].forEach((id) => fields[id].disabled = sameDelivery.checked);
}

function values() {
  const storeShortName = normalizeStoreName(fields.storeShortName.value);
  const legalRepresentative = fields.legalRepresentative.value.trim() || fields.partyName.value.trim();
  return {
    party_type: fields.partyType.value === "company" ? "企业" : "自然人",
    party_name: fields.partyName.value.trim(),
    party_id: fields.partyId.value.trim(),
    legal_representative: legalRepresentative,
    party_address: fields.partyAddress.value.trim(),
    party_phone: fields.partyPhone.value.trim(),
    party_email: fields.partyEmail.value.trim(),
    notice_contact: fields.noticeContact.value.trim(),
    notice_phone: fields.noticePhone.value.trim(),
    notice_address: fields.noticeAddress.value.trim(),
    receiver_name: fields.receiverName.value.trim(),
    receiver_phone: fields.receiverPhone.value.trim(),
    receiver_address: fields.receiverAddress.value.trim(),
    store_short_name: storeShortName,
    store_full_name: storeShortName ? `熊小小牛排饭POKEBEAR（${storeShortName}）` : "",
    store_address: fields.storeAddress.value.trim(),
    license_city: normalizeCity(fields.licenseCity.value),
    sign_date: chineseDate(fields.signDate.value),
    start_date: chineseDate(fields.signDate.value),
    end_date: endDate(fields.signDate.value, fields.termYears.value),
    term_years: fields.termYears.value
  };
}

function fillTemplate(template, data) {
  return template.replace(/\{\{([a-z_]+)\}\}/g, (_, key) => data[key] || "【待填写】");
}

function saveDraft() {
  const draft = Object.fromEntries(fieldIds.map((id) => [id, fields[id].value]));
  draft.sameNotice = sameNotice.checked;
  draft.sameDelivery = sameDelivery.checked;
  localStorage.setItem(storageKey, JSON.stringify(draft));
}

function render() {
  syncLinkedFields();
  const data = values();
  document.getElementById("fullStoreName").textContent = data.store_full_name || "待填写";
  document.getElementById("termPreview").textContent = data.start_date ? `${data.start_date} 至 ${data.end_date}` : "待计算";
  document.getElementById("readyText").textContent = form.checkValidity() && templates.brand && templates.service
    ? "资料已完整，可以生成并导出 Word 合同。"
    : "请先完整填写必填信息。";
  saveDraft();
}

function downloadDoc(filename, title, text) {
  const blob = new Blob(["\ufeff", ContractFormat.wordHtml(title, text)], { type: "application/msword;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function exportContract(type) {
  syncLinkedFields();
  if (!form.reportValidity()) return;
  const data = values();
  const brand = fillTemplate(templates.brand, data);
  const service = fillTemplate(templates.service, data);
  const suffix = data.store_short_name || data.party_name;
  if (type === "brand") downloadDoc(`品牌授权合同（${suffix}）.doc`, "品牌授权合同", brand);
  if (type === "service") downloadDoc(`服务合同和采购协议（${suffix}）.doc`, "服务合同和采购协议", service);
  if (type === "bundle") downloadDoc(`熊小小加盟合同全套（${suffix}）.doc`, "熊小小加盟合同全套", `${brand}\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n${service}`);
}

async function loadTemplates() {
  const [brand, service] = await Promise.all([
    fetch("./templates/brand-authorization.txt").then((response) => response.text()),
    fetch("./templates/service-purchase.txt").then((response) => response.text())
  ]);
  templates = { brand, service };
  render();
}

function loadDraft() {
  fields.signDate.value = localToday();
  fields.termYears.value = "3";
  try {
    const draft = JSON.parse(localStorage.getItem(storageKey) || "{}");
    fieldIds.forEach((id) => {
      if (draft[id] !== undefined) fields[id].value = draft[id];
    });
    sameNotice.checked = draft.sameNotice !== false;
    sameDelivery.checked = draft.sameDelivery !== false;
  } catch {}
  render();
}

form.addEventListener("input", render);
form.addEventListener("change", render);
document.querySelectorAll("[data-export]").forEach((button) => button.addEventListener("click", () => exportContract(button.dataset.export)));
document.getElementById("resetForm").addEventListener("click", () => {
  localStorage.removeItem(storageKey);
  form.reset();
  fields.signDate.value = localToday();
  fields.termYears.value = "3";
  sameNotice.checked = true;
  sameDelivery.checked = true;
  render();
});

loadDraft();
loadTemplates().catch(() => {
  document.getElementById("readyText").textContent = "合同模板加载失败，请刷新页面后重试。";
});
