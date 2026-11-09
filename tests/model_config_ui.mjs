// Run the actual toast and model-save UI functions against a synthetic clock/API.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const core=fs.readFileSync('static/js/core.js','utf8');
const drawer=fs.readFileSync('static/js/drawer.js','utf8');
const scheduled=[];
const notifications=[];
const wrap={appendChild(node){notifications.push(node)}};
let resolveSave,rejectSave;
const ctx=vm.createContext({
  $:()=>wrap,
  h:(tag,props)=>({...props,removed:false,remove(){this.removed=true}}),
  window:{setTimeout(fn,delay){scheduled.push({fn,delay})}},
  model:{config:{model:'old'},saving:false,error:''},
  api:{saveModelConfig:()=>new Promise((resolve,reject)=>{resolveSave=resolve;rejectSave=reject})},
  renderModelConfig(){},
  friendlyError:err=>({text:err.message}),
});
vm.runInContext(core.slice(core.indexOf('export function toast('),core.indexOf('export async function copyText(')).replace('export ',''),ctx);
vm.runInContext(drawer.slice(drawer.indexOf('async function saveModel('),drawer.indexOf('async function deleteModel(')),ctx);
let pending=ctx.saveModel('custom','https://synthetic.test/v1','test-model','synthetic-key');
assert.equal(ctx.model.saving,true);
assert.equal(notifications.length,0,'pending verification must not announce success');
resolveSave({data:{configured:true,model:'test-model'}});await pending;
assert.equal(ctx.model.saving,false);
assert.match(notifications[0].text,/配置成功/);
assert.equal(scheduled[0].delay,1500);
assert.equal(notifications[0].removed,false);scheduled[0].fn();assert.equal(notifications[0].removed,true);
pending=ctx.saveModel('custom','https://synthetic.test/v1','bad-model','synthetic-key');
rejectSave(new Error('API Key 无效或没有访问权限'));await pending;
assert.equal(ctx.model.config.model,'test-model','failure must not replace the current config');
assert.match(notifications[1].class,/is-error/);
assert.match(notifications[1].text,/配置失败.*Key 无效/);
assert.equal(scheduled[1].delay,3000);
scheduled[1].fn();assert.equal(notifications[1].removed,true);
console.log('Model tips: verified success only, 1500 ms success, safe failure reason, 3000 ms error.');
