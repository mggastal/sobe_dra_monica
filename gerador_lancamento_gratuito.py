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

NOME_CLIENTE     = "Dra Monica"
LOGO_LETRA       = "DM"
COR_ACENTO       = "#0ea5e9"

LANCAMENTO_COD   = "RDC02"        # filtra campanhas; "" = ver tudo
USAR_PESQUISA    = True            # False = oculta aba Pesquisa
USAR_VENDAS      = True            # False = oculta menu Vendas (Hotmart)


# Metas do funil — define cores (verde/amarelo/vermelho)
CPL_BOM          = 5.0    # Custo por Lead ≤ 5 → verde | 5-10 → amarelo | acima → vermelho
CPL_MEDIO        = 10.0
CTR_BOM          = 1.2    # CTR ≥ 1.2% → verde | 0.8-1.2% → amarelo | abaixo → vermelho
CTR_MEDIO        = 0.8
CR_BOM           = 40.0   # Connect Rate ≥ 40% → verde | 25-40% → amarelo | abaixo → vermelho
CR_MEDIO         = 25.0
TX_CONV_BOM      = 30.0   # Taxa Conversão (Lead/PV) ≥ 30% → verde | 15-30% → amarelo | abaixo → vermelho
TX_CONV_MEDIO    = 15.0
CPM_BOM          = 5.0    
CPM_MEDIO        = 12.0

# ══════════════════════════════════════════════════════
def sheet_url(t): return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={t}"
URL_META = sheet_url("meta-ads")
URL_PES  = sheet_url("Pesquisa")
URL_GA   = sheet_url("breakdown-gender-age")
URL_PT   = sheet_url("breakdown-platform")
URL_HOTMART = sheet_url("hotmart")

def to_num(s):
    if pd.api.types.is_numeric_dtype(s): return s.fillna(0)
    clean = s.astype(str).str.strip().str.replace("R$","",regex=False).str.strip()
    if clean.str.contains(r"\d,\d", regex=True).any():
        clean = clean.str.replace(".","",regex=False).str.replace(",",".",regex=False)
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
        "Date":"date","Campaign Name":"campaign","Adset Name":"adset",
        "Ad Name":"ad","Thumbnail URL":"thumb","Status":"status",
        "Spend (Cost, Amount Spent)":"spend","Impressions":"impressions",
        "Action Link Clicks":"link_clicks",
        "Action Landing Page View":"page_view",
        "Action Leads":"leads"
    })
    df["date"]=pd.to_datetime(df["date"],errors="coerce")
    for c in ["spend","impressions","link_clicks","page_view","leads"]:
        if c in df.columns: df[c]=to_num(df[c])
    if "status" not in df.columns: df["status"]=""
    df["status"]=df["status"].astype(str).str.strip().str.upper()
    df["is_lct"]=df["campaign"].str.contains(LANCAMENTO_COD,na=False,case=False) if LANCAMENTO_COD else True
    df=df.dropna(subset=["date"])
    print(f"     {len(df)} linhas | {df['date'].min().date()} → {df['date'].max().date()}")
    return df

def calc_kpis(p):
    sp=float(p["spend"].sum()); imp=float(p["impressions"].sum())
    lc=float(p["link_clicks"].sum()); pv=float(p["page_view"].sum())
    ld=float(p["leads"].sum())
    return {
        "spend":round(sp,2),"impressions":int(imp),"link_clicks":int(lc),
        "page_view":int(pv),"leads":int(ld),
        "ctr":   round(lc/imp*100,2) if imp>0 else None,
        "connect_rate":round(pv/lc*100,2) if lc>0 else None,
        "tx_conv":round(ld/pv*100,2) if pv>0 else None,
        "cpl":   round(sp/ld,2) if ld>0 else None,
        "cpm":   round(sp/imp*1000,2) if imp>0 else None
    }

def meta_kpis(df):
    return {"lct":calc_kpis(df[df["is_lct"]]),"all":calc_kpis(df)}

def build_daily(p):
    agg=p.groupby("date").agg(
        spend=("spend","sum"),impressions=("impressions","sum"),
        link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),
        leads=("leads","sum")
    ).reset_index().sort_values("date")
    out={k:[] for k in ["days","spend","impressions","link_clicks","page_view","leads","ctr","connect_rate","tx_conv","cpl","cpm"]}
    for _,r in agg.iterrows():
        sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
        pv=float(r["page_view"]); ld=float(r["leads"])
        out["days"].append(r["date"].strftime("%d/%m"))
        out["spend"].append(round(sp,2)); out["impressions"].append(int(imp))
        out["link_clicks"].append(int(lc)); out["page_view"].append(int(pv))
        out["leads"].append(int(ld))
        out["ctr"].append(round(lc/imp*100,2) if imp>0 else None)
        out["connect_rate"].append(round(pv/lc*100,2) if lc>0 else None)
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
            result[key][camp]=build_daily(subset[subset["campaign"]==camp])
    return result

_STATUS_PRIORITY={"ACTIVE":0,"WITH_ISSUES":1,"PAUSED":2,"ADSET_PAUSED":3,"CAMPAIGN_PAUSED":4,"ARCHIVED":5}

def _pick_status(group):
    if "status" not in group.columns: return ""
    g=group[group["status"].notna()&(group["status"]!="")&(group["status"]!="NAN")]
    if len(g)==0: return ""
    last_date=g["date"].max()
    last=g[g["date"]==last_date]
    if (last["status"]=="ACTIVE").any(): return "ACTIVE"
    statuses=last["status"].unique().tolist()
    statuses.sort(key=lambda s:_STATUS_PRIORITY.get(s,99))
    return statuses[0]

def meta_raw(df):
    has_status="status" in df.columns
    camp_st={k:_pick_status(g) for k,g in df.groupby("campaign")} if has_status else {}
    adset_st={(c,a):_pick_status(g) for (c,a),g in df.groupby(["campaign","adset"])} if has_status else {}
    rows=[]
    agg=df.groupby(["date","campaign","adset","is_lct"]).agg(
        spend=("spend","sum"),leads=("leads","sum"),
        impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),
        page_view=("page_view","sum")
    ).reset_index()
    for _,r in agg.iterrows():
        rows.append({
            "d":r["date"].strftime("%d/%m"),"c":str(r["campaign"]),"a":str(r["adset"]),
            "lct":bool(r["is_lct"]),"sp":round(float(r["spend"]),2),
            "ld":int(r["leads"]),"imp":int(r["impressions"]),
            "lc":int(r["link_clicks"]),"pv":int(r["page_view"]),
            "sc":camp_st.get(str(r["campaign"]),""),
            "sa":adset_st.get((str(r["campaign"]),str(r["adset"])),""),
        })
    return rows

def meta_tables_period(df, p, img_dir):
    def ag(sub,cols): return sub.groupby(cols).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),leads=("leads","sum")).reset_index()

    def calc_row(r):
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"])
        pv=int(r["page_view"]); ld=int(r["leads"])
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"ld":ld,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cr":round(pv/lc*100,2) if lc>0 else None,
            "tx_cv":round(ld/pv*100,2) if pv>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None,
            "cpm":round(sp/imp*1000,2) if imp>0 else None}

    # Mapas de status usando df completo (não só o período filtrado)
    camp_st={k:_pick_status(g) for k,g in df.groupby("campaign")}
    adset_st={(c,a):_pick_status(g) for (c,a),g in df.groupby(["campaign","adset"])}
    ad_st={(c,a,n):_pick_status(g) for (c,a,n),g in df.groupby(["campaign","adset","ad"])}

    camps_agg=ag(p,"campaign")
    camps=[{"n":str(r["campaign"]),"status":camp_st.get(str(r["campaign"]),""),**calc_row(r)} for _,r in camps_agg.sort_values("leads",ascending=False).iterrows()]

    adsets_agg=ag(p,["campaign","adset"])
    adsets=[{"n":str(r["adset"]),"camp":str(r["campaign"]),"status":adset_st.get((str(r["campaign"]),str(r["adset"])),""),**calc_row(r)} for _,r in adsets_agg.sort_values("leads",ascending=False).iterrows()]

    # Thumbs do df completo
    df_full_thumb=df[df["thumb"].notna()&(df["thumb"].astype(str)!="nan")] if "thumb" in df.columns else pd.DataFrame()
    thumb_map={}
    for _,r in df_full_thumb.iterrows():
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        if k not in thumb_map: thumb_map[k]=download_thumb(str(r["thumb"]),img_dir)

    ads_agg=p.groupby(["ad","adset","campaign"]).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False)
    ads=[]
    for _,r in ads_agg.iterrows():
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"]); ld=int(r["leads"])
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        ads.append({"n":str(r["ad"]),"adset":str(r["adset"]),"camp":str(r["campaign"]),
            "status":ad_st.get((str(r["campaign"]),str(r["adset"]),str(r["ad"])),""),
            "thumb":thumb_map.get(k,""),"spend":sp,"imp":imp,"lc":lc,"ld":ld,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None})
    return {"camps":camps,"adsets":adsets,"ads":ads}

def meta_tables(df, img_dir):
    hoje=pd.Timestamp(date.today())
    ontem=hoje-pd.Timedelta(days=1)
    result={"lct":{},"all":{}}
    period_ranges={
        "1":  (ontem, ontem),
        "7":  (hoje-pd.Timedelta(days=6), hoje),
        "14": (hoje-pd.Timedelta(days=13), hoje),
        "30": (hoje-pd.Timedelta(days=29), hoje),
        "all": (None, None),
    }
    for key,subset in [("lct",df[df["is_lct"]]),("all",df)]:
        for pname,(start,end) in period_ranges.items():
            if start is None:
                p=subset
            else:
                p=subset[(subset["date"]>=start)&(subset["date"]<=end)]
            result[key][pname]=meta_tables_period(df,p,img_dir)
            print(f"     [{key}][{pname}]: {len(result[key][pname]['camps'])} camps | {len(result[key][pname]['ads'])} ads")
    return result

def meta_breakdowns(df):
    print("  Lendo breakdowns...")
    hoje_bd=pd.Timestamp(date.today())
    AGE_ORDER=["18-24","25-34","35-44","45-54","55-64","65+"]
    def seg(agg,dim):
        agg=agg[agg["spend"]>0].copy()
        agg["cpl"]=(agg["spend"]/agg["leads"]).where(agg["leads"]>0).round(2)
        return [{"n":str(r[dim]),"spend":round(float(r["spend"]),2),"ld":int(r["leads"]),"cpl":safe(r["cpl"])} for _,r in agg.iterrows()]
    try:
        df_ga=pd.read_csv(URL_GA)
        df_ga["date"]=pd.to_datetime(df_ga["Date"],errors="coerce")
        df_ga["spend"]=to_num(df_ga["Spend (Cost, Amount Spent)"])
        df_ga["leads"]=to_num(df_ga["Action Leads"])
        df_ga["age"]=df_ga["Age (Breakdown)"].astype(str)
        df_ga["gender"]=df_ga["Gender (Breakdown)"].astype(str)
        # Filtrar por campanha se a coluna existir
        if "Campaign Name" in df_ga.columns and LANCAMENTO_COD:
            df_ga["is_lct"]=df_ga["Campaign Name"].str.contains(LANCAMENTO_COD,na=False,case=False)
        else:
            df_ga["is_lct"]=True
        df_ga=df_ga.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso GA: {e}"); df_ga=pd.DataFrame()
    try:
        df_pt=pd.read_csv(URL_PT)
        df_pt["date"]=pd.to_datetime(df_pt["Date"],errors="coerce")
        df_pt["spend"]=to_num(df_pt["Spend (Cost, Amount Spent)"])
        df_pt["leads"]=to_num(df_pt["Action Leads"])
        df_pt["platform"]=df_pt["Platform Position (Breakdown)"].astype(str)
        # Filtrar por campanha se a coluna existir
        if "Campaign Name" in df_pt.columns and LANCAMENTO_COD:
            df_pt["is_lct"]=df_pt["Campaign Name"].str.contains(LANCAMENTO_COD,na=False,case=False)
        else:
            df_pt["is_lct"]=True
        df_pt=df_pt.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso PT: {e}"); df_pt=pd.DataFrame()

    result={}
    for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
        start=hoje_bd-pd.Timedelta(days=n-1) if n>0 else None
        # Aplicar filtro de lançamento em cada subset
        for lname,lct_filter in [("lct",True),("all",None)]:
            if len(df_ga)>0:
                pga=df_ga if lct_filter is None else df_ga[df_ga["is_lct"]]
                pga=pga[(pga["date"]>=start)&(pga["date"]<=hoje_bd)] if n>0 else pga
            else: pga=df_ga
            if len(df_pt)>0:
                ppt=df_pt if lct_filter is None else df_pt[df_pt["is_lct"]]
                ppt=ppt[(ppt["date"]>=start)&(ppt["date"]<=hoje_bd)] if n>0 else ppt
            else: ppt=df_pt
            age_d=[]; gen_d=[]; plat_d=[]
            if len(pga)>0:
                ag_age=pga[pga["age"].isin(AGE_ORDER)].groupby("age").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index()
                ag_age["_o"]=ag_age["age"].apply(lambda x:AGE_ORDER.index(x) if x in AGE_ORDER else 99)
                age_d=seg(ag_age.sort_values("_o"),"age")
                ag_gen=pga[pga["gender"].isin(["female","male"])].groupby("gender").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False)
                gen_d=seg(ag_gen,"gender")
            if len(ppt)>0:
                ag_pt=ppt.groupby("platform").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False).head(8)
                plat_d=seg(ag_pt,"platform")
            if lname not in result: result[lname]={}
            result[lname][pname]={"age":age_d,"gender":gen_d,"platform":plat_d}

    # Raw para datas livres — incluir flag is_lct
    raw_ga=[]
    if len(df_ga)>0:
        for _,r in df_ga.iterrows():
            if pd.isna(r['date']): continue
            raw_ga.append({'d':r['date'].strftime('%d/%m'),'age':str(r['age']),'gen':str(r['gender']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'lct':bool(r['is_lct']),'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
    raw_pt=[]
    if len(df_pt)>0:
        for _,r in df_pt.iterrows():
            if pd.isna(r['date']): continue
            raw_pt.append({'d':r['date'].strftime('%d/%m'),'plat':str(r['platform']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'lct':bool(r['is_lct']),'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
    result['_raw_ga']=raw_ga; result['_raw_pt']=raw_pt
    return result

# ══ HOTMART ═══════════════════════════════════════════
def hotmart_data():
    print("  Lendo hotmart...")
    try:
        df=pd.read_csv(URL_HOTMART)
        df=df.rename(columns={
            "Sales History Order Date":"date","Sales History Price":"price",
            "Sales History Transaction Status":"status",
            "Sales History Tracking Source SCK":"sck",
            "Sales History Payment Method":"pgto_raw",
            "Sales History Buyer Name":"nome","Sales History Buyer Email":"email",
            "Captacao_Campaign":"utm_camp","Captacao_Medium":"utm_medium","Captacao_Content":"utm_content",
        })
        df["date"]=pd.to_datetime(df["date"],errors="coerce")
        df["price"]=to_num(df["price"])
        df=df[df["status"]=="APPROVED"].dropna(subset=["date"])
        print(f"     {len(df)} vendas aprovadas | R${df['price'].sum():,.2f}")

        # Investimento Meta (só LANCAMENTO_COD)
        df_meta_inv=None
        try:
            df_m=pd.read_csv(URL_META)
            df_m["spend"]=to_num(df_m.get("Spend (Cost, Amount Spent)",pd.Series([0]*len(df_m))))
            df_m["leads"]=to_num(df_m.get("Action Leads",pd.Series([0]*len(df_m))))
            if LANCAMENTO_COD:
                df_m=df_m[df_m.get("Campaign Name",pd.Series([""])).str.contains(LANCAMENTO_COD,na=False)]
            df_meta_inv=df_m
        except: pass

        camp_inv=df_meta_inv.groupby("Campaign Name")["spend"].sum().to_dict() if df_meta_inv is not None else {}
        camp_leads_d=df_meta_inv.groupby("Campaign Name")["leads"].sum().to_dict() if df_meta_inv is not None else {}
        adset_inv=df_meta_inv.groupby("Adset Name")["spend"].sum().to_dict() if df_meta_inv is not None else {}
        adset_leads_d=df_meta_inv.groupby("Adset Name")["leads"].sum().to_dict() if df_meta_inv is not None else {}
        ad_inv=df_meta_inv.groupby("Ad Name")["spend"].sum().to_dict() if df_meta_inv is not None else {}
        ad_leads_d=df_meta_inv.groupby("Ad Name")["leads"].sum().to_dict() if df_meta_inv is not None else {}
        total_inv=df_meta_inv["spend"].sum() if df_meta_inv is not None else 0

        # Diário
        dg=df.groupby(df["date"].dt.strftime("%d/%m")).agg(vendas=("price","count"),receita=("price","sum")).reset_index().sort_values("date")
        daily={"days":dg["date"].tolist(),"vendas":dg["vendas"].tolist(),"receita":[round(v,2) for v in dg["receita"]]}

        # Canal SCK
        df["canal"]=df["sck"].astype(str).str.split("|").str[0].replace({"nan":"Sem rastreio","":"Sem rastreio"})
        cg=df.groupby("canal").agg(v=("price","count"),r=("price","sum")).reset_index().sort_values("v",ascending=False)
        canal=[{"n":str(r["canal"]),"v":int(r["v"]),"r":round(float(r["r"]),2)} for _,r in cg.iterrows()]

        # SCK detalhado
        sg=df.groupby("sck").agg(v=("price","count"),r=("price","sum")).reset_index().sort_values("v",ascending=False)
        sck_data=[{"n":str(r["sck"]),"v":int(r["v"]),"r":round(float(r["r"]),2)} for _,r in sg.iterrows()]

        # Temperatura
        camp_col=df["utm_camp"].fillna("").astype(str).str.upper()
        df["temp"]=camp_col.apply(lambda x:"Quente" if "QUENTE" in x else("Frio" if "FRIO" in x else "Sem rastreio"))
        tg=df.groupby("temp").agg(v=("price","count"),r=("price","sum")).reset_index()
        tg["_o"]=tg["temp"].map({"Quente":0,"Frio":1,"Sem rastreio":2})
        temperatura=[{"n":str(r["temp"]),"v":int(r["v"]),"r":round(float(r["r"]),2)} for _,r in tg.sort_values("_o").iterrows()]

        # Pagamentos
        def fmt_pgto(m):
            return "PIX" if ("ONEY" in str(m).upper() or "FINANCED" in str(m).upper()) else "Cartão de Crédito"
        def fmt_pgto_full(m):
            m=str(m).replace("CREDIT_CARD_","").replace("_"," ").title()
            return m.replace("Financed Installment Adyen Oney 12X","PIX Parcelado (Oney)")
        df["tipo_pgto"]=df["pgto_raw"].fillna("").apply(fmt_pgto)
        pg=df.groupby("tipo_pgto").agg(v=("price","count"),r=("price","sum")).reset_index().sort_values("v",ascending=False)
        pagamentos=[{"n":str(r["tipo_pgto"]),"v":int(r["v"]),"r":round(float(r["r"]),2)} for _,r in pg.iterrows()]

        # Cruzamento UTM x Meta
        def build_cruzamento(col,inv_d,leads_d,label_sem):
            df[col+"_c"]=df[col].fillna("").astype(str).str.strip()
            g=df.groupby(col+"_c").agg(v=("price","count"),r=("price","sum")).reset_index().sort_values("v",ascending=False)
            result=[]
            for _,row in g.iterrows():
                name=str(row[col+"_c"])
                inv=inv_d.get(name,0)
                lds=leads_d.get(name,0)
                if inv==0:
                    for k,v in inv_d.items():
                        if name.lower() in k.lower() or k.lower() in name.lower(): inv+=v
                if lds==0:
                    for k,v in leads_d.items():
                        if name.lower() in k.lower() or k.lower() in name.lower(): lds+=v
                lds=int(lds); inv=round(inv,2)
                result.append({"n":label_sem if name in("nan","NaN","","None") else name,
                    "v":int(row["v"]),"r":round(float(row["r"]),2),"inv":inv,"lds":lds,
                    "cpl":round(inv/lds,2) if lds>0 else None,
                    "roas":round(float(row["r"])/inv,2) if inv>0 else None})
            return result

        utm_camp=build_cruzamento("utm_camp",camp_inv,camp_leads_d,"E-mail não encontrado na captação")
        publicos=build_cruzamento("utm_medium",adset_inv,adset_leads_d,"Sem público")
        criativos=build_cruzamento("utm_content",ad_inv,ad_leads_d,"Sem criativo")
        roas_geral=round(df["price"].sum()/total_inv,2) if total_inv>0 else None

        # Raw para filtro de data no HTML
        raw_rows=[]
        for _,row in df.iterrows():
            sck_v=str(row["sck"]) if pd.notna(row["sck"]) else ""
            canal_v=sck_v.split("|")[0] if sck_v else ""
            canal_v="Sem rastreio" if canal_v in ("","nan") else canal_v
            camp_v=str(row.get("utm_camp","")) if pd.notna(row.get("utm_camp","")) else ""
            pgto_v=fmt_pgto(row.get("pgto_raw",""))
            temp_v="Quente" if "QUENTE" in camp_v.upper() else("Frio" if "FRIO" in camp_v.upper() else "Sem rastreio")
            raw_rows.append({"d":row["date"].strftime("%d/%m"),"r":round(float(row["price"]),2),
                "sck":sck_v,"canal":canal_v,"camp":camp_v if camp_v not in("","nan","NaN") else "",
                "temp":temp_v,"pgto":pgto_v})

        # Vendas individuais (tabela detalhada + gráfico horário)
        vendas_raw=[]
        for _,row in df.sort_values("date",ascending=False).iterrows():
            vendas_raw.append({
                "d":row["date"].strftime("%d/%m/%Y %H:%M"),
                "dia":row["date"].strftime("%d/%m"),
                "hora":int(row["date"].strftime("%H")),
                "nome":str(row.get("nome","")).title() if pd.notna(row.get("nome","")) else "—",
                "email":str(row.get("email","")) if pd.notna(row.get("email","")) else "—",
                "valor":round(float(row["price"]),2),
                "pgto":fmt_pgto_full(row.get("pgto_raw","")),
                "sck":str(row.get("sck","—")) if pd.notna(row.get("sck","")) else "—",
                "camp":str(row.get("utm_camp","—")) if pd.notna(row.get("utm_camp","")) else "—",
            })

        return {"daily":daily,"canal":canal,"sck":sck_data,"temperatura":temperatura,
                "pagamentos":pagamentos,"utm_camp":utm_camp,"publicos":publicos,"criativos":criativos,
                "total_inv":round(total_inv,2),"roas_geral":roas_geral,
                "raw":raw_rows,"vendas_raw":vendas_raw}
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  Aviso Hotmart: {e}"); return None

# ══ PESQUISA ══════════════════════════════════════════
def load_pesquisa():
    print("  Lendo pesquisa..."); return pd.read_csv(sheet_url("Pesquisa"))

def pesquisa_process(df, total_leads):
    UTM_COLS=["utm_source","utm_medium","utm_campaign","utm_content"]
    SKIP_COLS=set(UTM_COLS+["Carimbo de data/hora","Timestamp","Email","email",
                             "Qual seu e-mail de cadastro no evento?",
                             "Qual seu primeiro nome?","Qual seu whatsapp?",
                             "Nome","nome","ID","id","Unnamed: 0"])
    PERGUNTAS=[c for c in df.columns
               if c not in SKIP_COLS and not c.lower().startswith("unnamed")
               and str(c).strip() and pd.api.types.is_string_dtype(df[c])
               and df[c].nunique()<=50]
    graficos=[]
    for p in PERGUNTAS:
        if p not in df.columns: continue
        vc=df[p].value_counts(); total=vc.sum()
        graficos.append({"pergunta":p,"opcoes":[{"label":str(k),"qtd":int(v),"pct":round(v/total*100,1)} for k,v in vc.items()]})
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
    return {"total":len(df),"total_leads":int(total_leads),"graficos":graficos,"filtros":filtros,"rows":rows,"perguntas":PERGUNTAS}

# ══ INJEÇÃO ════════════════════════════════════════════
def replace_js_const(html, name, value):
    """Substitui 'const NAME = <valor>;' no HTML, mesmo com objetos/arrays aninhados."""
    replacement = f"const {name} = {json.dumps(value, ensure_ascii=False)};"
    pattern_start = re.compile(rf"const {name}\s*=\s*")
    m = pattern_start.search(html)
    if not m:
        print(f"  AVISO: não encontrou const {name}")
        return html
    start = m.start()
    val_start = m.end()
    i = val_start
    depth = 0
    in_str = False
    str_char = None
    while i < len(html):
        ch = html[i]
        if in_str:
            if ch == '\\': i += 2; continue
            if ch == str_char: in_str = False
        else:
            if ch in ('"', "'", '`'): in_str = True; str_char = ch
            elif ch in ('{', '['): depth += 1
            elif ch in ('}', ']'): depth -= 1
            elif ch == ';' and depth == 0: break
        i += 1
    end = i + 1
    html = html[:start] + replacement + html[end:]
    return html

def inject_all(tpl, meta_k, meta_d, meta_dc, meta_raw_c, meta_t, meta_bd, pes, hotmart):
    html=Path(tpl).read_text(encoding="utf-8")
    html=replace_js_const(html,"META_KPIS",     meta_k)
    html=replace_js_const(html,"META_DAILY",     meta_d)
    html=replace_js_const(html,"META_DAILY_CAMPS", meta_dc)
    html=replace_js_const(html,"META_RAW_CAMP",  meta_raw_c)
    html=replace_js_const(html,"META_TABLES",    meta_t)
    html=replace_js_const(html,"META_BD",        meta_bd)
    html=replace_js_const(html,"PESQUISA", pes if USAR_PESQUISA else False)
    html=replace_js_const(html,"HOTMART", hotmart if USAR_VENDAS else False)
    html=replace_js_const(html,"DATA_GERACAO", date.today().strftime("%Y-%m-%d"))
    # Suporte a CPL_BOM ou CPA_BOM (retrocompatibilidade)
    _cpl_bom   = globals().get("CPL_BOM",   globals().get("CPA_BOM",   5.0))
    _cpl_medio = globals().get("CPL_MEDIO", globals().get("CPA_MEDIO", 10.0))
    for k,v in [("LANCAMENTO_COD",f"'{LANCAMENTO_COD}'"),("NOME_CLIENTE",f"'{NOME_CLIENTE}'"),
                ("LOGO_LETRA",f"'{LOGO_LETRA}'"),("COR_ACENTO",f"'{COR_ACENTO}'"),
                ("CPL_BOM",str(_cpl_bom)),("CPL_MEDIO",str(_cpl_medio)),
                ("CTR_BOM",str(CTR_BOM)),("CTR_MEDIO",str(CTR_MEDIO)),
                ("CR_BOM",str(CR_BOM)),("CR_MEDIO",str(CR_MEDIO)),
                ("TX_CONV_BOM",str(TX_CONV_BOM)),("TX_CONV_MEDIO",str(TX_CONV_MEDIO)),
                ("CPM_BOM",str(CPM_BOM)),("CPM_MEDIO",str(CPM_MEDIO))]:
        html=re.sub(rf"const {k}\s*=\s*[^;]+;",f"const {k}={v};",html,count=1)
    html=re.sub(r"\d{2}/\d{2}/\d{4} · via planilha",date.today().strftime("%d/%m/%Y")+" · via planilha",html)
    return html

# ══ MAIN ═══════════════════════════════════════════════
def main():
    print("="*60)
    print(f"Dashboard Lançamento Gratuito — {NOME_CLIENTE} / {LANCAMENTO_COD or 'Todos'}")
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
    total_leads=m_k["lct"]["leads"] if LANCAMENTO_COD else m_k["all"]["leads"]
    print(f"  ✓ {total_leads} leads | R$ {m_k['lct']['spend']:,.2f} invest.")

    print("\n[PESQUISA]")
    if USAR_PESQUISA:
        df_pes=load_pesquisa()
        pes=pesquisa_process(df_pes, total_leads)
        print(f"  ✓ {pes['total']} respostas")
    else:
        pes=None
        print("  (desativada)")

    print("\n[HOTMART]")
    if USAR_VENDAS:
        hotmart=hotmart_data()
    else:
        hotmart=None
        print("  (desativado)")

    print("\n[HTML]")
    if not Path(TEMPLATE_FILE).exists():
        print(f"  ERRO: {TEMPLATE_FILE} não encontrado"); return
    html=inject_all(TEMPLATE_FILE,m_k,m_d,m_dc,m_raw,m_t,m_bd,pes,hotmart)
    Path(OUTPUT_FILE).write_text(html,encoding="utf-8")
    print(f"  ✓ {OUTPUT_FILE} ({len(html)//1024}KB)")

    data_json={"cliente":NOME_CLIENTE,"cor":COR_ACENTO,"letra":LOGO_LETRA,
               "lancamento":LANCAMENTO_COD,"atualizado":date.today().strftime("%d/%m/%Y"),
               "kpis":{"spend":m_k["lct"].get("spend"),"leads":m_k["lct"].get("leads"),"cpl":m_k["lct"].get("cpl")}}
    Path("data.json").write_text(json.dumps(data_json,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  ✓ data.json\n{'='*60}")

if __name__=="__main__":
    main()
