import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import ExcelJS from 'exceljs';

function table(book,name,columns,rows){
  const sheet=book.addWorksheet(name,{views:[{state:'frozen',ySplit:1}],properties:{defaultRowHeight:22}});
  sheet.addRow(columns);
  rows.forEach(row=>sheet.addRow(columns.map(c=>c==='日期'&&/^\d{4}-\d{2}-\d{2}$/.test(row[c])?new Date(row[c]+'T00:00:00Z'):(row[c]??null))));
  sheet.eachRow((row,n)=>{if(n>1)row.font={name:'Arial',size:11};});
  sheet.getRow(1).eachCell(cell=>{
    cell.font={name:'Arial',bold:true,color:{argb:'FFFFFFFF'},size:11};
    cell.fill={type:'pattern',pattern:'solid',fgColor:{argb:'FF244B43'}};
    cell.alignment={horizontal:'center',vertical:'middle'};
  });
  sheet.getRow(1).height=30;
  sheet.columns.forEach((col,i)=>{
    col.width=/品名|商品|状态/.test(columns[i])?42:/门店|备注|平台|日期|时间|说明/.test(columns[i])?30:22;
    if(/收入|实付|差额/.test(columns[i]))col.numFmt='#,##0.00';
    if(/记录数|订单|数量/.test(columns[i])&&!/率$/.test(columns[i]))col.numFmt='#,##0.####';
    if(/率$/.test(columns[i]))col.numFmt='0.0%';
    if(columns[i]==='日期')col.numFmt='yyyy-mm-dd';
    if(columns[i]==='状态'){
      col.alignment={wrapText:true,vertical:'middle'};
      rows.forEach((r,n)=>{sheet.getRow(n+2).height=Math.max(22,Math.ceil(String(r['状态']||'').length/20)*20);});
    }
  });
  sheet.views=[{state:'frozen',ySplit:1,showGridLines:false}];
  sheet.autoFilter={from:{row:1,column:1},to:{row:Math.max(1,rows.length+1),column:columns.length}};
  return sheet;
}
function notes(book,payload){
  const rows=[{'项目':'统计期间','内容':`${payload.start} 至 ${payload.end}`},
    {'项目':'数据来源','内容':payload.source||''},
    {'项目':'统计口径','内容':payload.note||''}];
  if(payload.previous_start)rows.push({'项目':'对比期间','内容':`${payload.previous_start} 至 ${payload.previous_end}`});
  for(const s of payload.sources||[])rows.push({'项目':s.scope==='direct'?'直营数据更新时间':'加盟数据更新时间','内容':`${s.generated_at||'未知'}；最新记录${s.latest_date||'未知'}`});
  if(payload.missing_dates?.length)rows.push({'项目':'无记录日期','内容':payload.missing_dates.join('、')});
  for(const error of payload.errors||[])rows.push({'项目':'数据问题','内容':error});
  const sheet=table(book,'口径说明',['项目','内容'],rows);sheet.getColumn(2).width=110;
  sheet.getColumn(2).alignment={wrapText:true,vertical:'middle'};
  sheet.eachRow((row,n)=>{if(n>1)row.height=42;});
}
async function save(book,title,root){
  const out=path.join(root,'outbox');fs.mkdirSync(out,{recursive:true,mode:0o700});
  const filename=String(title).replace(/[^\p{L}\p{N}_-]/gu,'_').slice(0,65);
  const file=path.join(out,`${filename}_${crypto.randomUUID().slice(0,8)}.xlsx`);
  await book.xlsx.writeFile(file);fs.chmodSync(file,0o600);return file;
}
export async function businessReport(payload,root){
  const book=new ExcelJS.Workbook();
  table(book,'门店汇总',['范围','门店','收入','订单数','记录数','收入缺失记录数'],payload.store_totals||[]);
  table(book,'经营明细',['范围','日期','门店','平台','收入','订单数','顾客实付'],payload.rows||[]);
  notes(book,payload);
  return save(book,`门店经营_${payload.start}_${payload.end}`,root);
}
export async function comparisonReport(payload,root){
  const book=new ExcelJS.Workbook();
  const columns=['范围','门店','本期可比收入','上期可比收入','收入差额','收入变化率','本期可比订单','上期可比订单','订单差额','订单变化率','可比平台','状态'];
  const sheet=table(book,'经营对比',columns,payload.rows||[]);
  (payload.rows||[]).forEach((row,i)=>{
    const n=i+2;
    for(const [col,current,previous,value] of [['E','C','D',row['收入差额']],['I','G','H',row['订单差额']]]){
      sheet.getCell(`${col}${n}`).value={formula:`IF(OR(${current}${n}="",${previous}${n}=""),"",${current}${n}-${previous}${n})`,result:value??''};
    }
    for(const [col,diff,previous,value] of [['F','E','D',row['收入变化率']],['J','I','H',row['订单变化率']]]){
      sheet.getCell(`${col}${n}`).value={formula:`IF(OR(${diff}${n}="",${previous}${n}="",${previous}${n}=0),"",${diff}${n}/${previous}${n})`,result:value??''};
    }
  });
  table(book,'原始明细',['期间','范围','日期','门店','平台','收入','订单数','顾客实付'],payload.detail_rows||[]);
  notes(book,payload);
  return save(book,`经营对比_${payload.start}_${payload.end}`,root);
}
export function orderTotals(rows){
  const map=new Map();
  for(const row of rows){
    const fields=['区域','门店','采购渠道','SKU','品名','单位'];
    const key=JSON.stringify(fields.map(k=>row[k]||''));
    if(!map.has(key))map.set(key,{...Object.fromEntries(fields.map(k=>[k,row[k]||''])),'数量':0,'数量缺失记录数':0});
    const group=map.get(key);
    if(typeof row['数量']==='number'&&Number.isFinite(row['数量']))group['数量']+=row['数量'];
    else group['数量缺失记录数']++;
  }
  return [...map.values()].map(row=>({...row,'数量':row['数量缺失记录数']?null:Math.round((row['数量']+Number.EPSILON)*10000)/10000}));
}
export async function orderReport(payload,root){
  const book=new ExcelJS.Workbook();
  table(book,'订货汇总',['区域','门店','采购渠道','SKU','品名','数量','单位','数量缺失记录数'],orderTotals(payload.rows||[]));
  const columns=[...new Set((payload.rows||[]).flatMap(r=>Object.keys(r)))];
  table(book,'订货明细',columns.length?columns:['提交时间','门店','订单号','SKU','品名','数量','单位'],payload.rows||[]);
  const statuses=[...(payload.submitted_stores||[]).map(s=>({'门店':s,'状态':'所选期间已提交'})),...(payload.unsubmitted_stores||[]).map(s=>({'门店':s,'状态':'所选期间未提交'}))];
  if(statuses.length)table(book,'门店订货状态',['门店','状态'],statuses);
  notes(book,payload);
  return save(book,`订货汇总_${payload.region}_${payload.start}_${payload.end}`,root);
}
