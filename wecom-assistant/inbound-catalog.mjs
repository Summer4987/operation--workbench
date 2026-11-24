import fs from 'node:fs';

// Business configuration approved from the user's template; never load private runtime files here.
export const catalogFile = new URL('./inbound-catalog.json', import.meta.url);
export function updateInboundCatalog(book, data = JSON.parse(fs.readFileSync(catalogFile, 'utf8'))) {
  const required = ['编码', '项目', '存储方式', '箱规', '单位'];
  if (!Array.isArray(data.headers) || required.some(h => !data.headers.includes(h)) || !Array.isArray(data.rows) || !data.rows.length) {
    throw Error('已批准的Sheet2商品配置不完整');
  }
  const codes = new Set();
  for (const row of data.rows) {
    if (!Array.isArray(row) || row.length !== data.headers.length || required.some(h => !String(row[data.headers.indexOf(h)] || '').trim())) throw Error('Sheet2商品配置缺少必填值');
    const sku = row[data.headers.indexOf('编码')];
    if (codes.has(sku) || data.headers.some((h, i) => h === '编码' && row[i] !== sku)) throw Error('Sheet2商品编码重复或不一致');
    codes.add(sku);
  }
  const sheet = book.getWorksheet('Sheet2');
  if (!sheet) throw Error('入库模板缺少Sheet2商品字典');
  let headerRow = 0;
  for (let n = 1; n <= Math.min(sheet.rowCount, 20); n++) {
    const values = sheet.getRow(n).values;
    if (values.includes('编码') && values.includes('项目')) { headerRow = n; break; }
  }
  if (!headerRow) throw Error('入库模板商品字典字段不完整');
  // Only replace the dictionary area; retain the template title, styles and other columns.
  const styles = data.headers.map((_, i) => structuredClone(sheet.getRow(headerRow + 1).getCell(i + 1).style));
  const width = Math.max(data.headers.length, sheet.getRow(headerRow).cellCount);
  for (let n = headerRow; n <= Math.max(sheet.rowCount, headerRow + data.rows.length); n++) {
    for (let c = 1; c <= width; c++) sheet.getRow(n).getCell(c).value = null;
  }
  data.headers.forEach((value, i) => { sheet.getRow(headerRow).getCell(i + 1).value = value; });
  data.rows.forEach((row, n) => row.forEach((value, i) => {
    const cell = sheet.getRow(headerRow + n + 1).getCell(i + 1);
    cell.style = structuredClone(styles[i]);
    cell.value = value || null;
  }));
  return {source: data.source, count: data.rows.length};
}
