/* Navegação compartilhada entre os dashboards da Dra Monica + assinatura Sobé.
   Incluído no fim de todas as páginas (<script src="nav.js"></script>).
   DM_NAV é regravado pelo gerador_perpetuo.py a cada execução. */
const DM_NAV = {"menu": "index.html", "itens": [{"grupo": "", "label": "Perpétuo · POPList", "href": "perpetuo.html", "cor": "#7c3aed"}, {"grupo": "Lançamentos", "label": "RDC04 · Outubro", "href": "RDC04.html", "cor": "#059669"}, {"grupo": "Lançamentos", "label": "RDC03 · Agosto", "href": "RDC03.html", "cor": "#0ea5e9"}, {"grupo": "Lançamentos", "label": "RDC02 · Maio", "href": "RDC02.html", "cor": "#f59e0b"}, {"grupo": "Lançamentos", "label": "RDC01 · Março", "href": "RDC01.html", "cor": "#94a3b8"}, {"grupo": "Consolidado", "label": "Geral", "href": "geral.html", "cor": "#cbd5e1"}]};

(function(){
  const here=(location.pathname.split('/').pop()||'index.html');
  const css=`
  .dmn-nav{padding:10px 8px 6px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:4px;}
  .dmn-menu{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:7px;color:rgba(255,255,255,.55);font-size:12px;font-weight:600;text-decoration:none;font-family:'DM Sans',sans-serif;}
  .dmn-menu:hover{background:rgba(255,255,255,.06);color:#fff;}
  .dmn-sw{position:relative;margin-top:4px;}
  .dmn-sw-btn{width:100%;display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.05);color:#fff;font-family:'DM Sans',sans-serif;font-size:12px;font-weight:700;cursor:pointer;text-align:left;}
  .dmn-sw-btn:hover{background:rgba(255,255,255,.09);}
  .dmn-sw-btn .dmn-car{margin-left:auto;opacity:.5;font-size:10px;}
  .dmn-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
  .dmn-sw-list{display:none;margin-top:4px;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);padding:4px;}
  .dmn-sw.open .dmn-sw-list{display:block;}
  .dmn-sw-grp{font-size:9px;font-weight:700;color:rgba(255,255,255,.3);text-transform:uppercase;letter-spacing:1.4px;padding:7px 8px 3px;}
  .dmn-sw-it{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;color:rgba(255,255,255,.7);font-size:12px;text-decoration:none;font-family:'DM Sans',sans-serif;}
  .dmn-sw-it:hover{background:rgba(255,255,255,.07);color:#fff;}
  .dmn-sw-it.cur{background:rgba(255,255,255,.1);color:#fff;font-weight:700;}
  .dmn-sw-it.off{opacity:.35;pointer-events:none;}
  .dmn-sw-it small{margin-left:auto;font-size:9px;opacity:.6;text-transform:uppercase;letter-spacing:.6px;}
  .dmn-by{display:flex;align-items:center;gap:7px;margin-top:8px;font-size:10px;color:rgba(255,255,255,.35);font-family:'DM Sans',sans-serif;}
  .dmn-by img{height:30px;width:auto;filter:brightness(0) invert(1);opacity:.8;}
  .dmn-foot{padding:22px 16px 26px;display:flex;justify-content:center;align-items:center;gap:8px;font-size:11px;color:var(--muted2,#9ca3af);font-family:'DM Sans',sans-serif;border-top:1px solid var(--border,rgba(0,0,0,.07));margin-top:18px;}
  .dmn-foot img{height:34px;width:auto;opacity:.85;}
  [data-theme="dark"] .dmn-foot img{filter:brightness(0) invert(1);opacity:.9;}
  `;
  const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
  if(!document.querySelector('link[rel="icon"]')){const l=document.createElement('link');l.rel='icon';l.type='image/png';l.href='sobe.png';document.head.appendChild(l);}

  // logo do produto no topo do menu lateral: RDCs = Checklist RDC, Perpétuo = POPList
  const prod=/^RDC/i.test(here)?{src:'logos/checklist.webp',alt:'Checklist RDC'}:here==='perpetuo.html'?{src:'logos/poplist_branco.svg',alt:'POPList'}:null;
  const lb=document.getElementById('logoBox'),nm=document.getElementById('sbNome');
  if(prod&&lb&&nm){lb.style.display='none';nm.style.display='none';
    const im=document.createElement('img');im.src=prod.src;im.alt=prod.alt;
    im.style.cssText='display:block;height:24px;width:auto;max-width:100%;object-fit:contain;object-position:left;margin-bottom:5px';
    nm.parentNode.insertBefore(im,nm);}

  const sobeImg='<img src="sobe.png" alt="Sobé Estratégias" onerror="this.replaceWith(document.createTextNode(\'Sobé Estratégias\'))">';
  const nav=document.querySelector('#sidebar .sb-nav, .sb .sb-nav');
  if(nav){
    const it=DM_NAV.itens||[];
    const cur=it.find(i=>i.href===here)||null;
    let grp=null,list='';
    it.forEach(i=>{
      if(i.grupo!==grp){grp=i.grupo;if(grp)list+=`<div class="dmn-sw-grp">${grp}</div>`;}
      const dot=`<span class="dmn-dot" style="background:${i.cor||'#94a3b8'}"></span>`;
      list+=i.href?`<a class="dmn-sw-it${i.href===here?' cur':''}" href="${i.href}">${dot}${i.label}</a>`
                  :`<span class="dmn-sw-it off">${dot}${i.label}<small>em breve</small></span>`;
    });
    const box=document.createElement('div');box.className='dmn-nav';
    box.innerHTML=`<a class="dmn-menu" href="${DM_NAV.menu}">← Menu de dashboards</a>
      <div class="dmn-sw"><button class="dmn-sw-btn" type="button">${cur?`<span class="dmn-dot" style="background:${cur.cor}"></span>${cur.label}`:'Trocar dashboard'}<span class="dmn-car">▾</span></button>
      <div class="dmn-sw-list">${list}</div></div>`;
    nav.prepend(box);
    box.querySelector('.dmn-sw-btn').onclick=()=>box.querySelector('.dmn-sw').classList.toggle('open');
  }
  const sf=document.querySelector('.sb-footer');
  if(sf&&!sf.querySelector('.dmn-by')){const d=document.createElement('div');d.className='dmn-by';d.innerHTML='Desenvolvido por '+sobeImg;sf.appendChild(d);}
  const content=document.querySelector('.content');
  if(content&&!document.querySelector('.dmn-foot')){const f=document.createElement('div');f.className='dmn-foot';f.innerHTML='Desenvolvido por '+sobeImg;content.appendChild(f);}
})();
