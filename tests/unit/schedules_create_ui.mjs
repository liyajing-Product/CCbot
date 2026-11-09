// Real create/confirm UI, synthetic transport: no account or reminder side effects.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.value='';this.open=false}
  append(...nodes){this.children.push(...nodes.filter(Boolean))}
  replaceChildren(...nodes){this.children=[];this.append(...nodes)}
  addEventListener(key,fn){this.events[key]=fn}
  setAttribute(key,value){this[key]=value}
  querySelectorAll(tag){return this.children.flatMap(node=>[...(node.tag===tag?[node]:[]),...node.querySelectorAll(tag)])}
  focus(){}
  showModal(){this.open=true}
  close(){this.open=false;this.events.close?.()}
  get textContent(){return (this.text||'')+this.children.map(n=>n.textContent||'').join('')}
  set textContent(value){this.text=value;this.children=[]}
}
const h=(tag,props={},children=[])=>{const el=new Element(tag);for(const [k,v] of Object.entries(props)){if(k==='onClick')el.events.click=v;else el[k]=v}el.append(...children);return el};
const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id)};
const body=$('schedulesBody');
let proposed=[],confirmed=[],listed=[],resolveProposal;
const preview={name:'合成提醒',job_kind:'medication',tz:'Asia/Shanghai',trigger:{type:'cron',expr:'15 8 * * *'},next_run_at:'2030-01-01T00:15:00Z',delivery:'in_app',prompt_text:'合成内容'};
const api={schedules:async()=>({data:{schedules:listed,stats:{run_count:0,success_count:0,fail_count:0},tz:'Asia/Shanghai',scheduler:{enabled:true,alive:true}}}),
 proposeSchedule:async payload=>{proposed.push(payload);return new Promise(resolve=>{resolveProposal=()=>resolve({data:{proposal:{id:'synthetic',operation:'create',preview:{...preview,...payload}}}})})},
 decideSchedule:async(id,value)=>{confirmed.push(value);if(value)listed=[{...preview,id:1,status:'active'}];return {data:{status:value?'confirmed':'rejected'}}}};
const ctx=vm.createContext({h,$,api,toast(){},friendlyError:e=>({text:e.message})});
vm.runInContext(fs.readFileSync('static/js/schedules.js','utf8').replace(/^import .*;\n/gm,'').replace(/^export /gm,''),ctx);
ctx.initSchedules();
await $('btnSchedules').events.click();
assert.equal($('schedulesTitle').textContent,'用药与日程');
assert(body.textContent.includes('阿哦～您还有没有建立日程，暂无日程信息'));
assert.equal(body.querySelectorAll('img')[0].src,'/static/images/capsule-schedule-empty.svg');
assert.equal(body.querySelectorAll('form').length,0,'empty view must not force a form');
await body.querySelectorAll('button').find(node=>node.textContent==='新建提醒').events.click();
assert($('schedulesPanel').open);
assert.equal($('schedulesTitle').textContent,'新建提醒');
assert(!body.textContent.includes('返回'));
const fields=()=>[...body.querySelectorAll('input'),...body.querySelectorAll('select'),...body.querySelectorAll('textarea')];
const field=label=>fields().find(node=>node['aria-label']===label);
field('提醒名称').value='合成提醒';field('每日提醒时间').value='08:15';
const form=body.querySelectorAll('form')[0];
const pending=form.events.submit({preventDefault(){}});
form.events.submit({preventDefault(){}});
assert.equal(proposed.length,1,'double submit must not create duplicate proposals');
assert.equal(proposed[0].trigger.expr,'15 8 * * *');assert.equal(proposed[0].tz,'Asia/Shanghai');
assert.equal(confirmed.length,0,'form submission only proposes, never approves');
resolveProposal();await pending;
assert(body.textContent.includes('每天 08:15'));
assert.equal($('schedulesTitle').textContent,'核对提醒');
const findButton=text=>body.querySelectorAll('button').find(node=>node.textContent===text);
body.querySelectorAll('button').find(node=>node['aria-label']==='修改提醒').events.click();
assert.equal(field('提醒名称').value,'合成提醒','editing a preview must retain the form');
assert(!body.textContent.includes('返回'));
const edited=body.querySelectorAll('form')[0].events.submit({preventDefault(){}});
resolveProposal();await edited;
await findButton('确认创建').events.click();
assert.deepEqual(confirmed,[true]);assert(body.textContent.includes('合成提醒'));
assert(body.textContent.includes('每天 08:15'),'list must directly show the saved reminder time');
assert.equal(body.querySelectorAll('img').length,0,'saved schedules must replace the empty illustration');
assert.equal($('schedulesTitle').textContent,'用药与日程');
await ctx.openScheduleCreate();
field('提醒类型').value='one_shot_reminder';field('提醒类型').events.change();
assert.equal(field('每日提醒时间').required,false);assert.equal(field('日程日期和时间').required,true);
field('提醒名称').value='合成日程';field('日程日期和时间').value='2030-02-01T15:30';
const once=body.querySelectorAll('form')[0].events.submit({preventDefault(){}});
assert.equal(proposed.at(-1).trigger.type,'once');assert.equal(proposed.at(-1).trigger.run_at,'2030-02-01T15:30');
resolveProposal();await once;
await findButton('取消').events.click();assert.deepEqual(confirmed,[true,false]);
console.log('Passed medication/one-shot form, preview before confirm, duplicate-submit guard, cancel and list refresh.');
