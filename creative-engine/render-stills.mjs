import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-core';
const root=path.resolve(process.argv[2]||'.');
const items=JSON.parse(fs.readFileSync(path.join(root,'content.json'),'utf8'));
const candidates=['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/usr/bin/chromium','/usr/bin/chromium-browser','/usr/bin/google-chrome'];
const executablePath=process.env.CML_CHROMIUM||candidates.find(p=>fs.existsSync(p));
if(!executablePath)throw new Error('Defina CML_CHROMIUM com o caminho de um Chrome/Chromium instalado.');
const browser=await chromium.launch({executablePath,headless:true});
const page=await browser.newPage({viewport:{width:1080,height:1350},deviceScaleFactor:1});
const findings=[];
for(const item of items.filter(x=>x.slides)){
 for(let i=0;i<item.slides.length;i++){
  const name=`${item.id}-${i+1}`;
  await page.goto(`file://${root}/${name}.html`);await page.evaluate(()=>document.fonts.ready);
  // Keep the approved hierarchy while fitting variable copy. Never clip or ellipsize words.
  await page.evaluate(()=>{
    const footer=document.querySelector('.footer').getBoundingClientRect();
    for(let pass=0;pass<7;pass++){
      const prose=[...document.querySelectorAll('h1,h2,.body,.accent,.small,.note,.step p,.location p')];
      if(!prose.some(x=>x.getBoundingClientRect().bottom>footer.top-16))break;
      for(const el of prose){
        if(getComputedStyle(el).position==='absolute')continue;
        const style=getComputedStyle(el),size=parseFloat(style.fontSize),floor=el.tagName==='H1'?60:el.tagName==='H2'?34:el.classList.contains('small')?22:26;
        if(size>floor)el.style.fontSize=Math.max(floor,size-5)+'px';
        const margin=parseFloat(style.marginTop);if(margin>28)el.style.marginTop=Math.max(28,margin-18)+'px';
      }
      const list=document.querySelector('.step-list');if(list){const margin=parseFloat(getComputedStyle(list).marginTop);list.style.marginTop=Math.max(30,margin-12)+'px';}
    }
  });
  const bad=await page.evaluate(()=>[...document.querySelectorAll('h1,h2,.body,.accent,.small,.note,.step p,.location p')].flatMap(el=>{
   const r=el.getBoundingClientRect();const footer=document.querySelector('.footer').getBoundingClientRect();
   return r.right>1080||r.left<0||r.bottom>footer.top-10?[{text:el.textContent,bottom:r.bottom,footer:footer.top,right:r.right}]:[];
  }));
  if(bad.length)findings.push({name,bad});
  await page.screenshot({path:path.join(root,'exports',name+'.jpg'),type:'jpeg',quality:96});
 }
}
await browser.close();
fs.writeFileSync(path.join(root,'exports','layout-check.json'),JSON.stringify(findings,null,2));
console.log(JSON.stringify({rendered:items.reduce((n,x)=>n+(x.slides?.length||0),0),findings}));
if(findings.length)process.exitCode=1;
