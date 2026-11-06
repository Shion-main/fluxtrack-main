const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('static/checker/offline_queue.js', 'utf8');
function browser(owner, records, response) {
  let posts = [];
  const bannerClasses=new Set(['hidden']);const timers=[];
  const elements = { 'offline-banner': {classList:{remove(value){bannerClasses.delete(value);},add(value){bannerClasses.add(value);}}}, 'offline-banner-text': {classList:{remove(){},add(){}},textContent:''} };
  const db = {transaction(){const tx={};tx.objectStore=()=>({getAll(){const req={};queueMicrotask(()=>req.onsuccess());req.result=records;return req;},put(record){records.push(record);queueMicrotask(()=>tx.oncomplete());},delete(id){records.splice(records.findIndex(r=>r.client_uuid===id),1);queueMicrotask(()=>tx.oncomplete());}});return tx;}};
  const window = {indexedDB:{open(){const req={result:db};queueMicrotask(()=>req.onsuccess());return req;}},crypto:{randomUUID:()=> 'new-id'},addEventListener(){}};
  const context={window,document:{documentElement:{getAttribute:()=>owner,hasAttribute:()=>false},getElementById:id=>elements[id],readyState:'loading',addEventListener(){},cookie:''},localStorage:{setItem(){},removeItem(){}},navigator:{onLine:true},fetch:async(url,options)=>{posts.push(JSON.parse(options.body));if(response==='fail')throw Error('offline');return {ok:true,json:async()=>({results:typeof response==='function'?response(posts.at(-1).items):[{uuid:'owned',status:'applied'},{uuid:'foreign',status:'applied'}]})};},setTimeout(fn,delay){timers.push({fn,delay});},Promise,Date,Math};
  vm.runInNewContext(code, context);
  return {queue:window.FluxTrackOfflineQueue,posts,records,elements,bannerClasses,timers};
}
(async()=>{
  let state=browser('1',[{client_uuid:'owned',owner_id:'1'},{client_uuid:'foreign',owner_id:'2'},{client_uuid:'legacy'}]);
  await state.queue.drain();
  assert.equal(state.posts[0].items.length,1);
  assert.equal(state.posts[0].items[0].owner_id,'1');
  assert.deepEqual(state.records.map(r=>r.client_uuid),['foreign','legacy']);
  state=browser('1',[{client_uuid:'owned',owner_id:'1'}],'fail');
  await state.queue.drain();assert.equal(state.records.length,1);
  state=browser('2',[]);await state.queue.enqueue({payload:'123456',action:'verified'});assert.equal(state.records[0].owner_id,'2');
  state=browser('',[{client_uuid:'owned',owner_id:'1'}]);await state.queue.drain();assert.equal(state.posts.length,0);
  state=browser('1',Array.from({length:501},(_,i)=>({client_uuid:'id-'+i,owner_id:'1'})),items=>items.map(r=>({uuid:r.client_uuid,status:'applied'})));
  await Promise.all([state.queue.drain(),state.queue.drain()]);assert.equal(state.posts.length,2);assert.equal(state.records.length,0);
  state=browser('1',Array.from({length:501},(_,i)=>({client_uuid:'id-'+i,owner_id:'1'})),items=>items.map(r=>({uuid:r.client_uuid,status:r.client_uuid==='id-500'?'applied':'rejected'})));
  await state.queue.drain();assert.equal(state.posts.length,2);assert.equal(state.records.length,500);
  state=browser('1',[{client_uuid:'owned',owner_id:'1'}],items=>items.map(r=>({uuid:r.client_uuid,status:'flagged'})));
  await state.queue.drain();await Promise.resolve();assert.equal(state.records.length,0);assert.equal(state.bannerClasses.has('hidden'),false);assert.match(state.elements['offline-banner-text'].textContent,/sent to IFO/);assert.equal(state.timers[0].delay,6000);
  state.timers[0].fn();for(let i=0;i<8;i++) await Promise.resolve();assert.equal(state.bannerClasses.has('hidden'),true);
  console.log('Offline queue ownership, quarantine, failure preservation: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
