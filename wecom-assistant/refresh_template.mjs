// Run by the operator's installer, not by the background service accessing Desktop.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRIVATE,settings,saveJson} from './core.mjs';
import {inboundTemplate,readInboundTemplate} from './inbound.mjs';
import {updateInboundCatalog} from './inbound-catalog.mjs';
const config=settings();delete config.WECOM_INBOUND_RUNTIME_TEMPLATE;
const source=inboundTemplate(config);
const {book}=await readInboundTemplate(config);
const catalog=updateInboundCatalog(book);
const folder=path.join(PRIVATE,'templates');fs.mkdirSync(folder,{recursive:true,mode:0o700});
const target=path.join(folder,'inbound.xlsx'),tmp=path.join(folder,crypto.randomUUID()+'.xlsx');
try {
  await book.xlsx.writeFile(tmp);fs.chmodSync(tmp,0o600);
  const verified=await readInboundTemplate({WECOM_INBOUND_TEMPLATE:tmp});
  if(verified.catalog.length!==catalog.count)throw Error('更新后商品字典数量不一致');
  fs.renameSync(tmp,target);
} finally { if(fs.existsSync(tmp))fs.unlinkSync(tmp); }
saveJson(path.join(folder,'inbound-source.json'),{source,catalog,refreshed_at:new Date().toISOString(),sha256:crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')});
console.log(`已按${catalog.source}刷新${catalog.count}项商品，原文件保持不变。`);
