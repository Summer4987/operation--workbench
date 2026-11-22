const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'workbench.js'), 'utf8');
const nav = html.match(/<nav\b[\s\S]*?<\/nav>/)[0];
const sections = new Map();
const links = [...nav.matchAll(/<a\b[^>]*href="#([^"]+)"[^>]*>([^<]+)<\/a>/g)].map(([,id,label]) => {
  const start = html.indexOf(`id="${id}"`);
  assert.ok(start >= 0, `Missing destination: ${id}`);
  if (id !== 'overview') {
    const body = html.slice(start).split(/<section\b/)[0];
    assert.equal(body.match(/<h2>([^<]+)<\/h2>/)?.[1], label, `Static heading: ${id}`);
    const heading = {textContent:'stale'};
    const center = {textContent:'stale'};
    const frame = {title:'stale'};
    sections.set(id, {heading, center, frame, querySelector:q=>q.endsWith('h2')?heading:center, querySelectorAll:()=>[frame]});
  }
  return {textContent:label, getAttribute:()=>`#${id}`, closest:()=>({querySelector:()=>({textContent:'current group'})})};
});
assert.ok(!/加盟店|推广预算全自动设置|推广出价调整/.test(html));
assert.ok(nav.includes('推广预算设置') && nav.includes('龙虾店长预览'));
const context = {navLinks:links, sectionForHash:id=>sections.get(id), commandBoard:{setAttribute:(k,v)=>{context.overviewLabel=v;}}};
vm.createContext(context);
vm.runInContext(js.slice(js.indexOf('function syncNavigationLabels()'),js.indexOf('function activatePage()')),context);
for (const link of links) {
  const section=sections.get(link.getAttribute().slice(1));
  if (!section) continue;
  assert.equal(section.heading.textContent,link.textContent);
  assert.equal(section.frame.title,link.textContent);
  assert.equal(section.center.textContent,'current group');
}
assert.equal(context.overviewLabel,'门店实时数据看板');
// Renaming only a menu must update its destination on the next synchronization.
links.find(l=>l.getAttribute()==='#budget').textContent='未来预算名称';
vm.runInContext('syncNavigationLabels()',context);
assert.equal(sections.get('budget').heading.textContent,'未来预算名称');
console.log(`Navigation labels verified: ${links.length} destinations, embedded titles, and future rename propagation.`);
