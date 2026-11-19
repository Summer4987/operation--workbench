import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyAccount, rolePermissions, validateAccount, previewAccount, MODULES } from '../account-permissions/model.js';

const account = () => ({ ...emptyAccount(), id: 'test-1', name: '测试店长', username: 'manager.test', stores: ['direct-1'] });
test('ordinary roles cannot change or approve promotion by default', () => {
  for (const role of ['regional', 'manager', 'finance', 'franchisee']) {
    const permissions = rolePermissions(role);
    for (const id of ['budget', 'bidding']) {
      assert.ok(!permissions[id].includes('edit'));
      assert.ok(!permissions[id].includes('approve'));
    }
    assert.deepEqual(permissions.accounts, []);
  }
});
test('store access requires explicit assignment, including administrators', () => {
  assert.deepEqual(emptyAccount().stores, []);
  assert.throws(() => validateAccount({ ...account(), role: 'admin', stores: [], permissions: rolePermissions('admin') }), /至少需要选择/);
  assert.throws(() => validateAccount({ ...account(), stores: ['unknown'] }), /未知门店/);
  assert.equal(previewAccount(account()).stores.length, 1);
});
test('usernames are case insensitive and must be unique', () => {
  assert.equal(validateAccount({ ...account(), username: 'MANAGER.Test' }).username, 'manager.test');
  assert.throws(() => validateAccount({ ...account(), id: 'test-2' }, [account()]), /已存在/);
  assert.doesNotThrow(() => validateAccount(account(), [account()]));
});
test('non-view actions cannot be saved without view permission', () => {
  const a = account();
  a.permissions.budget = ['approve'];
  assert.throws(() => validateAccount(a), /先勾选查看/);
  a.permissions.budget = ['view', 'approve'];
  assert.deepEqual(validateAccount(a).permissions.budget, ['view', 'approve']);
});
test('unsupported actions and empty enabled permissions are rejected', () => {
  const a = account();
  a.permissions['direct-daily'] = ['view', 'approve'];
  assert.throws(() => validateAccount(a), /格式无效/);
  assert.throws(() => validateAccount({ ...account(), permissions: rolePermissions('custom') }), /至少需要一项/);
});
test('disabled accounts preview no access and preserve configuration for later editing', () => {
  const a = { ...account(), enabled: false };
  assert.deepEqual(previewAccount(a), { stores: [], modules: [] });
  assert.deepEqual(validateAccount(a).stores, ['direct-1']);
});
test('administrator template is complete and store assignments are deduplicated', () => {
  const permissions = rolePermissions('admin');
  for (const module of MODULES) assert.deepEqual(permissions[module.id], module.actions);
  assert.deepEqual(validateAccount({ ...account(), stores: ['direct-1', 'direct-1'] }).stores, ['direct-1']);
});
