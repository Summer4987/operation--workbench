import { MODULES, ACTIONS, ROLES, STORES, rolePermissions, emptyAccount, validateAccount, previewAccount } from './model.js';

const KEY = 'xiong-access-drafts-v1';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
let accounts = [];
let editing = emptyAccount();
let pendingDelete = '';
let toastTimer;
let storageBlocked = false;
const roleCopy = { admin: '全部功能权限，门店仍需明确选择。', regional: '查看负责门店的经营与推广，处理评价和订货。', manager: '关注本店经营、评价、订货和库存。', finance: '查看经营、订货和库存，支持报表导出。', franchisee: '查看加盟门店经营，处理评价和订货。' };

function message(text) {
  $('toast').textContent = text;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
}
function persist(next) {
  if (storageBlocked) { message('原有草稿无法读取，已停止写入以免覆盖。请先检查浏览器存储。'); return false; }
  try {
    localStorage.setItem(KEY, JSON.stringify({ version: 1, accounts: next }));
    accounts = next;
    render();
    return true;
  } catch {
    $('storageError').textContent = '浏览器未能保存草稿（存储不可用或空间不足）。本次修改未保存，请检查浏览器设置。';
    $('storageError').hidden = false;
    return false;
  }
}
function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return;
    const payload = JSON.parse(raw);
    if (payload.version !== 1 || !Array.isArray(payload.accounts)) throw new Error();
    const validated = [];
    for (const a of payload.accounts) {
      if (!a.id || typeof a.id !== 'string' || validated.some(item => item.id === a.id)) throw new Error();
      validated.push(validateAccount(a, validated));
    }
    accounts = validated;
  } catch {
    storageBlocked = true;
    $('storageError').textContent = '无法读取已有草稿。原始数据未被覆盖，已停止写入；请检查此浏览器的本地存储后重新加载。';
    $('storageError').hidden = false;
  }
}
function render() {
  $('accountCount').textContent = accounts.length;
  $('enabledCount').textContent = accounts.filter(a => a.enabled).length;
  $('assignedCount').textContent = new Set(accounts.filter(a => a.enabled).flatMap(a => a.stores)).size;
  $('storeTotal').textContent = `目录共 ${STORES.length} 家门店`;
  $('moduleCount').textContent = MODULES.length;
  const search = $('search').value.trim().toLowerCase();
  const role = $('roleFilter').value;
  const status = $('statusFilter').value;
  const filtered = accounts.filter(a => (!search || `${a.name} ${a.username}`.toLowerCase().includes(search)) && (!role || a.role === role) && (!status || a.enabled === (status === 'enabled')));
  $('resultCount').textContent = `共 ${filtered.length} 个账号草稿`;
  $('accountRows').innerHTML = filtered.map(a => {
    const stores = STORES.filter(s => a.stores.includes(s.id));
    const modules = MODULES.filter(m => a.permissions[m.id]?.includes('view'));
    return `<tr><td><strong>${esc(a.name)}</strong><small>${esc(a.username)}</small></td><td><span class="badge">${esc(ROLES[a.role])}</span></td><td><div class="scope"><strong>${stores.length} 家门店</strong>${esc(stores.map(s => s.name).join('、') || '未分配门店')}</div></td><td><strong>${modules.length} 项功能</strong><small>${a.enabled ? '待接入后台生效' : '停用后预期不可访问'}</small></td><td><span class="badge ${a.enabled ? 'on' : ''}">${a.enabled ? '计划启用' : '计划停用'}</span></td><td><div class="actions"><button data-edit="${esc(a.id)}" type="button" aria-label="编辑 ${esc(a.name)}">编辑</button><button data-toggle="${esc(a.id)}" type="button" aria-label="${a.enabled ? '停用' : '启用'} ${esc(a.name)} 草稿">${a.enabled ? '停用' : '启用'}</button><button data-delete="${esc(a.id)}" type="button" aria-label="删除 ${esc(a.name)} 草稿">删除</button></div></td></tr>`;
  }).join('');
  $('emptyState').hidden = filtered.length > 0;
  $('emptyState').querySelector('h3').textContent = accounts.length ? '没有匹配的账号' : '从第一个账号开始';
  $('emptyState').querySelector('p').textContent = accounts.length ? '试试其他关键词，或调整角色和状态筛选。' : '新增人员，选择角色，再勾选他可以访问的门店。';
  $('exportButton').disabled = accounts.length === 0 || storageBlocked;
}
function renderStores() {
  const query = $('storeSearch').value.trim();
  $('storeGroups').innerHTML = ['直营门店', '加盟门店'].map(group => {
    const visible = STORES.filter(s => s.group === group && s.name.includes(query));
    if (!visible.length) return '';
    return `<div class="store-group"><div class="store-group-head"><strong>${group}</strong><button type="button" data-select-group="${group}">选择当前结果（${visible.length}）</button></div><div class="store-options">${visible.map(s => `<label><input type="checkbox" data-store="${s.id}" ${editing.stores.includes(s.id) ? 'checked' : ''}>${esc(s.name)}</label>`).join('')}</div></div>`;
  }).join('') || '<p class="muted">没有找到匹配门店。</p>';
  $('selectedStores').textContent = `已选 ${editing.stores.length} / ${STORES.length}`;
}
function renderPermissions() {
  let group = '';
  $('permissionRows').innerHTML = MODULES.map(m => {
    const header = group !== m.group ? `<tr class="group"><th colspan="5" scope="colgroup">${m.group}</th></tr>` : '';
    group = m.group;
    return `${header}<tr><td>${m.name}</td>${Object.entries(ACTIONS).map(([action, label]) => `<td>${m.actions.includes(action) ? `<input type="checkbox" data-module="${m.id}" data-action="${action}" aria-label="${m.name} ${label}" ${editing.permissions[m.id]?.includes(action) ? 'checked' : ''}>` : '<span aria-label="不适用">—</span>'}</td>`).join('')}</tr>`;
  }).join('');
}
function syncFields() {
  editing = { ...editing, name: $('name').value, username: $('username').value, note: $('note').value, role: $('role').value, enabled: $('enabled').value === 'true' };
}
function renderPreview() {
  syncFields();
  const preview = previewAccount(editing);
  $('previewSummary').textContent = editing.enabled ? `${editing.name.trim() || '此账号'}将可见 ${preview.stores.length} 家门店、访问 ${preview.modules.length} 项功能。${preview.stores.length ? `门店：${preview.stores.map(s => s.name).join('、')}。` : '请至少选择一家门店。'}` : '此账号计划停用：预期不能访问任何门店或功能。';
  $('previewModules').innerHTML = preview.modules.map(m => `<span class="chip">${m.name} · ${editing.permissions[m.id].map(a => ACTIONS[a]).join(' / ')}</span>`).join('');
}
function openEditor(id = '', role = 'manager') {
  const original = accounts.find(a => a.id === id);
  editing = original ? structuredClone(original) : { ...emptyAccount(), role, permissions: rolePermissions(role) };
  $('editorTitle').textContent = original ? '编辑账号草稿' : '新增账号草稿';
  $('name').value = editing.name;
  $('username').value = editing.username;
  $('role').value = editing.role;
  $('enabled').value = String(editing.enabled);
  $('note').value = editing.note;
  $('storeSearch').value = '';
  $('formError').hidden = true;
  renderStores(); renderPermissions(); renderPreview();
  $('editor').showModal();
  $('name').focus();
}
function applyTemplate() {
  syncFields();
  editing.permissions = rolePermissions(editing.role);
  renderPermissions(); renderPreview();
}
Object.entries(ROLES).forEach(([value, label]) => {
  $('role').add(new Option(label, value));
  $('roleFilter').add(new Option(label, value));
});
$('roleCards').innerHTML = Object.entries(roleCopy).map(([role, copy]) => `<article class="role-card"><h3>${ROLES[role]}</h3><p>${copy}</p><button type="button" data-template="${role}">使用模板</button></article>`).join('');
load(); render();
['search', 'roleFilter', 'statusFilter'].forEach(id => $(id).addEventListener('input', render));
['createButton', 'emptyCreate'].forEach(id => $(id).addEventListener('click', () => openEditor()));
['cancelEditor', 'closeEditor'].forEach(id => $(id).addEventListener('click', () => $('editor').close()));
$('roleCards').addEventListener('click', e => { const button = e.target.closest('[data-template]'); if (button) openEditor('', button.dataset.template); });
$('role').addEventListener('change', applyTemplate);
$('applyRole').addEventListener('click', applyTemplate);
['name', 'username', 'note', 'enabled'].forEach(id => $(id).addEventListener('input', renderPreview));
$('storeSearch').addEventListener('input', renderStores);
$('clearStores').addEventListener('click', () => { editing.stores = []; renderStores(); renderPreview(); });
$('storeGroups').addEventListener('change', e => {
  const id = e.target.dataset.store;
  if (!id) return;
  editing.stores = e.target.checked ? [...new Set([...editing.stores, id])] : editing.stores.filter(s => s !== id);
  $('selectedStores').textContent = `已选 ${editing.stores.length} / ${STORES.length}`;
  renderPreview();
});
$('storeGroups').addEventListener('click', e => {
  const button = e.target.closest('[data-select-group]');
  if (!button) return;
  const ids = STORES.filter(s => s.group === button.dataset.selectGroup && s.name.includes($('storeSearch').value.trim())).map(s => s.id);
  editing.stores = [...new Set([...editing.stores, ...ids])];
  renderStores(); renderPreview();
});
$('permissionRows').addEventListener('change', e => {
  const { module, action } = e.target.dataset;
  if (!module) return;
  let actions = editing.permissions[module] || [];
  if (e.target.checked) actions = [...new Set([...actions, 'view', action])];
  else actions = action === 'view' ? [] : actions.filter(a => a !== action);
  editing.permissions[module] = actions;
  renderPermissions(); renderPreview();
});
$('accountForm').addEventListener('submit', e => {
  e.preventDefault(); syncFields();
  try {
    // Avoid silently overwriting a draft changed in another tab during editing.
    if (localStorage.getItem(KEY) !== initialStorage) throw new Error('其他页面已修改草稿，请关闭编辑并刷新后重试。');
    const account = validateAccount(editing, accounts);
    if (!account.id) account.id = globalThis.crypto?.randomUUID?.() || `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const next = accounts.some(a => a.id === account.id) ? accounts.map(a => a.id === account.id ? account : a) : [...accounts, account];
    if (persist(next)) { initialStorage = localStorage.getItem(KEY); $('editor').close(); message('账号草稿已保存到此浏览器，尚未生效。'); }
  } catch (error) {
    $('formError').textContent = error.message;
    $('formError').hidden = false;
    $('formError').scrollIntoView({ block: 'nearest' });
  }
});
$('accountRows').addEventListener('click', e => {
  const button = e.target.closest('button');
  if (!button) return;
  if (button.dataset.edit) openEditor(button.dataset.edit);
  if (button.dataset.toggle) {
    const account = accounts.find(a => a.id === button.dataset.toggle);
    try {
      if (localStorage.getItem(KEY) !== initialStorage) throw new Error('其他页面已修改草稿，请刷新后重试。');
      const next = validateAccount({ ...account, enabled: !account.enabled }, accounts);
      if (persist(accounts.map(a => a.id === next.id ? next : a))) { initialStorage = localStorage.getItem(KEY); message('已更新草稿状态，尚未影响真实访问。'); }
    } catch (error) { message(error.message); }
  }
  if (button.dataset.delete) {
    pendingDelete = button.dataset.delete;
    const account = accounts.find(a => a.id === pendingDelete);
    $('confirmText').textContent = `将删除“${account.name}”在此浏览器保存的账号和权限草稿。此操作无法撤销。`;
    $('confirmDialog').returnValue = '';
    $('confirmDialog').showModal();
  }
});
$('confirmDialog').addEventListener('close', () => {
  if ($('confirmDialog').returnValue === 'delete') {
    try {
      if (localStorage.getItem(KEY) !== initialStorage) throw new Error('其他页面已修改草稿，请刷新后重试。');
      if (persist(accounts.filter(a => a.id !== pendingDelete))) { initialStorage = localStorage.getItem(KEY); message('账号草稿已删除。'); }
    } catch (error) { message(error.message); }
  }
  pendingDelete = '';
});
$('exportButton').addEventListener('click', () => {
  const payload = { schema: 'xiong-access-draft/v1', enforcement: 'not_connected', exported_at: new Date().toISOString(), stores: STORES, modules: MODULES, accounts };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = '熊小小-账号权限草稿.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  message('已导出配置草稿，不包含密码或登录凭据。');
});
let initialStorage;
try { initialStorage = localStorage.getItem(KEY); } catch { initialStorage = null; }
window.addEventListener('storage', e => {
  if (e.key === KEY || e.key === null) {
    $('storageError').textContent = '其他页面已修改草稿。请先复制尚未保存的内容，再刷新此页面以读取最新版本。';
    $('storageError').hidden = false;
  }
});
