import { MODULES, ACTIONS, ROLES, STORES, setStores, rolePermissions, emptyAccount, validateAccount, previewAccount } from './model.js';

const API = '/api/access/';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
let accounts = [];
let canEdit = false;
let editing = emptyAccount();
let pendingDelete = '';
let toastTimer;
const storageBlocked = false;
const roleCopy = { admin: '全局管理员，覆盖全部门店并管理账号。', regional: '查看负责门店的经营与推广，处理评价和订货。', manager: '关注本店经营、评价、订货和库存。', finance: '查看经营、订货和库存，支持报表导出。', franchisee: '查看加盟门店经营，处理评价和订货。' };

function message(text) {
  $('toast').textContent = text;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
}
async function api(path, payload) {
  const response = await fetch(API + path, payload === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const result = await response.json();
  if (response.status === 401) { location.assign('/login?next=' + encodeURIComponent(location.pathname)); throw new Error('需要重新登录'); }
  if (!response.ok) throw new Error(result.detail || '请求失败');
  return result;
}
async function load() {
  const result = await api('accounts');
  canEdit = result.can_edit;
  setStores(result.stores);
  accounts = result.accounts;
  render();
  const audit = await api('audit');
  const names = {create_account:'新增账号',update_account:'更新账号权限',reset_password:'重置密码',login:'登录',export:'导出数据',create_request:'提交变更申请',review_request:'审批申请'};
  $('auditRows').innerHTML = audit.items.map(r => `<tr><td>${esc(new Date(r.at * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'}))}</td><td>${esc(r.actor)}</td><td>${esc(names[r.action] || r.action)}</td><td>${esc(accounts.find(a => a.id === r.target)?.name || r.target)}</td></tr>`).join('');
}
function credentials(password) {
  if (!password) return;
  $('credentialValue').textContent = password;
  $('credentialDialog').showModal();
}
function render() {
  $('createButton').disabled = !canEdit;
  $('emptyCreate').disabled = !canEdit;
  document.querySelectorAll('[data-template]').forEach(button => { button.disabled = !canEdit; });
  $('accountCount').textContent = accounts.length;
  $('enabledCount').textContent = accounts.filter(a => a.enabled).length;
  $('assignedCount').textContent = new Set(accounts.filter(a => a.enabled).flatMap(a => a.stores)).size;
  $('storeTotal').textContent = `目录共 ${STORES.length} 家门店`;
  $('moduleCount').textContent = MODULES.length;
  const search = $('search').value.trim().toLowerCase();
  const role = $('roleFilter').value;
  const status = $('statusFilter').value;
  const filtered = accounts.filter(a => (!search || `${a.name} ${a.username}`.toLowerCase().includes(search)) && (!role || a.role === role) && (!status || a.enabled === (status === 'enabled')));
  $('resultCount').textContent = `共 ${filtered.length} 个账号`;
  $('accountRows').innerHTML = filtered.map(a => {
    const stores = STORES.filter(s => a.stores.includes(s.id));
    const modules = MODULES.filter(m => a.permissions[m.id]?.includes('view'));
    return `<tr><td><strong>${esc(a.name)}</strong><small>${esc(a.username)}</small></td><td><span class="badge">${esc(ROLES[a.role])}</span></td><td><div class="scope"><strong>${stores.length} 家门店</strong>${esc(stores.map(s => s.name).join('、') || '未分配门店')}</div></td><td><strong>${modules.length} 项功能</strong><small>${a.enabled ? '后台权限已生效' : '已撤销登录会话'}</small></td><td><span class="badge ${a.enabled ? 'on' : ''}">${a.enabled ? '已启用' : '已停用'}</span></td><td><div class="actions"><button ${canEdit ? '' : 'disabled'} data-edit="${esc(a.id)}" type="button" aria-label="编辑 ${esc(a.name)}">编辑</button><button ${canEdit ? '' : 'disabled'} data-toggle="${esc(a.id)}" type="button" aria-label="${a.enabled ? '停用' : '启用'} ${esc(a.name)}">${a.enabled ? '停用' : '启用'}</button><button ${canEdit ? '' : 'disabled'} data-reset="${esc(a.id)}" type="button" aria-label="重置 ${esc(a.name)} 密码">重置密码</button></div></td></tr>`;
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
  $('previewSummary').textContent = editing.enabled ? `${editing.name.trim() || '此账号'}可见 ${preview.stores.length} 家门店、访问 ${preview.modules.length} 项功能。${preview.stores.length ? `门店：${preview.stores.map(s => s.name).join('、')}。` : '请至少选择一家门店。'}` : '此账号已停用：预期不能访问任何门店或功能。';
  $('previewModules').innerHTML = preview.modules.map(m => `<span class="chip">${m.name} · ${editing.permissions[m.id].map(a => ACTIONS[a]).join(' / ')}</span>`).join('');
}
function openEditor(id = '', role = 'manager') {
  const original = accounts.find(a => a.id === id);
  editing = original ? structuredClone(original) : { ...emptyAccount(), role, permissions: rolePermissions(role), stores: role === 'admin' ? STORES.map(s => s.id) : [] };
  $('editorTitle').textContent = original ? '编辑账号' : '新增账号';
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
  if (editing.role === 'admin') editing.stores = STORES.map(s => s.id);
  renderStores();
  renderPermissions(); renderPreview();
}
Object.entries(ROLES).forEach(([value, label]) => {
  $('role').add(new Option(label, value));
  $('roleFilter').add(new Option(label, value));
});
$('roleCards').innerHTML = Object.entries(roleCopy).map(([role, copy]) => `<article class="role-card"><h3>${ROLES[role]}</h3><p>${copy}</p><button type="button" data-template="${role}">使用模板</button></article>`).join('');
load().catch(error => { $('storageError').textContent = error.message; $('storageError').hidden = false; });
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
$('accountForm').addEventListener('submit', async e => {
  e.preventDefault(); syncFields();
  const button = e.target.querySelector('button[type=submit]'); button.disabled = true;
  try {
    const original = accounts.find(a => a.id === editing.id);
    const account = validateAccount(editing, accounts);
    const result = await api('accounts', { ...account, revision: original?.revision });
    $('editor').close(); credentials(result.initial_password); await load();
    message('账号及权限已保存。该账号原有登录会话已撤销。');
  } catch (error) {
    $('formError').textContent = error.message; $('formError').hidden = false; $('formError').scrollIntoView({ block: 'nearest' });
  } finally { button.disabled = false; }
});
$('accountRows').addEventListener('click', async e => {
  const button = e.target.closest('button'); if (!button) return;
  if (button.dataset.edit) openEditor(button.dataset.edit);
  if (button.dataset.toggle) {
    const account = accounts.find(a => a.id === button.dataset.toggle);
    button.disabled = true;
    try { await api('accounts', { ...account, enabled: !account.enabled }); await load(); message('账号状态已更新，原登录会话已撤销。'); }
    catch (error) { message(error.message); button.disabled = false; }
  }
  if (button.dataset.reset) {
    pendingDelete = button.dataset.reset;
    const account = accounts.find(a => a.id === pendingDelete);
    $('confirmText').textContent = `为“${account.name}”生成新密码，并立即撤销该账号的全部登录会话？`;
    $('confirmDialog').returnValue = ''; $('confirmDialog').showModal();
  }
});
$('confirmDialog').addEventListener('close', async () => {
  if ($('confirmDialog').returnValue === 'delete') {
    try { const result = await api('accounts/' + encodeURIComponent(pendingDelete) + '/reset-password', {}); credentials(result.initial_password); await load(); }
    catch (error) { message(error.message); }
  }
  pendingDelete = '';
});
$('closeCredentials').addEventListener('click', () => { $('credentialDialog').close(); $('credentialValue').textContent = ''; });
$('credentialDialog').addEventListener('close', () => { $('credentialValue').textContent = ''; });
$('exportButton').addEventListener('click', () => {
  const payload = { schema: 'xiong-access/v1', enforcement: 'server', exported_at: new Date().toISOString(), stores: STORES, modules: MODULES, accounts };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = '熊小小-账号权限配置.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
