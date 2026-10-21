// Explicit realtime sales requests use the official collected snapshot, not model arithmetic.
export function isRealtimeRequest(text){
  if(/入库|预约|实时订货|订货实时/.test(text))return false;
  if(/昨天|前天|上周|最近\s*\d+\s*天|\d{4}-\d{2}-\d{2}/.test(text))return false;
  return (/实时/.test(text)&&/单量|订单|营业|收入|经营/.test(text)) || (/加盟/.test(text)&&/今天|今日|现在/.test(text)&&/单量|订单量|营业额|经营/.test(text)&&!/订货/.test(text));
}
export function realtimeReply(data){
  const count=v=>v==null?'缺失':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:0});
  const title=data.reset?'加盟店采集尚未就绪':data.stale?'加盟店最近一次销售快照（已过期）':'加盟店实时销售单量';
  const lines=[title,`采集时间：${data.generated_at}（北京时间）`, `覆盖：${data.store_count}家门店，${data.platform_store_count}个平台门店`,
    `销售订单合计：${count(data.totals?.['订单数'])}${data.totals?.['订单数']==null?'':'单'}${data.missing_order_rows?'（仅已采集部分）':''}`];
  lines.push(`已验证营业收入合计：${data.totals?.['收入']==null?'缺失':Number(data.totals['收入']).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+'元'}（仅已采集且已验证部分）`);
  for(const row of data.store_totals||[]){
    const platforms=(data.rows||[]).filter(r=>r['门店']===row['门店']).map(r=>`${r['平台']}${count(r['订单数'])}${r['订单数']==null?'':'单'}`).join('，');
    lines.push(`• ${row['门店']}：${count(row['订单数'])}${row['订单数']==null?'':'单'}${row['单量缺失记录数']?'（部分缺失）':''}；${platforms}`);
  }
  for(const error of data.errors||[])lines.push('注意：'+error);
  lines.push('以上为最近一次已采集的门店销售单量，非订货量；本次查询不触发平台刷新。');
  return lines.join('\n');
}
