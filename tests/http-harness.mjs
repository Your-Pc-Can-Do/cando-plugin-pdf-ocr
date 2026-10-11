import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import readline from 'node:readline';
import {createRequire} from 'node:module';
export async function openHarness(plugin, slug, source, options={}) {
 const client=process.env.CANDO_CLIENT_DIR;assert(client,'Set CANDO_CLIENT_DIR');
 const {chromium,expect}=createRequire(path.join(client,'package.json'))('@playwright/test');
 const out=process.env.CANDO_TEST_OUTPUT_DIR||path.join(client,'.test-data','stage4-'+slug);await fs.mkdir(out,{recursive:true});
 const python=options.python||path.join(client,'runtime/python.exe'),token='synthetic-browser-token';
 const launch="import sys,runpy;sys.path[:0]=[sys.argv[1],sys.argv[2]];runpy.run_path(sys.argv[2]+'/main.py',run_name='__main__')";
 const be=spawn(python,['-I','-u','-B','-X','utf8','-c',launch,path.join(client,'sdk/python'),plugin],{env:{...process.env,CANDO_PORT:'0',CANDO_TOKEN:token,LOCALAPPDATA:path.join(out,'appdata'),...options.env},windowsHide:true});
 let stderr='';be.stderr.on('data',data=>stderr+=data);const rl=readline.createInterface({input:be.stdout});
 const ready=JSON.parse((await Promise.race([once(rl,'line'),once(be,'exit').then(()=>{throw Error(stderr)})]))[0]);
 const base=`http://127.0.0.1:${ready.port}`;
 const call=async(route,value)=>{const response=await fetch(base+route,{method:value===undefined?'GET':'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});assert.equal(response.status,200,await response.clone().text());return response.json();};
 const refs=new Map();let refCounter=0;const calls=[];
 async function register(file){let ref=[...refs].find(([,value])=>value===file)?.[0];if(!ref){ref='fixture-'+(++refCounter);refs.set(ref,file);}return {fileRef:ref,path:file,name:path.basename(file),size:(await fs.stat(file)).size};}
 const input=await register(source);
 const server=http.createServer(async(req,res)=>{try{
  const url=new URL(req.url,'http://local');
  if(url.pathname==='/'){res.setHeader('Content-Type','text/html');res.end(`<!doctype html><iframe sandbox="allow-scripts" src="/ui/index.html" style="width:1100px;height:900px"></iframe><script>window.lang='en';window.addEventListener('message',async event=>{const m=event.data;if(m.channel!=='cando.http.v1')return;const send=value=>event.source.postMessage({channel:m.channel,...value},'*');if(m.type==='ready')send({type:'init',context:{apiBase:${JSON.stringify(base)},token:${JSON.stringify(token)},instanceId:'fixture-instance',pluginId:'fixture',language:window.lang,theme:'dark'}});if(m.type==='host-request'){try{send({type:'host-response',id:m.id,result:await fixtureHost(m)});}catch(error){send({type:'host-response',id:m.id,error:error.message});}}});</script>`);return;}
  if(url.pathname.startsWith('/files/')){const filename=refs.get(url.pathname.split('/').at(-1));assert(filename);const bytes=await fs.readFile(filename);res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Accept-Ranges','bytes');res.setHeader('Content-Type',mime(filename));let start=0,end=bytes.length-1;const range=/bytes=(\d+)-(\d*)/.exec(req.headers.range||'');if(range){start=Number(range[1]);end=Math.min(range[2]?Number(range[2]):end,end);res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${bytes.length}`);}res.setHeader('Content-Length',end-start+1);res.end(req.method==='HEAD'?undefined:bytes.subarray(start,end+1));return;}
  const target=url.pathname.endsWith('_cando/sdk.js')?path.join(client,'sdk/ui/cando-http.js'):path.join(plugin,url.pathname);res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Content-Type',mime(target));res.end(await fs.readFile(target));
 }catch(error){res.statusCode=404;res.end(String(error));}});
 function mime(filename){return ({'.js':'text/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.png':'image/png','.jpg':'image/jpeg','.gif':'image/gif','.mp4':'video/mp4','.txt':'text/plain'})[path.extname(filename)]||'application/octet-stream';}
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.exposeFunction('fixtureHost',async message=>{calls.push(message);switch(message.method){case 'files.pick':return [input];case 'files.pickFolder':return out;case 'files.save':return path.join(out,'edited.txt');case 'files.register':return register(message.params.path);case 'files.url':assert(refs.has(message.params.fileRef));return origin+'/files/'+message.params.fileRef;case 'files.release':refs.delete(message.params.fileRef);return null;default:return null;}});
 await page.goto(origin);const frame=page.frameLocator('iframe');
 return {page,frame,call,out,calls,errors,expect,source,refs,async reload(language='en'){await page.evaluate(language=>{window.lang=language;document.querySelector('iframe').src='/ui/index.html?return='+Date.now();},language);},async close(report){const errorText=await frame.locator('#error').textContent().catch(()=>'');await browser.close();await call('/.cando/shutdown',{}).catch(()=>{});if(be.exitCode===null)await once(be,'exit');await new Promise(resolve=>server.close(resolve));await fs.writeFile(path.join(out,'ui-report.json'),JSON.stringify({...report,stderr,errorText,errors,limitations:['Native file dialogs, file registration, clipboard and Explorer are host mocks. The SDK, opaque iframe, direct HTTP backend, OCR and preview file reads are real.']},null,2));}};
}
