// Read-only local renderer health probe. Never navigates, evaluates JS or submits.
const [endpoint,rawTimeout]=process.argv.slice(2);
let url;try{url=new URL(endpoint);}catch{process.exit(64);}
if(url.protocol!=='ws:'||url.hostname!=='127.0.0.1'||url.port!=='9222'||!/^\/devtools\/page\/[a-fA-F0-9]+$/.test(url.pathname))process.exit(64);
let open=false,done=false;
const finish=value=>{if(done)return;done=true;process.stdout.write(JSON.stringify(value),()=>process.exit(0));};
const ws=new WebSocket(url);
const timer=setTimeout(()=>finish({responsive:open?false:null,phase:open?'renderer':'transport'}),Math.min(5000,Math.max(100,Number(rawTimeout)||1800)));
ws.addEventListener('open',()=>{open=true;ws.send(JSON.stringify({id:1,method:'Page.getFrameTree'}));});
ws.addEventListener('message',event=>{try{const d=JSON.parse(event.data);if(d.id===1){clearTimeout(timer);finish({responsive:d.result?true:null,phase:'renderer'});}}catch{}});
ws.addEventListener('error',()=>{clearTimeout(timer);finish({responsive:null,phase:'transport'});});
