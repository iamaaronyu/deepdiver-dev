// Explicit paid acceptance: one bounded comparative task, preserving all results.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium} from '@playwright/test';
const folder='data/business-review/'+new Date().toISOString().replace(/[:.]/g,'-');console.log(JSON.stringify({artifact_folder:folder}));await mkdir(folder,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const context=await browser.newContext({viewport:{width:1536,height:1050}});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8000/');await page.getByText('研究服务在线',{exact:true}).waitFor();
 await page.screenshot({path:folder+'/home.png',fullPage:true});
 await page.getByLabel('研究问题',{exact:true}).fill('为 Python 异步服务选型：TaskGroup 与 asyncio.gather 在子任务异常传播、兄弟任务取消、父任务取消和结果收集上有哪些区别？分析适用边界、迁移注意事项和容易误解的地方，优先使用 Python 官方文档与 PEP，结论请用中文。');
 await page.locator('summary').click();await page.getByLabel('研究轮数',{exact:true}).selectOption('2');
 await page.getByRole('button',{name:'开始研究',exact:true}).click();await page.waitForURL(/\/task\/\?id=[a-f0-9]{32}/);
 const id=new URL(page.url()).searchParams.get('id');console.log(JSON.stringify({id,status:'created',settings:{depth:'deep',rounds:2,budget_usd:.25}}));
 await writeFile(folder+'/task.json',JSON.stringify({id},null,2));
 const get=async suffix=>{const r=await context.request.get('http://127.0.0.1:8000/api/research/'+id+suffix);assert(r.ok());return r.json();};
 let task;let previous='';const until=Date.now()+620000;
 while(Date.now()<until){task=await get('');const marker=task.status+':'+(task.usage.rounds||0);if(marker!==previous){console.log(JSON.stringify({status:task.status,round:task.usage.rounds,model_calls:task.usage.model_call_attempts}));previous=marker;}if(['COMPLETED','FAILED','TIMED_OUT','BUDGET_EXCEEDED','CANCELLED'].includes(task.status))break;await new Promise(r=>setTimeout(r,3000));}
 const material=await get('/evidence');
 const response=await context.request.get('http://127.0.0.1:8000/api/research/'+id+'/report');const report=await response.text();await writeFile(folder+'/report.md',report);
 const result={id,status:task.status,usage:task.usage,claims:material.claims.length,evidence:material.evidence.length,valid_sources:material.sources.filter(s=>s.fetch_status==='FETCHED').length,verification:material.claims.reduce((a,c)=>({...a,[c.verification_status]:(a[c.verification_status]||0)+1}),{}),analysis:report.includes('## 核心判断'),characters:report.length,errors};
 await page.reload();await page.getByRole('tab',{name:'研究报告',exact:true}).click();await page.locator('.markdown h1').waitFor();
 await page.screenshot({path:folder+'/report.png'});
 const citation=page.locator('.markdown a[href^="#evidence-"]').first();if(await citation.count()){const anchor=await citation.getAttribute('href');assert.equal(await page.locator(anchor).count(),1);await citation.click();assert(new URL(page.url()).hash.startsWith('#evidence-'));result.citation_navigation=true;}
 await page.setViewportSize({width:390,height:844});await page.goto('http://127.0.0.1:8000/task/?id='+id);await page.locator('.markdown h1').waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:folder+'/report-mobile.png'});
 await page.goto('http://127.0.0.1:8000/');await page.getByText('研究服务在线',{exact:true}).waitFor();await page.screenshot({path:folder+'/mobile.png',fullPage:true});
 await writeFile(folder+'/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 assert.equal(task.status,'COMPLETED');assert(result.analysis);assert.equal(task.usage.rounds,2);assert(material.claims.length>=5);assert.deepEqual(errors,[]);
}finally{await browser.close();}
