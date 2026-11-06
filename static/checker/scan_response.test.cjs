const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('templates/checker/scan.html','utf8').split('<script>')[1].split('</script>')[0];
function setup(){
 const listeners={};const outcome={innerHTML:'',scrollIntoView(){}};const input={value:''};const form={addEventListener:(name,fn)=>listeners['form:'+name]=fn};input.addEventListener=(name,fn)=>listeners['input:'+name]=fn;
 const requests=[];const context={document:{getElementById:id=>({'outcome':outcome,'manual-code':input,'manual-scan-form':form}[id]),querySelector:()=>{const match=outcome.innerHTML.match(/session=(\d+)/);return match?{value:match[1]}:null;},addEventListener(){}},window:{},navigator:{onLine:true},FormData:class{append(){}},fetch:()=>new Promise(resolve=>requests.push(resolve))};vm.createContext(context);vm.runInContext(source,context);return {context,listeners,outcome,input,requests};
}
async function tick(){await Promise.resolve();await Promise.resolve();}
(async()=>{
 let s=setup();let a=vm.runInContext("postPayload('QR-A')",s.context);let b=vm.runInContext("postPayload('QR-B')",s.context);
 s.requests[1]({text:async()=> 'session=2'});await b;s.requests[0]({text:async()=> 'session=1'});await a;
 assert.equal(s.outcome.innerHTML,'session=2');assert.equal(vm.runInContext('pendingSessionId',s.context),'2');
 s=setup();s.input.value='111111';s.listeners['form:submit']({preventDefault(){}});s.input.value='222222';s.listeners['input:input']();s.listeners['form:submit']({preventDefault(){}});
 s.requests[1]({text:async()=> 'session=2'});await tick();s.requests[0]({text:async()=> 'session=1'});await tick();assert.equal(s.outcome.innerHTML,'session=2');assert.equal(vm.runInContext('pendingSessionId',s.context),'2');
 s=setup();vm.runInContext("postPayload('QR-A')",s.context);s.input.value='222222';s.listeners['input:input']();s.requests[0]({text:async()=> 'session=1'});await tick();assert.equal(s.outcome.innerHTML,'');assert.equal(vm.runInContext('pendingSessionId',s.context),null);
 console.log('Delayed QR/manual responses preserve current payload session: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
