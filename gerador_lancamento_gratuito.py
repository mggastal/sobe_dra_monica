#!/usr/bin/env python3
"""Gerador Dashboard Lançamento Gratuito v1"""

import pandas as pd, json, re, hashlib, requests
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
SHEET_ID         = "1s0UHuiOL17BdkrYEMC7bmcdQW5snl0agA6v8qoIVHAs"
TEMPLATE_FILE    = "dashboard_lancamento_gratuito.html"
OUTPUT_FILE      = "index.html"
NOME_CLIENTE     = "Dra Mônica"
LOGO_LETRA       = "DM"
COR_ACENTO       = "#0ea5e9"
LANCAMENTO_COD   = "RDC02"        # filtra campanhas pelo código; "" = ver tudo
USAR_PESQUISA    = False            # False = oculta aba Pesquisa

# Metas de CPL — define cores (verde/amarelo/vermelho)
CPL_BOM          = 3.0    # CPL ≤ R$5 → verde
CPL_MEDIO        = 5.0   # CPL ≤ R$12 → amarelo | acima → vermelho

# Metas do funil
CTR_BOM          = 1.5
CTR_MEDIO        = 1.0
CR_BOM           = 75.0
CR_MEDIO         = 65.0
TX_LEAD_BOM      = 30.0   # Taxa Lead LP ≥ 20% → verde
TX_LEAD_MEDIO    = 15.0
TX_CONV_BOM      = 30.0   # Taxa Conversão PV→Lead ≥ 30% → verde
TX_CONV_MEDIO    = 15.0

# ══════════════════════════════════════════════════════
def sheet_url(t): return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={t}"
URL_META = sheet_url("meta-ads")
URL_PES  = sheet_url("Pesquisa")
URL_GA   = sheet_url("breakdown-gender-age")
URL_PT   = sheet_url("breakdown-platform")

def to_num(s):
    if pd.api.types.is_numeric_dtype(s): return s.fillna(0)
    clean = s.astype(str).str.strip().str.replace("R$","",regex=False).str.strip()
    if clean.str.contains(r"\d,\d", regex=True).any():
        clean = clean.str.replace(".",",",regex=False).str.replace(",",".",regex=False)
    return pd.to_numeric(clean, errors="coerce").fillna(0)

def safe(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return None
    return round(float(v),2) if float(v)!=0 else None

def download_thumb(url, d):
    if not url or str(url)=="nan": return ""
    try:
        ext=".png" if ".png" in url.lower() else ".jpg"
        fname=hashlib.md5(url.encode()).hexdigest()[:16]+ext
        fp=d/fname
        if not fp.exists():
            r=requests.get(url,timeout=10,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200: fp.write_bytes(r.content)
            else: return ""
        return "imgs/"+fname
    except: return ""

# ══ META ADS ══════════════════════════════════════════
def load_meta():
    print("  Lendo meta-ads...")
    df=pd.read_csv(URL_META)
    df=df.rename(columns={
        "Date":"date","Campaign Name":"campaign","Adset Name":"adset","Ad Name":"ad",
        "Thumbnail URL":"thumb",
        "Spend (Cost, Amount Spent)":"spend",
        "Impressions":"impressions",
        "Action Link Clicks":"link_clicks",
        "Action Landing Page View":"page_view",
        # ── Lead é o evento de conversão aqui (sem Hotmart/checkout)
        # Adapte o nome da coluna conforme seu relatório Meta:
        # "Action Lead" ou "Action Omni Lead" ou "Results" dependendo do objetivo da campanha
        "Action Lead":"leads",
        # Se usar objetivo de Leads nativos do Meta:
        # "Results":"leads",
    })
    # Fallback: se não tiver coluna leads, tenta variantes
    if "leads" not in df.columns:
        for candidate in ["Action Omni Lead","Results","Action Complete Registration","Leads"]:
            if candidate in df.columns:
                df=df.rename(columns={candidate:"leads"})
                print(f"     ⚠ Usando coluna '{candidate}' como leads")
                break
        if "leads" not in df.columns:
            df["leads"]=0
            print("     ⚠ Coluna de leads não encontrada — usando 0")

    df["date"]=pd.to_datetime(df["date"],errors="coerce")
    for c in ["spend","impressions","link_clicks","page_view","leads"]:
        if c in df.columns: df[c]=to_num(df[c])
    df["is_lct"]=df["campaign"].str.contains(LANCAMENTO_COD,na=False,case=False) if LANCAMENTO_COD else True
    df=df.dropna(subset=["date"])
    print(f"     {len(df)} linhas | {df['date'].min().date()} → {df['date'].max().date()}")
    return df

def calc_kpis(p):
    sp=float(p["spend"].sum()); imp=float(p["impressions"].sum())
    lc=float(p["link_clicks"].sum()); pv=float(p["page_view"].sum())
    ld=float(p["leads"].sum())
    return {
        "spend":round(sp,2), "impressions":int(imp), "link_clicks":int(lc),
        "page_view":int(pv), "leads":int(ld),
        "ctr":    round(lc/imp*100,2) if imp>0 else None,
        "connect_rate": round(pv/lc*100,2) if lc>0 else None,
        "tx_lead": round(ld/pv*100,2) if pv>0 else None,
        "tx_conv": round(ld/pv*100,2) if pv>0 else None,
        "cpl":    round(sp/ld,2) if ld>0 else None,
        "cpm":    round(sp/imp*1000,2) if imp>0 else None,
    }

def meta_kpis(df):
    return {"lct":calc_kpis(df[df["is_lct"]]),"all":calc_kpis(df)}

def build_daily(p):
    agg=p.groupby("date").agg(
        spend=("spend","sum"), impressions=("impressions","sum"),
        link_clicks=("link_clicks","sum"), page_view=("page_view","sum"),
        leads=("leads","sum")
    ).reset_index().sort_values("date")
    out={k:[] for k in ["days","spend","impressions","link_clicks","page_view","leads","ctr","connect_rate","tx_lead","tx_conv","cpl","cpm"]}
    for _,r in agg.iterrows():
        sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
        pv=float(r["page_view"]); ld=float(r["leads"])
        out["days"].append(r["date"].strftime("%d/%m"))
        out["spend"].append(round(sp,2)); out["impressions"].append(int(imp))
        out["link_clicks"].append(int(lc)); out["page_view"].append(int(pv))
        out["leads"].append(int(ld))
        out["ctr"].append(round(lc/imp*100,2) if imp>0 else None)
        out["connect_rate"].append(round(pv/lc*100,2) if lc>0 else None)
        out["tx_lead"].append(round(ld/pv*100,2) if pv>0 else None)
        out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        out["cpl"].append(round(sp/ld,2) if ld>0 else None)
        out["cpm"].append(round(sp/imp*1000,2) if imp>0 else None)
    return out

def meta_daily(df):
    return {"lct":build_daily(df[df["is_lct"]]),"all":build_daily(df)}

def meta_daily_camps(df):
    result={"lct":{},"all":{}}
    for key,subset in [("lct",df[df["is_lct"]]),("all",df)]:
        for camp in subset["campaign"].unique():
            p=subset[subset["campaign"]==camp]
            result[key][camp]=build_daily(p)
    return result

def meta_raw(df):
    """Raw por dia+campanha+adset — para filtros de datas livres no JS"""
    rows=[]
    agg=df.groupby(["date","campaign","adset","is_lct"]).agg(
        spend=("spend","sum"), impressions=("impressions","sum"),
        link_clicks=("link_clicks","sum"), page_view=("page_view","sum"),
        leads=("leads","sum")
    ).reset_index()
    for _,r in agg.iterrows():
        rows.append({
            "d": r["date"].strftime("%d/%m"),
            "c": str(r["campaign"]),
            "a": str(r["adset"]),
            "lct": bool(r["is_lct"]),
            "sp": round(float(r["spend"]),2),
            "imp": int(r["impressions"]),
            "lc": int(r["link_clicks"]),
            "pv": int(r["page_view"]),
            "leads": int(r["leads"]),
            # origem pago/orgânico (sem Hotmart, estimado pelo is_lct ou UTM)
            "leads_pago": int(r["leads"]) if r["is_lct"] else 0,
            "leads_org": 0 if r["is_lct"] else int(r["leads"]),
        })
    return rows

def build_rows_leads(agg_df, col):
    rows=[]
    for _,r in agg_df.sort_values("leads",ascending=False).iterrows():
        sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
        pv=float(r["page_view"]); ld=float(r["leads"])
        rows.append({
            "n": str(r[col]),
            "spend": round(sp,2), "imp": int(imp), "lc": int(lc),
            "pv": int(pv), "leads": int(ld),
            "ctr":  round(lc/imp*100,2) if imp>0 else None,
            "cr":   round(pv/lc*100,2)  if lc>0  else None,
            "tx_lead": round(ld/pv*100,2) if pv>0 else None,
            "cpl":  round(sp/ld,2) if ld>0 else None,
            "cpm":  round(sp/imp*1000,2) if imp>0 else None,
        })
    return rows

def meta_tables_period(df, p, img_dir):
    def ag(sub,col):
        return sub.groupby(col).agg(
            spend=("spend","sum"), impressions=("impressions","sum"),
            link_clicks=("link_clicks","sum"), page_view=("page_view","sum"),
            leads=("leads","sum")
        ).reset_index()
    def make_adsets(sub):
        agg2=sub.groupby(["campaign","adset"]).agg(
            spend=("spend","sum"), impressions=("impressions","sum"),
            link_clicks=("link_clicks","sum"), page_view=("page_view","sum"),
            leads=("leads","sum")
        ).reset_index()
        rows=[]
        for _,r in agg2.sort_values("leads",ascending=False).iterrows():
            sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
            pv=float(r["page_view"]); ld=float(r["leads"])
            rows.append({
                "n":str(r["adset"]), "camp":str(r["campaign"]),
                "spend":round(sp,2), "imp":int(imp), "lc":int(lc), "pv":int(pv), "leads":int(ld),
                "ctr":  round(lc/imp*100,2) if imp>0 else None,
                "cr":   round(pv/lc*100,2)  if lc>0  else None,
                "tx_lead": round(ld/pv*100,2) if pv>0 else None,
                "cpl":  round(sp/ld,2) if ld>0 else None,
                "cpm":  round(sp/imp*1000,2) if imp>0 else None,
            })
        return rows

    # Mapa de thumbs
    df_thumb=df[df["thumb"].notna()&(df["thumb"].astype(str)!="nan")]
    thumb_map={}
    for _,r in df_thumb.iterrows():
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        if k not in thumb_map:
            thumb_map[k]=download_thumb(str(r["thumb"]),img_dir)

    def make_ads(sub):
        agg=sub.groupby(["ad","adset","campaign"]).agg(
            spend=("spend","sum"), impressions=("impressions","sum"),
            link_clicks=("link_clicks","sum"), leads=("leads","sum")
        ).reset_index().sort_values("leads",ascending=False)
        if agg.empty: return []
        ads=[]
        for _,r in agg.iterrows():
            sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"]); ld=float(r["leads"])
            k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
            ads.append({
                "n":str(r["ad"]), "adset":str(r["adset"]), "camp":str(r["campaign"]),
                "thumb":thumb_map.get(k,""),
                "spend":round(sp,2), "leads":int(ld), "imp":int(imp), "lc":int(lc),
                "ctr":round(lc/imp*100,2) if imp>0 else None,
                "cpl":round(sp/ld,2) if ld>0 else None,
            })
        return ads

    camps=build_rows_leads(ag(p,"campaign"),"campaign")
    adsets=make_adsets(p)
    ads=make_ads(p)
    return {"camps":camps,"adsets":adsets,"ads":ads}

def meta_tables(df, img_dir):
    hoje=pd.Timestamp(date.today())
    result={"lct":{},"all":{}}
    periods={"1":1,"7":7,"14":14,"30":30,"all":0}
    for key,subset in [("lct",df[df["is_lct"]]),("all",df)]:
        for pname,n in periods.items():
            p=subset[subset["date"]>=hoje-pd.Timedelta(days=n-1)] if n>0 else subset
            result[key][pname]=meta_tables_period(df,p,img_dir)
            print(f"     [{key}][{pname}]: {len(result[key][pname]['camps'])} camps | {sum(c['leads'] for c in result[key][pname]['camps'])} leads")
    return result

def meta_breakdowns(df):
    print("  Lendo breakdowns...")
    hoje_bd=pd.Timestamp(date.today())
    AGE_ORDER=["18-24","25-34","35-44","45-54","55-64","65+"]
    def seg(agg,dim):
        agg=agg[agg["spend"]>0].copy()
        agg["cpl"]=(agg["spend"]/agg["leads"]).where(agg["leads"]>0).round(2)
        return [{"n":str(r[dim]),"spend":round(float(r["spend"]),2),"leads":int(r["leads"]),"cpl":safe(r["cpl"])} for _,r in agg.iterrows()]
    try:
        df_ga=pd.read_csv(URL_GA)
        df_ga["date"]=pd.to_datetime(df_ga["Date"],errors="coerce")
        df_ga["spend"]=to_num(df_ga["Spend (Cost, Amount Spent)"])
        # breakdown de leads — adapte a coluna conforme seu relatório
        lead_col_ga=next((c for c in df_ga.columns if "lead" in c.lower() or "result" in c.lower()),"Action Lead")
        df_ga["leads"]=to_num(df_ga[lead_col_ga]) if lead_col_ga in df_ga.columns else 0
        df_ga["age"]=df_ga["Age (Breakdown)"].astype(str)
        df_ga["gender"]=df_ga["Gender (Breakdown)"].astype(str)
        df_ga=df_ga.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso GA: {e}"); df_ga=pd.DataFrame()
    try:
        df_pt=pd.read_csv(URL_PT)
        df_pt["date"]=pd.to_datetime(df_pt["Date"],errors="coerce")
        df_pt["spend"]=to_num(df_pt["Spend (Cost, Amount Spent)"])
        lead_col_pt=next((c for c in df_pt.columns if "lead" in c.lower() or "result" in c.lower()),"Action Lead")
        df_pt["leads"]=to_num(df_pt[lead_col_pt]) if lead_col_pt in df_pt.columns else 0
        df_pt["platform"]=df_pt["Platform Position (Breakdown)"].astype(str)
        df_pt=df_pt.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso PT: {e}"); df_pt=pd.DataFrame()

    result={}
    for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
        if n>0:
            start=hoje_bd-pd.Timedelta(days=n-1)
            pga=df_ga[(df_ga["date"]>=start)&(df_ga["date"]<=hoje_bd)] if len(df_ga)>0 else df_ga
            ppt=df_pt[(df_pt["date"]>=start)&(df_pt["date"]<=hoje_bd)] if len(df_pt)>0 else df_pt
        else: pga=df_ga; ppt=df_pt
        if len(pga)>0:
            ag_age=pga[pga["age"].isin(AGE_ORDER)].groupby("age").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index()
            ag_age["_o"]=ag_age["age"].apply(lambda x:AGE_ORDER.index(x) if x in AGE_ORDER else 99)
            age_d=seg(ag_age.sort_values("_o"),"age")
            ag_gen=pga[pga["gender"].isin(["female","male"])].groupby("gender").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False)
            gen_d=seg(ag_gen,"gender")
        else: age_d=[]; gen_d=[]
        if len(ppt)>0:
            ag_pt=ppt.groupby("platform").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False).head(8)
            plat_d=seg(ag_pt,"platform")
        else: plat_d=[]
        result[pname]={"age":age_d,"gender":gen_d,"platform":plat_d}
    # Raw para datas livres
    raw_ga=[]
    if len(df_ga)>0:
        for _,r in df_ga.iterrows():
            if pd.isna(r["date"]): continue
            raw_ga.append({"d":r["date"].strftime("%d/%m"),"age":str(r["age"]),"gen":str(r["gender"]),"sp":round(float(r["spend"]),2),"leads":int(r["leads"])})
    raw_pt=[]
    if len(df_pt)>0:
        for _,r in df_pt.iterrows():
            if pd.isna(r["date"]): continue
            raw_pt.append({"d":r["date"].strftime("%d/%m"),"plat":str(r["platform"]),"sp":round(float(r["spend"]),2),"leads":int(r["leads"])})
    result["_raw_ga"]=raw_ga; result["_raw_pt"]=raw_pt
    return result

# ══ PESQUISA ══════════════════════════════════════════
def load_pesquisa():
    print("  Lendo pesquisa..."); return pd.read_csv(URL_PES)

def pesquisa_process(df, total_leads):
    UTM_COLS=["utm_source","utm_medium","utm_campaign","utm_content"]
    SKIP_COLS=set(UTM_COLS+["Carimbo de data/hora","Timestamp","Email","email","Nome","nome","ID","id","Unnamed: 0"])
    PERGUNTAS=[c for c in df.columns
               if c not in SKIP_COLS
               and not c.lower().startswith("unnamed")
               and pd.api.types.is_string_dtype(df[c])
               and df[c].nunique()<=50]
    filtros={}
    for col in UTM_COLS:
        if col in df.columns:
            filtros[col]=sorted([v for v in df[col].dropna().unique().tolist() if v and str(v)!="nan"])
    rows=[]
    for _,r in df.iterrows():
        row={}
        for p in PERGUNTAS: row[p]=str(r[p]) if p in df.columns and pd.notna(r.get(p)) else None
        for col in UTM_COLS: row[col]=str(r[col]) if col in df.columns and pd.notna(r.get(col)) else None
        rows.append(row)
    return {"total":len(df),"total_leads":int(total_leads),"filtros":filtros,"rows":rows,"perguntas":PERGUNTAS}

# ══ INJEÇÃO ═══════════════════════════════════════════
def replace_js_const(html, name, value):
    pattern=rf"const {name}\s*=\s*(?:null|true|false|-?\d[\d\.]*|'[^']*'|\"[^\"]*\"|\{{[\s\S]*?\}}|\[[\s\S]*?\])\s*;"
    replacement=f"const {name} = {json.dumps(value,ensure_ascii=False)};"
    found=[0]
    def do_replace(m): found[0]+=1; return replacement
    new_html=re.sub(pattern,do_replace,html,count=1)
    if not found[0]: print(f"  AVISO: não encontrou const {name}")
    return new_html

def inject_all(tpl, meta_k, meta_d, meta_dc, meta_raw_c, meta_t, meta_bd, pes, total_leads):
    html=Path(tpl).read_text(encoding="utf-8")
    html=replace_js_const(html,"META_KPIS",    meta_k)
    html=replace_js_const(html,"META_DAILY",       meta_d)
    html=replace_js_const(html,"META_DAILY_CAMPS", meta_dc)
    html=replace_js_const(html,"META_RAW_CAMP",    meta_raw_c)
    html=replace_js_const(html,"META_TABLES",      meta_t)
    html=replace_js_const(html,"META_BD",          meta_bd)
    html=replace_js_const(html,"PESQUISA",         pes if USAR_PESQUISA else False)
    hoje_brt=date.today()
    html=replace_js_const(html,"DATA_GERACAO",     hoje_brt.strftime("%Y-%m-%d"))
    for k,v in [
        ("LANCAMENTO_COD",f"'{LANCAMENTO_COD}'"),("NOME_CLIENTE",f"'{NOME_CLIENTE}'"),
        ("LOGO_LETRA",f"'{LOGO_LETRA}'"),("COR_ACENTO",f"'{COR_ACENTO}'"),
        ("CPL_BOM",str(CPL_BOM)),("CPL_MEDIO",str(CPL_MEDIO)),
        ("CTR_BOM",str(CTR_BOM)),("CTR_MEDIO",str(CTR_MEDIO)),
        ("CR_BOM",str(CR_BOM)),("CR_MEDIO",str(CR_MEDIO)),
        ("TX_LEAD_BOM",str(TX_LEAD_BOM)),("TX_LEAD_MEDIO",str(TX_LEAD_MEDIO)),
        ("TX_CONV_BOM",str(TX_CONV_BOM)),("TX_CONV_MEDIO",str(TX_CONV_MEDIO)),
    ]:
        html=re.sub(rf"const {k}\s*=\s*[^;]+;",f"const {k}={v};",html,count=1)
    html=re.sub(r"\d{2}/\d{2}/\d{4} · via planilha",date.today().strftime("%d/%m/%Y")+" · via planilha",html)
    return html

# ══ MAIN ══════════════════════════════════════════════
def main():
    print("="*60)
    print(f"Dashboard Gratuito — {NOME_CLIENTE} / {LANCAMENTO_COD or 'Todos'}")
    print("="*60)
    img_dir=Path("imgs"); img_dir.mkdir(exist_ok=True)

    print("\n[META ADS]")
    df_meta=load_meta()
    m_k=meta_kpis(df_meta)
    m_d=meta_daily(df_meta)
    m_dc=meta_daily_camps(df_meta)
    m_raw=meta_raw(df_meta)
    m_t=meta_tables(df_meta,img_dir)
    m_bd=meta_breakdowns(df_meta)
    total_leads=m_k["lct"]["leads"]
    print(f"  ✓ {total_leads} leads | CPL: R$ {m_k['lct']['cpl'] or '—'} | Invest: R$ {m_k['lct']['spend']:,.2f}")

    pes=None
    if USAR_PESQUISA:
        print("\n[PESQUISA]")
        try:
            df_pes=load_pesquisa()
            pes=pesquisa_process(df_pes,total_leads)
            print(f"  ✓ {pes['total']} respostas")
        except Exception as e:
            print(f"  ⚠ Pesquisa ignorada: {e}")

    print("\n[HTML]")
    if not Path(TEMPLATE_FILE).exists():
        print(f"  ERRO: {TEMPLATE_FILE} não encontrado"); return
    html=inject_all(TEMPLATE_FILE,m_k,m_d,m_dc,m_raw,m_t,m_bd,pes,total_leads)
    Path(OUTPUT_FILE).write_text(html,encoding="utf-8")
    print(f"  ✓ {OUTPUT_FILE} ({len(html)//1024}KB)")

    data_json={
        "cliente":NOME_CLIENTE,"cor":COR_ACENTO,"letra":LOGO_LETRA,
        "lancamento":LANCAMENTO_COD,"atualizado":date.today().strftime("%d/%m/%Y"),
        "kpis":{"spend":m_k["lct"].get("spend"),"leads":m_k["lct"].get("leads"),"cpl":m_k["lct"].get("cpl")}
    }
    Path("data.json").write_text(json.dumps(data_json,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  ✓ data.json\n{'='*60}")

if __name__=="__main__":
    main()
