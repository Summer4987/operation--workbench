// 主动推送用模板卡片：企微通知栏/会话列表对 Markdown 只显示"发来了一条消息"，卡片标题可以预览。
// 卡片放不下的长内容，另发一条 Markdown 全文。
const cut=(s,n)=>{s=String(s||'');return s.length>n?s.slice(0,n-1)+'…':s;};

export function noticeCard(text,url){
  const lines=String(text||'').split(/\r?\n/).map(l=>l.trim()).filter(Boolean);
  const head=(lines[0]||'运营通知').replace(/^【(.*)】$/,'$1');
  const desc=lines[1]||'';
  const rest=lines.slice(2).join('\n');
  const card={card_type:'text_notice',main_title:{title:cut(head,26),...(desc?{desc:cut(desc,30)}:{})},
    card_action:{type:1,url:url||'https://139.155.148.169/operation-workbench/'}};
  if(rest)card.sub_title_text=cut(rest,112);
  const complete=head.length<=26&&desc.length<=30&&rest.length<=112;
  return {card,needsFullText:!complete};
}

export async function sendNotice(client,owner,text,{format='card',url}={}){
  const markdown=()=>client.sendMessage(owner,{msgtype:'markdown',markdown:{content:text}});
  if(format!=='card'){await markdown();return 'markdown';}
  const {card,needsFullText}=noticeCard(text,url);
  try{await client.sendMessage(owner,{msgtype:'template_card',template_card:card});}
  catch{await markdown();return 'markdown-fallback';}
  if(needsFullText)await markdown();
  return needsFullText?'card+markdown':'card';
}
