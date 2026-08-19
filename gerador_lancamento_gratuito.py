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

LANCAMENTO_COD   = "RDC03"        # filtra campanhas; "" = ver tudo
USAR_PESQUISA    = True            # False = oculta aba Pesquisa
USAR_VENDAS      = True            # False = oculta menu Vendas (Hotmart)
USAR_COMPARATIVO = True            # False = oculta menu Comparativo de lançamentos

# Lançamentos comparados na aba "Comparativo" (ordem = ordem no gráfico)
# "receita": total oficial do lançamento. Quando presente, fixa a receita total naquele
# valor e ajusta a curva diária proporcionalmente (as contagens de vendas/dia não mudam).
# Útil quando o número fechado da reunião não bate exatamente com nenhuma coluna da planilha.
LANCAMENTOS_COMPARAR = [
    {"cod":"RDC01","aba":"RDC01",  "label":"RDC01 · Março","cor":"#94a3b8", "receita":124066.20},
    {"cod":"RDC02","aba":"RDC02",  "label":"RDC02 · Maio", "cor":"#f59e0b", "receita":138850.14},
    {"cod":"RDC03","aba":"RDC03", "label":"RDC03 · Atual","cor":"#0ea5e9","atual":True},
]
# Ignora vendas abaixo deste valor (ex.: 10 descarta compras-teste de R$1). 0 = não filtra.
VENDA_VALOR_MIN  = 0

# Valor fixo por produto (substitui o preço da planilha, que traz juros de parcelamento).
# Aplicado só nas abas listadas em PRECO_FIXO_ABAS. Deixe {} para usar o preço da planilha.
#
# O valor pode ser:
#   • um número            → mesmo preço para todas as datas
#   • uma lista de faixas  → preço muda conforme a data da venda:
#       {"ate": "24/07/2026", "valor": 1429.10}                       # até 24/07 (aberto no início)
#       {"de": "25/07/2026", "ate": "02/08/2026", "valor": 1790.00}   # 25/07 a 02/08 (inclusive)
#     "de"/"ate" são opcionais (ausência = sem limite). Datas no formato dd/mm/aaaa.
#     Venda fora de todas as faixas usa a faixa mais próxima e imprime um aviso.
PRECO_FIXO = {
    "De frente com Dra Monica": 1710.90,
    "Guia de Adequação à RDC 1002/2025": 97.00,   # downsell
    "Checklist: O passo a passo para garantir a segurança do seu consultório": [
        {"ate": "24/07/2026", "valor": 1429.10},                      # promo de abertura
        {"de": "25/07/2026", "ate": "02/08/2026", "valor": 1790.00},  # sem promo
        # downsell 03/08–20/08 é OUTRO produto → entra como nova chave aqui quando você mandar
    ],
}
PRECO_FIXO_ABAS = ["hotmart"]   # abas onde PRECO_FIXO vale (o lançamento ao vivo)

# Quando o lançamento FECHA, a Hotmart exporta a planilha completa com a coluna
# "Valor de compra sem impostos" (faturamento sem taxa de cartão / sem juros de parcela).
# Aponte aqui a aba dessa exportação: o dashboard passa a usar o valor EXATO por venda
# (casado por e-mail+produto), em vez do preço fixo aproximado. Deixe None durante o
# lançamento ao vivo — aí valem os PRECO_FIXO acima.
VALOR_LIQUIDO_ABA = "RDC03"

# Produtos tratados como DOWNSELL — saem das "Vendas (produtos principais)" e do Comparativo,
# e formam a seção "Downsell" (Visão Geral + Vendas Diárias, sem investimento).
DOWNSELL_PRODUTOS = ["Guia de Adequação à RDC 1002/2025"]
USAR_DOWNSELL     = True         # False = oculta a seção Downsell
USAR_TOTAIS       = True         # False = oculta a seção Vendas Totais (principais + downsell)
COMPARATIVO_INCLUI_DOWNSELL = True  # True = RDC03 entra no comparativo com o downsell (faturamento cheio)


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
from urllib.parse import quote as _q
def sheet_url(t): return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={_q(str(t))}"
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
# Abas tentadas, em ordem, até uma responder com dados.
HOTMART_ABAS = ["hotmart", "hotmart tratado", "hotmart-tratado", "Hotmart", "hotmart_tratado"]

def _txt(serie):
    """Series -> texto seguro. Colunas 100% vazias viram '' em vez de quebrar o .str"""
    return serie.astype(object).where(serie.notna(), "").astype(str)

def _norm_col(c):
    """normaliza header: minúsculo, sem acento, sem pontuação, sem prefixo Sales History"""
    import unicodedata
    s = str(c).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("sales history", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

# aliases aceitos por campo (comparados já normalizados)
# Aliases por campo, em ordem de prioridade. Comparados com o header normalizado,
# primeiro por igualdade exata; só se nenhum casar exato é que se tenta "contém".
# Ordem importa no formato longo da Hotmart (ex.: "nome do produto" NÃO pode virar comprador).
# Métrica de receita da aba de fechamento (formato longo da Hotmart):
#   "com" = "Valor de compra COM impostos" (bruto — inclui juros de parcela / taxa de cartão)
#   "sem" = "Valor de compra SEM impostos" (sem a taxa de cartão)
VALOR_FECHAMENTO_METRICA = "com"   # RDC03 fechado: cliente pediu o valor com impostos (R$131.754,43)

_COL_COM = ["valor de compra com impostos", "faturamento com impostos"]
_COL_SEM = ["valor de compra sem impostos", "faturamento bruto sem impostos"]
_COL_VALOR_PREF = (_COL_COM + _COL_SEM) if VALOR_FECHAMENTO_METRICA == "com" else (_COL_SEM + _COL_COM)

_HM_ALIAS = {
    "date":       ["order date", "data de venda", "data da transacao", "order date time", "data pedido", "data da compra", "date", "data"],
    "price":      _COL_VALOR_PREF + ["price", "preco do produto", "product price", "total price", "valor", "commission value"],
    "status":     ["transaction status", "status da transacao", "status"],
    "sck":        ["tracking source sck", "origem de checkout", "codigo sck", "sck", "source sck", "src sck", "tracking sck"],
    "pgto_raw":   ["payment method", "tipo de pagamento", "metodo de pagamento", "forma pagamento", "metodo pagamento", "payment type"],
    "nome":       ["buyer name", "comprador a", "nome", "nome comprador", "name"],
    "email":      ["buyer email", "email do a comprador a", "email", "e mail", "email comprador"],
    "produto":    ["product name", "nome do produto", "produto"],
    "utm_camp":   ["captacao campaign", "utm campaign", "campaign", "campanha"],
    "utm_medium": ["captacao medium", "utm medium", "medium", "publico"],
    "utm_content":["captacao content", "utm content", "content", "criativo"],
}
# Campos cujo alias pode aparecer como substring de OUTRA coluna (ex.: "nome" dentro de
# "nome do produto"): só casam por igualdade exata, nunca por "contém".
_HM_SO_EXATO = {"date", "price", "status", "nome", "email", "produto", "sck", "pgto_raw"}

def _norm_pgto(m):
    """Normaliza forma de pagamento (aceita PT e EN da Hotmart) em PIX / Cartão de Crédito / Boleto / Outro."""
    s = str(m).upper()
    if "PIX" in s or "ONEY" in s or "FINANCED" in s:      return "PIX"
    if "BOLETO" in s or "BILLET" in s:                    return "Boleto"
    if "CREDIT" in s or "CARD" in s or "CARTAO" in s or "CRÉDITO" in s or "CREDITO" in s or "NUPAY" in s or "HOTPAY" in s:
        return "Cartão de Crédito"
    if s in ("", "NAN", "NONE"):                          return "Outro"
    return "Cartão de Crédito"

_VL_CACHE = {}
def _mapa_valor_liquido():
    """Lê VALOR_LIQUIDO_ABA e devolve {email||produto: valor sem impostos}.
    None se não configurado ou se a aba não tiver as colunas necessárias."""
    if not VALOR_LIQUIDO_ABA:
        return None
    if VALOR_LIQUIDO_ABA in _VL_CACHE:
        return _VL_CACHE[VALOR_LIQUIDO_ABA]
    try:
        d = pd.read_csv(sheet_url(VALOR_LIQUIDO_ABA))
    except Exception as e:
        print(f"     ⚠ valor líquido: aba '{VALOR_LIQUIDO_ABA}' ilegível ({type(e).__name__}) — mantendo preços fixos")
        _VL_CACHE[VALOR_LIQUIDO_ABA] = None; return None
    d, _, _ = _map_hotmart_cols(d)
    if not all(c in d.columns for c in ("price", "email", "produto")):
        print(f"     ⚠ valor líquido: aba '{VALOR_LIQUIDO_ABA}' sem valor/email/produto — mantendo preços fixos")
        _VL_CACHE[VALOR_LIQUIDO_ABA] = None; return None
    d = d.assign(_v=to_num(d["price"]),
                 _k=_txt(d["email"]).str.strip().str.lower() + "||" + _txt(d["produto"]).str.strip())
    mapa = d.groupby("_k")["_v"].sum().to_dict()
    _lbl = "com impostos" if VALOR_FECHAMENTO_METRICA == "com" else "sem impostos"
    print(f"     valor de fechamento ({_lbl}): {len(mapa)} chave(s) de '{VALOR_LIQUIDO_ABA}' (soma R${sum(mapa.values()):,.2f})")
    _VL_CACHE[VALOR_LIQUIDO_ABA] = mapa
    return mapa

def _aplicar_valor_liquido(df):
    """Substitui price pelo valor sem impostos (casando por email+produto). Marca as linhas
    cobertas em _vl_ok para o preço fixo não sobrescrevê-las depois."""
    mapa = _mapa_valor_liquido()
    if not mapa or not all(c in df.columns for c in ("email", "produto")):
        return df
    df = df.copy()
    k = _txt(df["email"]).str.strip().str.lower() + "||" + _txt(df["produto"]).str.strip()
    novo = k.map(mapa)
    ok = novo.notna()
    df["price"] = novo.where(ok, df["price"])
    df["_vl_ok"] = ok.values
    _lbl = "com impostos" if VALOR_FECHAMENTO_METRICA == "com" else "sem impostos"
    print(f"     valor de fechamento ({_lbl}) aplicado em {int(ok.sum())}/{len(df)} venda(s)")
    return df

def _preco_fixo_produto(produto, data):
    """Preço fixo para (produto, data) ou None se o produto não está em PRECO_FIXO.
    Aceita número (fixo sempre) ou lista de faixas {de?, ate?, valor}. Devolve
    (valor, fora_da_faixa) — fora_da_faixa=True quando a data não caiu em nenhuma faixa."""
    regra = PRECO_FIXO.get(produto)
    if regra is None:
        return None, False
    if not isinstance(regra, (list, tuple)):
        return float(regra), False
    d = pd.to_datetime(data, errors="coerce")
    if pd.isna(d):
        return float(regra[0]["valor"]), True
    d = d.normalize()
    faixas = []
    for f in regra:
        de  = pd.to_datetime(f["de"],  dayfirst=True, errors="coerce").normalize() if f.get("de")  else pd.Timestamp.min
        ate = pd.to_datetime(f["ate"], dayfirst=True, errors="coerce").normalize() if f.get("ate") else pd.Timestamp.max
        faixas.append((de, ate, float(f["valor"])))
    faixas.sort(key=lambda x: x[0])
    for de, ate, val in faixas:
        if de <= d <= ate:
            return val, False
    # fora de todas as faixas → usa a mais próxima e sinaliza
    return (faixas[0][2] if d < faixas[0][0] else faixas[-1][2]), True

def _aplicar_preco_fixo(df, aba):
    """Se a aba está em PRECO_FIXO_ABAS, substitui price pelo valor fixo do produto,
    resolvido pela data da venda. Só age nas linhas ainda sem valor exato (_vl_ok=False);
    produtos sem regra mantêm o preço da planilha."""
    if not PRECO_FIXO or aba not in PRECO_FIXO_ABAS or "produto" not in df.columns:
        return df.drop(columns=["_vl_ok"], errors="ignore")
    df = df.copy()
    exato = df["_vl_ok"].tolist() if "_vl_ok" in df.columns else [False]*len(df)
    prod = _txt(df["produto"]).str.strip()
    precos = df["price"].astype(float).tolist()
    aplicados, sem_regra, fora = 0, set(), []
    for i, (p, d) in enumerate(zip(prod, df["date"])):
        if exato[i]:               # já tem valor exato sem impostos → não mexe
            continue
        val, foraFaixa = _preco_fixo_produto(p, d)
        if val is not None:
            precos[i] = val; aplicados += 1
            if foraFaixa:
                fora.append((p, d))
        elif p and p != "nan":
            sem_regra.add(p)
    df["price"] = precos
    if aplicados:
        print(f"     preço fixo aplicado em {aplicados} venda(s)")
    if fora:
        exemplos = sorted({(p[:30], (pd.to_datetime(d, errors='coerce').strftime('%d/%m') if pd.notna(pd.to_datetime(d, errors='coerce')) else '?')) for p, d in fora})
        print(f"     ⚠ {len(fora)} venda(s) fora das faixas de data (usei a faixa mais próxima): {exemplos[:5]}")
    if sem_regra:
        print(f"     ⚠ produtos SEM preço fixo (usando valor da planilha): {sorted(sem_regra)}")
    return df.drop(columns=["_vl_ok"], errors="ignore")

def _map_hotmart_cols(df):
    """devolve (df_renomeado, faltando[], achados{}) mapeando headers reais -> nomes internos.
    Casa primeiro por igualdade exata do header normalizado; só depois, e apenas para campos
    fora de _HM_SO_EXATO, tenta 'contém'. Cada coluna original é usada uma única vez, evitando
    que 'nome do produto' seja confundido com 'nome' (comprador) no export longo da Hotmart."""
    norm = {_norm_col(c): c for c in df.columns}   # header_normalizado -> header_real
    ren, achados, usados = {}, {}, set()

    # passo 1 — igualdade exata (respeita a ordem de prioridade dos aliases)
    for interno, aliases in _HM_ALIAS.items():
        for a in aliases:
            real = norm.get(a)
            if real and real not in usados:
                ren[real] = interno; achados[interno] = real; usados.add(real); break

    # passo 2 — 'contém', só para campos seguros ainda não resolvidos
    for interno, aliases in _HM_ALIAS.items():
        if interno in achados or interno in _HM_SO_EXATO:
            continue
        for a in aliases:
            for n, real in norm.items():
                if real in usados:
                    continue
                if a in n:
                    ren[real] = interno; achados[interno] = real; usados.add(real); break
            if interno in achados:
                break

    df = df.rename(columns=ren)
    faltando = [k for k in ("date", "price") if k not in df.columns]
    return df, faltando, achados

def _ler_hotmart():
    """tenta as abas de HOTMART_ABAS até achar uma legível. Devolve (df, nome_aba)."""
    erros = []
    for aba in HOTMART_ABAS:
        try:
            d = pd.read_csv(sheet_url(aba))
            if len(d.columns) == 0:
                erros.append(f"{aba}: sem colunas"); continue
            print(f"     aba '{aba}' OK — {len(d)} linhas, {len(d.columns)} colunas")
            return d, aba
        except Exception as e:
            erros.append(f"{aba}: {type(e).__name__}")
    print("     nenhuma aba de vendas encontrada → " + " | ".join(erros))
    return None, None

def hotmart_data(excluir_produtos=None, apenas_produtos=None, rotulo="hotmart"):
    """excluir_produtos: descarta esses produtos (ex.: tira o downsell das Vendas principais).
    apenas_produtos:  mantém só esses produtos (ex.: página Downsell)."""
    print(f"  Lendo {rotulo}...")
    try:
        df, aba = _ler_hotmart()
        if df is None:
            print(f"  ✗ VENDAS DESATIVADAS: nenhuma das abas {HOTMART_ABAS} existe na planilha.")
            print("    → ajuste HOTMART_ABAS no topo do gerador com o nome exato da aba.")
            return None

        df, faltando, achados = _map_hotmart_cols(df)
        if faltando:
            print(f"  ✗ VENDAS DESATIVADAS: coluna(s) obrigatória(s) não encontrada(s): {faltando}")
            print(f"    Colunas disponíveis na aba '{aba}': {list(df.columns)[:25]}")
            return None
        print(f"     colunas mapeadas: {achados}")

        # colunas opcionais ausentes viram vazias (em vez de quebrar tudo)
        for opc in ("status", "sck", "pgto_raw", "nome", "email", "utm_camp", "utm_medium", "utm_content"):
            if opc not in df.columns: df[opc] = ""

        # filtro por produto (Vendas principais x Downsell)
        if (excluir_produtos or apenas_produtos) and "produto" in df.columns:
            prod = _txt(df["produto"]).str.strip()
            if apenas_produtos:
                df = df[prod.isin(apenas_produtos)]
                print(f"     filtro: apenas {apenas_produtos} → {len(df)} linha(s)")
            elif excluir_produtos:
                df = df[~prod.isin(excluir_produtos)]
                print(f"     filtro: excluindo {excluir_produtos} → {len(df)} linha(s)")
            if len(df) == 0:
                print(f"     ⚠ nenhuma venda após filtro de produto — '{rotulo}' ficará vazio.")
                return None

        # data: ISO (2026-07-10) sem dayfirst; formato BR (10/07/2026) com dayfirst
        _amostra = _txt(df["date"]).str.strip()
        _iso = _amostra.str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False).mean() > 0.5
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=not _iso)
        df["price"] = to_num(df["price"])
        df = _aplicar_valor_liquido(df)   # valor exato sem impostos (quando a aba de fechamento existe)
        df = _aplicar_preco_fixo(df, aba) # preço fixo só como fallback nas linhas sem valor exato
        df = df.dropna(subset=["date"])

        # status: aceita variações PT/EN; se a coluna vier vazia, não filtra
        st = _txt(df["status"]).str.strip().str.upper()
        aprovados = ["APPROVED", "COMPLETE", "COMPLETED", "APROVADO", "APROVADA", "COMPLETO", "PAGO", "PAID"]
        if st.isin(aprovados).any():
            antes = len(df); df = df[st.isin(aprovados)]
            print(f"     status: {len(df)}/{antes} linhas aprovadas")
        elif st.replace("", pd.NA).notna().any() and st.nunique() > 1:
            print(f"     ⚠ status não reconhecido {sorted(st.unique())[:8]} — usando TODAS as linhas")
        if len(df) == 0:
            print("  ⚠ Aba de vendas lida, mas 0 linhas válidas — menu Vendas ficará vazio.")

        print(f"     {len(df)} vendas | R${df['price'].sum():,.2f}")

        # Investimento Meta (só LANCAMENTO_COD)
        df_meta_inv = None
        try:
            df_m = pd.read_csv(URL_META)
            df_m["spend"] = to_num(df_m.get("Spend (Cost, Amount Spent)", pd.Series([0]*len(df_m))))
            df_m["leads"] = to_num(df_m.get("Action Leads", pd.Series([0]*len(df_m))))
            if LANCAMENTO_COD and "Campaign Name" in df_m.columns:
                df_m = df_m[df_m["Campaign Name"].str.contains(LANCAMENTO_COD, na=False)]
            df_meta_inv = df_m
        except Exception as e:
            print(f"     ⚠ cruzamento Meta indisponível ({type(e).__name__}) — tabelas sem investimento")

        def _soma(col, val):
            if df_meta_inv is None or col not in df_meta_inv.columns: return {}
            return df_meta_inv.groupby(col)[val].sum().to_dict()

        camp_inv      = _soma("Campaign Name", "spend")
        camp_leads_d  = _soma("Campaign Name", "leads")
        adset_inv     = _soma("Adset Name", "spend")
        adset_leads_d = _soma("Adset Name", "leads")
        ad_inv        = _soma("Ad Name", "spend")
        ad_leads_d    = _soma("Ad Name", "leads")
        total_inv     = float(df_meta_inv["spend"].sum()) if df_meta_inv is not None else 0

        # Diário — ordena pela data real, não pelo texto dd/mm
        dg = (df.groupby(df["date"].dt.normalize())
                .agg(vendas=("price", "count"), receita=("price", "sum"))
                .reset_index().sort_values("date"))
        daily = {"days": [d.strftime("%d/%m") for d in dg["date"]],
                 "vendas": [int(v) for v in dg["vendas"]],
                 "receita": [round(float(v), 2) for v in dg["receita"]]}

        # Canal SCK
        df["canal"] = _txt(df["sck"]).str.split("|").str[0].replace({"nan": "Sem rastreio", "": "Sem rastreio", "na": "Sem rastreio"})
        cg = df.groupby("canal").agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("v", ascending=False)
        canal = [{"n": str(r["canal"]), "v": int(r["v"]), "r": round(float(r["r"]), 2)} for _, r in cg.iterrows()]

        # SCK detalhado
        sg = df.groupby(_txt(df["sck"])).agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("v", ascending=False)
        sck_data = [{"n": str(r.iloc[0]), "v": int(r["v"]), "r": round(float(r["r"]), 2)} for _, r in sg.iterrows()]

        # Produtos (para a Visão de Vendas Totais)
        if "produto" in df.columns:
            pdg = df.assign(_p=_txt(df["produto"]).str.strip().replace({"": "—", "nan": "—"})) \
                    .groupby("_p").agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("r", ascending=False)
            produtos = [{"n": str(r["_p"]), "v": int(r["v"]), "r": round(float(r["r"]), 2)} for _, r in pdg.iterrows()]
        else:
            produtos = []

        # Temperatura
        camp_col = _txt(df["utm_camp"]).str.upper()
        df["temp"] = camp_col.apply(lambda x: "Quente" if "QUENTE" in x else ("Frio" if "FRIO" in x else "Sem rastreio"))
        tg = df.groupby("temp").agg(v=("price", "count"), r=("price", "sum")).reset_index()
        tg["_o"] = tg["temp"].map({"Quente": 0, "Frio": 1, "Sem rastreio": 2})
        temperatura = [{"n": str(r["temp"]), "v": int(r["v"]), "r": round(float(r["r"]), 2)} for _, r in tg.sort_values("_o").iterrows()]

        # Pagamentos
        fmt_pgto = _norm_pgto
        fmt_pgto_full = _norm_pgto
        df["tipo_pgto"] = df["pgto_raw"].fillna("").apply(fmt_pgto)
        pg = df.groupby("tipo_pgto").agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("v", ascending=False)
        pagamentos = [{"n": str(r["tipo_pgto"]), "v": int(r["v"]), "r": round(float(r["r"]), 2)} for _, r in pg.iterrows()]

        # Cruzamento UTM x Meta
        def build_cruzamento(col, inv_d, leads_d, label_sem):
            df[col+"_c"] = _txt(df[col]).str.strip()
            g = df.groupby(col+"_c").agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("v", ascending=False)
            result = []
            for _, row in g.iterrows():
                name = str(row[col+"_c"])
                inv = inv_d.get(name, 0); lds = leads_d.get(name, 0)
                if inv == 0:
                    for k, v in inv_d.items():
                        if name and (name.lower() in k.lower() or k.lower() in name.lower()): inv += v
                if lds == 0:
                    for k, v in leads_d.items():
                        if name and (name.lower() in k.lower() or k.lower() in name.lower()): lds += v
                lds = int(lds); inv = round(float(inv), 2)
                result.append({"n": label_sem if name in ("nan", "NaN", "", "None") else name,
                               "v": int(row["v"]), "r": round(float(row["r"]), 2), "inv": inv, "lds": lds,
                               "cpl": round(inv/lds, 2) if lds > 0 else None,
                               "roas": round(float(row["r"])/inv, 2) if inv > 0 else None})
            return result

        utm_camp   = build_cruzamento("utm_camp", camp_inv, camp_leads_d, "E-mail não encontrado na captação")
        publicos   = build_cruzamento("utm_medium", adset_inv, adset_leads_d, "Sem público")
        criativos  = build_cruzamento("utm_content", ad_inv, ad_leads_d, "Sem criativo")
        roas_geral = round(df["price"].sum()/total_inv, 2) if total_inv > 0 else None

        # Raw para filtro de data no HTML
        raw_rows = []
        for _, row in df.iterrows():
            sck_v = str(row["sck"]) if pd.notna(row["sck"]) else ""
            canal_v = sck_v.split("|")[0] if sck_v else ""
            canal_v = "Sem rastreio" if canal_v in ("", "nan", "na") else canal_v
            camp_v = str(row.get("utm_camp", "")) if pd.notna(row.get("utm_camp", "")) else ""
            raw_rows.append({"d": row["date"].strftime("%d/%m"), "r": round(float(row["price"]), 2),
                             "sck": sck_v, "canal": canal_v,
                             "camp": camp_v if camp_v not in ("", "nan", "NaN") else "",
                             "temp": "Quente" if "QUENTE" in camp_v.upper() else ("Frio" if "FRIO" in camp_v.upper() else "Sem rastreio"),
                             "pgto": fmt_pgto(row.get("pgto_raw", ""))})

        # Vendas individuais (tabela detalhada + gráfico horário)
        vendas_raw = []
        for _, row in df.sort_values("date", ascending=False).iterrows():
            vendas_raw.append({
                "d": row["date"].strftime("%d/%m/%Y %H:%M"),
                "dia": row["date"].strftime("%d/%m"),
                "hora": int(row["date"].strftime("%H")),
                "nome": str(row.get("nome", "")).title() if pd.notna(row.get("nome", "")) and str(row.get("nome", "")) else "—",
                "email": str(row.get("email", "")) if pd.notna(row.get("email", "")) and str(row.get("email", "")) else "—",
                "valor": round(float(row["price"]), 2),
                "pgto": fmt_pgto_full(row.get("pgto_raw", "")),
                "sck": str(row.get("sck", "")) or "—",
                "camp": str(row.get("utm_camp", "")) or "—",
            })

        return {"daily": daily, "canal": canal, "sck": sck_data, "temperatura": temperatura,
                "pagamentos": pagamentos, "utm_camp": utm_camp, "publicos": publicos, "criativos": criativos,
                "produtos": produtos, "total_inv": round(total_inv, 2), "roas_geral": roas_geral,
                "raw": raw_rows, "vendas_raw": vendas_raw}
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  ✗ VENDAS DESATIVADAS por erro: {type(e).__name__}: {e}")
        return None

# ══ COMPARATIVO DE LANÇAMENTOS ════════════════════════
def _serie_lancamento(df, cod, label, cor, atual):
    """monta a série diária alinhada por dia do lançamento (D1 = primeira venda)"""
    df = df.sort_values("date")
    ini = df["date"].min().normalize()
    df = df.assign(_dia=(df["date"].dt.normalize() - ini).dt.days + 1)

    g = df.groupby("_dia").agg(v=("price", "count"), r=("price", "sum")).reset_index()
    ndias = int(g["_dia"].max())
    vendas = [0]*ndias; receita = [0.0]*ndias
    for _, row in g.iterrows():
        vendas[int(row["_dia"])-1] = int(row["v"])
        receita[int(row["_dia"])-1] = round(float(row["r"]), 2)
    cum_v, cum_r, av, ar = [], [], 0, 0.0
    for i in range(ndias):
        av += vendas[i]; ar += receita[i]
        cum_v.append(av); cum_r.append(round(ar, 2))

    # data de calendário de cada dia do lançamento
    datas = [(ini + pd.Timedelta(days=i)).strftime("%d/%m") for i in range(ndias)]

    # pagamento e canal
    def _agg(serie, label_vazio):
        s = _txt(serie).str.strip().replace({"": label_vazio, "nan": label_vazio})
        a = df.assign(_k=s).groupby("_k").agg(v=("price", "count"), r=("price", "sum")).reset_index().sort_values("v", ascending=False)
        return [{"n": str(x["_k"]), "v": int(x["v"]), "r": round(float(x["r"]), 2)} for _, x in a.iterrows()]

    pgto_s = _txt(df["pgto_raw"]).apply(_norm_pgto)
    canal_s = _txt(df["sck"]).str.split("|").str[0]

    # vendas por hora do dia (padrão de horário de compra)
    horas = [0]*24
    for h in df["date"].dt.hour:
        horas[int(h)] += 1

    tot_v = int(len(df)); tot_r = round(float(df["price"].sum()), 2)
    return {
        "cod": cod, "label": label, "cor": cor, "atual": bool(atual),
        "ini": ini.strftime("%d/%m/%Y"), "fim": df["date"].max().strftime("%d/%m/%Y"),
        "dias": ndias, "vendas": tot_v, "receita": tot_r,
        "ticket": round(tot_r/tot_v, 2) if tot_v else 0,
        "pico": {"dia": int(vendas.index(max(vendas)))+1, "v": max(vendas)} if vendas else None,
        "serie": {"datas": datas, "vendas": vendas, "receita": receita, "cum_v": cum_v, "cum_r": cum_r},
        "pgto": _agg(pgto_s, "Outro"), "canal": _agg(canal_s, "Sem rastreio"), "horas": horas,
    }

def lancamentos_data(excluir_produtos=None):
    print("  Lendo lançamentos anteriores...")
    out = []
    for cfg in LANCAMENTOS_COMPARAR:
        aba = cfg["aba"]
        try:
            df = pd.read_csv(sheet_url(aba))
        except Exception as e:
            print(f"     ✗ {cfg['cod']}: aba '{aba}' ilegível ({type(e).__name__})"); continue
        df, faltando, _ = _map_hotmart_cols(df)
        if faltando:
            print(f"     ✗ {cfg['cod']}: faltam colunas {faltando} na aba '{aba}'"); continue
        for opc in ("status", "sck", "pgto_raw"):
            if opc not in df.columns: df[opc] = ""

        # tira o downsell do comparativo (mantém as Vendas principais comparáveis entre lançamentos)
        if excluir_produtos and "produto" in df.columns:
            prod = _txt(df["produto"]).str.strip()
            n0 = len(df); df = df[~prod.isin(excluir_produtos)]
            if n0 != len(df): print(f"     {cfg['cod']}: {n0-len(df)} venda(s) de downsell excluída(s) do comparativo")

        _amostra = _txt(df["date"]).str.strip()
        _iso = _amostra.str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False).mean() > 0.5
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=not _iso)
        df["price"] = to_num(df["price"])
        df = _aplicar_preco_fixo(df, aba)
        df = df.dropna(subset=["date"])

        st = _txt(df["status"]).str.strip().str.upper()
        aprovados = ["APPROVED", "COMPLETE", "COMPLETED", "APROVADO", "APROVADA", "COMPLETO", "PAGO", "PAID"]
        if st.isin(aprovados).any(): df = df[st.isin(aprovados)]
        if VENDA_VALOR_MIN > 0:
            antes = len(df); df = df[df["price"] >= VENDA_VALOR_MIN]
            if antes != len(df): print(f"     {cfg['cod']}: {antes-len(df)} venda(s) abaixo de R${VENDA_VALOR_MIN} ignorada(s)")
        if len(df) == 0:
            print(f"     ⚠ {cfg['cod']}: sem vendas válidas na aba '{aba}'"); continue

        s = _serie_lancamento(df, cfg["cod"], cfg.get("label", cfg["cod"]), cfg.get("cor", "#94a3b8"), cfg.get("atual", False))

        # receita oficial: fixa o total e reescala a curva diária (contagens não mudam)
        alvo = cfg.get("receita")
        if alvo is not None and s["receita"] > 0:
            f = float(alvo) / s["receita"]
            s["serie"]["receita"] = [round(v * f, 2) for v in s["serie"]["receita"]]
            s["serie"]["cum_r"]   = [round(v * f, 2) for v in s["serie"]["cum_r"]]
            for grp in ("pgto", "canal"):
                for it in s[grp]: it["r"] = round(it["r"] * f, 2)
            print(f"     {cfg['cod']}: receita ajustada R${s['receita']:,.2f} → R${float(alvo):,.2f} (fator {f:.4f})")
            s["receita"] = round(float(alvo), 2)
            s["ticket"]  = round(float(alvo) / s["vendas"], 2) if s["vendas"] else 0

        out.append(s)
        print(f"     ✓ {cfg['cod']}: {s['vendas']} vendas | R${s['receita']:,.2f} | {s['dias']} dia(s) | início {s['ini']}")

    if not out:
        print("  ⚠ Nenhum lançamento com dados — menu Comparativo não aparecerá."); return None
    return {"lista": out}

# ══ PESQUISA ══════════════════════════════════════════
def load_pesquisa():
    print("  Lendo pesquisa..."); return pd.read_csv(sheet_url("Pesquisa"))

def pesquisa_process(df, total_leads):
    UTM_COLS=["utm_source","utm_medium","utm_campaign","utm_content"]
    SKIP_COLS=set(UTM_COLS+["Carimbo de data/hora","Timestamp","Email","email",
                             "Qual seu e-mail de cadastro no evento?",
                             "Qual seu primeiro nome?","Qual seu whatsapp?",
                             "Nome","nome","ID","id","Unnamed: 0"])
    # Palavras que indicam campo de identificação livre (não é pergunta de múltipla escolha)
    _ID_HINTS=("nome","name","email","e-mail","mail","whats","telefone","phone",
               "celular","cpf","data","hora","carimbo","timestamp","marca temporal",
               "marca de tiempo","fecha","sello")
    def _is_pergunta(c):
        if c in SKIP_COLS or c.lower().startswith("unnamed"): return False
        if not str(c).strip(): return False
        cl=str(c).lower()
        if any(h in cl for h in _ID_HINTS): return False
        if not pd.api.types.is_string_dtype(df[c]): return False
        serie=df[c].dropna()
        n=len(serie)
        if n==0: return False
        nun=serie.nunique()
        if nun>50: return False
        # descarta perguntas "abertas": quando a maioria das respostas é única
        # (nome, e-mail, etc. que escaparam das dicas acima). Limiar: >60% únicas
        # e com pelo menos 8 respostas para evitar falso-positivo em amostras pequenas.
        if n>=8 and (nun/n)>0.6: return False
        return True
    PERGUNTAS=[c for c in df.columns if _is_pergunta(c)]
    def _clean_q(s): return " ".join(str(s).split())  # remove \n e espaços duplos
    graficos=[]  # reconstruído após filtrar rows vazias
    EMPTY_TOKEN="(vazio)"
    # Normaliza UTMs: valor real (str) ou EMPTY_TOKEN quando ausente/vazio.
    # Assim TODAS as respostas entram nos filtros e "tudo marcado" = 100% dos dados.
    def _utm_val(r, col):
        if col not in df.columns: return EMPTY_TOKEN
        v = r.get(col)
        if pd.isna(v): return EMPTY_TOKEN
        s = str(v).strip()
        return s if s and s.lower()!="nan" else EMPTY_TOKEN
    rows=[]
    for _,r in df.iterrows():
        row={}
        _tem_resposta=False
        for p in PERGUNTAS:
            val=str(r[p]) if p in df.columns and pd.notna(r.get(p)) else None
            row[p]=val
            if val and val.strip(): _tem_resposta=True
        for col in UTM_COLS: row[col]=_utm_val(r, col)
        # descarta linhas totalmente vazias (planilha às vezes traz milhares de linhas em branco)
        if _tem_resposta: rows.append(row)
    # gráficos a partir das rows válidas (não do df cru com linhas vazias)
    from collections import Counter as _Counter
    for p in PERGUNTAS:
        _c=_Counter(row[p] for row in rows if row.get(p) and str(row[p]).strip())
        _tot=sum(_c.values())
        if _tot==0: continue
        graficos.append({"pergunta":p,"opcoes":[{"label":str(k),"qtd":int(v),"pct":round(v/_tot*100,1)} for k,v in _c.most_common()]})
    # Filtros a partir dos valores efetivamente presentes nas rows (inclui EMPTY_TOKEN);
    # ordena com valores reais primeiro e "(vazio)" por último.
    filtros={}
    for col in UTM_COLS:
        vals=sorted(set(row[col] for row in rows if row.get(col) and row[col]!=EMPTY_TOKEN))
        if any(row.get(col)==EMPTY_TOKEN for row in rows): vals=vals+[EMPTY_TOKEN]
        if vals: filtros[col]=vals
    # Série de respostas por dia (para o gráfico no topo, adaptável ao período)
    resp_por_dia=[]
    _date_col=None
    for c in df.columns:
        cl=str(c).lower()
        if any(h in cl for h in ("carimbo","timestamp","marca temporal","marca de tiempo","data/hora","fecha","sello de tiempo")):
            _date_col=c; break
    if _date_col is not None:
        _dt=pd.to_datetime(df[_date_col], errors="coerce", dayfirst=True)
        _por_dia=_dt.dropna().dt.strftime("%d/%m").value_counts()
        def _dk(s):
            dd,mm=s.split("/"); return int(mm)*100+int(dd)
        for d in sorted(_por_dia.index, key=_dk):
            resp_por_dia.append({"d":d,"n":int(_por_dia[d])})
        # rows recebem a data para permitir filtro por período no front
        _dt_fmt=_dt.dt.strftime("%d/%m")
        for i,(_,r) in enumerate(df.iterrows()):
            if i<len(rows):
                v=_dt_fmt.iloc[i] if i<len(_dt_fmt) else None
                rows[i]["_d"]=v if pd.notna(v) else None
    return {"total":len(rows),"total_leads":int(total_leads),"graficos":graficos,
            "filtros":filtros,"rows":rows,"perguntas":PERGUNTAS,"resp_por_dia":resp_por_dia}

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


# ══ COMPARAÇÃO LP + CTV ════════════════════════════════════
def build_comp_data(df):
    """Agrega métricas por LPV01/LPV02 e IMG/VD para aba de comparação."""
    from collections import defaultdict

    sub = df[df["campaign"].str.contains(LANCAMENTO_COD, na=False)] if LANCAMENTO_COD else df

    lpv_d  = {"LPV01": defaultdict(lambda: defaultdict(float)),
               "LPV02": defaultdict(lambda: defaultdict(float))}
    ctv_d  = {"IMG":   defaultdict(lambda: defaultdict(float)),
               "VD":    defaultdict(lambda: defaultdict(float))}
    lpv_camps = defaultdict(lambda: defaultdict(float))
    ctv_camps = defaultdict(lambda: defaultdict(float))
    camp_tags = {}
    all_days_set = set()

    for _, row in sub.iterrows():
        camp = str(row.get("campaign", ""))
        d    = row["date"].strftime("%d/%m")
        sp   = float(row.get("spend",       0) or 0)
        imp  = float(row.get("impressions", 0) or 0)
        lc   = float(row.get("link_clicks", 0) or 0)
        pv   = float(row.get("page_view",   0) or 0)
        ld   = float(row.get("leads",       0) or 0)

        lpv = "LPV01" if "LPV01" in camp else ("LPV02" if "LPV02" in camp else None)
        ctv = "IMG"   if "IMG"   in camp else ("VD"    if "VD"    in camp else None)
        camp_tags[camp] = {"lpv": lpv, "ctv": ctv}
        all_days_set.add(d)

        if lpv:
            for k, v in [("sp",sp),("imp",imp),("lc",lc),("pv",pv),("ld",ld)]:
                lpv_d[lpv][d][k]    += v
                lpv_camps[camp][k]  += v
        if ctv:
            for k, v in [("sp",sp),("imp",imp),("lc",lc),("pv",pv),("ld",ld)]:
                ctv_d[ctv][d][k]    += v
                ctv_camps[camp][k]  += v

    def day_key(s):
        dd, mm = s.split("/"); return int(mm)*100 + int(dd)
    days = sorted(all_days_set, key=day_key)

    def metrics(agg):
        sp=round(float(agg.get("sp", agg.get("spend",0))),2)
        imp=int(agg.get("imp",0)); lc=int(agg.get("lc",0))
        pv=int(agg.get("pv",0));   ld=int(agg.get("ld", agg.get("leads",0)))
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"leads":ld,
                "cpm":  round(sp/imp*1000,2) if imp>0 else None,
                "ctr":  round(lc/imp*100,2)  if imp>0 else None,
                "cr":   round(pv/lc*100,2)   if lc>0  else None,
                "cpl":  round(sp/ld,2)        if ld>0  else None,
                "tx_conv":round(ld/pv*100,2)  if pv>0  else None}

    def build_daily(d_dict):
        out={"days":days,"spend":[],"imp":[],"lc":[],"pv":[],"leads":[],"cpl":[],"cr":[],"tx_conv":[]}
        for d in days:
            v=d_dict[d]; sp=round(float(v.get("sp",0)),2)
            imp=int(v.get("imp",0)); lc=int(v.get("lc",0))
            pv=int(v.get("pv",0));   ld=int(v.get("ld",0))
            out["spend"].append(sp);  out["imp"].append(imp)
            out["lc"].append(lc);     out["pv"].append(pv); out["leads"].append(ld)
            out["cpl"].append(round(sp/ld,2) if ld>0 else None)
            out["cr"].append(round(pv/lc*100,2) if lc>0 else None)
            out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        return out

    def totals(d_dict):
        t = defaultdict(float)
        for d in days:
            for k, v in d_dict[d].items(): t[k] += v
        return t

    def camp_list(camps_dict, filter_fn):
        result = []
        for c, v in sorted(camps_dict.items(), key=lambda x: -x[1].get("ld",0)):
            if not filter_fn(c): continue
            m = metrics(v); m["n"] = c; result.append(m)
        return result

    return {
        "LPV": {
            "LPV01": {"totals": metrics(totals(lpv_d["LPV01"])),
                      "daily":  build_daily(lpv_d["LPV01"]),
                      "camps":  camp_list(lpv_camps, lambda c: "LPV01" in c)},
            "LPV02": {"totals": metrics(totals(lpv_d["LPV02"])),
                      "daily":  build_daily(lpv_d["LPV02"]),
                      "camps":  camp_list(lpv_camps, lambda c: "LPV02" in c)},
            "days": days,
        },
        "CTV": {
            "IMG": {"totals": metrics(totals(ctv_d["IMG"])),
                    "daily":  build_daily(ctv_d["IMG"]),
                    "camps":  camp_list(ctv_camps, lambda c: "IMG" in c)},
            "VD":  {"totals": metrics(totals(ctv_d["VD"])),
                    "daily":  build_daily(ctv_d["VD"]),
                    "camps":  camp_list(ctv_camps, lambda c: "VD" in c and "IMG" not in c)},
            "days": days,
        },
    }

def inject_all(tpl, meta_k, meta_d, meta_dc, meta_raw_c, meta_t, meta_bd, pes, hotmart, comp_data=None, lancs=None, downsell=None, total=None):
    html=Path(tpl).read_text(encoding="utf-8")
    html=replace_js_const(html,"META_KPIS",     meta_k)
    html=replace_js_const(html,"META_DAILY",     meta_d)
    html=replace_js_const(html,"META_DAILY_CAMPS", meta_dc)
    html=replace_js_const(html,"META_RAW_CAMP",  meta_raw_c)
    html=replace_js_const(html,"META_TABLES",    meta_t)
    html=replace_js_const(html,"META_BD",        meta_bd)
    html=replace_js_const(html,"PESQUISA", pes if USAR_PESQUISA else False)
    html=replace_js_const(html,"HOTMART", hotmart if USAR_VENDAS else False)
    html=replace_js_const(html,"LANCAMENTOS", lancs if USAR_COMPARATIVO else False)
    html=replace_js_const(html,"DOWNSELL", downsell if USAR_DOWNSELL else False)
    html=replace_js_const(html,"TOTAIS", total if USAR_TOTAIS else False)
    if comp_data is not None:
        html=replace_js_const(html,"COMP_DATA", comp_data)
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
    downsell = None
    _excl = DOWNSELL_PRODUTOS if (USAR_DOWNSELL and DOWNSELL_PRODUTOS) else None
    if USAR_VENDAS:
        hotmart=hotmart_data(excluir_produtos=_excl, rotulo="hotmart (produtos principais)")
        if hotmart is None:
            print("  ⚠⚠ USAR_VENDAS=True porém sem dados → menu Vendas NÃO aparecerá no dashboard.")
    else:
        hotmart=None
        print("  (desativado)")

    print("\n[DOWNSELL]")
    if USAR_DOWNSELL and DOWNSELL_PRODUTOS:
        downsell=hotmart_data(apenas_produtos=DOWNSELL_PRODUTOS, rotulo="downsell")
        if downsell is None:
            print("  (sem vendas de downsell ainda — seção não aparecerá)")
    else:
        print("  (desativado)")

    print("\n[VENDAS TOTAIS]")
    total = None
    if USAR_VENDAS and USAR_TOTAIS:
        total = hotmart_data(rotulo="vendas totais (tudo)")   # sem filtro = principais + downsell
    else:
        print("  (desativado)")

    print("\n[COMPARATIVO]")
    lancs = lancamentos_data(excluir_produtos=None if COMPARATIVO_INCLUI_DOWNSELL else _excl) if USAR_COMPARATIVO else None

    print("\n[COMPARAÇÃO LP + CTV]")
    try:
        comp_data = build_comp_data(df_meta)
        l1=comp_data["LPV"]["LPV01"]["totals"]; l2=comp_data["LPV"]["LPV02"]["totals"]
        img=comp_data["CTV"]["IMG"]["totals"];   vd=comp_data["CTV"]["VD"]["totals"]
        print(f"  LPV01: {l1['leads']} leads | R${l1['cpl']} CPL")
        print(f"  LPV02: {l2['leads']} leads | R${l2['cpl']} CPL")
        print(f"  IMG:   {img['leads']} leads | {'sem dados' if not img['leads'] else f'R${img[chr(99)+chr(112)+chr(108)]} CPL'}")
        print(f"  VD:    {vd['leads']} leads | R${vd['cpl']} CPL")
    except Exception as e:
        print(f"  ⚠ {e}"); comp_data = None

    print("\n[HTML]")
    if not Path(TEMPLATE_FILE).exists():
        print(f"  ERRO: {TEMPLATE_FILE} não encontrado"); return
    html=inject_all(TEMPLATE_FILE,m_k,m_d,m_dc,m_raw,m_t,m_bd,pes,hotmart,comp_data,lancs,downsell,total)
    Path(OUTPUT_FILE).write_text(html,encoding="utf-8")
    print(f"  ✓ {OUTPUT_FILE} ({len(html)//1024}KB)")

    data_json={"cliente":NOME_CLIENTE,"cor":COR_ACENTO,"letra":LOGO_LETRA,
               "lancamento":LANCAMENTO_COD,"atualizado":date.today().strftime("%d/%m/%Y"),
               "kpis":{"spend":m_k["lct"].get("spend"),"leads":m_k["lct"].get("leads"),"cpl":m_k["lct"].get("cpl")}}
    Path("data.json").write_text(json.dumps(data_json,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  ✓ data.json\n{'='*60}")

if __name__=="__main__":
    main()
