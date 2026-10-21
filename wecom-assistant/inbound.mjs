import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import ExcelJS from 'exceljs';

const normalize = s => String(s ?? '').normalize('NFKC').toLowerCase().replace(/\s+/g, '').replace(/西蓝花/g, '西兰花');
const cleanName = s => normalize(s).replace(/^熊小小(?:牛排饭)?[-－]?/, '').replace(/[（(]冻[）)]|冷冻/g, '').replace(/冻$/, '');
const text = cell => String(cell?.text ?? cell?.value ?? '').trim();
export const INBOUND_HEADERS = ['预计入库日期','库存地点','供应商编码','供应商名称','商品编码','商品名称','物料规格','储存方式','到货数量','单位'];

export function inboundTemplate(config) {
  return config.WECOM_INBOUND_TEMPLATE || path.join(os.homedir(), 'Desktop/熊小小/易代仓预约.xlsx');
}

export async function readInboundTemplate(config) {
  const source = inboundTemplate(config);
  if (!fs.existsSync(source)) throw Error('入库模板不存在，请检查Mac mini上的易代仓预约.xlsx');
  const book = new ExcelJS.Workbook();
  await book.xlsx.readFile(source);
  const sheet = book.getWorksheet('Sheet1') || book.worksheets[0];
  const columns = {};
  sheet.getRow(1).eachCell((c, n) => { columns[text(c)] = n; });
  const missing = INBOUND_HEADERS.filter(h => !columns[h]);
  if (missing.length) throw Error('入库模板缺少字段：' + missing.join('、'));
  const dictionary = book.getWorksheet('Sheet2');
  if (!dictionary) throw Error('入库模板缺少Sheet2商品字典');
  let headerRow = 0, headers = {};
  for (let n=1;n<=Math.min(dictionary.rowCount,20);n++) {
    const map = {};
    dictionary.getRow(n).eachCell((c,i) => { map[text(c)] = i; });
    if (map['项目'] && map['编码']) { headerRow=n;headers=map;break; }
  }
  if (!headerRow) throw Error('入库模板商品字典字段不完整');
  const catalog = [];
  for (let n=headerRow+1;n<=dictionary.rowCount;n++) {
    const row=dictionary.getRow(n);
    const get=h=>headers[h]?text(row.getCell(headers[h])):'';
    if (get('编码') && get('项目')) catalog.push({sku:get('编码'),name:get('项目'),spec:get('箱规')||get('物料规格'),storage:get('存储方式'),unit:get('单位')});
  }
  if (!catalog.length) throw Error('入库模板商品字典为空');
  return {book,sheet,columns,catalog};
}

export function productAliases(product) {
  const aliases = new Set([normalize(product.sku),normalize(product.name),cleanName(product.name)]);
  if (cleanName(product.name).includes('腌制鸡胸')) aliases.add('鸡胸').add('鸡胸肉');
  if (cleanName(product.name).includes('腌制鸡腿')) aliases.add('鸡腿').add('鸡腿肉');
  if (cleanName(product.name).includes('牛五花')) aliases.add('牛五花');
  if (cleanName(product.name).includes('三文鱼')) aliases.add('三文鱼');
  return [...aliases].filter(s=>s.length>=2);
}

export function matchInboundProduct(catalog, query) {
  const q=cleanName(query);
  if(q.length<2) throw Error('入库商品名过短，请写完整名称或商品编码');
  const exact=catalog.filter(p=>productAliases(p).includes(q));
  const candidates=exact.length?exact:catalog.filter(p=>productAliases(p).some(a=>a.includes(q)));
  if (candidates.length===1) return candidates[0];
  if (candidates.length>1) throw Error('入库商品“'+query+'”有多个匹配，请明确：'+candidates.slice(0,6).map(p=>p.name).join('、'));
  throw Error('入库商品“'+query+'”不在模板字典中，请提供准确品名或商品编码');
}

function validDate(value) {
  const date=new Date(value+'T00:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0,10)!==value) throw Error('入库日期无效，请按YYYY-MM-DD填写');
  return value;
}
export function inboundDate(raw, today) {
  const dates=[...raw.matchAll(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?/g)].map(m=>`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`);
  if(new Set(dates).size>1 || (raw.includes('明天')&&raw.includes('后天')))throw Error('入库日期有多批，请按不同日期分开发送');
  const match=raw.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?/);
  if(match) return validDate(`${match[1]}-${match[2].padStart(2,'0')}-${match[3].padStart(2,'0')}`);
  const short=raw.match(/(?<!\d)(\d{1,2})月(\d{1,2})日?/);
  if(short)return validDate(`${today.slice(0,4)}-${short[1].padStart(2,'0')}-${short[2].padStart(2,'0')}`);
  const offset=raw.includes('后天')?2:raw.includes('明天')?1:0;
  return validDate(new Date(Date.parse(today+'T00:00:00Z')+offset*86400000).toISOString().slice(0,10));
}

function chineseNumber(word){
  const digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9};
  let sum=0,part=0,value=0;
  for(const c of word){
    if(c in digits)value=digits[c];
    else if(c==='万'){sum+=(part+value)*10000;part=0;value=0;}
    else {part+=(value||1)*({'十':10,'百':100,'千':1000}[c]||0);value=0;}
  }
  return sum+part+value;
}

export async function createInbound(args, raw, config, root, today) {
  if (!Array.isArray(args.items)||!args.items.length||args.items.length>100) throw Error('入库表需要1至100项商品');
  const loaded=await readInboundTemplate(config);
  const date=inboundDate(raw,today);
  if(args.inbound_date && args.inbound_date!==date) throw Error('入库日期与原文不一致，请确认预计入库日期');
  const warehouse=args.warehouse||'成都易代仓';
  if(warehouse!=='成都易代仓'&&!raw.includes(warehouse)) throw Error('入库仓库必须来自你的原文');
  const segments=raw.split(/[\n，,；;]/).map(normalize).map(s=>s.replace(/[零〇一二两三四五六七八九十百千万]+(?=件|箱|袋|个|斤|公斤|千克|kg|瓶)/g,word=>String(chineseNumber(word))));
  const records=args.items.map(item=>{
    const product=matchInboundProduct(loaded.catalog,item.product);
    const qty=item.quantity;
    if(typeof qty!=='number'||!Number.isFinite(qty)||qty<=0||qty>10000000) throw Error('入库数量须为明确的正数，请核对“'+item.product+'”');
    const evidence=segments.filter(segment=>productAliases(product).some(a=>segment.includes(a)))
      .flatMap(segment=>[...segment.matchAll(/(?<![\w.+-])\d+(?:\.\d+)?(?![\d.])/g)]
        .filter(m=>Number(m[0])===qty).map(m=>segment.slice(m.index+m[0].length)))
      .filter(s=>!/^e[+-]?\d/.test(s));
    if(!evidence.length) throw Error('入库商品与数量无法从同一条原文核对，请按“品名 数量 单位”逐项发送');
    const suppliedUnits=[...new Set(evidence.map(s=>s.match(/^(公斤|千克|kg|件|箱|袋|个|斤|瓶|包|桶|盒|吨)/)?.[1]).filter(Boolean))];
    if(suppliedUnits.length>1)throw Error('入库同一商品数量对应多个单位，请分行明确');
    const unit=item.unit||suppliedUnits[0]||product.unit;
    if(!unit||unit.length>8) throw Error('入库单位不明确，请补充单位');
    if(item.unit&&!evidence.some(s=>s.startsWith(normalize(unit)))) throw Error('入库单位与原文不一致，请核对');
    return {'预计入库日期':new Date(date+'T00:00:00Z'),'库存地点':warehouse,'供应商编码':null,'供应商名称':null,'商品编码':product.sku,'商品名称':product.name,'物料规格':product.spec,'储存方式':product.storage,'到货数量':qty,'单位':unit};
  });
  const {book,sheet,columns}=loaded;
  // A new reservation contains only this request; the original workbook is never changed.
  const styles=INBOUND_HEADERS.map(h=>structuredClone(sheet.getRow(2).getCell(columns[h]).style));
  for(let n=2;n<=sheet.rowCount;n++)for(const h of INBOUND_HEADERS)sheet.getRow(n).getCell(columns[h]).value=null;
  records.forEach((record,index)=>{
    for(const [i,h] of INBOUND_HEADERS.entries()){
      const cell=sheet.getRow(index+2).getCell(columns[h]);cell.style=structuredClone(styles[i]);cell.value=record[h];
      if(h==='预计入库日期')cell.numFmt='yyyy-mm-dd';
    }
  });
  const out=path.join(root,'outbox');fs.mkdirSync(out,{recursive:true,mode:0o700});
  const file=path.join(out,`易代仓入库预约_${date}_${crypto.randomUUID().slice(0,8)}.xlsx`);
  await book.xlsx.writeFile(file);fs.chmodSync(file,0o600);
  return {file,inbound_date:date,warehouse,line_count:records.length,items:records.map(r=>({sku:r['商品编码'],name:r['商品名称'],quantity:r['到货数量'],unit:r['单位']})),note:'生成独立预约文件，仅包含本次入库内容；未登记实际库存。未写日期默认今天，未写仓库默认成都易代仓，缺省单位使用模板字典单位，未做单位换算。'};
}
