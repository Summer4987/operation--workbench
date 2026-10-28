"use strict";
const $=id=>document.getElementById(id);
const names={meituan:"美团","taobao-shangou":"淘宝闪购"};
let current=null,requestId=0;
const accepted=r=>["visually_accepted","ocr_verified"].includes(r.status);
function element(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function read(url){const r=await fetch(url,{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw Error(`读取失败（${r.status}），请确认已登录看板`);return r.json();}
function safeImage(value){return typeof value==="string"&&/^images\/\d{4}-\d{2}-\d{2}\/(meituan|taobao-shangou)\/[a-f0-9]{64}\.png$/.test(value);}
function render(){
 if(!current)return;
 const rows=current.records.filter(r=>(!$("city").value||r.city===$("city").value)&&(!$("platform").value||r.platform===$("platform").value));
 const completed=rows.filter(accepted).length;
 const images=rows.reduce((sum,r)=>sum+(r.images||[]).length,0);
 const cities=[...new Set(rows.map(r=>r.city))];
 $("updated").textContent=`采集日期 ${current.date} · 发布于 ${current.published_at}（北京时间）`;
 $("message").textContent="历史采集记录 · 自动采集已停用，缺失项不再补采或提醒。";
 $("summary").replaceChildren();
 for(const [label,value,sub] of [["已完成",`${completed}/${rows.length}`,"店铺 × 平台"],["已核验原图",images,"张"],["本批次门店",new Set(rows.map(r=>r.city+r.store)).size,cities.join("、")||"无记录"],["历史缺失",rows.length-completed,"任务已停用 · 无需处理"]]){const box=element("div",undefined,"metric");box.append(element("span",label),element("strong",value),element("span",sub));$("summary").append(box);}
 $("results").replaceChildren();
 for(const key of [...new Set(rows.map(r=>`${r.city}\n${r.store}`))]){
  const group=rows.filter(r=>`${r.city}\n${r.store}`===key),section=element("article",undefined,"store"),head=element("div",undefined,"store-head");head.append(element("h2",group[0].store),element("span",group[0].city));section.append(head);const panels=element("div",undefined,"platforms");
  for(const row of group){const panel=element("section",undefined,"panel"),bar=element("div",undefined,"panel-head");bar.append(element("h3",names[row.platform]||row.platform),element("span",row.status==="ocr_verified"?"OCR自动核验":row.status==="visually_accepted"?"两图已复核":row.status_label||"待处理",`badge ${accepted(row)?"ok":"warn"}`));panel.append(bar,element("p",row.captured_at?`采集于 ${row.captured_at}`:"尚无合格原图","capture-time"));
   if(row.status==="ocr_verified")panel.append(element("p","自动核验，未人工逐图复核","capture-time"));
   if(row.reason)panel.append(element("p",row.reason,"reason"));const shots=element("div",undefined,"shots");
   for(const shot of row.images||[]){if(!safeImage(shot.url))continue;const figure=element("figure"),a=element("a"),img=element("img");a.href=shot.url;a.target="_blank";a.rel="noopener";img.src=shot.url;img.alt=`${row.store} ${names[row.platform]} ${shot.label}`;img.loading="lazy";a.append(img);figure.append(a,element("figcaption",shot.label+" · 点击查看原图"));shots.append(figure);}panel.append(shots);panels.append(panel);
  }section.append(panels);$("results").append(section);
 }
 if(!rows.length)$("results").append(element("p","所选范围没有已发布记录。"));
 $("notes").replaceChildren(...(current.notes||[]).map(n=>element("li",n)));
}
async function loadDate(){const id=++requestId;try{const data=await read(`data/${$("date").value}.json`);if(id!==requestId)return;current=data;const selected=$("city").value;$("city").replaceChildren(new Option("全部城市",""),...[...new Set(data.records.map(r=>r.city))].map(c=>new Option(c,c)));if([...$("city").options].some(o=>o.value===selected))$("city").value=selected;render();}catch(e){$("message").textContent=e.message;}}
async function init(){try{const selected=$("date").value||new URLSearchParams(location.search).get("date"),catalog=await read("data/index.json");$("date").replaceChildren(...catalog.dates.map(d=>new Option(d,d)));if(catalog.dates.includes(selected))$("date").value=selected;if(!catalog.dates.length){$("updated").textContent="尚无已发布结果";return;}await loadDate();}catch(e){$("message").textContent=e.message;$("updated").textContent="结果暂未加载";}}
$("date").addEventListener("change",loadDate);$("city").addEventListener("change",render);$("platform").addEventListener("change",render);$("refresh").addEventListener("click",init);init();
