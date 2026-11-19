// Draft configuration only. This module is not an authorization boundary.
export const MODULES = [
  { id: 'direct-daily', name: '直营店日报', group: '经营数据', actions: ['view', 'export'] },
  { id: 'direct-reviews', name: '直营店评价', group: '经营数据', actions: ['view', 'edit', 'export'] },
  { id: 'overview', name: '加盟店实时数据', group: '经营数据', actions: ['view', 'export'] },
  { id: 'daily', name: '加盟店日报', group: '经营数据', actions: ['view', 'export'] },
  { id: 'reviews', name: '加盟店评价', group: '经营数据', actions: ['view', 'edit', 'export'] },
  { id: 'budget', name: '推广预算', group: '推广中心', actions: ['view', 'edit', 'approve', 'export'] },
  { id: 'bidding', name: '推广出价', group: '推广中心', actions: ['view', 'edit', 'approve'] },
  { id: 'balances', name: '推广余额', group: '推广中心', actions: ['view', 'export'] },
  { id: 'ordering', name: '订货管理', group: '货流中心', actions: ['view', 'edit', 'approve', 'export'] },
  { id: 'inventory', name: '库存管理', group: '货流中心', actions: ['view', 'edit', 'export'] },
  { id: 'floor-plan', name: '平面图设计', group: '小工具', actions: ['view', 'edit', 'export'] },
  { id: 'sales-receipts', name: '销售单生成器', group: '小工具', actions: ['view', 'edit', 'export'] },
  { id: 'franchise-contract', name: '加盟合同生成器', group: '小工具', actions: ['view', 'edit', 'export'] },
  { id: 'accounts', name: '账号与权限', group: '系统管理', actions: ['view', 'edit'] },
];
export const ACTIONS = { view: '查看', edit: '修改', approve: '审批', export: '导出' };
export const ROLES = { admin: '总管理员', regional: '区域负责人', manager: '店长', finance: '财务', franchisee: '加盟商', custom: '自定义' };
// Seed directory from the existing direct/franchise report target stores.
// No city is inferred from store names. New stores must be explicitly selected.
export const STORES = [
  ...['朝阳门店', '银泰城店', '万象城店', '金融城店', '保利中心店'].map((name, i) => ({ id: `direct-${i + 1}`, name, group: '直营门店' })),
  ...['安贞', '中关村', '清河', '金融街', '丽泽', '双井', '光谷', '五一广场', '望京', '滨江店'].map((name, i) => ({ id: `franchise-${i + 1}`, name, group: '加盟门店' })),
];
export function rolePermissions(role) {
  const ids = {
    regional: ['direct-daily', 'direct-reviews', 'overview', 'daily', 'reviews', 'budget', 'bidding', 'balances', 'ordering'],
    manager: ['direct-daily', 'direct-reviews', 'ordering', 'inventory', 'balances'],
    finance: ['direct-daily', 'daily', 'ordering', 'inventory'],
    franchisee: ['overview', 'daily', 'reviews', 'ordering'],
  };
  return Object.fromEntries(MODULES.map(m => {
    let actions = [];
    if (role === 'admin') actions = m.actions;
    else if ((ids[role] || []).includes(m.id)) {
      actions = m.actions.filter(a => a === 'view' || a === 'export' || (a === 'edit' && ['regional', 'manager', 'franchisee'].includes(role) && ['direct-reviews', 'reviews', 'ordering'].includes(m.id)));
    }
    return [m.id, [...actions]];
  }));
}
export function emptyAccount() {
  return { id: '', name: '', username: '', role: 'manager', enabled: true, stores: [], permissions: rolePermissions('manager'), note: '' };
}
export function validateAccount(account, accounts = []) {
  if (!account || typeof account !== 'object') throw new Error('账号格式无效。');
  const name = String(account.name || '').trim();
  const username = String(account.username || '').trim().toLowerCase();
  if (!name || name.length > 40) throw new Error('请填写姓名，最多 40 个字。');
  if (!/^[a-z0-9][a-z0-9._@+-]{2,63}$/.test(username)) throw new Error('账号需为 3–64 位字母、数字或 . _ @ + -，以字母或数字开头。');
  if (accounts.some(a => a.id !== account.id && a.username.toLowerCase() === username)) throw new Error('这个账号已存在，请使用其他账号。');
  if (!Object.hasOwn(ROLES, account.role)) throw new Error('请选择有效角色。');
  if (typeof account.enabled !== 'boolean') throw new Error('账号状态无效。');
  const stores = [...new Set(account.stores || [])];
  if (stores.some(id => !STORES.some(s => s.id === id))) throw new Error('包含未知门店，请重新选择。');
  if (account.enabled && stores.length === 0) throw new Error('启用的账号至少需要选择一家可见门店。');
  const permissions = Object.fromEntries(MODULES.map(m => {
    const input = account.permissions?.[m.id] || [];
    if (!Array.isArray(input) || input.some(a => !m.actions.includes(a))) throw new Error('功能权限格式无效。');
    const actions = [...new Set(input)];
    if (actions.some(a => a !== 'view') && !actions.includes('view')) throw new Error(`${m.name}：请先勾选查看权限。`);
    return [m.id, actions];
  }));
  if (account.enabled && !Object.values(permissions).some(a => a.includes('view'))) throw new Error('启用的账号至少需要一项查看权限。');
  return { id: String(account.id || ''), name, username, role: account.role, enabled: account.enabled, stores, permissions, note: String(account.note || '').trim().slice(0, 300) };
}
export function previewAccount(account) {
  if (!account.enabled) return { stores: [], modules: [] };
  return { stores: STORES.filter(s => account.stores.includes(s.id)), modules: MODULES.filter(m => account.permissions[m.id]?.includes('view')) };
}
