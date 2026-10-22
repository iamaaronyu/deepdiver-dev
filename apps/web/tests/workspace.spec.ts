import {test,expect,Page} from '@playwright/test';
const id='a'.repeat(32);
const created='2026-10-22T00:00:00+08:00';
const settings={max_rounds:1,max_search_requests:6,max_sources_per_query:5,timeout_seconds:180,max_budget_usd:.25};
const task={id,question:'What is asyncio used for?',status:'COMPLETED',created_at:created,updated_at:created,cancel_requested:false,error_message:null,config:settings,usage:{duration_seconds:10,search_requests:1,model_call_attempts:3,input_tokens:100,output_tokens:50}};
const empty={claims:[],sources:[],evidence:[],subtasks:[]};
async function mock(page:Page,report='# Research report\n\nStored evidence report.'){
 await page.route('**/api/**',async route=>{const url=new URL(route.request().url());const path=url.pathname;
  if(path==='/api/health')return route.fulfill({json:{status:'ok',stage:'4',model_configured:true,search_configured:true,worker_running:true}});
  if(path==='/api/research/summary')return route.fulfill({json:{total:1,running:0,completed:1,stopped:0}});
  if(path==='/api/research'&&route.request().method()==='POST')return route.fulfill({status:202,json:{...task,status:'CREATED'}});
  if(path==='/api/research')return route.fulfill({headers:{'X-Total-Count':'1'},json:[task]});
  if(path.endsWith('/events'))return route.fulfill({contentType:'text/event-stream',body:'id: 1\nevent: task.status\ndata: '+JSON.stringify({id:1,type:'task.status',created_at:created,data:{status:'COMPLETED'}})+'\n\nevent: stream.end\ndata: {"status":"COMPLETED","cursor":1}\n\n'});
  if(path.endsWith('/evidence'))return route.fulfill({json:empty});
  if(path.endsWith('/report'))return route.fulfill({contentType:'text/markdown',body:report});
  if(path.endsWith('/cancel'))return route.fulfill({json:{...task,status:'CREATED',cancel_requested:true}});
  return route.fulfill({json:task});
 });
}

test('home starts a task with explicit settings and restores its report',async({page})=>{
 await mock(page);await page.goto('/');await expect(page.getByRole('heading',{name:'让研究，支撑下一步决策。'})).toBeVisible();
 await expect(page.getByText('研究服务在线',{exact:true})).toBeVisible();
 await page.getByLabel('研究问题',{exact:true}).fill('What is asyncio used for?');
 await page.locator('summary').click();await page.getByLabel('研究轮数',{exact:true}).selectOption('1');
 await page.getByLabel('最长时间（秒）',{exact:true}).fill('180');
 await page.getByLabel('每次候选来源数',{exact:true}).fill('10');
 const submitted=page.waitForRequest(request=>request.url().endsWith('/api/research')&&request.method()==='POST');
 await page.getByRole('button',{name:'开始研究'}).click();
 const request=await submitted;expect(request.postDataJSON().question).toBe('What is asyncio used for?');
 expect(request.postDataJSON().settings.max_budget_usd).toBe(.25);
 expect(request.postDataJSON().settings.max_rounds).toBe(1);
 expect(request.postDataJSON().settings.max_sources_per_query).toBe(10);
 await expect(page).toHaveURL(new RegExp('/task/\\?id='+id));
 await expect(page.getByRole('heading',{name:'Research report',exact:true})).toBeVisible();
 await page.reload();await expect(page.getByRole('heading',{name:'Research report',exact:true})).toBeVisible();
 await page.getByRole('tab',{name:'研究进展'}).click();await expect(page.locator('.event-list li')).toHaveCount(1);
});

test('history opens stored tasks and sends server-side filters',async({page})=>{
 await mock(page);await page.goto('/history/');await expect(page.getByRole('link',{name:/What is asyncio/})).toBeVisible();
 const request=page.waitForRequest(request=>request.url().includes('status=running'));
 await page.getByRole('button',{name:'进行中',exact:true}).click();await request;
 await page.getByRole('link',{name:/What is asyncio/}).click();
 await expect(page.getByRole('heading',{name:'Research report',exact:true})).toBeVisible();
});

test('untrusted Markdown cannot run HTML, script URLs, or remote images',async({page})=>{
 await mock(page,'# Safe report\n<script>window.__unsafe=1</script>\n<img src="https://tracker.invalid/x" onerror="window.__unsafe=1">\n\n[unsafe](javascript:alert(1))\n[reference](https://example.com/)');
 await page.goto('/task/?id='+id);
 await expect(page.getByRole('heading',{name:'Safe report'})).toBeVisible();
 expect(await page.locator('.markdown script,.markdown img').count()).toBe(0);
 expect(await page.locator('.markdown a[href^="javascript:"]').count()).toBe(0);
 expect(await page.evaluate(()=>(' __unsafe' in window)||Boolean((window as unknown as Record<string,unknown>).__unsafe))).toBe(false);
 const link=page.getByRole('link',{name:'reference',exact:true});await expect(link).toHaveAttribute('rel','noopener noreferrer');
});

test('mobile layout stays within the viewport',async({page})=>{
 await page.setViewportSize({width:390,height:844});await mock(page);await page.goto('/');
 await expect(page.getByRole('button',{name:'开始研究'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.goto('/task/?id='+id);await expect(page.getByRole('heading',{name:'Research report',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test('invalid task link has an actionable error',async({page})=>{
 await mock(page);await page.goto('/task/?id=invalid');
 await expect(page.getByRole('alert').filter({hasText:'任务链接不完整'})).toContainText('任务链接不完整');
 await expect(page.getByRole('link',{name:'← 研究记录'})).toBeVisible();
});

test('research depth presets submit bounded settings and citations navigate within report',async({page})=>{
 await mock(page,'# Analysis report\n\n## 核心判断\n\n有依据的分析 [证据 1](#evidence-1)。\n\n## 证据附录\n\n### 证据 1：原始主张\n\n实际来源摘录。');
 await page.goto('/');
 await expect(page.getByRole('button',{name:/深度研究/})).toHaveAttribute('aria-pressed','true');
 await page.getByRole('button',{name:/标准研究/}).click();
 await page.getByLabel('研究问题',{exact:true}).fill('Compare evidence');
 const request=page.waitForRequest(request=>request.url().endsWith('/api/research')&&request.method()==='POST');
 await page.getByRole('button',{name:'开始研究',exact:true}).click();
 expect((await request).postDataJSON().settings).toMatchObject({depth:'standard',max_rounds:1,timeout_seconds:180,max_budget_usd:.25});
 await expect(page.getByRole('heading',{name:'Analysis report'})).toBeVisible();
 await page.getByRole('navigation',{name:'报告目录'}).getByRole('link',{name:'核心判断'}).click();
 await expect(page).toHaveURL(/#section-0$/);
 const citation=page.locator('.markdown').getByRole('link',{name:'证据 1',exact:true});
 expect(await citation.getAttribute('target')).toBeNull();
 await citation.click();await expect(page).toHaveURL(/#evidence-1$/);
 await expect(page.locator('#evidence-1')).toContainText('原始主张');
});
