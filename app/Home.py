"""Tela única do estudo de malha: mapa + simulador/otimizador + ML + qualidade dos dados, em abas.

    streamlit run app/Home.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from malha import baseline, report
from malha.datasets import load
from malha.ml import clustering, hub_score, sla_radius
from malha.optimize import instancia_de_dados, resolver, resultado_base
from malha.scenario import Scenario, cenario_padrao
from malha.viz import map as vmap

st.set_page_config(page_title="Malha Logística SP — Ógea × PagResolve", layout="wide")


# --------------------------------------------------------------------------- dados (cacheados no processo)

@st.cache_resource
def _dados():
    return load()


@st.cache_data
def _kpis_polos(_d):
    return baseline.polo_kpis(_d)


@st.cache_data
def _demanda(_d):
    return baseline.demanda_municipio(_d)


@st.cache_data
def _defaults(_d, _k):
    return baseline.defaults(_d, _k)


@st.cache_resource
def _modelos_sla(_d):
    am = sla_radius.amostra(_d)
    return {tr: sla_radius.ajustar(am, tr) for tr in ("POLO", "OGEA")}


try:
    d = _dados()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

k = _kpis_polos(d)
dem = _demanda(d)
dfl = _defaults(d, k)
tipos = sorted(d.os["tipo_atendimento"].dropna().unique().tolist())
status_os = sorted(d.os["status"].dropna().unique().tolist())

if "sc" not in st.session_state:
    st.session_state.sc = cenario_padrao(dfl, tipos, status_os)
sc: Scenario = st.session_state.sc

st.title("🗺️ Malha Logística SP — Ógea × PagResolve")
st.caption("Hoje a Ógea atende {:.0%} das OS de julho/26 ({} cidades); os polos, {:.0%} (só {} cidades)."
          .format(dem["vol_ogea"].sum() / dem["vol_total"].sum(), int((dem["vol_ogea"] > 0).sum()),
                  dem["vol_polo"].sum() / dem["vol_total"].sum(), int((dem["vol_polo"] > 0).sum())))


# --------------------------------------------------------------------------- barra lateral: parâmetros do cenário

def _origem(nome):
    st.caption(f"↳ {dfl[nome]['origem']}")


base_custo_atual = baseline.custo_base(d)

with st.sidebar:
    st.header("⚙️ Parâmetros do cenário")
    with st.form("params"):
        st.subheader("Raio e distância")
        raio_km = st.slider("Raio de atendimento (km, linha reta)", 5.0, 250.0, float(sc.raio_km), 1.0)
        _origem("raio_km")

        st.subheader("Capacidade")
        meta = st.slider("Meta de OS por técnico/mês", 20.0, 600.0, float(sc.meta_os_tec), 5.0)
        _origem("meta_os_tec")
        usar_obs = st.checkbox("Equipe atual conta a produtividade que já entrega (não só a meta)",
                               value=sc.usar_prod_observada)

        st.subheader("Custos (contratação livre)")
        custo_tec = st.number_input("Custo por técnico novo (R$/mês)", 0.0, value=float(sc.custo_tecnico), step=500.0)
        _origem("custo_tecnico")
        custo_abrir = st.number_input("Custo fixo extra p/ abrir polo dormente ou hub novo (R$)",
                                      0.0, value=float(sc.custo_abrir), step=1000.0)
        custo_km = st.number_input("Custo de deslocamento (R$ por OS·km)", 0.0, value=float(sc.custo_km), step=0.1)
        orcamento_on = st.checkbox("Limitar por orçamento", value=sc.orcamento is not None)
        orcamento = st.number_input("Orçamento total (R$)", 0.0, value=float(sc.orcamento or base_custo_atual),
                                    step=10_000.0, disabled=not orcamento_on)

        st.subheader("Objetivo")
        modo = st.radio("Modo", ["simular", "otimizar"], index=["simular", "otimizar"].index(sc.modo),
                        format_func=lambda m: "Simular (só o que eu travar abaixo)" if m == "simular"
                        else "Otimizar (o modelo escolhe polos e técnicos)")
        permitir_fechar = st.checkbox("No modo Otimizar, permitir fechar polo ativo", value=sc.permitir_fechar_ativos)
        nao_devolver = st.checkbox("Não devolver à Ógea volume que já é do polo", value=sc.nao_devolver)

        st.subheader("Filtros de volume")
        tipos_sel = st.multiselect("Tipos de atendimento absorvíveis", tipos, default=list(sc.tipos_absorviveis))
        status_sel = st.multiselect("Status incluídos", status_os, default=list(sc.status_incluidos))

        aplicado = st.form_submit_button("▶ Aplicar", width='stretch')

    if aplicado:
        st.session_state.sc = sc.with_(
            raio_km=raio_km, meta_os_tec=meta, usar_prod_observada=usar_obs, custo_tecnico=custo_tec,
            custo_abrir=custo_abrir, custo_km=custo_km, orcamento=(orcamento if orcamento_on else None),
            modo=modo, permitir_fechar_ativos=permitir_fechar, nao_devolver=nao_devolver,
            tipos_absorviveis=tuple(sorted(tipos_sel)), status_incluidos=tuple(sorted(status_sel)))
        sc = st.session_state.sc
        st.rerun()

    st.divider()
    st.subheader("🔓/🔒 Travar polos")
    trava_df = pd.DataFrame({"codigo_polo": k["codigo_polo"], "nome": k["polo_nome"], "status_hoje": k["status_bd"]})
    trava_df = trava_df[trava_df["status_hoje"].ne("ARMAZEM_OGEA")]
    atuais = dict(sc.travas)
    trava_df["trava"] = trava_df["codigo_polo"].map(atuais).fillna("livre")
    ed = st.data_editor(trava_df, hide_index=True, width='stretch', key="travas_editor",
                        column_config={"trava": st.column_config.SelectboxColumn(options=["livre", "aberto", "fechado"])},
                        disabled=["codigo_polo", "nome", "status_hoje"])
    novas_travas = tuple((r.codigo_polo, r.trava) for r in ed.itertuples() if r.trava != "livre")
    if novas_travas != sc.travas:
        st.session_state.sc = sc.with_(travas=novas_travas)
        st.rerun()


# --------------------------------------------------------------------------- resolve o cenário atual

inst = instancia_de_dados(d, k, sc)
resultado = resolver(inst, sc)  # em modo "simular" sem travas/overrides, isto já reproduz a base
base = resultado_base(instancia_de_dados(d, k, cenario_padrao(dfl, tipos, status_os)),
                      cenario_padrao(dfl, tipos, status_os))

if resultado.avisos:
    for a in resultado.avisos:
        st.warning(a)
if not resultado.ok:
    st.error(resultado.mensagem)


# --------------------------------------------------------------------------- KPIs no topo

kp = resultado.kpis
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Share Ógea", f"{kp['share_ogea_cen']:.0%}", f"{(kp['share_ogea_cen'] - kp['share_ogea_base']):+.0%}")
c2.metric("OS absorvidas da Ógea", f"{kp['absorvido']:,.0f}".replace(",", "."))
c3.metric("Técnicos a contratar", f"{kp['tec_contratar']:,.0f}".replace(",", "."))
c4.metric("Custo do cenário", f"R$ {kp['custo_cen']:,.0f}".replace(",", "."), f"R$ {kp['delta_custo']:+,.0f}".replace(",", "."))
c5.metric("Polos abertos", f"{kp['polos_abertos']}",
         f"+{kp['polos_reabertos']} reabertos" if kp["polos_reabertos"] else None)

aba_mapa, aba_polos, aba_ml, aba_dados = st.tabs(
    ["🗺️ Mapa", "🏭 Polos e rateio", "🤖 Machine Learning", "🔍 Qualidade dos dados"])


# --------------------------------------------------------------------------- aba MAPA

with aba_mapa:
    esq, dir_ = st.columns([3, 1])
    with dir_:
        mostrar_circulos = st.checkbox("Mostrar raio (círculo)", value=True)
        mostrar_fluxos = st.checkbox("Mostrar fluxos absorvidos", value=True)
        st.caption("Cores dos municípios")
        for rot, cor in vmap.ROTULO_STATUS.items():
            st.markdown(f'<span style="color:{vmap.CORES_STATUS[rot]}">●</span> {cor}', unsafe_allow_html=True)
    with esq:
        mun_cor = vmap.cor_municipios(dem, resultado.cidades)
        pol_map = resultado.polos.assign(
            status_mapa=lambda x: vmap.status_polos(x),
            raio_km=lambda x: x["raio_km"], tecnicos=lambda x: x["tecnicos"], nome=lambda x: x["nome"],
            volume=lambda x: x["volume"])
        ogea_ll = tuple(k.loc[k["codigo_polo"].eq("OGEA"), ["lat", "lon"]].iloc[0])
        m = vmap.mapa(d.malha, mun_cor, pol_map, fluxos=resultado.fluxos if mostrar_fluxos else None,
                     ogea=ogea_ll, mostrar_circulos=mostrar_circulos)
        st_folium(m, height=620, width='stretch', returned_objects=[])

    xls = report.excel_cenario(resultado, base, sc, d.municipios)
    st.download_button("⬇️ Exportar cenário (Excel)", xls, "cenario_malha.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------------------- aba POLOS E RATEIO

with aba_polos:
    st.subheader("Cada polo: o que atende hoje e no cenário")
    cols = ["codigo_polo", "nome", "status", "aberto", "tecnicos", "contratar", "v0", "vol_absorvido", "volume",
            "utilizacao", "cmu_base", "cmu_cen", "custo"]
    show = resultado.polos[cols].rename(columns={
        "v0": "volume_hoje", "vol_absorvido": "absorvido_ogea", "utilizacao": "ocupação",
        "cmu_base": "CMU hoje", "cmu_cen": "CMU cenário"}).sort_values("absorvido_ogea", ascending=False)
    st.dataframe(show.style.format({
        "utilizacao": "{:.0%}", "ocupação": "{:.0%}", "CMU hoje": "R$ {:.2f}", "CMU cenário": "R$ {:.2f}",
        "custo": "R$ {:,.0f}", "volume_hoje": "{:.0f}", "absorvido_ogea": "{:.0f}", "volume": "{:.0f}"}),
        width='stretch', hide_index=True)

    st.subheader("Curva de rateio (CMU × volume) de um polo")
    polo_sel = st.selectbox("Polo", inst.polos.index, format_func=lambda p: f"{p} — {inst.polos.at[p, 'nome']}")
    from malha.costs import break_even, curva_rateio
    pr = inst.polos.loc[polo_sel]
    v_max = max(float(pr["v0"]) * 3, sc.meta_os_tec * 6, 500.0)
    curva = curva_rateio(pr["v0"], pr["custo_atual"], pr["t0"], sc.meta_os_tec, sc.custo_tecnico, v_max,
                         sc.usar_prod_observada, sc.custo_abrir)
    preco_medio_ogea = float(d.preco_ogea["preco_ogea"].mean())
    be = break_even(curva, preco_medio_ogea)
    st.line_chart(curva.set_index("volume")[["cmu"]])
    st.caption(f"Preço médio Ógea (todos os tipos): R$ {preco_medio_ogea:.2f}. "
              + (f"O CMU do polo fica abaixo disso a partir de {be:,.0f} OS/mês.".replace(",", ".")
                 if be else "O CMU do polo não cai abaixo do preço da Ógea na faixa mostrada."))

    st.subheader("Override de share por município (força uma % fixa para a Ógea)")
    mun_op = dem.loc[dem["vol_total"] > 0, ["cod_ibge", "municipio"]].sort_values("municipio")
    c1, c2 = st.columns([2, 1])
    cod_sel = c1.selectbox("Município", mun_op["cod_ibge"], format_func=lambda c: mun_op.set_index("cod_ibge").at[c, "municipio"])
    share_sel = c2.slider("Share Ógea alvo", 0.0, 1.0, 0.0, 0.05)
    if st.button("Adicionar override"):
        st.session_state.sc = sc.with_(share_municipio=sc.share_municipio + ((int(cod_sel), share_sel),))
        st.rerun()
    if sc.share_municipio:
        ov = pd.DataFrame(sc.share_municipio, columns=["cod_ibge", "share_ogea_alvo"])
        ov["municipio"] = ov["cod_ibge"].map(mun_op.set_index("cod_ibge")["municipio"])
        st.dataframe(ov, hide_index=True, width='stretch')
        if st.button("Limpar overrides"):
            st.session_state.sc = sc.with_(share_municipio=())
            st.rerun()


# --------------------------------------------------------------------------- aba ML

with aba_ml:
    st.markdown("#### 1. Raio de SLA sugerido (aprendido dos dados)")
    mods = _modelos_sla(d)
    c1, c2 = st.columns(2)
    for col, tr in zip((c1, c2), ("POLO", "OGEA")):
        m = mods[tr]
        curva_sla = sla_radius.curva(m)
        rs = sla_radius.raio_sugerido(curva_sla, dfl["sla_alvo"]["valor"])
        with col:
            st.markdown(f"**{tr}** — {m.metricas['n_os']:,.0f} OS em {m.metricas['n_municipios']} municípios"
                       .replace(",", "."))
            st.line_chart(curva_sla.set_index("d_km")[["p_prazo"]])
            st.caption(rs["texto"] + (" *(fora da faixa observada)*" if rs["limitado_pelo_dado"] else ""))
            st.caption(f"Erro do modelo vs. referência simples (faixas de 10 km): "
                      f"pinball {m.metricas['pinball_modelo']:.3f} vs {m.metricas['pinball_referencia']:.3f} "
                      f"(menor é melhor).")

    st.markdown("#### 2. Demanda órfã → hubs novos sugeridos")
    ativos = k[k["status_bd"].eq("ATIVO")].assign(raio_km=sc.raio_km)
    orfa = clustering.demanda_orfa(dem, ativos[["lat", "lon", "raio_km"]])
    st.caption(f"{len(orfa)} cidades fora do raio de {sc.raio_km:.0f} km de qualquer polo ativo, "
              f"somando {orfa['vol_ogea'].sum():,.0f} OS Ógea.".replace(",", "."))
    if len(orfa):
        n_k = st.slider("Quantos hubs candidatos sugerir", 1, min(20, len(orfa)), min(6, len(orfa)))
        vol_min = st.number_input("Volume mínimo para considerar viável (OS/mês)", 0.0,
                                  value=float(ativos["volume"].quantile(0.25)), step=50.0)
        cand, _ = clustering.hubs(orfa, n_k, sc.raio_km, d.polos, vol_min)
        st.dataframe(cand.drop(columns=["lat", "lon"]).style.format({
            "vol_ogea": "{:.0f}", "vol_no_raio": "{:.0f}", "dist_media_km": "{:.0f}", "dist_polo_atual_km": "{:.0f}"}),
            width='stretch', hide_index=True)
        st.caption("`polo_dormente_no_municipio` mostra quando o hub sugerido já tem polo cadastrado dormente ali.")

    st.markdown("#### 3. Score de HUB estratégico (polos ativos)")
    feat = hub_score.features(k, dem, d.dist, sc.raio_km)
    sco = hub_score.score(feat)
    st.dataframe(sco[["codigo_polo", "polo_nome", "vol_ogea_proximo", "cmu_vs_ogea", "lt_medio", "pct_prazo",
                      "dist_vizinho_km", "score", "classe"]].style.format({
        "cmu_vs_ogea": "{:.2f}", "lt_medio": "{:.2f}", "pct_prazo": "{:.0%}", "dist_vizinho_km": "{:.0f}",
        "score": "{:.2f}", "vol_ogea_proximo": "{:.0f}"}),
        width='stretch', hide_index=True)
    st.caption("`vol_ogea_proximo`: OS Ógea nas cidades onde este é o polo ativo mais próximo dentro do raio "
              "(sem dupla contagem entre polos).")

    st.markdown("##### Polos dormentes: quanto cada um destravaria")
    dorm = hub_score.dormentes(k, dem, d.dist, sc.raio_km)
    st.dataframe(dorm[["codigo_polo", "polo_nome", "vol_ogea_no_raio", "vol_ogea_sem_cobertura",
                      "ativo_mais_proximo", "dist_ativo_km"]].style.format(
        {"vol_ogea_no_raio": "{:.0f}", "vol_ogea_sem_cobertura": "{:.0f}", "dist_ativo_km": "{:.0f}"}),
        width='stretch', hide_index=True)
    st.caption("`vol_ogea_sem_cobertura`: dessa OS Ógea, quanto NENHUM polo ativo alcança hoje "
              "(o que esse dormente destravaria sozinho).")


# --------------------------------------------------------------------------- aba QUALIDADE

with aba_dados:
    q = d.qualidade
    st.subheader("Checagens automáticas (rodadas em `python -m malha.build`)")
    c1, c2, c3 = st.columns(3)
    c1.metric("OS total", f"{q['os_total']:,.0f}".replace(",", "."))
    c2.metric("Cidades casadas com IBGE", "100%" if not q["template_nao_resolvido"] else "⚠ incompleto")
    c3.metric("Polos cadastrados", f"{q['polos_cadastro'].get('ATIVO', 0)} ativos / "
             f"{q['polos_cadastro'].get('DORMENTE', 0)} dormentes")

    st.markdown("**Distritos da capital mapeados** (Cidade = bairro na BD)")
    st.json(q["os_por_distrito_capital"])
    st.markdown("**Preço Ógea por tipo — BD vs. aba CMU** (deve bater)")
    st.dataframe(pd.DataFrame(q["preco_ogea_bd_vs_aba"]), hide_index=True, width='stretch')
    if q["codigo_polo_bd_divergente"]:
        st.markdown("**Código de polo divergente entre BD e nome** ⚠")
        st.dataframe(pd.DataFrame(q["codigo_polo_bd_divergente"]), hide_index=True)
    st.markdown("**Municípios do IBGE ausentes no TEMPLATE** (não afeta a BD, só a checagem cruzada)")
    st.write(", ".join(q["ibge_ausentes_no_template"]) or "—")
    st.markdown("**Geocodificação dos polos** (fonte e confiança de cada ponto)")
    geo = pd.DataFrame(q["geocode"])
    st.dataframe(geo, hide_index=True, width='stretch')
    if (geo["coord_confianca"] == "baixa").any():
        st.warning("Polos com coordenada de baixa confiança (caiu na sede do município, sem API validada): "
                  + ", ".join(geo.loc[geo["coord_confianca"].eq("baixa"), "codigo_polo"]))
