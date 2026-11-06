const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/views.py','utf8').split('SW_JS = r"""')[1].split('"""')[0];
const handlers={};let writes=0;let fetches=0;let deleted=[];
const caches={open:async()=>({put:async()=>{writes++;}}),match:async()=>({offline:true}),keys:async()=>['fluxtrack-shell-v6','fluxtrack-private-v1','other-app'],delete:async key=>deleted.push(key)};
let response={ok:true,type:'basic',redirected:false,headers:{get:()=> 'private, no-store'},clone(){return this;}};
const self={addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting(){},clients:{claim(){}},location:{origin:'https://example.test'}};
vm.runInNewContext(source,{self,caches,URL,location:self.location,fetch:async()=>{fetches++;return response;},Promise});
function event(path,mode='cors'){return {request:{url:'https://example.test'+path,method:'GET',mode},respondWith(p){this.result=p;},waitUntil(p){this.result=p;}};}
(async()=>{
 let e=event('/checker/floor');handlers.fetch(e);assert.equal(e.result,undefined);assert.equal(fetches,0);
 e=event('/static/app.js');handlers.fetch(e);await e.result;await Promise.resolve();assert.equal(writes,0);
 response={...response,headers:{get:()=> 'public,max-age=300'}};e=event('/static/app.js');handlers.fetch(e);await e.result;await Promise.resolve();assert.equal(writes,1);
 e=event('/checker/floor','navigate');handlers.fetch(e);await e.result;assert.equal(writes,1);
 e=event('/static/app.js?private=1');handlers.fetch(e);assert.equal(e.result,undefined);
 e=event('/activate');handlers.activate(e);await e.result;assert.deepEqual(deleted,['fluxtrack-shell-v6','fluxtrack-private-v1']);
 console.log('Service worker private route/response exclusion and legacy eviction: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
