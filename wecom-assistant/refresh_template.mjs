// Run by the operator's installer, not by the background service accessing Desktop.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRIVATE,settings,saveJson} from './core.mjs';
import {inboundTemplate,readInboundTemplate} from './inbound.mjs';
const config=settings();delete config.WECOM_INBOUND_RUNTIME_TEMPLATE;
const source=inboundTemplate(config);
await readInboundTemplate(config);
const folder=path.join(PRIVATE,'templates');fs.mkdirSync(folder,{recursive:true,mode:0o700});
const target=path.join(folder,'inbound.xlsx'),tmp=path.join(folder,crypto.randomUUID()+'.xlsx');
fs.copyFileSync(source,tmp);fs.chmodSync(tmp,0o600);fs.renameSync(tmp,target);
saveJson(path.join(folder,'inbound-source.json'),{source,refreshed_at:new Date().toISOString(),sha256:crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')});
console.log('已刷新服务私密目录中的入库模板副本，原文件保持不变。');
