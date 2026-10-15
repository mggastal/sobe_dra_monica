#!/usr/bin/env python3
"""Gerador Perpétuo + Geral + RDC01 + Menu — Dra Monica

Páginas (todas no visual do dashboard de lançamento):
  • perpetuo.html → campanhas PERPETUO (Meta) × vendas do produto perpétuo (Hotmart, via SCK)
  • geral.html    → todas as campanhas (lançamentos + perpétuo) + comparativo de lançamentos
  • RDC01.html    → snapshot do RDC01 (rodar com --rdc01; não precisa rodar todo dia)
  • MENU_FILE     → menu inicial (Perpétuo / Lançamentos / Geral)
  • nav.js        → menu lateral compartilhado ("← Menu" + trocar dashboard) + assinatura Sobé

Reaproveita leitura/normalização do gerador_lancamento_gratuito.py (mesma planilha).
"""

import sys, re, json, hashlib, requests
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd

import gerador_lancamento_gratuito as G

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
PERPETUO_TAG      = "PERPETUO"   # trecho no nome da campanha (Meta) e no SCK (Hotmart)
PERPETUO_PRODUTO  = "POPList - Passo a passo para colocar os POPs da sua clínica odontológica em ordem"
PERPETUO_ABA      = "hotmart"    # aba com o histórico de vendas ao vivo
# Vendas do produto ANTES desta data pertencem aos lançamentos (POPList foi order bump no RDC04).
# None = 1º dia com investimento em campanha PERPETUO.
PERPETUO_INICIO   = None
COR_PERPETUO      = "#7c3aed"

# Metas do perpétuo (cores verde/amarelo/vermelho)
CPA_BOM, CPA_MEDIO   = 90.0, 187.0   # custo por venda (ticket ≈ R$187)
ROAS_BOM, ROAS_MEDIO = 2.0, 1.0
TX_CONV_BOM, TX_CONV_MEDIO = 3.0, 1.0   # vendas ÷ page views (%)
IC_BOM, IC_MEDIO     = 10.0, 5.0        # checkouts ÷ page views (%)
ICV_BOM, ICV_MEDIO   = 40.0, 20.0       # vendas ÷ checkouts (%)

TEMPLATE_PERPETUO = "dashboard_perpetuo.html"
TEMPLATE_LCT      = "dashboard_lancamento_gratuito.html"
TEMPLATE_MENU     = "dashboard_hub.html"
OUT_PERPETUO      = "perpetuo.html"
OUT_GERAL         = "geral.html"
MENU_FILE         = "index.html"      # menu = página inicial do site

# Lançamentos (menu + nav). arquivo None = página ainda não existe
LANCAMENTOS_PAGINAS = [
    {"cod": "RDC04", "label": "RDC04 · Outubro", "arquivo": "RDC04.html", "cor": "#059669"},
    {"cod": "RDC03", "label": "RDC03 · Agosto",  "arquivo": "RDC03.html", "cor": "#0ea5e9"},
    {"cod": "RDC02", "label": "RDC02 · Maio",    "arquivo": "RDC02.html", "cor": "#f59e0b"},
    {"cod": "RDC01", "label": "RDC01 · Março",   "arquivo": "RDC01.html", "cor": "#94a3b8"},
]

# ══════════════════════════════════════════════════════
def thumb_local(url, d):
    """Baixa a thumb uma vez só. Nome = hash do PATH da URL (a query assinada da Meta muda
    todo dia; hashear a URL inteira re-baixava a mesma imagem a cada execução)."""
    if not url or str(url) == "nan": return ""
    try:
        path = urlparse(str(url)).path
        ext = ".png" if path.lower().endswith(".png") else ".jpg"
        fp = Path(d) / (hashlib.md5(path.encode()).hexdigest()[:16] + ext)
        if not fp.exists():
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200: return ""
            fp.write_bytes(r.content)
        return "imgs/" + fp.name
    except Exception:
        return ""
G.download_thumb = thumb_local   # vale também para as páginas geradas pelo template de lançamento
_ORIG = {k: getattr(G, k) for k in ["LANCAMENTO_COD", "UPSELL_PRODUTOS", "DOWNSELL_PRODUTOS", "PRECO_FIXO",
                                      "VALOR_LIQUIDO_ABA", "HOTMART_ABAS", "_ler_hotmart", "PERPETUO_PRODUTO"]}
def restaurar_config():
    """Volta a config do gerador de lançamento (o perpétuo/RDC01 mexem nela em tempo de execução)."""
    for k, v in _ORIG.items(): setattr(G, k, v)

def r2(v): return round(float(v), 2)
def dv(a, b, k=1): return round(a / b * k, 2) if b else None

# ══ META ═══════════════════════════════════════════════
def ler_meta():
    df = pd.read_csv(G.URL_META)
    ren = {"Date": "date", "Campaign Name": "camp", "Adset Name": "adset", "Ad Name": "ad",
           "Thumbnail URL": "thumb", "Status": "status", "Spend (Cost, Amount Spent)": "sp",
           "Impressions": "imp", "Action Link Clicks": "lc", "Action Landing Page View": "pv",
           "Action Omni Initiated Checkout": "ic", "Action Omni Purchase": "pc", "Action Leads": "lead"}
    df = df.rename(columns=ren)
    for c in ["sp", "imp", "lc", "pv", "ic", "pc", "lead"]:
        df[c] = G.to_num(df[c]) if c in df.columns else 0
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for c in ["camp", "adset", "ad", "status"]:
        df[c] = G._txt(df[c]).str.strip() if c in df.columns else ""
    df["status"] = df["status"].str.upper()
    return df

# ══ HOTMART (perpétuo) ═════════════════════════════════
def ler_vendas_raw():
    """Aba de vendas crua, só com o produto perpétuo a partir do início do perpétuo."""
    df = pd.read_csv(G.sheet_url(PERPETUO_ABA))
    m, falt, _ = G._map_hotmart_cols(df.copy())
    if falt or "produto" not in m.columns:
        raise RuntimeError(f"aba '{PERPETUO_ABA}' sem colunas {falt or ['produto']}")
    return df, m

def vendas_perpetuo(inicio):
    """Devolve (df_original_filtrado, df_mapeado_filtrado). O original vai para o
    hotmart_data do template (com Captacao_* preenchido a partir do SCK)."""
    orig, m = ler_vendas_raw()
    iso = G._txt(m["date"]).str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False).mean() > 0.5
    dt = pd.to_datetime(m["date"], errors="coerce", dayfirst=not iso)
    keep = (G._txt(m["produto"]).str.strip() == PERPETUO_PRODUTO) & (dt.dt.normalize() >= inicio)
    orig, m = orig[keep.values].copy(), m[keep.values].copy()
    m["date"] = dt[keep.values]
    m["price"] = G.to_num(m["price"])
    st = G._txt(m.get("status", pd.Series([""] * len(m), index=m.index))).str.strip().str.upper()
    ok = ["APPROVED", "COMPLETE", "COMPLETED", "APROVADO", "APROVADA", "COMPLETO", "PAGO", "PAID"]
    val = st.isin(ok) if st.isin(ok).any() else pd.Series(True, index=m.index)
    val &= m["price"] >= G.VENDA_VALOR_MIN
    # SCK da Meta: meta|público|campanha|criativo  → preenche as colunas de cruzamento
    sck = G._txt(m.get("sck", pd.Series([""] * len(m), index=m.index))).str.strip()
    parts = sck.str.split("|", expand=True).reindex(columns=range(4)).fillna("")
    is_meta = parts[0].str.lower() == "meta"
    orig["Captacao_Campaign"] = parts[2].where(is_meta, "").values
    orig["Captacao_Medium"]   = parts[1].where(is_meta, "").values
    orig["Captacao_Content"]  = parts[3].where(is_meta, "").values
    m["v_camp"], m["v_adset"], m["v_ad"] = parts[2].where(is_meta, ""), parts[1].where(is_meta, ""), parts[3].where(is_meta, "")
    m["perp"] = is_meta & m["v_camp"].str.upper().str.contains(PERPETUO_TAG, na=False)
    print(f"  {int(val.sum())} venda(s) aprovada(s) do POPList desde {inicio.strftime('%d/%m/%Y')} | "
          f"{int((val & m['perp']).sum())} com SCK do perpétuo")
    return orig, m[val.values]

# ══ ESTRUTURAS NO FORMATO DO TEMPLATE ══════════════════
NUM = ["sp", "imp", "lc", "pv", "ic", "ld", "rec", "pc"]

def row_metrics(o):
    sp, imp, lc, pv, ic, ld, rec = (float(o.get(k, 0) or 0) for k in ["sp", "imp", "lc", "pv", "ic", "ld", "rec"])
    return {"spend": r2(sp), "imp": int(imp), "lc": int(lc), "pv": int(pv), "ic": int(ic), "ld": int(ld), "rec": r2(rec),
            "pc": int(o.get("pc", 0) or 0),
            "ctr": dv(lc, imp, 100), "cr": dv(pv, lc, 100), "tx_cv": dv(ld, pv, 100), "cpl": dv(sp, ld),
            "cpm": dv(sp, imp, 1000), "roas": dv(rec, sp)}

def kpis(p):
    s = p[NUM].sum()
    return {"spend": r2(s.sp), "impressions": int(s.imp), "link_clicks": int(s.lc), "page_view": int(s.pv),
            "leads": int(s.ld), "ic": int(s.ic), "rec": r2(s.rec), "ctr": dv(s.lc, s.imp, 100),
            "connect_rate": dv(s.pv, s.lc, 100), "tx_conv": dv(s.ld, s.pv, 100), "cpl": dv(s.sp, s.ld),
            "cpm": dv(s.sp, s.imp, 1000), "roas": dv(s.rec, s.sp)}

def daily(p, dias):
    g = p.groupby("date")[NUM].sum().reindex(dias, fill_value=0)
    out = {k: [] for k in ["days", "spend", "impressions", "link_clicks", "page_view", "leads", "ic", "rec",
                           "ctr", "connect_rate", "tx_conv", "cpl", "cpm", "roas", "cic", "tx_ic"]}
    for d, r in g.iterrows():
        out["days"].append(d.strftime("%d/%m")); out["spend"].append(r2(r.sp)); out["impressions"].append(int(r.imp))
        out["link_clicks"].append(int(r.lc)); out["page_view"].append(int(r.pv)); out["leads"].append(int(r.ld))
        out["ic"].append(int(r.ic)); out["rec"].append(r2(r.rec))
        out["ctr"].append(dv(r.lc, r.imp, 100)); out["connect_rate"].append(dv(r.pv, r.lc, 100))
        out["tx_conv"].append(dv(r.ld, r.pv, 100)); out["cpl"].append(dv(r.sp, r.ld)); out["cpm"].append(dv(r.sp, r.imp, 1000))
        out["roas"].append(dv(r.rec, r.sp)); out["cic"].append(dv(r.sp, r.ic)); out["tx_ic"].append(dv(r.ic, r.pv, 100))
    return out

def status_maps(p):
    st = G._pick_status   # usa colunas date/status
    return ({k: st(g) for k, g in p.groupby("camp")},
            {k: st(g) for k, g in p.groupby(["camp", "adset"])},
            {k: st(g) for k, g in p.groupby(["camp", "adset", "ad"])})

def perpetuo(df_meta, img_dir):
    p = df_meta[df_meta["camp"].str.upper().str.contains(PERPETUO_TAG, na=False)].copy()
    if len(p) == 0:
        print("  ⚠ nenhuma campanha com PERPETUO no nome"); return None
    inicio = pd.Timestamp(PERPETUO_INICIO) if PERPETUO_INICIO else p.loc[p["sp"] > 0, "date"].min().normalize()
    orig, vend = vendas_perpetuo(inicio)

    # vendas atribuídas → linhas (dia, campanha, público, criativo)
    va = vend[vend["perp"]].assign(date=lambda x: x["date"].dt.normalize())
    va = va.groupby(["date", "v_camp", "v_adset", "v_ad"]).agg(ld=("price", "size"), rec=("price", "sum")).reset_index() \
           .rename(columns={"v_camp": "camp", "v_adset": "adset", "v_ad": "ad"})
    agg = p.groupby(["date", "camp", "adset", "ad"])[["sp", "imp", "lc", "pv", "ic", "pc"]].sum().reset_index()
    agg = agg.merge(va, on=["date", "camp", "adset", "ad"], how="outer").fillna({k: 0 for k in NUM})
    sem_match = va.merge(p[["camp", "adset", "ad"]].drop_duplicates(), on=["camp", "adset", "ad"], how="left", indicator=True)
    sem_match = sem_match[sem_match["_merge"] == "left_only"]
    if len(sem_match):
        print(f"  ⚠ {int(sem_match['ld'].sum())} venda(s) com SCK de anúncio que não existe no Meta: "
              f"{sem_match[['camp','adset','ad']].drop_duplicates().values.tolist()[:3]}")
    dias = pd.date_range(inicio, max(pd.Timestamp(date.today()), agg["date"].max()), freq="D")

    st_c, st_a, st_ad = status_maps(p)
    thumbs = {}
    for (c, a, n), g in p.sort_values("date").groupby(["camp", "adset", "ad"]):
        u = g[G._txt(g["thumb"]).str.startswith("http")]["thumb"] if "thumb" in g else []
        thumbs[(c, a, n)] = thumb_local(u.iloc[-1], img_dir) if len(u) else ""

    k = kpis(agg); d = daily(agg, dias)
    dcamps = {c: daily(g, dias) for c, g in agg.groupby("camp")}

    raw = []
    for (dt, c, a), g in agg.groupby(["date", "camp", "adset"]):
        s = g[NUM].sum()
        raw.append({"d": dt.strftime("%d/%m"), "c": c, "a": a, "lct": True, "sp": r2(s.sp), "ld": int(s.ld),
                    "imp": int(s.imp), "lc": int(s.lc), "pv": int(s.pv), "ic": int(s.ic), "rec": r2(s.rec), "pc": int(s.pc),
                    "sc": st_c.get(c, ""), "sa": st_a.get((c, a), ""),
                    "ads": [{"n": r.ad, "sp": r2(r.sp), "imp": int(r.imp), "lc": int(r.lc), "pv": int(r.pv),
                             "ic": int(r.ic), "ld": int(r.ld), "rec": r2(r.rec)} for r in g.itertuples()]})

    hoje = pd.Timestamp(date.today()); ontem = hoje - pd.Timedelta(days=1)
    per = {"1": (ontem, ontem), "7": (hoje - pd.Timedelta(days=6), hoje), "14": (hoje - pd.Timedelta(days=13), hoje),
           "30": (hoje - pd.Timedelta(days=29), hoje), "all": (None, None)}
    tables = {}
    for pk, (a0, a1) in per.items():
        q = agg if a0 is None else agg[(agg["date"] >= a0) & (agg["date"] <= a1)]
        camps = [{"n": c, "status": st_c.get(c, ""), **row_metrics(g[NUM].sum())} for c, g in q.groupby("camp")]
        adsets = [{"n": a, "camp": c, "status": st_a.get((c, a), ""), **row_metrics(g[NUM].sum())} for (c, a), g in q.groupby(["camp", "adset"])]
        ads = [{"n": n, "adset": a, "camp": c, "status": st_ad.get((c, a, n), ""), "thumb": thumbs.get((c, a, n), ""),
                **row_metrics(g[NUM].sum())} for (c, a, n), g in q.groupby(["camp", "adset", "ad"])]
        key = lambda r: (-(r["roas"] or -1), -r["ld"], -r["spend"])
        tables[pk] = {"camps": sorted(camps, key=key), "adsets": sorted(adsets, key=key), "ads": sorted(ads, key=key)}

    # melhores criativos: todo o histórico, somando por nome
    melhores = []
    for n, g in agg.groupby("ad"):
        s = g[NUM].sum(); ativos = g[g["sp"] > 0]["date"]
        th = next((thumbs[k2] for k2 in thumbs if k2[2] == n and thumbs[k2]), "")
        stt = "ACTIVE" if any(v == "ACTIVE" for k2, v in st_ad.items() if k2[2] == n) else ""
        melhores.append({"n": n, "thumb": th, "status": stt, "days": int(ativos.nunique()),
                         "first": ativos.min().strftime("%d/%m/%y") if len(ativos) else "—",
                         "last": ativos.max().strftime("%d/%m/%y") if len(ativos) else "—",
                         "spend": r2(s.sp), "imp": int(s.imp), "lc": int(s.lc), "pv": int(s.pv),
                         "ic": int(s.ic), "ld": int(s.ld), "rec": r2(s.rec)})

    bd = breakdowns_pixel(inicio)

    # Vendas (aba Hotmart do template): hotmart_data com a aba já filtrada e o SCK nas colunas Captacao_*
    G.LANCAMENTO_COD, G.UPSELL_PRODUTOS, G.DOWNSELL_PRODUTOS = PERPETUO_TAG, [], []
    G.PRECO_FIXO, G.VALOR_LIQUIDO_ABA = {}, None
    G.PERPETUO_PRODUTO = ""   # aqui as vendas do perpétuo são justamente o que interessa
    _orig_ler = G._ler_hotmart
    G._ler_hotmart = lambda: (orig.reset_index(drop=True), PERPETUO_ABA)
    hm = G.hotmart_data(rotulo="hotmart (POPList perpétuo)") if len(orig) else None
    G._ler_hotmart = _orig_ler
    restaurar_config()

    tot_v, tot_r = len(vend), float(vend["price"].sum())
    print(f"  ✓ Perpétuo: R${k['spend']:,.2f} invest. | {k['leads']} vendas atribuídas (R${k['rec']:,.2f}) | "
          f"{tot_v} vendas do produto no total (R${tot_r:,.2f}) | {len(melhores)} criativos")
    return {"consts": {"META_KPIS": {"lct": k, "all": k}, "META_DAILY": {"lct": d, "all": d},
                       "META_DAILY_CAMPS": {"lct": dcamps, "all": dcamps}, "META_RAW_CAMP": raw,
                       "META_TABLES": {"lct": tables, "all": tables}, "META_BD": bd,
                       "PESQUISA": False, "HOTMART": hm or False, "LANCAMENTOS": False, "DOWNSELL": False,
                       "TOTAIS": False, "MELHORES": melhores, "DATA_GERACAO": date.today().strftime("%Y-%m-%d")},
            "resumo": {"spend": k["spend"], "vendas": tot_v, "receita": r2(tot_r), "roas": dv(tot_r, k["spend"]),
                       "vendas_attr": k["leads"], "rec_attr": k["rec"], "inicio": inicio.strftime("%d/%m/%Y")}}

def breakdowns_pixel(inicio):
    """Gênero/idade/posicionamento do perpétuo. Hotmart não tem esse corte → usa compras do pixel."""
    out = {"_raw_ga": [], "_raw_pt": []}
    for url, key, cols in [(G.URL_GA, "_raw_ga", ["Age (Breakdown)", "Gender (Breakdown)"]),
                           (G.URL_PT, "_raw_pt", ["Platform Position (Breakdown)"])]:
        try:
            b = pd.read_csv(url)
            b = b[G._txt(b["Campaign Name"]).str.upper().str.contains(PERPETUO_TAG, na=False)].copy()
            b["date"] = pd.to_datetime(b["Date"], errors="coerce"); b = b.dropna(subset=["date"])
            b["sp"] = G.to_num(b["Spend (Cost, Amount Spent)"])
            b["ld"] = G.to_num(b["Action Omni Purchase"]) if "Action Omni Purchase" in b else 0
            for _, r in b.iterrows():
                row = {"d": r["date"].strftime("%d/%m"), "sp": r2(r["sp"]), "ld": int(r["ld"]), "lct": True, "camp": str(r["Campaign Name"])}
                if key == "_raw_ga": row.update(age=str(r[cols[0]]), gen=str(r[cols[1]]))
                else: row.update(plat=str(r[cols[0]]))
                out[key].append(row)
        except Exception as e:
            print(f"  ⚠ breakdown {key}: {type(e).__name__}: {e}")
    return out

# ══ PÁGINAS PELO TEMPLATE DE LANÇAMENTO (Geral / RDC01) ═══
def pagina_lancamento(cod, saida, aba_vendas=None, pesquisa=False, vendas=True, comparativo=True, abrir_em_tudo=True,
                      resumo=None, receita_oficial=None):
    restaurar_config()
    G.LANCAMENTO_COD = cod
    G.USAR_PESQUISA, G.USAR_VENDAS, G.USAR_COMPARATIVO = pesquisa, vendas, comparativo
    G.USAR_DOWNSELL, G.USAR_TOTAIS = False, False
    G.PRECO_FIXO, G.VALOR_LIQUIDO_ABA = {}, None
    if aba_vendas: G.HOTMART_ABAS = [aba_vendas]
    if receita_oficial: escalar_receita(receita_oficial)
    img = Path("imgs")
    df = G.load_meta()
    mk, md, mdc, mraw, mt, mbd = G.meta_kpis(df), G.meta_daily(df), G.meta_daily_camps(df), G.meta_raw(df), G.meta_tables(df, img), G.meta_breakdowns(df)
    hm = G.hotmart_data(rotulo=f"vendas {cod or 'geral'}") if vendas else None
    lancs = G.lancamentos_data() if comparativo else None
    try: comp = G.build_comp_data(df)
    except Exception: comp = None
    html = G.inject_all(TEMPLATE_LCT, mk, md, mdc, mraw, mt, mbd, None, hm, comp, lancs, None, None)
    if not cod:
        html = geral_pos(html, resumo)
    if abrir_em_tudo:   # lançamento fechado / visão geral: abre no período inteiro em vez de "30d"
        html = html.replace("periodDays=30,", "periodDays=0,", 1)
        html = html.replace('<button class="pb active" onclick="setPeriod(30,this)">30d</button>', '<button class="pb" onclick="setPeriod(30,this)">30d</button>', 1)
        html = html.replace('<button class="pb" onclick="setPeriod(0,this)">Tudo</button>', '<button class="pb active" onclick="setPeriod(0,this)">Tudo</button>', 1)
    Path(saida).write_text(html, encoding="utf-8")
    print(f"  ✓ {saida} ({len(html)//1024}KB)")
    restaurar_config()
    return {"mk": mk, "lancs": lancs}

def escalar_receita(alvo):
    """Lançamento fechado cujo total oficial (LANCAMENTOS_COMPARAR.receita) não bate com a soma da
    planilha: multiplica cada venda pelo mesmo fator, como o comparativo já faz."""
    d0, aba = G._ler_hotmart()
    m, _, achados = G._map_hotmart_cols(d0.copy())
    col = achados["price"]
    preco = G.to_num(m["price"])
    st = G._txt(m.get("status", pd.Series([""] * len(m)))).str.strip().str.upper()
    ok = ["APPROVED", "COMPLETE", "COMPLETED", "APROVADO", "APROVADA", "COMPLETO", "PAGO", "PAID"]
    val = (st.isin(ok) if st.isin(ok).any() else True) & (preco >= G.VENDA_VALOR_MIN)
    tot = float(preco[val].sum())
    if tot <= 0: return
    f = alvo / tot
    novo = (preco * f).round(2)
    resid = round(alvo - float(novo[val].sum()), 2)        # centavos perdidos no arredondamento
    if resid and val.any(): novo.loc[novo[val].idxmax()] += resid
    d0[col] = novo.values
    print(f"     receita da aba '{aba}' ajustada R${tot:,.2f} → R${alvo:,.2f} (fator {f:.4f})")
    G._ler_hotmart = lambda: (d0.copy(), aba)

def geral_pos(html, resumo):
    """geral.html: sem Comparar LP/CTV, sem funil nem gráfico diário; resumo por iniciativa no topo."""
    html = html.replace('<div class="logo-sub">Lançamento</div>', '<div class="logo-sub">Geral</div>', 1)
    html = re.sub(r'\s*<button class="sb-item" onclick="goPage\(\'comp\',this\)">.*?</button>', '', html, count=1)
    html = html.replace('<div class="funnel-card mb14">', '<div class="funnel-card mb14" style="display:none">', 1)
    html = re.sub(r'<div class="cc mb14">(\s*<div class="cc-t">Leads Diários & Investimento</div>)',
                  r'<div class="cc mb14" style="display:none">\1', html, count=1)
    snip = Path("geral_resumo.html").read_text(encoding="utf-8")
    bloco, script = snip.split("<script>", 1)
    script = G.replace_js_const("<script>" + script, "RESUMO", resumo)
    html = html.replace('<div class="page-section active" id="page-meta">',
                        '<div class="page-section active" id="page-meta">\n' + bloco, 1)
    html = html.replace('<script src="nav.js"></script>', script + '\n<script src="nav.js"></script>', 1)
    html = html.replace("meta:'Meta Ads',", "meta:'Visão Geral',", 1)
    return html

def resumo_geral(df_meta, lancs, perp_resumo):
    def ini(c):
        u = c.upper()
        if PERPETUO_TAG in u: return "POPList"
        for l in LANCAMENTOS_PAGINAS:
            if l["cod"] in u: return l["cod"]
        return "Outros"
    d = df_meta.assign(ini=df_meta["camp"].map(ini), mes=df_meta["date"].dt.strftime("%Y-%m"))
    mensal = d.groupby(["mes", "ini"])["sp"].sum().unstack(fill_value=0)
    ordem = [l["cod"] for l in sorted(LANCAMENTOS_PAGINAS, key=lambda l: l["cod"])] + ["POPList", "Outros"]
    linhas = sorted(lancs, key=lambda l: l["cod"])
    if perp_resumo:
        linhas = linhas + [{"cod": "POPList", "label": "Perpétuo · POPList", "cor": COR_PERPETUO, "arquivo": OUT_PERPETUO,
                            "spend": perp_resumo["spend"], "leads": None, "cpl": None, "vendas": perp_resumo["vendas"],
                            "receita": perp_resumo["receita"], "roas": perp_resumo["roas"], "periodo": f"desde {perp_resumo['inicio'][:5]}"}]
    return {"linhas": linhas, "outros_spend": r2(d.loc[d["ini"] == "Outros", "sp"].sum()), "meses": list(mensal.index),
            "mensal": {k: [r2(mensal.loc[m, k]) if k in mensal.columns else 0 for m in mensal.index] for k in ordem},
            "cores": {**{l["cod"]: l["cor"] for l in LANCAMENTOS_PAGINAS}, "POPList": COR_PERPETUO, "Outros": "#cbd5e1"}}

# ══ MENU / NAV ═════════════════════════════════════════
def resumo_lancamentos(df_meta):
    lancs = {}
    try:
        for s in (G.lancamentos_data() or {}).get("lista", []): lancs[s["cod"]] = s
    except Exception as e:
        print(f"  ⚠ receita dos lançamentos indisponível: {e}")
    out = []
    for l in LANCAMENTOS_PAGINAS:
        sub = df_meta[df_meta["camp"].str.upper().str.contains(l["cod"], na=False)]
        sp, ld = float(sub["sp"].sum()), int(sub["lead"].sum())
        s = lancs.get(l["cod"], {})
        out.append({**l, "arquivo": l["arquivo"] if (l["arquivo"] and Path(l["arquivo"]).exists()) else None,
                    "spend": r2(sp), "leads": ld, "cpl": dv(sp, ld), "vendas": s.get("vendas"),
                    "receita": s.get("receita"), "roas": dv(s.get("receita") or 0, sp) if s.get("receita") else None,
                    "periodo": f"{sub['date'].min():%d/%m} – {sub['date'].max():%d/%m/%y}" if len(sub) else ""})
    return out

def escrever_nav(lancs):
    itens = [{"grupo": "", "label": "Perpétuo · POPList", "href": OUT_PERPETUO, "cor": COR_PERPETUO}]
    itens += [{"grupo": "Lançamentos", "label": l["label"], "href": l["arquivo"], "cor": l["cor"]} for l in lancs]
    itens += [{"grupo": "Consolidado", "label": "Geral", "href": OUT_GERAL, "cor": "#cbd5e1"}]
    js = G.replace_js_const(Path("nav.js").read_text(encoding="utf-8"), "DM_NAV", {"menu": MENU_FILE, "itens": itens})
    Path("nav.js").write_text(js, encoding="utf-8"); print("  ✓ nav.js")

def render(tpl, out, consts, simples=None):
    html = Path(tpl).read_text(encoding="utf-8")
    for k, v in consts.items(): html = G.replace_js_const(html, k, v)
    for k, v in (simples or {}).items(): html = re.sub(rf"const {k}\s*=\s*[^;]+;", f"const {k}={v};", html, count=1)
    Path(out).write_text(html, encoding="utf-8"); print(f"  ✓ {out} ({len(html)//1024}KB)")

def main():
    so_rdc01 = "--rdc01" in sys.argv
    print("=" * 60); print("Dra Monica — Perpétuo / Geral / Menu" + (" / RDC01" if so_rdc01 else "")); print("=" * 60)
    Path("imgs").mkdir(exist_ok=True)
    print("\n[META ADS]"); df_meta = ler_meta()
    print(f"  {len(df_meta)} linhas | {df_meta['date'].min().date()} → {df_meta['date'].max().date()}")

    print("\n[PERPÉTUO]"); perp = perpetuo(df_meta, "imgs")
    if perp:
        render(TEMPLATE_PERPETUO, OUT_PERPETUO, perp["consts"], {
            "LANCAMENTO_COD": "'PERPETUO'", "NOME_CLIENTE": f"'{G.NOME_CLIENTE}'", "LOGO_LETRA": f"'{G.LOGO_LETRA}'",
            "COR_ACENTO": f"'{COR_PERPETUO}'", "CPL_BOM": CPA_BOM, "CPL_MEDIO": CPA_MEDIO,
            "CTR_BOM": G.CTR_BOM, "CTR_MEDIO": G.CTR_MEDIO, "CR_BOM": G.CR_BOM, "CR_MEDIO": G.CR_MEDIO,
            "TX_CONV_BOM": TX_CONV_BOM, "TX_CONV_MEDIO": TX_CONV_MEDIO, "CPM_BOM": G.CPM_BOM, "CPM_MEDIO": G.CPM_MEDIO,
            "ROAS_BOM": ROAS_BOM, "ROAS_MEDIO": ROAS_MEDIO, "IC_BOM": IC_BOM, "IC_MEDIO": IC_MEDIO,
            "ICV_BOM": ICV_BOM, "ICV_MEDIO": ICV_MEDIO})

    if so_rdc01:
        alvo = next((c.get("receita") for c in G.LANCAMENTOS_COMPARAR if c["cod"] == "RDC01"), None)
        print("\n[RDC01]"); pagina_lancamento("RDC01", "RDC01.html", aba_vendas="RDC01", receita_oficial=alvo)

    print("\n[RESUMO]"); lancs = resumo_lancamentos(df_meta)
    print("\n[GERAL]"); pagina_lancamento("", OUT_GERAL, vendas=False, comparativo=True,
                                         resumo=resumo_geral(df_meta, lancs, perp["resumo"] if perp else None))

    print("\n[MENU]")
    escrever_nav(lancs)
    render(TEMPLATE_MENU, MENU_FILE, {"DATA": {"perp": perp["resumo"] if perp else None, "lancs": lancs,
            "outros_spend": None, "total_spend": r2(df_meta["sp"].sum()),
            "perp_arquivo": OUT_PERPETUO, "geral_arquivo": OUT_GERAL, "cor_perp": COR_PERPETUO,
            "atualizado": date.today().strftime("%d/%m/%Y")}})
    print("=" * 60)

if __name__ == "__main__":
    main()
