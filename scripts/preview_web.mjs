import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
await mkdir('data/ui-preview',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('http://127.0.0.1:8000/');
 await page.getByText('研究服务在线',{exact:true}).waitFor();
 await page.getByText('全部研究',{exact:true}).waitFor();
 await page.screenshot({path:'data/ui-preview/home.png',fullPage:true});
 await page.goto('http://127.0.0.1:8000/task/?id=9247aced17d24589b025ba1a9b6e3f1d');
 await page.getByRole('heading',{name:'DeepDive 研究报告',exact:true}).waitFor();
 await page.screenshot({path:'data/ui-preview/report.png'});
 await page.getByRole('tab',{name:'研究进展'}).click();
 await page.locator('.event-list li').first().waitFor();
 await page.screenshot({path:'data/ui-preview/progress.png'});
 await page.setViewportSize({width:390,height:844});await page.goto('http://127.0.0.1:8000/');
 await page.getByText('研究服务在线',{exact:true}).waitFor();
 await page.screenshot({path:'data/ui-preview/mobile.png',fullPage:true});
 console.log(JSON.stringify({screenshots:['home','report','progress','mobile'],pageErrors:errors}));
}finally{await browser.close();}
